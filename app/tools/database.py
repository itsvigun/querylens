"""Bounded SQL tool using dedicated credentials and server-owned transactions."""

import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from time import monotonic
from uuid import uuid4

import psycopg2
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import AnalyticsSettings, SQLToolLimits
from app.tools.sql_validation import SQLValidationError, validate_sql

ERROR_MESSAGES = {
    "invalid_sql": "The query could not be parsed as supported PostgreSQL SQL.",
    "forbidden_sql": "The query uses a construct, relation, function, or type outside the policy.",
    "query_limit": "The query exceeds the SQL size or complexity limit.",
    "result_limit": "The query or column metadata cannot fit within the result budget.",
    "timeout": "PostgreSQL stopped the query after its statement or lock timeout.",
    "deadline_exceeded": "The SQL tool's time budget was exhausted.",
    "unknown_column": "A referenced column is unavailable; check the reviewed schema.",
    "database_unavailable": "The analytics database is unavailable.",
    "database_error": "PostgreSQL could not execute the validated query.",
    "result_format": "The query returned a value outside the supported result format.",
}
TYPE_NAMES = {
    16: "boolean",
    20: "bigint",
    21: "smallint",
    23: "integer",
    25: "text",
    700: "real",
    701: "double precision",
    1042: "char",
    1043: "varchar",
    1082: "date",
    1114: "timestamp",
    1184: "timestamptz",
    1186: "interval",
    1700: "numeric",
}


class ToolError(BaseModel):
    category: str
    message: str


class ResultColumn(BaseModel):
    name: str
    type: str


class SQLResult(BaseModel):
    status: str
    executed_sql: str | None = None
    columns: list[ResultColumn] = Field(default_factory=list)
    rows: list[list[str | int | float | bool | None]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    truncation_reasons: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    error: ToolError | None = None

    def json_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(), ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")


def _json_value(value):
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, int):
        # Preserve integers that a JavaScript client cannot represent exactly.
        return str(value) if abs(value) > 2**53 - 1 else value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("result_format")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("result_format")
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    raise ValueError("result_format")


class DatabaseTools:
    """Reusable reader pool, owned and closed by the server/CLI calling this tool.

    No owner/writer engine can be injected. A future workflow may supply an
    absolute monotonic deadline, which can only shorten the configured tool budget.
    """

    def __init__(
        self, settings: AnalyticsSettings | None = None, limits: SQLToolLimits | None = None
    ) -> None:
        settings = settings if settings is not None else AnalyticsSettings()
        if (
            not isinstance(settings, AnalyticsSettings)
            or settings.postgres_user != "querylens_analytics_ro"
        ):
            raise ValueError("DatabaseTools requires dedicated analytics reader settings")
        self.limits = limits if limits is not None else SQLToolLimits()
        args = settings.database_connect_args
        args["connect_timeout"] = min(
            settings.db_connect_timeout_seconds,
            max(1, math.ceil(self.limits.sql_tool_timeout_ms / 1000)),
        )
        args["options"] += " -c search_path=pg_catalog -c default_transaction_read_only=on"
        self.engine = create_engine(
            settings.database_url,
            connect_args=args,
            pool_size=2,
            max_overflow=0,
            pool_timeout=min(
                settings.db_connect_timeout_seconds, self.limits.sql_tool_timeout_ms / 1000
            ),
            hide_parameters=True,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self.engine.dispose()

    def execute_sql(self, query: str, *, deadline: float | None = None) -> SQLResult:
        started = monotonic()
        deadline = min(
            deadline if deadline is not None else math.inf,
            started + self.limits.sql_tool_timeout_ms / 1000,
        )
        deadline_limited = False

        def fail(category: str, *, rejected: bool = False) -> SQLResult:
            return SQLResult(
                status="rejected" if rejected else "error",
                duration_ms=int((monotonic() - started) * 1000),
                error=ToolError(category=category, message=ERROR_MESSAGES[category]),
            )

        def remaining_ms() -> int:
            nonlocal deadline_limited
            remaining = int((deadline - monotonic()) * 1000)
            if remaining < 1:
                raise TimeoutError
            deadline_limited = remaining <= self.limits.sql_statement_timeout_ms
            return min(remaining, self.limits.sql_statement_timeout_ms)

        try:
            remaining_ms()
            validated = validate_sql(query, max_rows=self.limits.sql_max_rows)
            result = SQLResult(
                status="ok",
                executed_sql=validated.execution_query,
                duration_ms=9999999999,
                row_count=self.limits.sql_max_rows,
                truncated=True,
                truncation_reasons=["row_limit", "byte_limit"],
            )
            # Reserve timing/truncation overhead while building a bounded response.
            if len(result.json_bytes()) > self.limits.sql_max_result_bytes:
                return fail("result_limit", rejected=True)
            remaining_ms()
            with self.engine.connect().execution_options(postgresql_readonly=True) as connection:
                with connection.begin():
                    connection.exec_driver_sql("SET LOCAL search_path = pg_catalog")
                    connection.exec_driver_sql("SET LOCAL standard_conforming_strings = on")
                    connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
                    connection.exec_driver_sql("SET LOCAL lock_timeout = '1000ms'")
                    identity = connection.exec_driver_sql(
                        "SELECT current_user, current_setting('transaction_read_only')"
                    ).one()
                    if identity != ("querylens_analytics_ro", "on"):
                        return fail("database_error")
                    raw = connection.connection.driver_connection
                    # A server-side cursor avoids fetching a whole result into Python memory.
                    with raw.cursor(name="querylens_" + uuid4().hex) as cursor:
                        connection.exec_driver_sql(
                            "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                            (str(remaining_ms()),),
                        )
                        # No DBAPI parameter interpolation on user SQL (including literal '%').
                        cursor.execute(validated.execution_query)
                        reasons = []
                        response_bytes = 0
                        while True:
                            connection.exec_driver_sql(
                                "SELECT pg_catalog.set_config('statement_timeout', %s, true)",
                                (str(remaining_ms()),),
                            )
                            batch = cursor.fetchmany(16)
                            if not result.columns:
                                result.columns = [
                                    ResultColumn(
                                        name=column.name,
                                        type=TYPE_NAMES.get(column.type_code, "unsupported"),
                                    )
                                    for column in cursor.description
                                ]
                                response_bytes = len(result.json_bytes())
                                if (
                                    len(result.columns) > 64
                                    or response_bytes > self.limits.sql_max_result_bytes
                                ):
                                    return fail("result_limit")
                            if not batch:
                                break
                            for row in batch:
                                remaining_ms()
                                if len(result.rows) == self.limits.sql_max_rows:
                                    reasons.append("row_limit")
                                    break
                                values = [_json_value(value) for value in row]
                                row_bytes = len(
                                    json.dumps(
                                        values,
                                        ensure_ascii=False,
                                        allow_nan=False,
                                        separators=(",", ":"),
                                    ).encode("utf-8")
                                ) + bool(result.rows)
                                if response_bytes + row_bytes > self.limits.sql_max_result_bytes:
                                    reasons.append("byte_limit")
                                    break
                                result.rows.append(values)
                                response_bytes += row_bytes
                            if reasons:
                                break
                        result.truncated = bool(reasons)
                        result.truncation_reasons = reasons
                        result.row_count = len(result.rows)
            remaining_ms()
            result.duration_ms = int((monotonic() - started) * 1000)
            return result
        except SQLValidationError as error:
            return fail(error.category, rejected=True)
        except TimeoutError:
            return fail("deadline_exceeded")
        except (SQLAlchemyError, psycopg2.Error) as error:
            original = getattr(error, "orig", error)
            code = getattr(original, "pgcode", None)
            if code in {"57014", "55P03"}:
                return fail(
                    "deadline_exceeded"
                    if monotonic() >= deadline or deadline_limited
                    else "timeout"
                )
            if monotonic() >= deadline:
                return fail("deadline_exceeded")
            if code == "42703":
                return fail("unknown_column")
            if code is None or code.startswith("08"):
                return fail("database_unavailable")
            return fail("database_error")
        except ValueError:
            return fail("result_format")

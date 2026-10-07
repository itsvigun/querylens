"""Fail-closed PostgreSQL AST policy for the four synthetic business tables."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import sqlglot
from sqlglot import ErrorLevel, exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.db.schema import ANALYTICS_TABLES

ALLOWED_TABLES = frozenset(table.name for table in ANALYTICS_TABLES)
MAX_SQL_BYTES = 16384
MAX_AST_NODES = 600
MAX_AST_DEPTH = 40

# Exact classes, not base classes: newly introduced syntax/functions stay denied.
STRUCTURAL_NODES = frozenset(
    {
        exp.Select,
        exp.Subquery,
        exp.Union,
        exp.Intersect,
        exp.Except,
        exp.With,
        exp.CTE,
        exp.Alias,
        exp.From,
        exp.Join,
        exp.Table,
        exp.TableAlias,
        exp.Column,
        exp.Identifier,
        exp.Star,
        exp.Literal,
        exp.Null,
        exp.Boolean,
        exp.Paren,
        exp.Where,
        exp.Group,
        exp.Having,
        exp.Order,
        exp.Ordered,
        exp.Limit,
        exp.Offset,
        exp.Distinct,
        exp.EQ,
        exp.NEQ,
        exp.LT,
        exp.LTE,
        exp.GT,
        exp.GTE,
        exp.And,
        exp.Or,
        exp.Not,
        exp.In,
        exp.Between,
        exp.Is,
        exp.Add,
        exp.Sub,
        exp.Mul,
        exp.Div,
        exp.Mod,
        exp.Neg,
        exp.Case,
        exp.If,
        exp.Exists,
        exp.Filter,
        exp.Window,
        exp.WindowSpec,
        exp.Var,
        exp.Interval,
        exp.DataType,
        exp.DataTypeParam,
        exp.Tuple,
        exp.Like,
        exp.ILike,
        exp.DPipe,
    }
)
ALLOWED_FUNCTIONS = frozenset(
    {
        exp.Count,
        exp.Sum,
        exp.Avg,
        exp.Min,
        exp.Max,
        exp.LogicalAnd,
        exp.LogicalOr,
        exp.Coalesce,
        exp.Nullif,
        exp.Abs,
        exp.Round,
        exp.Floor,
        exp.Ceil,
        exp.Cast,
        exp.Extract,
        exp.TimestampTrunc,
        exp.Lower,
        exp.Upper,
        exp.Length,
        exp.Substring,
        exp.RowNumber,
        exp.Rank,
        exp.DenseRank,
        exp.Lag,
        exp.Lead,
    }
)
ALLOWED_TYPES = frozenset(
    {
        exp.DataType.Type.BOOLEAN,
        exp.DataType.Type.BIGINT,
        exp.DataType.Type.INT,
        exp.DataType.Type.SMALLINT,
        exp.DataType.Type.DECIMAL,
        exp.DataType.Type.DOUBLE,
        exp.DataType.Type.FLOAT,
        exp.DataType.Type.TEXT,
        exp.DataType.Type.VARCHAR,
        exp.DataType.Type.CHAR,
        exp.DataType.Type.DATE,
        exp.DataType.Type.TIMESTAMP,
        exp.DataType.Type.TIMESTAMPTZ,
        exp.DataType.Type.INTERVAL,
    }
)
TIME_UNITS = frozenset(
    {
        "year",
        "quarter",
        "month",
        "week",
        "day",
        "hour",
        "minute",
        "second",
        "millisecond",
        "microsecond",
        "epoch",
        "dow",
        "doy",
        "isodow",
        "isoyear",
    }
)


class SQLValidationError(ValueError):
    """Contains a safe reason code only, never parser text or user SQL."""

    def __init__(self, category: str = "forbidden_sql") -> None:
        self.category = category
        super().__init__(category)


class ReviewedPostgres(Postgres):
    class Parser(Postgres.Parser):
        def _warn_unsupported(self) -> None:
            # Pinned parser hook: reject command fallbacks before they log raw SQL.
            raise SQLValidationError()


@dataclass(frozen=True)
class ValidatedSQL:
    query: str
    execution_query: str


def _check_node(node: exp.Expression) -> None:
    if type(node) not in STRUCTURAL_NODES | ALLOWED_FUNCTIONS:
        raise SQLValidationError()
    if isinstance(node, exp.With) and node.args.get("recursive"):
        raise SQLValidationError()
    if isinstance(node, exp.Identifier):
        if not node.this or len(node.this.encode("utf-8")) > 63:
            raise SQLValidationError("invalid_sql")
        # PostgreSQL folds unquoted names to lowercase. Quote only after this normalization.
        if not node.args.get("quoted"):
            node.set("this", node.this.lower())
    if isinstance(node, exp.Literal) and not node.is_string:
        try:
            value = Decimal(node.this)
            if not value.is_finite() or value.adjusted() > 18 or value.as_tuple().exponent < -12:
                raise SQLValidationError()
        except InvalidOperation as error:
            raise SQLValidationError("invalid_sql") from error
    if isinstance(node, exp.DataType):
        if node.this not in ALLOWED_TYPES or node.args.get("nested"):
            raise SQLValidationError()
        for parameter in node.expressions:
            literal = parameter.this
            if not isinstance(literal, exp.Literal) or not literal.is_int:
                raise SQLValidationError()
            if not 0 <= int(literal.this) <= 256:
                raise SQLValidationError()
    if isinstance(node, exp.Var):
        if type(node.parent) not in {exp.Interval, exp.Extract, exp.TimestampTrunc}:
            raise SQLValidationError()
        unit = node.name.lower()
        if isinstance(node.parent, exp.Interval):
            unit = unit.removesuffix("s")
        if unit not in TIME_UNITS:
            raise SQLValidationError()
    if isinstance(node, exp.Column):
        if node.catalog or (node.db and node.db != "analytics"):
            raise SQLValidationError()
    if isinstance(node, exp.Star) and any(node.args.values()):
        raise SQLValidationError()
    if isinstance(node, exp.Offset | exp.Limit):
        literal = node.expression
        cap = 100000 if isinstance(node, exp.Offset) else 1000000
        if not isinstance(literal, exp.Literal) or not literal.is_int:
            raise SQLValidationError()
        if not 0 <= int(literal.this) <= cap:
            raise SQLValidationError()


def validate_sql(query: str, *, max_rows: int = 1000) -> ValidatedSQL:
    """Validate all subtrees/scopes, then generate the only SQL allowed to execute.

    Parser acceptance is not authorization. PostgreSQL permissions and runtime
    limits remain necessary even after this application policy succeeds.
    """
    if not isinstance(query, str) or not query.strip():
        raise SQLValidationError("invalid_sql")
    try:
        query_bytes = len(query.encode("utf-8"))
    except UnicodeError as error:
        raise SQLValidationError("invalid_sql") from error
    if query_bytes > MAX_SQL_BYTES:
        raise SQLValidationError("query_limit")
    if not 1 <= max_rows <= 1000:
        raise ValueError("max_rows must be between 1 and 1000")
    try:
        statements = sqlglot.parse(query, read=ReviewedPostgres, error_level=ErrorLevel.RAISE)
        # A trailing semicolon is fine; additional empty statements are not.
        if len(statements) != 1 or not isinstance(
            statements[0], exp.Select | exp.Union | exp.Intersect | exp.Except | exp.Subquery
        ):
            raise SQLValidationError()
        tree = statements[0]
        for count, node in enumerate(tree.walk(), start=1):
            if count > MAX_AST_NODES or node.depth > MAX_AST_DEPTH:
                raise SQLValidationError("query_limit")
            _check_node(node)
        seen_tables = set()
        for scope in traverse_scope(tree):
            for node, source in scope.selected_sources.values():
                if isinstance(node, exp.Table):
                    seen_tables.add(id(node))
                if isinstance(source, Scope):
                    # A CTE/subquery alias is resolved in its actual lexical scope.
                    # Explicit schemas must never be mistaken for CTE aliases.
                    if isinstance(node, exp.Table) and (node.db or node.catalog):
                        raise SQLValidationError()
                    continue
                if not isinstance(source, exp.Table) or not isinstance(source.this, exp.Identifier):
                    raise SQLValidationError()
                if source.catalog or source.db not in {"", "analytics"}:
                    raise SQLValidationError()
                if source.name not in ALLOWED_TABLES:
                    raise SQLValidationError()
                source.set("db", exp.to_identifier("analytics"))
        if any(id(table) not in seen_tables for table in tree.find_all(exp.Table)):
            raise SQLValidationError()
        canonical = tree.sql(
            dialect="postgres", identify=True, comments=False, unsupported_level=ErrorLevel.RAISE
        )
        # Cap the top-level LIMIT through the AST, preserving ORDER BY/OFFSET and
        # any smaller user limit. One extra row establishes row-limit truncation.
        original_limit = tree.args.get("limit")
        effective_limit = min(
            max_rows + 1, int(original_limit.expression.this) if original_limit else max_rows + 1
        )
        bounded = tree.limit(effective_limit)
        execution = bounded.sql(
            dialect="postgres", identify=True, comments=False, unsupported_level=ErrorLevel.RAISE
        )
        if (
            len(canonical.encode("utf-8")) > MAX_SQL_BYTES
            or len(execution.encode("utf-8")) > MAX_SQL_BYTES + 256
        ):
            raise SQLValidationError("query_limit")
        # Do not allow generation to introduce functions or unsupported constructs silently.
        generated = sqlglot.parse_one(
            execution, read=ReviewedPostgres, error_level=ErrorLevel.RAISE
        )
        for node in generated.walk():
            _check_node(node)
        return ValidatedSQL(canonical, execution)
    except RecursionError as error:
        raise SQLValidationError("query_limit") from error
    except (SqlglotError, UnicodeError, ValueError) as error:
        if isinstance(error, SQLValidationError):
            raise
        raise SQLValidationError("invalid_sql") from error

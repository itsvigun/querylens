"""Owner-only invitation administration. Secrets go to a new private file, never logs."""

import argparse
import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.access import issue_credential
from app.config import Settings
from app.db.connection import create_database_engine
from app.demo_gate import LOCK

TOKEN_REPORT_SQL = (
    "SELECT t.id,t.name,t.created_at,t.expires_at,t.revoked_at,t.max_requests, "
    "t.budget_micro_usd,t.requests_per_minute,u.admitted_requests,u.reserved_micro_usd, "
    "u.charged_micro_usd,u.unknown_requests, "
    "u.first_used_at,u.last_used_at FROM operations.access_tokens t "
    "JOIN operations.access_usage u ON u.token_id=t.id "
)


class TokenOptions(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    max_requests: int = Field(default=10, ge=1, le=10000)
    budget_usd: Decimal = Field(default=Decimal("1"), ge=0, le=100, decimal_places=6)
    requests_per_minute: int = Field(default=2, ge=1, le=60)
    expires_in_days: int = Field(default=30, ge=1, le=365)

    @field_validator("name")
    @classmethod
    def printable_name(cls, value):
        if not value.strip() or not value.isprintable():
            raise ValueError("Use a printable name")
        return value.strip()


def lock(connection):
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})


def identifier(value):
    if UUID(value).hex != value:
        raise ValueError("Use a canonical token ID")
    return value


def create_token(engine, options: TokenOptions, output: Path):
    token_id, credential, digest = issue_credential("qlt")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(credential + "\n")
        with engine.begin() as connection:
            lock(connection)
            now = connection.scalar(text("SELECT clock_timestamp()"))
            expires = now + timedelta(days=options.expires_in_days)
            connection.execute(
                text(
                    "INSERT INTO operations.access_tokens "
                    "(id,secret_digest,name,created_at,expires_at,max_requests,"
                    "budget_micro_usd,requests_per_minute) "
                    "VALUES (:id,:digest,:name,:now,:expires,:max_requests,:budget,:rate)"
                ),
                {
                    "id": token_id,
                    "digest": digest,
                    "name": options.name,
                    "now": now,
                    "expires": expires,
                    "max_requests": options.max_requests,
                    "budget": int(options.budget_usd * 1_000_000),
                    "rate": options.requests_per_minute,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO operations.access_usage "
                    "(token_id,admitted_requests,reserved_micro_usd,rate_count) VALUES (:id,0,0,0)"
                ),
                {"id": token_id},
            )
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {
        "created": True,
        "token_id": token_id,
        "name": options.name,
        "expires_at": expires,
        "secret_file": str(output),
    }


def list_tokens(engine):
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(TOKEN_REPORT_SQL + "ORDER BY t.created_at DESC LIMIT 1000")
            ).mappings()
        ]


def revoke_token(engine, token_id):
    token_id = identifier(token_id)
    with engine.begin() as connection:
        lock(connection)
        result = connection.execute(
            text(
                "UPDATE operations.access_tokens "
                "SET revoked_at=COALESCE(revoked_at,clock_timestamp()) "
                "WHERE id=:id"
            ),
            {"id": token_id},
        )
        if result.rowcount != 1:
            raise ValueError("Unknown token ID")
    return {"revoked": True, "token_id": token_id}


def update_token(engine, token_id, changes):
    token_id = identifier(token_id)
    with engine.begin() as connection:
        lock(connection)
        old = (
            connection.execute(
                text("SELECT * FROM operations.access_tokens WHERE id=:id"), {"id": token_id}
            )
            .mappings()
            .one()
        )
        if old["revoked_at"] is not None:
            raise ValueError("Revoked tokens cannot be reactivated")
        merged = {
            "name": old["name"],
            "max_requests": old["max_requests"],
            "budget_usd": Decimal(old["budget_micro_usd"]) / 1_000_000,
            "requests_per_minute": old["requests_per_minute"],
            **changes,
        }
        options = TokenOptions(**merged)
        expires = old["expires_at"]
        if "expires_in_days" in changes:
            expires = connection.scalar(text("SELECT clock_timestamp()")) + timedelta(
                days=options.expires_in_days
            )
        connection.execute(
            text(
                "UPDATE operations.access_tokens SET name=:name,max_requests=:max_requests, "
                "budget_micro_usd=:budget,requests_per_minute=:rate,"
                "expires_at=:expires WHERE id=:id"
            ),
            {
                "id": token_id,
                "name": options.name,
                "max_requests": options.max_requests,
                "budget": int(options.budget_usd * 1_000_000),
                "rate": options.requests_per_minute,
                "expires": expires,
            },
        )
    return {"updated": True, "token_id": token_id, "usage_preserved": True}


def token_usage(engine, token_id, limit=50):
    token_id = identifier(token_id)
    if not 1 <= limit <= 1000:
        raise ValueError("Invalid report limit")
    with engine.connect() as connection:
        token = (
            connection.execute(text(TOKEN_REPORT_SQL + "WHERE t.id=:id"), {"id": token_id})
            .mappings()
            .one_or_none()
        )
        if token is None:
            raise ValueError("Unknown token ID")
        requests = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT request_id,created_at,completed_at,reserved_micro_usd,"
                    "charged_micro_usd,usage_state,"
                    "pricing_version,summary FROM operations.access_requests "
                    "WHERE token_id=:id ORDER BY created_at DESC LIMIT :limit"
                ),
                {"id": token_id, "limit": limit},
            ).mappings()
        ]
    return {"token": dict(token), "requests": requests}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--output", required=True, type=Path)
    update = commands.add_parser("update")
    for subparser in (create, update):
        subparser.add_argument("--name", required=subparser is create)
        subparser.add_argument("--max-requests", type=int)
        subparser.add_argument("--budget-usd")
        subparser.add_argument("--requests-per-minute", type=int)
        subparser.add_argument("--expires-in-days", type=int)
    update.add_argument("token_id")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("token_id")
    commands.add_parser("list")
    usage = commands.add_parser("usage")
    usage.add_argument("token_id")
    usage.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    engine = None
    try:
        engine = create_database_engine(Settings())
        changes = {
            key: getattr(args, key)
            for key in TokenOptions.model_fields
            if getattr(args, key, None) is not None
        }
        if args.command == "create":
            result = create_token(engine, TokenOptions(**changes), args.output)
        elif args.command == "update":
            result = update_token(engine, args.token_id, changes)
        elif args.command == "revoke":
            result = revoke_token(engine, args.token_id)
        elif args.command == "usage":
            result = token_usage(engine, args.token_id, args.limit)
        else:
            result = {"tokens": list_tokens(engine)}
        print(json.dumps(result, default=str))
        return 0
    except SQLAlchemyError, OSError, ValidationError, ValueError:
        print(json.dumps({"status": "error", "error": {"category": "access_admin_failed"}}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

"""Explicit administrator policy configuration, status and crash recovery."""

import argparse
import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import EmbeddingSettings, LLMSettings, PublicDemoSettings, Settings
from app.db.connection import create_database_engine
from app.demo_gate import LOCK, PRICING_VERSION, DemoPolicy


def configure(engine, policy: DemoPolicy):
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
        if connection.scalar(text("SELECT count(*) FROM operations.demo_leases")):
            raise ValueError("Active leases prevent policy changes")
        connection.execute(
            text(
                "INSERT INTO operations.demo_policy(id, fingerprint) VALUES (1, :fingerprint) "
                "ON CONFLICT (id) DO UPDATE SET fingerprint=EXCLUDED.fingerprint"
            ),
            {"fingerprint": policy.fingerprint},
        )
    # Updating policy never resets monthly charges or request counts.


def status(engine):
    with engine.connect() as connection:
        return {
            "configured": connection.scalar(text("SELECT count(*) FROM operations.demo_policy"))
            == 1,
            "months": [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT month, charged_micro_usd, rate_minute, rate_count "
                        "FROM operations.demo_months ORDER BY month DESC LIMIT 12"
                    )
                ).mappings()
            ],
            "leases": [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT request_id, admitted_at FROM operations.demo_leases "
                        "ORDER BY admitted_at"
                    )
                ).mappings()
            ],
        }


def release_stale(engine, request_id: str):
    UUID(request_id)
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK})
        connection.execute(
            text("DELETE FROM operations.demo_leases WHERE request_id=:id"), {"id": request_id}
        )
        connection.execute(
            text(
                "UPDATE operations.access_requests SET completed_at=clock_timestamp(), "
                "summary=CAST(:summary AS jsonb) "
                "WHERE request_id=:id AND completed_at IS NULL"
            ),
            {
                "id": request_id,
                "summary": json.dumps(
                    {
                        "status": "error",
                        "error_category": "request_interrupted",
                        "usage_complete": False,
                    }
                ),
            },
        )
    # The potentially billed request remains charged, including after a crash.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--configure", action="store_true")
    commands.add_argument("--status", action="store_true")
    commands.add_argument("--release-stale", metavar="REQUEST_ID")
    parser.add_argument("--all-workers-stopped", action="store_true")
    args = parser.parse_args()
    if args.release_stale and not args.all_workers_stopped:
        parser.error(
            "Stop all API workers before releasing a stale lease; pass --all-workers-stopped"
        )
    engine = None
    try:
        engine = create_database_engine(Settings())
        if args.configure:
            demo = PublicDemoSettings()
            if not demo.public_demo_enabled:
                raise ValueError("Public demo controls must be enabled for configuration")
            policy = DemoPolicy.from_settings(demo, LLMSettings(), EmbeddingSettings())
            configure(engine, policy)
            result = {
                "configured": True,
                "pricing_version": PRICING_VERSION,
                "monthly_micro_usd": policy.monthly_micro_usd,
                "request_reservation_micro_usd": policy.request_micro_usd,
            }
        elif args.release_stale:
            release_stale(engine, args.release_stale)
            result = {"released": True, "charge_preserved": True}
        else:
            result = status(engine)
        print(json.dumps(result, default=str))
        return 0
    except SQLAlchemyError, OSError, ValidationError, ValueError:
        print(json.dumps({"status": "error", "error": {"category": "demo_admin_failed"}}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

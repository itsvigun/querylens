"""Provision database-scoped grants and dedicated login credentials."""

import sys

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import encrypt_password
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import Settings

ANALYTICS_ROLE = "querylens_analytics_ro"
KNOWLEDGE_ROLE = "querylens_knowledge_writer"
KNOWLEDGE_READER_ROLE = "querylens_knowledge_ro"


class RolePasswords(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    analytics_readonly_password: SecretStr = Field(min_length=16)
    knowledge_writer_password: SecretStr = Field(min_length=16)
    knowledge_readonly_password: SecretStr = Field(min_length=16)


def provision_roles(settings: Settings, passwords: RolePasswords) -> None:
    """Run as the dedicated local database administrator, after migrations.

    Roles are cluster-wide, so this command targets a dedicated QueryLens cluster.
    It refuses existing role memberships rather than inheriting unexpected access.
    """
    with psycopg2.connect(
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        **settings.database_connect_args,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(716202601)")
            profiles = (
                (ANALYTICS_ROLE, passwords.analytics_readonly_password, "analytics"),
                (KNOWLEDGE_ROLE, passwords.knowledge_writer_password, "knowledge"),
                (KNOWLEDGE_READER_ROLE, passwords.knowledge_readonly_password, "knowledge"),
            )
            if len({password.get_secret_value() for _, password, _ in profiles}) != 3:
                raise ValueError("Dedicated role passwords must differ")
            for role, password, schema in profiles:
                if password.get_secret_value() == settings.postgres_password.get_secret_value():
                    raise ValueError("Role passwords must differ from the administrator password")
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cursor.fetchone() is None:
                    cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
                cursor.execute(
                    "SELECT 1 FROM pg_auth_members WHERE member = "
                    "(SELECT oid FROM pg_roles WHERE rolname = %s)",
                    (role,),
                )
                if cursor.fetchone() is not None:
                    raise ValueError("Dedicated roles must not have any role memberships")
                cursor.execute(
                    "SELECT 1 FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass "
                    "AND refobjid = (SELECT oid FROM pg_roles WHERE rolname = %s) "
                    "AND deptype = 'o' LIMIT 1",
                    (role,),
                )
                if cursor.fetchone() is not None:
                    raise ValueError("Dedicated roles must not own database objects")
                # Hash client-side: the plaintext password is never sent in an SQL statement.
                verifier = encrypt_password(
                    password.get_secret_value(), role, connection, algorithm="scram-sha-256"
                )
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %s"
                    ).format(sql.Identifier(role)),
                    (verifier,),
                )
                cursor.execute(
                    sql.SQL("ALTER ROLE {} SET search_path TO pg_catalog, {}").format(
                        sql.Identifier(role), sql.Identifier(schema)
                    )
                )
                for setting, value in (
                    ("timezone", "UTC"),
                    ("statement_timeout", "5000"),
                    ("lock_timeout", "1000"),
                    ("default_transaction_read_only", "off" if role == KNOWLEDGE_ROLE else "on"),
                ):
                    cursor.execute(
                        sql.SQL("ALTER ROLE {} SET {} TO %s").format(
                            sql.Identifier(role), sql.Identifier(setting)
                        ),
                        (value,),
                    )

            if (
                passwords.analytics_readonly_password.get_secret_value()
                == passwords.knowledge_writer_password.get_secret_value()
            ):
                raise ValueError("Dedicated role passwords must differ")
            database = sql.Identifier(settings.postgres_db)
            cursor.execute(
                sql.SQL("REVOKE CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC").format(database)
            )
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute("REVOKE ALL ON SCHEMA analytics, knowledge FROM PUBLIC")
            cursor.execute("REVOKE ALL ON ALL TABLES IN SCHEMA analytics, knowledge FROM PUBLIC")
            for role, _, _ in profiles:
                identifier = sql.Identifier(role)
                cursor.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(database, identifier)
                )
                cursor.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, identifier)
                )
                cursor.execute(
                    sql.SQL("REVOKE ALL ON SCHEMA public, analytics, knowledge FROM {}").format(
                        identifier
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "REVOKE ALL ON ALL TABLES IN SCHEMA public, analytics, knowledge FROM {}"
                    ).format(identifier)
                )
                cursor.execute(
                    sql.SQL(
                        "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public, analytics, knowledge FROM {}"
                    ).format(identifier)
                )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA analytics TO {}").format(
                    sql.Identifier(ANALYTICS_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT ON analytics.users, analytics.orders, "
                    "analytics.events, analytics.subscriptions TO {}"
                ).format(sql.Identifier(ANALYTICS_ROLE))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA knowledge TO {}").format(
                    sql.Identifier(KNOWLEDGE_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA knowledge TO {}"
                ).format(sql.Identifier(KNOWLEDGE_ROLE))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA knowledge TO {}").format(
                    sql.Identifier(KNOWLEDGE_ROLE)
                )
            )
            # Default privileges apply to objects created by this migration owner only.
            cursor.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge "
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
                ).format(sql.Identifier(KNOWLEDGE_ROLE))
            )
            cursor.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge "
                    "GRANT USAGE, SELECT ON SEQUENCES TO {}"
                ).format(sql.Identifier(KNOWLEDGE_ROLE))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA knowledge TO {}").format(
                    sql.Identifier(KNOWLEDGE_READER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA knowledge TO {}").format(
                    sql.Identifier(KNOWLEDGE_READER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(KNOWLEDGE_READER_ROLE))
            )


def main() -> int:
    try:
        provision_roles(Settings(), RolePasswords())
    except psycopg2.Error, ValidationError, ValueError:
        print(
            "Role provisioning failed. Check local configuration and administrator access.",
            file=sys.stderr,
        )
        return 1
    print("Provisioned analytics reader, knowledge reader, and knowledge writer roles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

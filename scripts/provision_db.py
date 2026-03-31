from __future__ import annotations

import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import tuple_row

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.settings import settings  # noqa: E402


def database_exists(conn: psycopg.Connection, db_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        return cur.fetchone() is not None


def role_exists(conn: psycopg.Connection, role_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
        return cur.fetchone() is not None


def ensure_database(conn: psycopg.Connection, db_name: str) -> None:
    if database_exists(conn, db_name):
        print(f"Database exists: {db_name}")
        return

    print(f"Creating database: {db_name}")
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))


def ensure_role(conn: psycopg.Connection, role_name: str, password: str) -> None:
    if role_exists(conn, role_name):
        print(f"Role exists: {role_name}")
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(role_name),
                    sql.Literal(password),
                )
            )
        return

    print(f"Creating role: {role_name}")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role_name),
                sql.Literal(password),
            )
        )


def grant_db_privileges(conn: psycopg.Connection, db_name: str, role_name: str) -> None:
    print(f"Granting privileges on {db_name} to {role_name}")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                sql.Identifier(db_name), sql.Identifier(role_name)
            )
        )


def grant_schema_privileges(db_name: str, role_name: str) -> None:
    admin_dsn_db = settings.admin_dsn.replace("/postgres", f"/{db_name}")

    with psycopg.connect(admin_dsn_db, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("GRANT CONNECT, TEMP ON DATABASE {} TO {}").format(
                    sql.Identifier(db_name),
                    sql.Identifier(role_name),
                )
            )
            cur.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                    sql.Identifier(role_name)
                )
            )
            cur.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
                    "ON ALL TABLES IN SCHEMA public TO {}"
                ).format(sql.Identifier(role_name))
            )
            cur.execute(
                sql.SQL("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                    sql.Identifier(role_name)
                )
            )
            cur.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
                ).format(sql.Identifier(role_name))
            )
            cur.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {}"
                ).format(sql.Identifier(role_name))
            )


def role_owns_database(conn: psycopg.Connection, db_name: str, role_name: str) -> bool:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            SELECT pg_get_userbyid(datdba)
            FROM pg_database
            WHERE datname = %s
            """,
            (db_name,),
        )
        row = cur.fetchone()
        return row is not None and row[0] == role_name


def transfer_database_ownership(conn: psycopg.Connection, db_name: str, role_name: str) -> None:
    if role_owns_database(conn, db_name, role_name):
        return

    print(f"Assigning database owner for {db_name} -> {role_name}")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(db_name),
                sql.Identifier(role_name),
            )
        )


def main() -> None:
    admin_dsn = settings.admin_dsn
    db_name = settings.postgres_db
    app_user = settings.app_db_user
    app_password = settings.app_db_password

    print("Provisioning target:")
    print(f"  db: {db_name}")
    print(f"  app_user: {app_user}")
    print(f"  host: {settings.postgres_host}:{settings.postgres_port}")

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        ensure_database(conn, db_name)
        ensure_role(conn, app_user, app_password)
        transfer_database_ownership(conn, db_name, app_user)
        grant_db_privileges(conn, db_name, app_user)

    grant_schema_privileges(db_name, app_user)

    print("Provisioning complete.")


if __name__ == "__main__":
    main()

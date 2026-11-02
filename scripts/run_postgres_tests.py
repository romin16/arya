"""Run PostgreSQL integration tests in a uniquely named disposable database."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from dotenv import dotenv_values
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    admin_url = os.getenv("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    if not admin_url:
        raise SystemExit("DATABASE_URL is required to create a disposable test database")
    db_name = "arya_test_" + uuid4().hex[:12]
    parts = urlsplit(admin_url)
    test_url = urlunsplit((parts.scheme, parts.netloc, "/" + db_name, parts.query, parts.fragment))
    try:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(db_name)))
        with psycopg.connect(test_url) as connection:
            from db.apply_schema import MIGRATIONS, apply_migrations

            apply_migrations(connection, MIGRATIONS)
        environment = os.environ.copy()
        environment["ARYA_TEST_DATABASE_URL"] = test_url
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/integration", "-q"],
            cwd=ROOT,
            env=environment,
            check=False,
        )
        return result.returncode
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (db_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))


if __name__ == "__main__":
    raise SystemExit(main())

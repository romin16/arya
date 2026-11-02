"""Apply ordered, checksummed PostgreSQL migrations from the repository."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "db" / "migrations"
MIGRATION_RE = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")


def apply_migrations(connection, migration_dir: Path = MIGRATIONS, *, target_version: int | None = None) -> list[int]:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
             version integer PRIMARY KEY,
             name text NOT NULL,
             checksum text NOT NULL,
             applied_at timestamptz NOT NULL DEFAULT now()
           )"""
    )
    connection.commit()
    rows = connection.execute(
        "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied = {int(row[0]): (row[1], row[2]) for row in rows}
    ran: list[int] = []
    migration_files = []
    for path in sorted(migration_dir.glob("*.sql")):
        match = MIGRATION_RE.fullmatch(path.name)
        if not match:
            raise RuntimeError(f"Invalid migration filename: {path.name}")
        migration_files.append((int(match.group(1)), path))
    versions = [version for version, _ in migration_files]
    if len(versions) != len(set(versions)):
        raise RuntimeError("Migration version numbers must be unique")

    for version, path in migration_files:
        if target_version is not None and version > target_version:
            break
        content = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        previous = applied.get(version)
        if previous is not None:
            if previous != (path.name, checksum):
                raise RuntimeError(
                    f"Applied migration {version:03d} differs from its recorded name/checksum"
                )
            continue
        connection.execute(content.decode("utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations(version,name,checksum) VALUES (%s,%s,%s)",
            (version, path.name, checksum),
        )
        connection.commit()
        applied[version] = (path.name, checksum)
        ran.append(version)
        print(f"Applied schema migration {version:03d}: {path.name}")

    expected = versions if target_version is None else [version for version in versions if version <= target_version]
    missing = [version for version in expected if version not in applied]
    if missing:
        raise RuntimeError(f"Migrations did not apply cleanly; missing versions: {missing}")
    return ran


def main() -> int:
    load_dotenv(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required; set it in the project .env")
    with psycopg.connect(database_url) as connection:
        ran = apply_migrations(connection)
        row = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()
    version = int(row[0] or 0)
    if not ran:
        print("No pending database migrations.")
    print(f"Database schema is at version {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

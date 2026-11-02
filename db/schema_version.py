from __future__ import annotations

import psycopg

CURRENT_SCHEMA_VERSION = 2
MIGRATION_COMMAND = "uv run --no-sync python -m db.apply_schema"


async def ensure_schema_current(pool) -> None:
    try:
        async with pool.connection() as connection:
            row = await (await connection.execute(
                "SELECT max(version) AS version FROM schema_migrations",
            )).fetchone()
    except psycopg.errors.UndefinedTable as exc:
        raise RuntimeError(
            f"Database schema is not versioned. Apply migrations first: {MIGRATION_COMMAND}"
        ) from exc
    actual = int(row["version"] or 0)
    if actual < CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema is behind the application (version {actual}; "
            f"requires {CURRENT_SCHEMA_VERSION}). Apply migrations first: {MIGRATION_COMMAND}"
        )
    if actual > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {actual} is newer than this application supports "
            f"(version {CURRENT_SCHEMA_VERSION}). Update the application before starting core."
        )

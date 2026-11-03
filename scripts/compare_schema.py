"""Compare SQL column dependencies in the memory/action stores with PostgreSQL."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COLUMNS = {
    "schema_migrations": {"version", "name", "checksum", "applied_at"},
    "entities": {"id", "user_id", "key", "value", "confidence", "source", "valid_from", "valid_to", "superseded_by"},
    "episodes": {"id", "user_id", "thread_id", "ts", "summary", "body", "embedding", "topics", "tools_used", "tsv"},
    "knowledge_docs": {"id", "user_id", "title", "source", "created_at"},
    "knowledge_chunks": {"id", "user_id", "doc_id", "chunk_idx", "title", "text", "embedding", "metadata", "tsv"},
    "procedures": {"id", "user_id", "rule_text", "scope", "tool_pattern", "severity", "active", "created_at", "confidence", "argument_constraints", "inactive_at"},
    "patterns": {"id", "user_id", "text", "embedding", "confidence", "evidence_count", "pattern_key", "status", "first_seen", "last_seen"},
    "pattern_observations": {"id", "user_id", "pattern_key", "text", "observation_day", "observation_count", "first_seen", "last_seen"},
    "memory_tombstones": {"id", "user_id", "store", "fingerprint", "normalized_content", "created_at", "suppressed_until"},
    "pending_operations": {"id", "user_id", "thread_id", "operation_type", "payload", "created_at", "expires_at"},
    "action_log": {"id", "user_id", "thread_id", "tool_call_id", "ts", "tool", "args", "status", "result_summary", "approved_by", "approved_at", "approval_channel", "duration_ms"},
    "pii_vault": {"token", "kind", "value_enc", "created_at"},
}


def compare(connection) -> dict[str, tuple[set[str], set[str]]]:
    rows = connection.execute(
        """SELECT table_name,column_name FROM information_schema.columns
           WHERE table_schema=current_schema()"""
    ).fetchall()
    actual: dict[str, set[str]] = {}
    for table, column in rows:
        actual.setdefault(table, set()).add(column)
    return {
        table: (columns - actual.get(table, set()), actual.get(table, set()) - columns)
        for table, columns in EXPECTED_COLUMNS.items()
    }


def main() -> int:
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required; set it in the project .env")
    with psycopg.connect(url) as connection:
        differences = compare(connection)
        actual_rows = connection.execute(
            """SELECT table_name,column_name FROM information_schema.columns
               WHERE table_schema=current_schema() ORDER BY table_name,ordinal_position"""
        ).fetchall()
    actual: dict[str, list[str]] = {}
    for table, column in actual_rows:
        actual.setdefault(table, []).append(column)
    print("table | code columns | database columns | missing | database-only")
    for table, (missing, extra) in differences.items():
        print(
            f"{table} | {','.join(sorted(EXPECTED_COLUMNS[table]))} | "
            f"{','.join(actual.get(table, [])) or '(table missing)'} | "
            f"{','.join(sorted(missing)) or '-'} | {','.join(sorted(extra)) or '-'}"
        )
    return 1 if any(missing for missing, _ in differences.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())

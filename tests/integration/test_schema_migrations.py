from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from db.apply_schema import MIGRATIONS, apply_migrations

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.getenv("ARYA_TEST_DATABASE_URL"),
    reason="set ARYA_TEST_DATABASE_URL to a disposable PostgreSQL database",
)


def test_phase1_schema_upgrades_without_losing_rows_and_is_repeatable():
    database_url = os.environ["ARYA_TEST_DATABASE_URL"]
    schema = "upgrade_test_" + uuid4().hex[:12]
    with psycopg.connect(database_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.commit()
        try:
            connection.execute(
                sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)),
            )
            assert apply_migrations(connection, MIGRATIONS, target_version=1) == [1]
            assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 1

            connection.execute(
                "INSERT INTO entities(user_id,key,value) VALUES ('migration-test','employer','\"ARYA Labs\"')"
            )
            doc_id = connection.execute(
                "INSERT INTO knowledge_docs(user_id,title) VALUES ('migration-test','Existing doc') RETURNING id"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO knowledge_chunks(doc_id,chunk_idx,text) VALUES (%s,0,'Existing chunk')",
                (doc_id,),
            )
            connection.commit()

            assert apply_migrations(connection, MIGRATIONS) == [2]
            assert apply_migrations(connection, MIGRATIONS) == []
            assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 2
            assert connection.execute(
                "SELECT value FROM entities WHERE user_id='migration-test' AND key='employer'"
            ).fetchone()[0] == "ARYA Labs"
            assert connection.execute(
                "SELECT user_id,text FROM knowledge_chunks WHERE doc_id=%s", (doc_id,),
            ).fetchone() == ("migration-test", "Existing chunk")
            assert connection.execute(
                "SELECT confidence,argument_constraints,inactive_at FROM procedures LIMIT 0"
            ).description
            assert connection.execute(
                "SELECT pattern_key FROM patterns LIMIT 0"
            ).description
            assert connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema=%s "
                "AND table_name IN ('pending_operations','memory_tombstones','pattern_observations')",
                (schema,),
            ).fetchone()[0] == 3
            action_columns = {
                row[0] for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=%s AND table_name='action_log'", (schema,),
                ).fetchall()
            }
            assert {"tool_call_id", "approved_at", "approval_channel"} <= action_columns
        finally:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from db.apply_schema import MIGRATIONS, apply_migrations
from db.schema_check import validate_schema_reads
from core.memory.repositories import MemoryRepositories

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

            assert apply_migrations(connection, MIGRATIONS) == [2, 3]
            assert apply_migrations(connection, MIGRATIONS) == []
            assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 3
            assert connection.execute(
                "SELECT value FROM entities WHERE user_id='migration-test' AND key='employer'"
            ).fetchone()[0] == "ARYA Labs"
            assert connection.execute(
                "SELECT user_id,text FROM knowledge_chunks WHERE doc_id=%s", (doc_id,),
            ).fetchone() == ("migration-test", "Existing chunk")
            assert connection.execute(
                "SELECT title FROM knowledge_chunks WHERE doc_id=%s", (doc_id,),
            ).fetchone()[0] == "Existing doc"
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


def test_migration_is_not_recorded_when_its_expected_column_is_missing(tmp_path):
    database_url = os.environ["ARYA_TEST_DATABASE_URL"]
    schema = "verify_migration_" + uuid4().hex[:12]
    bad_migration = tmp_path / "003_knowledge_chunk_title.sql"
    bad_migration.write_text("SELECT 1;", encoding="utf-8")
    with psycopg.connect(database_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        connection.commit()
        try:
            assert apply_migrations(connection, MIGRATIONS, target_version=2) == [1, 2]
            with pytest.raises(RuntimeError, match="knowledge_chunks.title"):
                apply_migrations(connection, tmp_path)
            assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 2
        finally:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.asyncio
async def test_phase1_schema_runs_all_memory_store_read_and_write_paths():
    database_url = os.environ["ARYA_TEST_DATABASE_URL"]
    schema = "memory_upgrade_" + uuid4().hex[:12]
    with psycopg.connect(database_url) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        connection.commit()
        try:
            assert apply_migrations(connection, MIGRATIONS, target_version=1) == [1]
            doc_id = connection.execute(
                "INSERT INTO knowledge_docs(user_id,title,source) VALUES('u','Prior title','test') RETURNING id"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO knowledge_chunks(doc_id,chunk_idx,text) VALUES(%s,0,'prior text')", (doc_id,),
            )
            connection.commit()
            assert apply_migrations(connection, MIGRATIONS, target_version=2) == [2]
            connection.commit()
            probe = AsyncConnectionPool(
                conninfo=make_conninfo(database_url, options=f"-c search_path={schema},public"),
                min_size=1,
                max_size=1,
                open=False,
                kwargs={"autocommit": True, "row_factory": dict_row},
            )
            await probe.open(wait=True)
            try:
                with pytest.raises(RuntimeError, match="knowledge_chunks.title"):
                    await validate_schema_reads(probe)
            finally:
                await probe.close()
            assert apply_migrations(connection, MIGRATIONS) == [3]
        finally:
            connection.commit()

    conninfo = make_conninfo(database_url, options=f"-c search_path={schema},public")
    pool = AsyncConnectionPool(
        conninfo=conninfo, min_size=1, max_size=1, open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    await pool.open(wait=True)
    try:
        await validate_schema_reads(pool)
        repo = MemoryRepositories(pool)
        vector = [0.0] * 1536
        await repo.upsert_entity("u", "employer", "ARYA Labs")
        assert (await repo.current_entities("u"))[0]["value"] == "ARYA Labs"

        episode_id = await repo.add_episode("u", "thread", "Quarterly plan", "Plan for Q4", vector)
        assert episode_id is not None
        assert await repo.search_episodes("u", "quarterly plan", vector)

        knowledge_id = await repo.add_knowledge_chunk(
            "u", "New title", "test", "Knowledge body", vector,
        )
        knowledge = await repo.search_knowledge("u", "knowledge body", vector)
        assert knowledge and knowledge[0]["id"] == knowledge_id
        assert knowledge[0]["title"] == "New title"

        await repo.add_procedure(
            "u", "Never message Alex on WhatsApp", tool_pattern="whatsapp_send",
            argument_constraints=[{"argument": "contact", "value": "Alex"}],
        )
        assert (await repo.active_procedures("u"))[0]["tool_pattern"] == "whatsapp_send"

        observation = await repo.record_pattern_observation("u", "market-worry", "Market worry")
        assert observation["observations"] == 1
        pattern_id = await repo.add_pattern("u", "Market worry", vector, confidence=0.7)
        patterns = await repo.search_patterns("u", "market worry", vector)
        assert pattern_id is not None and patterns and patterns[0]["id"] == pattern_id
    finally:
        await pool.close()
        with psycopg.connect(database_url) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

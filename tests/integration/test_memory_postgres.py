from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from core.graph.runtime import (
    CoreGraphRuntime,
    LoadSkillArgs,
    MemoryEntity,
    MemoryEpisode,
    MemoryWrite,
    RouteDecision,
)
from core.memory.repositories import MemoryRepositories
from core.memory.service import MemoryService
from core.pii.vault import PIIVault
from core.skills_runtime import SkillsRuntime

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.getenv("ARYA_TEST_DATABASE_URL"),
    reason="set ARYA_TEST_DATABASE_URL to a disposable database with db/schema.sql applied",
)


class ScriptedRouter:
    async def ainvoke(self, messages):
        return RouteDecision(memory_intent="none")


class ScriptedAgent:
    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def astream(self, messages):
        user_text = next(message.content for message in reversed(messages) if isinstance(message, HumanMessage))
        lowered = user_text.casefold()
        if lowered.startswith("forget"):
            args = {"query": "Aditya", "confirm": False}
            yield _memory_forget_call(args, "forget-preview")
        elif lowered.strip(" .!\n") in {"confirm", "yes"}:
            args = {"query": "Aditya", "confirm": True}
            yield _memory_forget_call(args, "forget-confirm")
        else:
            yield AIMessageChunk(content="Saved for this test.")


class ScriptedWriter:
    def __init__(self, email: str | None = None):
        self.calls = 0
        self.email = email

    async def ainvoke(self, messages):
        self.calls += 1
        if self.email:
            return MemoryWrite(
                entities=[
                    MemoryEntity(key="employment", value="TCS"),
                    MemoryEntity(key="email_address", value=self.email),
                ],
                episode=MemoryEpisode(
                    summary=f"User email is {self.email}",
                    body=f"Remember this email: {self.email}",
                    topics=["contact details"],
                ),
                procedures=[{"rule_text": f"Never email {self.email}"}],
            )
        # Deliberately emulate the bad historical extraction: a rule and its
        # contact name are offered as entity facts. The service must reject them.
        return MemoryWrite(
            entities=[
                MemoryEntity(key="Aditya_rule", value="Aditya"),
                MemoryEntity(key="contact", value="Aditya"),
            ],
            episode=MemoryEpisode(
                summary="A standing WhatsApp contact rule was set.",
                body="Never message Aditya on WhatsApp again.",
            ),
        )


class FakeNetworkTool:
    name = "whatsapp_send"

    async def ainvoke(self, args):
        raise AssertionError("The hard rule must block this before the mocked network tool runs")


def _memory_forget_call(args, call_id):
    return AIMessageChunk(content="", tool_call_chunks=[{
        "name": "memory_forget",
        "args": json.dumps(args),
        "id": call_id,
        "index": 0,
    }])


async def _runtime(database_url: str, *, writer: ScriptedWriter, session: str):
    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=4,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True)
    saver = AsyncPostgresSaver(pool)
    await saver.setup()

    def persist(token: str, kind: str, encrypted: bytes):
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "INSERT INTO pii_vault(token,kind,value_enc) VALUES(%s,%s,%s) ON CONFLICT(token) DO NOTHING",
                (token, kind, encrypted),
            )

    def lookup(token: str):
        with psycopg.connect(database_url) as connection:
            row = connection.execute("SELECT kind,value_enc FROM pii_vault WHERE token=%s", (token,)).fetchone()
        return (row[0], bytes(row[1])) if row else None

    vault = PIIVault(b"integration-memory-secret", Fernet.generate_key(), persist=persist, lookup=lookup)
    embedded = []

    async def embed(text):
        embedded.append(text)
        return [0.001] * 1536

    memory = MemoryService(
        MemoryRepositories(pool), vault, embed, tombstone_suppression_days=14,
    )
    runtime = CoreGraphRuntime()
    runtime.pool = pool
    runtime.saver = saver
    runtime.vault = vault
    runtime.memory = memory
    runtime.memory_writer_model = writer
    runtime.router_model = ScriptedRouter()
    runtime.main_model = ScriptedAgent()
    runtime.skills = SkillsRuntime(ROOT / "skills")
    runtime.limits = {"max_tool_rounds": 8, "tool_timeout_seconds": 2, "token_budget": 100}
    runtime.persona = "Test persona"
    runtime.tools = {"whatsapp_send": FakeNetworkTool()}
    runtime.device_tools = runtime.tools

    async def load_skill(name: str):
        return runtime.skills.load(name, [])[0]

    runtime.load_skill_tool = StructuredTool.from_function(
        coroutine=load_skill, name="load_skill", description="Load a skill.", args_schema=LoadSkillArgs,
    )
    runtime.memory_tools = {
        "memory_search": StructuredTool.from_function(
            coroutine=runtime._memory_search_tool, name="memory_search", description="Search memory.",
        ),
        "memory_forget": StructuredTool.from_function(
            coroutine=runtime._memory_forget_tool, name="memory_forget", description="Preview and forget memory.",
        ),
    }
    runtime.graph = runtime._build_graph()
    runtime.session_id = session
    runtime.embedded = embedded
    return runtime


async def _drain_writer(runtime):
    while runtime.background_tasks:
        await asyncio.gather(*list(runtime.background_tasks), return_exceptions=True)


async def _turn(runtime, message, user_id):
    events = [event async for event in runtime.stream_turn(
        SimpleNamespace(message=message, user_id=user_id), runtime.session_id,
    )]
    await _drain_writer(runtime)
    return "".join(event.get("chunk", "") for event in events), events


@pytest.mark.asyncio
async def test_graph_forget_confirm_tombstone_dedup_and_writer_suppression():
    database_url = os.environ["ARYA_TEST_DATABASE_URL"]
    session = f"memory-forget-{uuid4().hex}"
    user_id = f"memory-user-{uuid4().hex}"
    writer = ScriptedWriter()
    runtime = await _runtime(database_url, writer=writer, session=session)
    try:
        rule = "Never message Aditya on WhatsApp again."
        first, _ = await _turn(runtime, rule, user_id)
        assert first == "Saved for this test."

        user_token = runtime.vault.tokenise(user_id)
        entities = await runtime.memory.repositories.current_entities(user_token)
        assert entities == []
        for phrase in (
            rule,
            "never   message Aditya on WhatsApp again",
            "NEVER message Aditya on WhatsApp again!",
        ):
            await runtime.memory.write_records(user_token, session, {}, user_texts=[phrase])
        active = await runtime.memory.repositories.active_procedures(user_token)
        assert len(active) == 1
        assert active[0]["tool_pattern"] == "whatsapp_send"
        assert active[0]["argument_constraints"][0]["value"] == "Aditya"

        preview, _ = await _turn(runtime, "Forget the rule about Aditya", user_id)
        assert "Found 1 matching memory item" in preview
        assert "Nothing was deleted" in preview
        assert len(await runtime.memory.repositories.active_procedures(user_token)) == 1

        confirmation, _ = await _turn(runtime, "confirm", user_id)
        assert confirmation == "Found 1 matching memory item(s). Deleted 1; 0 failed.\nDeleted:\n- procedures: Never message Aditya on WhatsApp again."
        assert len(await runtime.memory.repositories.active_procedures(user_token)) == 0
        assert writer.calls == 1  # Both forget turns skipped memory extraction.

        await runtime.memory.write_records(
            user_token, session, {}, user_texts=["never   message Aditya on WhatsApp again"],
        )
        assert len(await runtime.memory.repositories.active_procedures(user_token)) == 0
        async with runtime.pool.connection() as conn:
            tombstones = await (await conn.execute(
                "SELECT count(*) AS count FROM memory_tombstones WHERE user_id=%s AND store='procedure'",
                (user_token,),
            )).fetchone()
        assert tombstones["count"] == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_real_graph_tokenizes_email_before_entities_episodes_and_procedures():
    database_url = os.environ["ARYA_TEST_DATABASE_URL"]
    raw_email = f"memory-{uuid4().hex[:10]}@arya.dev"
    session = f"memory-pii-{uuid4().hex}"
    user_id = f"memory-pii-user-{uuid4().hex}"
    writer = ScriptedWriter(email=raw_email)
    runtime = await _runtime(database_url, writer=writer, session=session)
    try:
        reply, _ = await _turn(
            runtime,
            f"My employer is TCS and my email is {raw_email}. Never email {raw_email}.",
            user_id,
        )
        assert reply == "Saved for this test."
        assert raw_email not in repr(runtime.embedded)
        user_token = runtime.vault.tokenise(user_id)
        async with runtime.pool.connection() as conn:
            for table, predicate in (
                ("entities", "value::text ILIKE %s"),
                ("episodes", "(coalesce(summary,'')||' '||coalesce(body,'')) ILIKE %s"),
                ("procedures", "rule_text ILIKE %s"),
            ):
                row = await (await conn.execute(
                    f"SELECT count(*) AS count FROM {table} WHERE user_id=%s AND {predicate}",
                    (user_token, f"%{raw_email}%"),
                )).fetchone()
                assert row["count"] == 0, f"raw email persisted in {table}"
            entities = await (await conn.execute(
                "SELECT key,value FROM entities WHERE user_id=%s AND valid_to IS NULL", (user_token,),
            )).fetchall()
            assert any(row["key"] == "employer" for row in entities)
    finally:
        await runtime.close()

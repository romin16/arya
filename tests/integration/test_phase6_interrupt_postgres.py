from __future__ import annotations

import asyncio
import os
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

if asyncio.get_event_loop_policy().__class__.__name__ != "WindowsSelectorEventLoopPolicy" and os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

pytestmark = pytest.mark.skipif(
    not os.getenv("ARYA_TEST_DATABASE_URL"),
    reason="set ARYA_TEST_DATABASE_URL to a disposable database for the Postgres interrupt test",
)


class ApprovalState(TypedDict, total=False):
    question: str
    answer: dict


@pytest.mark.asyncio
async def test_installed_langgraph_interrupt_resume_with_postgres_checkpointer():
    pool = AsyncConnectionPool(
        conninfo=os.environ["ARYA_TEST_DATABASE_URL"], min_size=1, max_size=2,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True)
    saver = AsyncPostgresSaver(pool)
    await saver.setup()

    async def approval_node(state: ApprovalState):
        decision = interrupt({"question": state["question"]})
        return {"answer": decision}

    builder = StateGraph(ApprovalState)
    builder.add_node("approval", approval_node)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    graph = builder.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": f"phase6-b0-{uuid4().hex}"}}
    try:
        paused = await graph.ainvoke({"question": "Confirm this test operation?"}, config)
        interrupts = paused.get("__interrupt__", ())
        assert len(interrupts) == 1
        assert interrupts[0].value == {"question": "Confirm this test operation?"}

        resumed = await graph.ainvoke(Command(resume={"decision": "approve"}), config)
        assert resumed["answer"] == {"decision": "approve"}
    finally:
        await pool.close()

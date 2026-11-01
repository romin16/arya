"""ARYA core HTTP API and the browser's SSE contract."""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from contextlib import asynccontextmanager

import httpx
import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import APIConnectionError

from core.graph.runtime import CoreGraphRuntime
from core.sse import encode_event

# Psycopg's async libpq integration requires a selector loop on Windows.
if sys.platform == "win32" and not isinstance(
    asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy
):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger("arya.core.http")


def _is_connection_failure(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            ConnectionError,
            psycopg.OperationalError,
            APIConnectionError,
        )):
            return True
        current = current.__cause__ or current.__context__
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = CoreGraphRuntime()
    await runtime.start()
    app.state.runtime = runtime
    try:
        yield
    finally:
        await runtime.close()


app = FastAPI(title="arya-core", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str


class ApprovalRequest(BaseModel):
    thread_id: str
    decision: str
    edited_args: list[dict] | None = None


@app.get("/health")
async def health():
    runtime = getattr(app.state, "runtime", None)
    ready = runtime is not None and runtime.graph is not None
    return {
        "status": "healthy",
        "database": "connected" if ready else "not_initialized",
        "mcp": {"device": "connected" if ready else "not_initialized"},
        "device": "connected" if ready else "not_initialized",
        "observability": "disabled",
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    runtime = getattr(app.state, "runtime", None)

    async def events():
        yield encode_event({"session_id": session_id})
        try:
            if runtime is None:
                raise RuntimeError("Core runtime has not started")
            async for event in runtime.stream_turn(req, session_id):
                yield encode_event(event)
        except Exception as exc:
            logger.exception("Core chat turn failed")
            if _is_connection_failure(exc):
                yield encode_event({"chunk": "I couldn't reach my assistant services just now."})
                yield encode_event({"activity": {"event": "Error", "message": "Core service unavailable"}})
            else:
                yield encode_event({"chunk": "I hit an internal error while handling that request."})
                yield encode_event({"activity": {"event": "Error", "message": "Request failed"}})
        yield encode_event({"done": True})
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/approve")
async def approve(payload: ApprovalRequest):
    if payload.decision not in {"approve", "reject", "edit"}:
        return {"accepted": False, "detail": "decision must be approve, reject, or edit."}
    runtime = getattr(app.state, "runtime", None)
    if runtime is None:
        return {"accepted": False, "detail": "Core runtime has not started."}
    return await runtime.resume_approval(
        payload.thread_id, payload.decision, payload.edited_args,
    )

"""ARYA core HTTP contract. Graph construction is isolated for the next phase."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.sse import encode_event

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="arya-core")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str


@app.get("/health")
async def health():
    return {"status": "healthy", "database": "unconfigured" if not os.getenv("DATABASE_URL") else "unknown",
            "mcp": "not_initialized", "device": "unknown", "observability": "optional"}


@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    async def events():
        yield encode_event({"session_id": session_id})
        try:
            # Deliberately fail honestly until the configured graph is available.
            from core.graph.runtime import stream_turn
            async for event in stream_turn(req, session_id):
                yield encode_event(event)
        except Exception:
            yield encode_event({"chunk": "I couldn't reach my assistant services just now."})
            yield encode_event({"activity": {"event": "Error", "message": "Core service unavailable"}})
        yield encode_event({"done": True})
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/approve")
async def approve(payload: dict):
    return {"accepted": False, "detail": "No pending approval is active."}

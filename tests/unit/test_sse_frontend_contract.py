"""Replay the core SSE payloads against the contract consumed by frontend/arya.html."""
import json
from pathlib import Path

import httpx
import pytest

from core.app import app


ROOT = Path(__file__).resolve().parents[2]


def _decode_sse(body: str) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_sse_replay_matches_frontend_success_and_error_contract():
    frontend = (ROOT / "frontend" / "arya.html").read_text(encoding="utf-8")
    parser = frontend[frontend.index("if (d.session_id)"):frontend.index("} catch(e) { /* skip malformed lines */ }")]
    for field in ("session_id", "chunk", "activity", "done"):
        assert f"d.{field}" in parser

    class FakeRuntime:
        async def stream_turn(self, request, session_id):
            assert session_id == "sse-contract"
            yield {"activity": {"event": "Memory", "message": "Reading"}}
            yield {"chunk": "All set."}

    app.state.runtime = FakeRuntime()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as client:
        response = await client.post("/chat", json={
            "message": "Do it", "session_id": "sse-contract", "user_id": "user-test",
        })
    events = _decode_sse(response.text)
    assert response.status_code == 200
    assert [next(iter(event)) for event in events] == ["session_id", "activity", "chunk", "done"]
    assert events[0]["session_id"] == "sse-contract"
    assert events[1]["activity"]["event"] == "Memory"
    assert events[2]["chunk"] == "All set."
    assert events[-1] == {"done": True}

    class BrokenRuntime:
        async def stream_turn(self, request, session_id):
            raise RuntimeError("private internal detail")
            yield  # pragma: no cover

    app.state.runtime = BrokenRuntime()
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as client:
        response = await client.post("/chat", json={"message": "Do it", "user_id": "user-test"})
    error_events = _decode_sse(response.text)
    assert [next(iter(event)) for event in error_events] == ["session_id", "chunk", "activity", "done"]
    assert error_events[1] == {"chunk": "I hit an internal error while handling that request."}
    assert error_events[2] == {"activity": {"event": "Error", "message": "Request failed"}}
    assert error_events[-1] == {"done": True}
    assert "private internal detail" not in response.text

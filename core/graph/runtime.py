"""LangGraph runtime placeholder; refuses silent fallback to an unbacked chat."""


async def stream_turn(request, session_id: str):
    raise RuntimeError("LangGraph runtime has not been configured")
    yield  # pragma: no cover

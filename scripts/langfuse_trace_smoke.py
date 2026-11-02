"""Send one content-free trace to the already configured local Langfuse instance."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.runnables import RunnableLambda
from langfuse import get_client

from core.observability import langfuse_chat_trace, langfuse_startup_status, langfuse_trace_config
from core.pii.vault import PIIVault

ROOT = Path(__file__).resolve().parents[1]


async def main() -> int:
    load_dotenv(ROOT / ".env")
    os.environ["LANGFUSE_TRACING_ENABLED"] = "true"
    host = urlsplit(os.getenv("LANGFUSE_HOST", "")).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("LANGFUSE_HOST must point to the already running local instance")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    enabled, authenticated = langfuse_startup_status()
    if not enabled or not authenticated:
        print(f"Langfuse tracing enabled={str(enabled).lower()} auth_check={str(authenticated).lower()}")
        return 1

    vault = PIIVault.from_env()
    session_id = f"manual-smoke-{uuid4()}"
    user_id = os.getenv("ARYA_USER_ID") or "arya-local"
    config = langfuse_trace_config(vault=vault, session_id=session_id, user_id=user_id)
    async with langfuse_chat_trace(
        vault=vault,
        session_id=session_id,
        user_id=user_id,
        message="Manual Langfuse trace smoke check.",
    ):
        await RunnableLambda(lambda _value: {"status": "ok"}).with_config(
            run_name="smoke.agent",
        ).ainvoke({"message": "Manual Langfuse trace smoke check."}, config=config)
    await asyncio.to_thread(get_client().flush)
    print("Langfuse local trace export=complete; no model or external provider was called.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

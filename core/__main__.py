"""Launch the core with an asyncio loop supported by psycopg on Windows."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    import uvicorn

    uvicorn.run(
        "core.app:app",
        host=os.getenv("ARYA_CORE_HOST", "127.0.0.1"),
        port=int(os.getenv("ARYA_CORE_PORT", "5000")),
    )


if __name__ == "__main__":
    main()

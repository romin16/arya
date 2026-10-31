"""Launch the core with an asyncio loop supported by psycopg on Windows."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class FlushingStreamHandler(logging.StreamHandler):
    """Write each ARYA core log record through immediately for redirected logs."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_core_logging(stream=None) -> FlushingStreamHandler:
    handler = FlushingStreamHandler(stream or sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    core_logger = logging.getLogger("arya.core")
    core_logger.handlers.clear()
    core_logger.addHandler(handler)
    core_logger.setLevel(logging.INFO)
    core_logger.propagate = False
    return handler


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    import uvicorn

    configure_core_logging()
    uvicorn.run(
        "core.app:app",
        host=os.getenv("ARYA_CORE_HOST", "127.0.0.1"),
        port=int(os.getenv("ARYA_CORE_PORT", "5000")),
    )


if __name__ == "__main__":
    main()

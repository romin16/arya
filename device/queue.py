"""Run blocking desktop actions on one worker, preserving order even after timeout."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable


class SerialDesktopQueue:
    """One-at-a-time executor with per-action deadlines and queued-action panic."""

    def __init__(self, action_timeout: float = 30.0):
        if action_timeout <= 0:
            raise ValueError("action_timeout must be positive")
        self.action_timeout = action_timeout
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arya-device")
        self._lock = asyncio.Lock()
        self._generation = 0

    async def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        generation = self._generation
        async with self._lock:
            if generation != self._generation:
                raise asyncio.CancelledError("device action cancelled by panic")
            loop = asyncio.get_running_loop()
            call = partial(fn, *args, **kwargs)
            future = loop.run_in_executor(self._executor, call)
            try:
                deadline = self.action_timeout if timeout is None else timeout
                if deadline <= 0:
                    raise ValueError("timeout must be positive")
                result = await asyncio.wait_for(future, deadline)
            except TimeoutError as exc:
                raise TimeoutError("device action timed out") from exc
            if generation != self._generation:
                raise asyncio.CancelledError("device action cancelled by panic")
            return result

    def panic(self) -> None:
        """Cancel actions waiting in the queue; a running OS call cannot be killed safely."""
        self._generation += 1

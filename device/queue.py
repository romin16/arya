"""Single serial executor for blocking interactive-desktop operations."""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial


class SerialDesktopQueue:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arya-device")
        self._lock = asyncio.Lock()
        self._generation = 0

    async def run(self, fn, *args, timeout: float = 30):
        async with self._lock:
            generation = self._generation
            result = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(self._executor, partial(fn, *args)), timeout)
            if generation != self._generation:
                raise asyncio.CancelledError("device action cancelled by panic")
            return result

    def panic(self):
        self._generation += 1

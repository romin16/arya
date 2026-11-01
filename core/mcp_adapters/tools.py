from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any

import httpx
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel


class ToolRefused(RuntimeError):
    """A policy refusal raised before an external tool can execute."""


def transient_failure(error: BaseException) -> bool:
    if isinstance(error, (asyncio.TimeoutError, httpx.TimeoutException, httpx.NetworkError, ConnectionError)):
        return True
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status is None:
        status = getattr(error, "status_code", None)
    if status in {408, 425, 429, 500, 502, 503, 504}:
        return True
    return bool(re.search(r"\b(?:408|425|429|500|502|503|504)\b", str(error)))


class MCPToolAdapter:
    """Expose a LangChain MCP tool behind one bounded, retrying invocation."""

    def __init__(
        self,
        *,
        public_name: str,
        source_tool: BaseTool | None,
        description: str,
        timeout_seconds: float = 30,
        retries: int = 1,
        args_schema: type[BaseModel] | None = None,
        transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        refusal: str | None = None,
        error_label: str = "Google MCP tool",
    ):
        self.public_name = public_name
        self.source_tool = source_tool
        self.description = description
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)
        self.args_schema = args_schema or (source_tool.args_schema if source_tool else None)
        self.transform = transform or (lambda args: args)
        self.refusal = refusal
        self.error_label = error_label

    async def ainvoke(self, arguments: dict[str, Any]) -> Any:
        if self.refusal:
            return {
                "success": False,
                "approval_required": True,
                "message": self.refusal,
            }
        if self.source_tool is None:
            raise RuntimeError(f"{self.error_label} {self.public_name} is unavailable because its source tool is missing.")
        prepared = self.transform(arguments)
        for attempt in range(self.retries + 1):
            try:
                return await asyncio.wait_for(
                    self.source_tool.ainvoke(prepared), timeout=self.timeout_seconds
                )
            except Exception as exc:
                if attempt < self.retries and transient_failure(exc):
                    continue
                if isinstance(exc, asyncio.TimeoutError):
                    raise RuntimeError(
                        f"{self.error_label} {self.public_name} timed out after {self.timeout_seconds:g} seconds: {exc}"
                    ) from None
                if transient_failure(exc):
                    raise RuntimeError(
                        f"{self.error_label} {self.public_name} failed after a transient error and retry: {exc}"
                    ) from None
                raise RuntimeError(
                    f"{self.error_label} {self.public_name} failed: {exc}"
                ) from None

    def as_langchain_tool(self) -> StructuredTool:
        async def call(**arguments: Any) -> Any:
            return await self.ainvoke(arguments)

        return StructuredTool.from_function(
            coroutine=call,
            name=self.public_name,
            description=self.description,
            args_schema=self.args_schema,
        )

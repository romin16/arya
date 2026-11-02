"""Optional observability adapters with PII-safe Langfuse callbacks."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger("arya.core.observability")
_warned: set[str] = set()
_flush_threads: set[threading.Thread] = set()


def _enabled_by_config() -> bool:
    return os.getenv("LANGFUSE_TRACING_ENABLED", "true").strip().lower() not in {
        "0", "false", "no", "off",
    }


def _configured() -> bool:
    return _enabled_by_config() and all(os.getenv(key) for key in (
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
    )) and bool(os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST"))


def _warn_once(name: str, error: BaseException) -> None:
    if name in _warned:
        return
    _warned.add(name)
    logger.warning("%s observability disabled after %s", name, type(error).__name__)


def _tokenise_payload(value: Any, vault):
    """Recursively mask strings in callback payloads before an exporter sees them."""
    from langchain_core.messages import BaseMessage
    from pydantic import BaseModel

    if isinstance(value, str):
        return vault.tokenise(value)
    if isinstance(value, BaseException):
        return RuntimeError(vault.tokenise(str(value)))
    if isinstance(value, BaseMessage):
        return value.model_copy(update={
            "content": _tokenise_payload(value.content, vault),
            "additional_kwargs": _tokenise_payload(value.additional_kwargs, vault),
            "response_metadata": _tokenise_payload(value.response_metadata, vault),
        })
    if isinstance(value, dict):
        return {
            _tokenise_payload(key, vault): _tokenise_payload(item, vault)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_tokenise_payload(item, vault) for item in value]
    if isinstance(value, tuple):
        return tuple(_tokenise_payload(item, vault) for item in value)
    if isinstance(value, BaseModel):
        updates = {
            name: _tokenise_payload(getattr(value, name), vault)
            for name in type(value).model_fields
        }
        return value.model_copy(update=updates)
    return value


class PIISafeCallbackHandler(BaseCallbackHandler):
    """Sanitize every callback argument before delegating to Langfuse."""

    def __init__(self, downstream, vault, *, session_id: str = "", user_id: str = ""):
        self.downstream = downstream
        self.vault = vault
        self.disabled = False
        self.session_id = vault.tokenise(session_id) if session_id else ""
        self.user_id = vault.tokenise(user_id) if user_id else ""

    def _forward(self, event_name: str, *args, **kwargs):
        if self.disabled:
            return None
        try:
            safe_args = _tokenise_payload(args, self.vault)
            safe_kwargs = _tokenise_payload(kwargs, self.vault)
            return getattr(self.downstream, event_name)(*safe_args, **safe_kwargs)
        except Exception as exc:
            self.disabled = True
            _warn_once("Langfuse", exc)
            return None

    def on_chain_start(self, *args, **kwargs):
        return self._forward("on_chain_start", *args, **kwargs)

    def on_chain_end(self, *args, **kwargs):
        return self._forward("on_chain_end", *args, **kwargs)

    def on_chain_error(self, *args, **kwargs):
        return self._forward("on_chain_error", *args, **kwargs)

    def on_chat_model_start(self, *args, **kwargs):
        return self._forward("on_chat_model_start", *args, **kwargs)

    def on_llm_start(self, *args, **kwargs):
        return self._forward("on_llm_start", *args, **kwargs)

    def on_llm_new_token(self, *args, **kwargs):
        return self._forward("on_llm_new_token", *args, **kwargs)

    def on_llm_end(self, *args, **kwargs):
        return self._forward("on_llm_end", *args, **kwargs)

    def on_llm_error(self, *args, **kwargs):
        return self._forward("on_llm_error", *args, **kwargs)

    def on_tool_start(self, *args, **kwargs):
        return self._forward("on_tool_start", *args, **kwargs)

    def on_tool_end(self, *args, **kwargs):
        return self._forward("on_tool_end", *args, **kwargs)

    def on_tool_error(self, *args, **kwargs):
        return self._forward("on_tool_error", *args, **kwargs)

    def on_retriever_start(self, *args, **kwargs):
        return self._forward("on_retriever_start", *args, **kwargs)

    def on_retriever_end(self, *args, **kwargs):
        return self._forward("on_retriever_end", *args, **kwargs)

    def on_retriever_error(self, *args, **kwargs):
        return self._forward("on_retriever_error", *args, **kwargs)

    def on_agent_action(self, *args, **kwargs):
        return self._forward("on_agent_action", *args, **kwargs)

    def on_agent_finish(self, *args, **kwargs):
        return self._forward("on_agent_finish", *args, **kwargs)

    def on_retry(self, *args, **kwargs):
        return self._forward("on_retry", *args, **kwargs)

    def on_text(self, *args, **kwargs):
        return self._forward("on_text", *args, **kwargs)

    def on_custom_event(self, *args, **kwargs):
        return self._forward("on_custom_event", *args, **kwargs)


def langfuse_trace_config(*, vault, session_id: str, user_id: str) -> dict[str, Any]:
    """Create a per-turn callback config, or return an empty config if unavailable."""
    if not _configured():
        return {}
    try:
        from langfuse.langchain import CallbackHandler

        handler = PIISafeCallbackHandler(
            CallbackHandler(), vault, session_id=session_id, user_id=user_id,
        )
        return {
            "callbacks": [handler],
            "metadata": {
                "langfuse_session_id": vault.tokenise(session_id),
                "langfuse_user_id": vault.tokenise(user_id),
                "langfuse_trace_name": "arya.chat",
            },
            "run_name": "arya.chat",
        }
    except Exception as exc:
        _warn_once("Langfuse", exc)
        return {}


def langfuse_startup_status() -> tuple[bool, bool]:
    """Check credentials once at startup, without exposing any key material."""
    configured = _configured()
    enabled = False
    authenticated = False
    if configured:
        try:
            from langfuse import get_client
            from langfuse.langchain import CallbackHandler

            CallbackHandler()
            client = get_client()
            authenticated = bool(client.auth_check())
            enabled = True
            if not authenticated:
                _warn_once("Langfuse", RuntimeError("auth_check failed"))
        except Exception as exc:
            _warn_once("Langfuse", exc)
    logger.info(
        "Langfuse tracing startup enabled=%s auth_check=%s",
        str(enabled).lower(), str(authenticated).lower(),
    )
    return enabled, authenticated


def _schedule_flush(client) -> None:
    async def flush_async():
        try:
            await asyncio.to_thread(client.flush)
        except Exception as exc:
            _warn_once("Langfuse", exc)

    try:
        asyncio.get_running_loop().create_task(flush_async(), name="arya-langfuse-flush")
    except RuntimeError:
        def flush_sync():
            try:
                client.flush()
            except Exception as exc:
                _warn_once("Langfuse", exc)
            finally:
                _flush_threads.discard(threading.current_thread())

        thread = threading.Thread(target=flush_sync, name="arya-langfuse-flush", daemon=True)
        _flush_threads.add(thread)
        thread.start()


@contextlib.asynccontextmanager
async def langfuse_chat_trace(*, vault, session_id: str, user_id: str, message: str):
    """Create one PII-safe trace scope around an entire /chat request."""
    if not _configured():
        yield
        return
    try:
        from langfuse import get_client, propagate_attributes

        client = get_client()
        trace_input = {"message": vault.tokenise(message)}
        propagation_context = propagate_attributes(
            user_id=vault.tokenise(user_id),
            session_id=vault.tokenise(session_id),
            trace_name="arya.chat",
        )
        span_context = client.start_as_current_observation(
            name="arya.chat", as_type="span", input=trace_input,
        )
        propagation_context.__enter__()
        span = span_context.__enter__()
    except Exception as exc:
        _warn_once("Langfuse", exc)
        yield
        return
    try:
        try:
            yield
        except BaseException:
            with contextlib.suppress(Exception):
                span.update(output={"status": "failed"})
            raise
        else:
            with contextlib.suppress(Exception):
                span.update(output={"status": "completed"})
    finally:
        with contextlib.suppress(Exception):
            span_context.__exit__(None, None, None)
        with contextlib.suppress(Exception):
            propagation_context.__exit__(None, None, None)
        _schedule_flush(client)

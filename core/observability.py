"""Optional observability adapters with PII-safe Langfuse callbacks."""
from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger("arya.core.observability")
_warned: set[str] = set()
_logfire_configured = False


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

    def _forward(self, name: str, *args, **kwargs):
        if self.disabled:
            return None
        try:
            safe_args = _tokenise_payload(args, self.vault)
            safe_kwargs = _tokenise_payload(kwargs, self.vault)
            return getattr(self.downstream, name)(*safe_args, **safe_kwargs)
        except Exception as exc:
            self.disabled = True
            _warn_once("Langfuse", exc)
            return None

    def on_chain_start(self, *args, **kwargs):
        result = self._forward("on_chain_start", *args, **kwargs)
        parent_run_id = kwargs.get("parent_run_id")
        run_id = kwargs.get("run_id")
        if not self.disabled and parent_run_id is None and run_id is not None:
            try:
                span = getattr(self.downstream, "runs", {}).get(run_id)
                if span is not None and hasattr(span, "update_trace"):
                    span.update_trace(
                        name="arya.chat", session_id=self.session_id, user_id=self.user_id,
                    )
            except Exception as exc:
                self.disabled = True
                _warn_once("Langfuse", exc)
        return result

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
    if not all(os.getenv(key) for key in (
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST",
    )):
        _warn_once("Langfuse", RuntimeError("configuration missing"))
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
            },
            "run_name": "arya.chat",
        }
    except Exception as exc:
        _warn_once("Langfuse", exc)
        return {}


def configure_logfire(app) -> bool:
    """Enable infrastructure-only instrumentation. Content bodies stay disabled."""
    global _logfire_configured
    token = os.getenv("LOGFIRE_TOKEN")
    if not token:
        _warn_once("Logfire", RuntimeError("configuration missing"))
        return False
    if _logfire_configured:
        return True
    try:
        import logfire

        logfire.configure(token=token, send_to_logfire=True, inspect_arguments=False)
        logfire.instrument_fastapi(
            app,
            capture_headers=False,
            record_send_receive=False,
            request_attributes_mapper=lambda _request, _attributes: None,
        )
        logfire.instrument_psycopg()
        logfire.instrument_httpx(
            capture_all=False, capture_headers=False,
            capture_request_body=False, capture_response_body=False,
        )
        _logfire_configured = True
        return True
    except Exception as exc:
        _warn_once("Logfire", exc)
        return False

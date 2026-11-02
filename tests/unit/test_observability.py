from __future__ import annotations

import contextlib
import logging
from uuid import uuid4

from cryptography.fernet import Fernet
from langchain_core.messages import HumanMessage

from core.observability import (
    PIISafeCallbackHandler,
    langfuse_chat_trace,
    langfuse_startup_status,
    langfuse_trace_config,
)
from core.pii.vault import PIIVault


def _vault():
    return PIIVault(b"test-hmac-secret", Fernet.generate_key())


def test_langfuse_callback_exports_only_tokenised_content():
    class Sink:
        def __init__(self):
            self.received = None
            self.runs = {}

        def on_chat_model_start(self, *args, **kwargs):
            self.received = (args, kwargs)

        def on_chain_start(self, *args, **kwargs):
            self.runs[kwargs["run_id"]] = (args, kwargs)

    vault = _vault()
    sink = Sink()
    callback = PIISafeCallbackHandler(
        sink, vault, session_id="thread@example.org", user_id="alex@example.org",
    )
    raw = "Email alex@example.org or call +1 415-555-2671."
    callback.on_chat_model_start(
        {"name": "chat-model"}, [[HumanMessage(content=raw)]], run_id=uuid4(),
    )
    exported = repr(sink.received)
    assert "alex@example.org" not in exported
    assert "+1 415-555-2671" not in exported
    assert "[EMAIL_" in exported
    assert "[PHONE_" in exported

    run_id = uuid4()
    callback.on_chain_start({"name": "graph"}, {"input": raw}, run_id=run_id)
    exported_chain = repr(sink.runs[run_id])
    assert "alex@example.org" not in exported_chain
    assert "+1 415-555-2671" not in exported_chain
    assert "[EMAIL_" in exported_chain
    assert "[PHONE_" in exported_chain


def test_trace_config_attaches_callback_and_tokenised_metadata(monkeypatch):
    import langfuse.langchain

    class NoNetworkHandler:
        pass

    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", NoNetworkHandler)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    vault = _vault()
    config = langfuse_trace_config(
        vault=vault, session_id="thread@example.org", user_id="alex@example.org",
    )
    assert isinstance(config["callbacks"][0], PIISafeCallbackHandler)
    assert config["metadata"]["langfuse_session_id"] == vault.tokenise("thread@example.org")
    assert config["metadata"]["langfuse_user_id"] == vault.tokenise("alex@example.org")
    assert config["metadata"]["langfuse_trace_name"] == "arya.chat"


def test_chat_trace_context_exports_only_tokenised_input(monkeypatch):
    import langfuse
    import core.observability as observability

    class Span:
        def __init__(self):
            self.outputs = []

        def update(self, **kwargs):
            self.outputs.append(kwargs)

    class Client:
        def __init__(self):
            self.input = None
            self.span = Span()

        @contextlib.contextmanager
        def start_as_current_observation(self, *, name, as_type, input):
            assert as_type == "span"
            self.input = (name, input)
            yield self.span

        def flush(self):
            pass

    client = Client()
    monkeypatch.setattr(langfuse, "get_client", lambda: client)
    propagated = []
    monkeypatch.setattr(
        langfuse,
        "propagate_attributes",
        lambda **kwargs: (propagated.append(kwargs) or contextlib.nullcontext()),
    )
    monkeypatch.setattr(observability, "_schedule_flush", lambda _client: None)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    vault = _vault()

    async def use_trace():
        async with langfuse_chat_trace(
            vault=vault,
            session_id="thread@example.org",
            user_id="alex@example.org",
            message="Contact alex@example.org at +1 415-555-2671",
        ):
            pass

    import asyncio
    asyncio.run(use_trace())

    exported = repr((client.input, client.span.outputs, propagated))
    assert "alex@example.org" not in exported
    assert "+1 415-555-2671" not in exported
    assert "[EMAIL_" in exported
    assert "[PHONE_" in exported
    assert client.input[0] == "arya.chat"
    assert propagated[0]["session_id"] == vault.tokenise("thread@example.org")
    assert propagated[0]["user_id"] == vault.tokenise("alex@example.org")


def test_langfuse_startup_logs_status_without_credentials(monkeypatch, caplog):
    import langfuse
    import langfuse.langchain

    class Client:
        def auth_check(self):
            return True

    monkeypatch.setattr(langfuse, "get_client", lambda: Client())
    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", lambda: object())
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-secret-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    with caplog.at_level(logging.INFO, logger="arya.core.observability"):
        assert langfuse_startup_status() == (True, True)
    assert "Langfuse tracing startup enabled=true auth_check=true" in caplog.text
    assert "public-secret-test" not in caplog.text
    assert "secret-test" not in caplog.text


def test_langfuse_down_is_failure_safe_and_warns_once(monkeypatch, caplog):
    import langfuse
    import core.observability as observability

    def fail_client():
        raise RuntimeError("local service is down")

    monkeypatch.setattr(langfuse, "get_client", fail_client)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setattr(observability, "_warned", set())
    vault = _vault()

    async def use_trace():
        async with langfuse_chat_trace(
            vault=vault, session_id="thread", user_id="user", message="hello",
        ):
            return "chat continued"

    with caplog.at_level(logging.WARNING, logger="arya.core.observability"):
        import asyncio
        assert asyncio.run(use_trace()) == "chat continued"
        assert langfuse_startup_status() == (False, False)
    assert sum("Langfuse observability disabled" in row.message for row in caplog.records) == 1


def test_langfuse_can_be_disabled_for_tests_and_local_runs(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    assert langfuse_startup_status() == (False, False)
    assert langfuse_trace_config(vault=_vault(), session_id="thread", user_id="user") == {}

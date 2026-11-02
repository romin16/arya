from __future__ import annotations

import logging
from uuid import uuid4

from cryptography.fernet import Fernet
from langchain_core.messages import HumanMessage

from core.observability import (
    PIISafeCallbackHandler,
    configure_logfire,
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
            self.runs[kwargs["run_id"]] = self

        def update_trace(self, **kwargs):
            self.trace = kwargs

    vault = _vault()
    sink = Sink()
    callback = PIISafeCallbackHandler(sink, vault)
    raw = "Email alex@example.org or call +1 415-555-2671."
    callback.on_chat_model_start(
        {"name": "chat-model"},
        [[HumanMessage(content=raw)]],
        run_id=uuid4(),
    )
    exported = repr(sink.received)
    assert "alex@example.org" not in exported
    assert "+1 415-555-2671" not in exported
    assert "[EMAIL_" in exported
    assert "[PHONE_" in exported

    run_id = uuid4()
    callback.session_id = vault.tokenise("thread@example.org")
    callback.user_id = vault.tokenise("alex@example.org")
    callback.on_chain_start({"name": "graph"}, {"input": raw}, run_id=run_id)
    assert sink.trace["name"] == "arya.chat"
    assert sink.trace["session_id"] != "thread@example.org"
    assert sink.trace["user_id"] != "alex@example.org"


def test_trace_config_sets_tokenised_user_and_session(monkeypatch):
    import langfuse.langchain

    class NoNetworkHandler:
        pass

    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", NoNetworkHandler)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://127.0.0.1:3000")
    vault = _vault()
    config = langfuse_trace_config(
        vault=vault, session_id="thread@example.org", user_id="alex@example.org",
    )
    assert config["metadata"]["langfuse_session_id"] != "thread@example.org"
    assert config["metadata"]["langfuse_user_id"] != "alex@example.org"
    assert isinstance(config["callbacks"][0], PIISafeCallbackHandler)


def test_logfire_capture_bodies_are_disabled(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = []
    fake = SimpleNamespace(
        configure=lambda **kwargs: calls.append(("configure", kwargs)),
        instrument_fastapi=lambda app, **kwargs: calls.append(("fastapi", kwargs)),
        instrument_psycopg=lambda **kwargs: calls.append(("psycopg", kwargs)),
        instrument_httpx=lambda **kwargs: calls.append(("httpx", kwargs)),
    )
    monkeypatch.setenv("LOGFIRE_TOKEN", "test-only-token")
    monkeypatch.setitem(sys.modules, "logfire", fake)
    import core.observability as observability
    monkeypatch.setattr(observability, "_logfire_configured", False)
    assert configure_logfire(object())
    options = dict(calls)
    assert options["configure"]["inspect_arguments"] is False
    assert options["fastapi"]["record_send_receive"] is False
    assert options["fastapi"]["request_attributes_mapper"](object(), {"values": "sensitive"}) is None
    assert options["httpx"]["capture_request_body"] is False
    assert options["httpx"]["capture_response_body"] is False


def test_missing_or_failed_observability_warns_once_and_keeps_running(monkeypatch, caplog):
    import sys
    from types import SimpleNamespace

    import core.observability as observability

    monkeypatch.setattr(observability, "_warned", set())
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.setattr(observability, "_logfire_configured", False)
    with caplog.at_level(logging.WARNING, logger="arya.core.observability"):
        assert not configure_logfire(object())
        assert not configure_logfire(object())
    assert sum("Logfire observability disabled" in row.message for row in caplog.records) == 1

    monkeypatch.setenv("LOGFIRE_TOKEN", "test-only-token")
    monkeypatch.setitem(sys.modules, "logfire", SimpleNamespace(
        configure=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")),
    ))
    monkeypatch.setattr(observability, "_warned", set())
    with caplog.at_level(logging.WARNING, logger="arya.core.observability"):
        assert not configure_logfire(object())
        assert not configure_logfire(object())
    assert sum("Logfire observability disabled" in row.message for row in caplog.records) == 2

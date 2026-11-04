import pytest
import httpx

from core.pii.vault import PIIVault, StreamingDetokenizer
from core.pii.egress import guard_payload, sanitize_tool_schema
from core.graph.runtime import _scan_openai_payload


@pytest.fixture
def vault(monkeypatch):
    from cryptography.fernet import Fernet
    return PIIVault(b"test-only-hmac-secret", Fernet.generate_key())


def test_email_token_round_trip(vault):
    raw = "arya.test@example.com"
    masked = vault.tokenise(raw)
    assert raw not in masked
    assert masked == vault.tokenise(raw)
    assert vault.detokenise(masked) == raw.lower()


def test_streaming_token_split(vault):
    raw = "arya.test@example.com"
    token = vault.tokenise(raw)
    stream = StreamingDetokenizer(vault)
    output = stream.feed("To "+token[:8])
    output += stream.feed(token[8:])
    output += stream.feed(" now", final=True)
    assert output == "To "+raw.lower()+" now"


def test_unknown_token_is_rejected_for_tool_args(vault):
    with pytest.raises(ValueError, match="unknown token"):
        vault.detokenise_args({"to": "[EMAIL_abcdef]"})


def test_outbound_pii_is_tokenised_and_strict_mode_fails(vault):
    raw = "person" + "@arya" + ".dev"
    safe = guard_payload({"messages": [{"role": "user", "content": raw}]}, vault, strict=False)
    assert raw not in str(safe)
    assert "[EMAIL_" in str(safe)
    with pytest.raises(ValueError, match="raw EMAIL.*user message"):
        guard_payload({"messages": [{"role": "user", "content": raw}]}, vault, strict=True)


def test_guard_default_retokenizes_but_environment_flag_can_fail_closed(vault, monkeypatch):
    raw = "person" + "@arya" + ".dev"
    monkeypatch.setenv("PII_EGRESS_STRICT", "0")
    safe = guard_payload(raw, vault)
    assert raw not in safe
    assert "[EMAIL_" in safe
    monkeypatch.setenv("PII_EGRESS_STRICT", "1")
    with pytest.raises(ValueError, match="raw EMAIL"):
        guard_payload(raw, vault)


def test_reserved_example_addresses_and_fake_numbers_are_not_pii(vault):
    examples = "dev@example.com test@example.org fake@example.net unit@local.test bad@local.invalid, 1234567890, 202-555-0123"
    assert guard_payload(examples, vault, strict=True) == examples


def test_egress_log_has_kind_context_and_hash_without_value(vault, caplog):
    raw = "person" + "@arya" + ".dev"
    safe = guard_payload(
        {"messages": [{"role": "system", "content": "ARYA prompt\n\nActive skill instructions:\nContact " + raw}]},
        vault,
        strict=False,
    )
    assert raw not in str(safe)
    assert '"kind": "EMAIL"' in caplog.text
    assert '"location": "skill text"' in caplog.text
    assert '"path": "$' in caplog.text
    assert raw not in caplog.text


def test_tool_schema_examples_are_removed_and_redacted_in_logs(caplog):
    raw = "Use contact person" + "@arya" + ".dev or phone 202-555-0123."
    description, schema = sanitize_tool_schema(
        "search_email",
        raw,
        {"type": "object", "properties": {"query": {"type": "string", "description": raw}}},
    )
    serialized = str((description, schema))
    assert "example.com" not in serialized
    assert "202-555-0123" not in serialized
    assert "[email example removed]" in serialized
    assert '"event": "pii_tool_schema_sanitized"' in caplog.text
    assert raw not in caplog.text


@pytest.mark.asyncio
async def test_openai_request_retokenizes_genuine_email_by_default(vault, monkeypatch):
    monkeypatch.setenv("PII_EGRESS_STRICT", "0")
    raw = "person" + "@arya" + ".dev"
    request = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        json={"messages": [{"role": "user", "content": raw}]},
    )
    await _scan_openai_payload(vault)(request)
    assert raw not in request.content.decode()
    assert "[EMAIL_" in request.content.decode()

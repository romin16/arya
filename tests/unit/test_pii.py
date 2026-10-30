import pytest

from core.pii.vault import PIIVault, StreamingDetokenizer
from core.pii.egress import guard_payload


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
    safe = guard_payload({"messages": ["Contact arya.test@example.com"]}, vault)
    assert "arya.test@example.com" not in str(safe)
    with pytest.raises(ValueError, match="raw PII"):
        guard_payload("arya.test@example.com", vault, strict=True)

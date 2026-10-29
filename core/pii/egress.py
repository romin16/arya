"""Fail-closed guard for outbound model, embedding, and observability payloads."""
from __future__ import annotations
import json
import logging
from core.pii.vault import EMAIL_RE, PHONE_CANDIDATE_RE, PIIVault

logger = logging.getLogger("arya.pii")


def guard_text(text: str, vault: PIIVault, *, strict: bool = False) -> str:
    """Tokenise detected values; in strict test mode reject any raw PII found."""
    has_email = EMAIL_RE.search(text) is not None
    phone_matches = []
    for match in PHONE_CANDIDATE_RE.finditer(text):
        digits = "".join(c for c in match.group(0) if c.isdigit())
        if len(digits) >= 10:
            phone_matches.append(match.group(0))
    has_phone = bool(phone_matches)
    if not (has_email or has_phone):
        return text
    if has_phone and any(vault._normalise_phone(value) is None for value in phone_matches):
        logger.warning(json.dumps({"event": "pii_egress_blocked"}))
        raise ValueError("possible raw phone number could not be normalised")
    safe = vault.tokenise(text)
    logger.warning(json.dumps({"event": "pii_egress_blocked"}))
    raw_phone_remains = any(sum(c.isdigit() for c in m.group(0)) >= 10 for m in PHONE_CANDIDATE_RE.finditer(safe))
    if strict or EMAIL_RE.search(safe) or raw_phone_remains:
        raise ValueError("raw PII detected in outbound payload")
    return safe


def guard_payload(payload, vault: PIIVault, *, strict: bool = False):
    if isinstance(payload, str):
        return guard_text(payload, vault, strict=strict)
    if isinstance(payload, list):
        return [guard_payload(item, vault, strict=strict) for item in payload]
    if isinstance(payload, tuple):
        return tuple(guard_payload(item, vault, strict=strict) for item in payload)
    if isinstance(payload, dict):
        return {key: guard_payload(value, vault, strict=strict) for key, value in payload.items()}
    return payload

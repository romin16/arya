"""Inspect and re-tokenize PII in outbound model payloads."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re

from core.pii.vault import EMAIL_RE, PHONE_CANDIDATE_RE, PIIVault

logger = logging.getLogger("arya.pii")
_RESERVED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
_ACTIVE_SKILL_MARKER = "\n\nActive skill instructions:\n"


def _strict_mode(strict: bool | None) -> bool:
    if strict is not None:
        return strict
    return os.getenv("PII_EGRESS_STRICT", "0").strip().casefold() in {"1", "true", "yes", "on"}


def _reserved_example_email(value: str) -> bool:
    domain = value.rsplit("@", 1)[-1].rstrip(".>").casefold()
    return (
        any(domain == item or domain.endswith("." + item) for item in _RESERVED_EMAIL_DOMAINS)
        or domain.endswith(".test")
        or domain.endswith(".invalid")
    )


def _phone_digits(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def _obviously_fake_phone(value: str) -> bool:
    digits = _phone_digits(value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) < 10:
        return True
    if any(value in digits for value in ("0123456789", "1234567890", "0987654321", "9876543210")):
        return True
    return (
        len(set(digits)) == 1
        or digits in {"0123456789", "1234567890", "0987654321", "9876543210"}
        or (len(digits) == 10 and digits[:3] == "555")
        or (len(digits) == 10 and digits[3:6] == "555" and digits[6:8] == "01")
    )


def _log_detection(
    kind: str,
    value: str,
    location: str,
    path: str,
    *,
    strict: bool,
    event: str | None = None,
) -> None:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    logger.warning(json.dumps({
        "event": event or ("pii_egress_blocked" if strict else "pii_egress_retokenized"),
        "kind": kind,
        "location": location,
        "path": path,
        "hash": digest,
    }))


def sanitize_tool_schema(tool_name: str, description: str, schema: dict | None) -> tuple[str, dict | None]:
    """Remove all address/phone examples from a server-provided MCP schema."""
    def scrub_text(value: str, path: str) -> str:
        def email_sub(match: re.Match[str]) -> str:
            _log_detection(
                "EMAIL", match.group(0), "tool schema", path,
                strict=False, event="pii_tool_schema_sanitized",
            )
            return "[email example removed]"

        def phone_sub(match: re.Match[str]) -> str:
            digits = _phone_digits(match.group(0))
            if len(digits) < 10:
                return match.group(0)
            _log_detection(
                "PHONE", match.group(0), "tool schema", path,
                strict=False, event="pii_tool_schema_sanitized",
            )
            return "[phone example removed]"

        value = EMAIL_RE.sub(email_sub, value)
        return PHONE_CANDIDATE_RE.sub(phone_sub, value)

    def scrub(item, path: str):
        if isinstance(item, str):
            return scrub_text(item, path)
        if isinstance(item, list):
            return [scrub(value, f"{path}[{index}]") for index, value in enumerate(item)]
        if isinstance(item, dict):
            return {key: scrub(value, f"{path}.{key}") for key, value in item.items()}
        return item

    safe_description = scrub_text(description or "", f"tools.{tool_name}.description")
    return safe_description, scrub(schema, f"tools.{tool_name}.inputSchema") if schema else schema


def guard_text(
    text: str,
    vault: PIIVault,
    *,
    strict: bool | None = None,
    location: str = "payload",
    path: str = "$",
) -> str:
    """Retokenize genuine emails/phones; strict mode logs and rejects instead."""
    fail_closed = _strict_mode(strict)
    findings: list[tuple[str, str]] = []
    for match in EMAIL_RE.finditer(text):
        if not _reserved_example_email(match.group(0)):
            findings.append(("EMAIL", match.group(0)))
    for match in PHONE_CANDIDATE_RE.finditer(text):
        digits = _phone_digits(match.group(0))
        if len(digits) >= 10 and not _obviously_fake_phone(match.group(0)):
            findings.append(("PHONE", match.group(0)))

    if not findings:
        return text
    for kind, value in findings:
        _log_detection(kind, value, location, path, strict=fail_closed)
    if fail_closed:
        kinds = ", ".join(sorted({kind for kind, _ in findings}))
        raise ValueError(f"raw {kinds} detected in outbound payload at {location} ({path})")

    def replace_email(match: re.Match[str]) -> str:
        value = match.group(0)
        return value if _reserved_example_email(value) else vault.tokenise(value)

    def replace_phone(match: re.Match[str]) -> str:
        value = match.group(0)
        digits = _phone_digits(value)
        if len(digits) < 10 or _obviously_fake_phone(value):
            return value
        normalized = vault._normalise_phone(value) or value
        return vault._store("PHONE", normalized)

    safe = EMAIL_RE.sub(replace_email, text)
    return PHONE_CANDIDATE_RE.sub(replace_phone, safe)


def _message_location(role: str, parent: str) -> str:
    if role == "system":
        return "system prompt"
    if role == "user":
        return "user message"
    if role == "tool":
        return "tool result"
    return parent


def _guard_system_content(
    content: str,
    vault: PIIVault,
    *,
    strict: bool | None,
    path: str,
) -> str:
    if _ACTIVE_SKILL_MARKER not in content:
        return guard_text(content, vault, strict=strict, location="system prompt", path=path)
    prompt, skills = content.split(_ACTIVE_SKILL_MARKER, 1)
    prompt = guard_text(prompt, vault, strict=strict, location="system prompt", path=path)
    skills = guard_text(
        skills,
        vault,
        strict=strict,
        location="skill text",
        path=path + ".active_skill_instructions",
    )
    return prompt + _ACTIVE_SKILL_MARKER + skills


def guard_payload(
    payload,
    vault: PIIVault,
    *,
    strict: bool | None = None,
    location: str = "payload",
    path: str = "$",
):
    """Walk model request data with role/schema context and sanitize strings."""
    if isinstance(payload, str):
        return guard_text(payload, vault, strict=strict, location=location, path=path)
    if isinstance(payload, list):
        output = []
        for index, item in enumerate(payload):
            item_path = f"{path}[{index}]"
            if isinstance(item, dict) and item.get("role") in {"system", "user", "tool"}:
                output.append(guard_payload(
                    item,
                    vault,
                    strict=strict,
                    location=_message_location(str(item["role"]), location),
                    path=item_path,
                ))
            else:
                output.append(guard_payload(item, vault, strict=strict, location=location, path=item_path))
        return output
    if isinstance(payload, tuple):
        return tuple(
            guard_payload(item, vault, strict=strict, location=location, path=f"{path}[{index}]")
            for index, item in enumerate(payload)
        )
    if isinstance(payload, dict):
        role = payload.get("role")
        output = {}
        for key, item in payload.items():
            item_path = f"{path}.{key}"
            if role == "system" and key == "content" and isinstance(item, str):
                output[key] = _guard_system_content(item, vault, strict=strict, path=item_path)
            else:
                item_location = location
                if key in {"tools", "functions"}:
                    item_location = "tool schema"
                elif key in {"tool_result", "tool_results"}:
                    item_location = "tool result"
                output[key] = guard_payload(
                    item,
                    vault,
                    strict=strict,
                    location=item_location,
                    path=item_path,
                )
        return output
    return payload

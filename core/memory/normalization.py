"""Canonical identities and conservative parsing for memory records."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ENTITY_ALIASES = {
    "employment": "employer",
    "workplace": "employer",
    "company": "employer",
    "company_name": "employer",
    "employer_name": "employer",
    "job_employer": "employer",
    "current_employer": "employer",
    "home_city": "location",
    "current_city": "location",
    "city": "location",
    "preferred_music": "music_genre",
    "music_preference": "music_genre",
}

_PREFIX = re.compile(
    r"^\s*(?:(?:please\s+)?remember(?:\s+as\s+a\s+rule)?\s*[:,]?\s*|"
    r"from\s+now\s+on\s*[:,]?\s*|going\s+forward\s*[:,]?\s*)*",
    re.I,
)
_DIRECTIVE = re.compile(
    r"^\s*(?:please\s+)?(?P<directive>never|do\s+not|don't)\s+"
    r"(?P<action>message|text|contact|email|call|recommend|suggest|share|send|tell|mention|use|book|schedule)\b"
    r"(?P<rest>.*)$",
    re.I,
)


def normalize_text(value: str) -> str:
    value = re.sub(r"[^\w]+", " ", str(value).casefold(), flags=re.UNICODE)
    return " ".join(value.split())


def pattern_identity(value: str) -> str:
    """Stable non-reversible key shared with the PostgreSQL pattern index."""
    normalized = normalize_text(value)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def canonical_entity_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", normalize_text(value)).strip("_")
    return ENTITY_ALIASES.get(key, key)


def split_sentences(text: str) -> list[str]:
    return [item.strip(" \t\r\n\"'") for item in re.split(r"(?<=[.!?])\s+|\n+", text) if item.strip()]


def parse_explicit_rule(sentence: str) -> dict[str, Any] | None:
    candidate = _PREFIX.sub("", sentence, count=1)
    match = _DIRECTIVE.match(candidate)
    if not match:
        return None
    action = match.group("action").casefold()
    rest = match.group("rest").strip(" .,!?:;")
    rule_text = candidate.strip()
    lower = rule_text.casefold()
    tool_pattern = None
    constraints: list[dict[str, str]] = []

    if "whatsapp" in lower:
        tool_pattern = "whatsapp_voice_call" if action == "call" else "whatsapp_send"
        target_match = re.search(
            r"\b(?:message|text|contact)\s+(.+?)(?:\s+(?:on|via)\s+whatsapp\b|\s+again\b|\s+anymore\b|$)",
            rule_text,
            re.I,
        )
        if not target_match and action == "send":
            target_match = re.search(r"\bsend\s+(?:a\s+)?message\s+to\s+(.+?)(?:\s+(?:on|via)\s+whatsapp\b|\s+again\b|$)", rule_text, re.I)
        if target_match:
            target = target_match.group(1).strip(" .,!?:;")
            if target.casefold() not in {"me", "myself", "someone", "anyone", "people"}:
                constraints.append({"argument": "contact", "operator": "contains_casefold", "value": target})
    elif action == "email" or (action == "send" and "email" in lower):
        tool_pattern = "gmail_send"
    elif action in {"recommend", "suggest"}:
        # The prohibited subject is checked against query-like tool arguments.
        subject = re.sub(r"\s+(?:to me|for me|again|anymore|from now on|going forward)\b.*$", "", rest, flags=re.I)
        subject = subject.strip(" .,!?:;")
        if subject:
            tool_pattern = "*"
            constraints.append({"argument": "query", "operator": "contains_casefold", "value": subject})
    else:
        tool_pattern = "*"
        target = rest
        if action in {"message", "text", "contact", "call"}:
            target_match = re.match(r"\s*(?:to\s+)?(.+?)(?:\s+again\b|\s+anymore\b|\s+from\s+now\s+on\b|$)", rest, re.I)
            target = target_match.group(1) if target_match else rest
            argument = "contact"
        else:
            target = re.sub(r"\s+(?:to me|for me|again|anymore)\b.*$", "", rest, flags=re.I)
            argument = "query"
        target = target.strip(" .,!?:;")
        if target:
            constraints.append({"argument": argument, "operator": "contains_casefold", "value": target})

    return {
        "rule_text": rule_text,
        "scope": "global",
        "tool_pattern": tool_pattern,
        "argument_constraints": constraints,
        "severity": "hard",
        "confidence": 1.0,
    }


def explicit_user_rules(texts: list[str]) -> list[dict[str, Any]]:
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for text in texts:
        for sentence in split_sentences(text):
            record = parse_explicit_rule(sentence)
            if record is None:
                continue
            identity = (
                normalize_text(record["rule_text"]),
                normalize_text(record.get("tool_pattern") or ""),
                normalize_text(record["scope"]),
            )
            found.setdefault(identity, record)
    return list(found.values())


def soft_user_rules(texts: list[str]) -> list[dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    directed_preference = re.compile(
        r"^\s*(?:I\s+prefer\s+you\s+to|I'd\s+like\s+you\s+to|I\s+would\s+like\s+you\s+to|"
        r"please\s+try\s+to|please\s+avoid)\s+(.+)$",
        re.I,
    )
    for text in texts:
        for sentence in split_sentences(text):
            if parse_explicit_rule(sentence):
                continue
            match = directed_preference.match(sentence)
            if not match:
                continue
            rule_text = sentence.strip()
            lower = rule_text.casefold()
            preference = match.group(1).strip(" .,!?:;")
            if "whatsapp" in lower and any(v in lower for v in ("message", "text")):
                tool_pattern = "whatsapp_send"
                target_match = re.search(r"\b(?:message|text)\s+(.+?)(?:\s+(?:on|via)\s+whatsapp\b|$)", preference, re.I)
                constraints = ([{"argument": "contact", "operator": "contains_casefold", "value": target_match.group(1).strip()}]
                               if target_match else [])
            elif "email" in lower:
                tool_pattern = "gmail_send"
                constraints = []
            else:
                tool_pattern = "*"
                constraints = [{"argument": "query", "operator": "contains_casefold", "value": preference}]
            record = {
                "rule_text": rule_text,
                "scope": "global",
                "tool_pattern": tool_pattern,
                "argument_constraints": constraints,
                "severity": "soft",
                "confidence": 0.3,
            }
            found[(normalize_text(rule_text), normalize_text(tool_pattern or ""))] = record
    return list(found.values())


def is_recurring_first_person(text: str) -> bool:
    return bool(re.search(r"\bI\s+(?:usually|often|typically|frequently|regularly|tend\s+to)\b", text, re.I))


def fingerprint(store: str, payload: Any) -> str:
    if store == "procedure" and isinstance(payload, dict):
        normalized: Any = {
            "rule_text": normalize_text(payload.get("rule_text", "")),
            "tool_pattern": normalize_text(payload.get("tool_pattern") or ""),
            "scope": normalize_text(payload.get("scope") or "global"),
        }
    elif store == "entity" and isinstance(payload, dict):
        normalized = {
            "key": canonical_entity_key(str(payload.get("key", ""))),
            "value": _normalize_value(payload.get("value")),
        }
    else:
        normalized = _normalize_value(payload)
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{store}:{encoded}".encode("utf-8")).hexdigest()


def _normalize_value(value: Any):
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key).casefold(): _normalize_value(item) for key, item in sorted(value.items())}
    return value

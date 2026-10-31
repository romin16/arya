"""Deterministic enforcement for hard procedural memories."""
from __future__ import annotations

import fnmatch
import json
import re
from typing import Any

from core.memory.normalization import parse_explicit_rule


def hard_rule_for(tool_name: str, args: dict[str, Any], procedures: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the first active hard rule that explicitly covers this tool call."""
    rendered_args = json.dumps(args, ensure_ascii=False, default=str).casefold()
    for rule in procedures:
        if str(rule.get("severity", "")).casefold() != "hard":
            continue
        if not rule.get("active", True):
            continue
        parsed = parse_explicit_rule(str(rule.get("rule_text", "")))
        pattern = str(rule.get("tool_pattern") or (parsed or {}).get("tool_pattern") or "").strip()
        scope = str(rule.get("scope") or "global").strip()
        tool_matches = bool(pattern and fnmatch.fnmatchcase(tool_name.casefold(), pattern.casefold()))
        if not pattern and scope.casefold() in {tool_name.casefold(), f"tool:{tool_name}".casefold()}:
            tool_matches = True

        constraints = rule.get("argument_constraints") or (parsed or {}).get("argument_constraints", [])
        if tool_matches and constraints:
            if all(_constraint_matches(args, constraint) for constraint in constraints):
                return rule
            continue
        if tool_matches and pattern:
            return rule
        if not pattern and scope.casefold() == "global" and not constraints:
            # Legacy hard rules like "Never recommend equity" can still be
            # enforced before their next load/backfill adds structured fields.
            match = re.search(r"\b(?:never|do not|don't)\s+(?:recommend|suggest|use|send|share)\s+(.+?)(?:\s+to me|\s+again|[.!?]|$)", str(rule.get("rule_text", "")), re.I)
            if match:
                subject = match.group(1).strip(" '\".,!?;:").casefold()
                if len(subject) >= 3 and subject in rendered_args:
                    return rule

        # Rules such as "Never recommend equity" apply when the prohibited
        # subject is part of the proposed tool arguments. This is deliberately
        # conservative: vague rules do not block unrelated tool calls.
    return None


def _constraint_matches(args: dict[str, Any], constraint: dict[str, Any]) -> bool:
    key = str(constraint.get("argument", ""))
    operator = str(constraint.get("operator", "contains_casefold"))
    expected = str(constraint.get("value", "")).casefold()
    if not key or not expected:
        return False
    value = next((item for name, item in args.items() if str(name).casefold() == key.casefold()), None)
    values = _flatten_values(value)
    for candidate in values:
        actual = str(candidate).casefold()
        if operator in {"contains_casefold", "token_contains_casefold"} and expected in actual:
            return True
        if operator in {"equals_casefold", "token_equals_casefold"} and expected == actual:
            return True
    return False


def _flatten_values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten_values(child)]
    if isinstance(value, (list, tuple, set)):
        return [item for child in value for item in _flatten_values(child)]
    return [] if value is None else [value]

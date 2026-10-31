"""Deterministic enforcement for hard procedural memories."""
from __future__ import annotations

import fnmatch
import json
import re
from typing import Any


def hard_rule_for(tool_name: str, args: dict[str, Any], procedures: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the first active hard rule that explicitly covers this tool call."""
    rendered_args = json.dumps(args, ensure_ascii=False, default=str).casefold()
    for rule in procedures:
        if str(rule.get("severity", "")).casefold() != "hard":
            continue
        if rule.get("active", True) is False:
            continue
        pattern = str(rule.get("tool_pattern") or "").strip()
        scope = str(rule.get("scope") or "global").strip()
        if pattern and fnmatch.fnmatchcase(tool_name.casefold(), pattern.casefold()):
            return rule
        if scope.casefold() in {tool_name.casefold(), f"tool:{tool_name}".casefold()}:
            return rule

        # Rules such as "Never recommend equity" apply when the prohibited
        # subject is part of the proposed tool arguments. This is deliberately
        # conservative: vague rules do not block unrelated tool calls.
        match = re.search(r"\b(?:never|do not|don't)\s+(?:recommend|suggest|use|send|share)\s+(.+?)(?:\s+to me|\s+again|[.!?]|$)", str(rule.get("rule_text", "")), re.I)
        if match:
            subject = match.group(1).strip(" '\".,!?;:").casefold()
            if len(subject) >= 3 and subject in rendered_args:
                return rule
    return None

"""Config-driven, deterministic tool policy decisions."""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml


class ToolPolicy:
    def __init__(self, config: dict[str, Any], registered_tools: set[str]):
        entries = config.get("tools", {})
        if not isinstance(entries, dict):
            raise ValueError("config/policy.yaml tools must be a mapping")
        self.entries: dict[str, str] = {}
        self.registered_tools = set(registered_tools)
        self.injection_taint_escalation = bool(config.get("injection_taint_escalation", True))
        self.approval_timeout_seconds = max(1, int(config.get("approval_timeout_seconds", 120)))
        approval = config.get("approval", {})
        if not isinstance(approval, dict):
            raise ValueError("config/policy.yaml approval must be a mapping")
        self.edit_requires_reconfirm = bool(approval.get("edit_requires_reconfirm", True))
        for pattern, entry in entries.items():
            mode = entry.get("mode") if isinstance(entry, dict) else entry
            if mode not in {"auto", "ask", "block"}:
                raise ValueError(f"Invalid policy mode for {pattern!r}: {mode!r}")
            matches = {name for name in registered_tools if fnmatch.fnmatchcase(name, pattern)}
            if not matches:
                raise ValueError(f"Policy key {pattern!r} does not match any registered tool")
            self.entries[pattern] = mode

    @classmethod
    def from_file(cls, path: Path, registered_tools: set[str]) -> "ToolPolicy":
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(config, registered_tools)

    def mode_for(self, tool_name: str, arguments: dict[str, Any] | None = None, *, tainted: bool = False) -> str:
        del arguments  # Reserved for argument-sensitive policy rules; tool semantics remain code-owned.
        if tool_name not in self.registered_tools:
            return "block"
        matches = [pattern for pattern in self.entries if fnmatch.fnmatchcase(tool_name, pattern)]
        if not matches:
            return "block"
        # The most specific matching glob wins; exact names beat broad safety defaults.
        pattern = max(matches, key=lambda value: (sum(char not in "*?[]" for char in value), len(value)))
        mode = self.entries[pattern]
        if tainted and self.injection_taint_escalation and mode == "auto" and _has_side_effect(tool_name):
            return "ask"
        return mode


def _has_side_effect(tool_name: str) -> bool:
    name = tool_name.casefold()
    return any(part in name for part in (
        "create", "update", "delete", "send", "reply", "trash", "type_text", "run_command",
        "open_app", "close_app", "set_volume", "spotify_play", "spotify_pause", "spotify_resume",
        "spotify_next", "spotify_previous", "whatsapp_voice_call", "calendar_move", "calendar_respond",
        "gmail_archive", "gmail_mark_read", "gmail_mark_unread", "contacts_save_other",
    ))

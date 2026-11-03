"""Runtime guard for phrases prohibited in ARYA's spoken replies."""
from __future__ import annotations

import re

_BANNED_REPLACEMENTS = (
    (re.compile(r"\benjoy\b", re.IGNORECASE), "Try"),
    (re.compile(r"\bof\s+course\b", re.IGNORECASE), "Yes"),
    (re.compile(r"\bsure\b", re.IGNORECASE), "Done"),
    (re.compile(r"\bcertainly\b", re.IGNORECASE), "Done"),
)


def sanitize_persona_text(text: str) -> str:
    for pattern, replacement in _BANNED_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


class PersonaReplyGuard:
    """Hold a short suffix so prohibited phrases split across chunks are caught."""

    _HOLD = 16

    def __init__(self) -> None:
        self.pending = ""

    def feed(self, chunk: str, *, final: bool = False) -> str:
        self.pending += chunk
        if final:
            output = sanitize_persona_text(self.pending)
            self.pending = ""
            return output
        safe_end = max(0, len(self.pending) - self._HOLD)
        if not safe_end:
            return ""
        boundary = max(self.pending.rfind(" ", 0, safe_end), self.pending.rfind("\n", 0, safe_end))
        if boundary < 0:
            return ""
        output = sanitize_persona_text(self.pending[: boundary + 1])
        self.pending = self.pending[boundary + 1 :]
        return output

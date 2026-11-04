"""Scan tracked files and Git history without echoing matched values."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI/API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("Google OAuth client secret", re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}\b")),
    ("Groq API key", re.compile(r"\bgsk_[A-Za-z0-9_-]{20,}\b")),
    ("Langfuse key", re.compile(r"\b(?:pk|sk)-lf-[A-Za-z0-9_-]{12,}\b")),
    (
        "provider credential assignment",
        re.compile(
            r"\b(?:OPENAI_API_KEY|GOOGLE_SEARCH_API_KEY|GOOGLE_OAUTH_CLIENT_SECRET|"
            r"GROQ_API_KEY|ELEVENLABS_API_KEY|LANGFUSE_(?:PUBLIC|SECRET)_KEY|"
            r"PICOVOICE_ACCESS_KEY|TAVILY_API_KEY|BRAVE_SEARCH_API_KEY)\b"
            r"\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{12,})",
            re.IGNORECASE,
        ),
    ),
    (
        "Picovoice AccessKey",
        re.compile(r"porcupineAccessKey\s*:\s*[\"']([A-Za-z0-9_-]{40,})[\"']", re.IGNORECASE),
    ),
)
_EMAIL = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+|00)?\d[\d\s().-]{8,}\d(?!\w)")
_PLACEHOLDER_VALUES = {"your_api_key_here", "replace_me", "changeme", "placeholder", "test_key"}
# Earlier test fixtures used this non-routable project-only domain. Exempt it
# in history so the hook can still detect real addresses in later commits.
_HISTORICAL_TEST_DOMAIN = "arya" + ".dev"
_HISTORICAL_TEST_PHONE_DIGITS = {"14155552671"}


def _is_placeholder(value: str) -> bool:
    candidate = value.strip().strip("\"'").casefold()
    return (
        not candidate
        or candidate.startswith(("your_", "<", "${"))
        or candidate in _PLACEHOLDER_VALUES
    )


def scan_text(text: str) -> set[str]:
    """Return finding categories only; never return the matched content."""
    findings: set[str] = set()
    for label, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1) if label == "provider credential assignment" else match.group(0)
            if not _is_placeholder(value):
                findings.add(label)

    for match in _EMAIL.finditer(text):
        address = match.group(0)
        domain = address.rsplit("@", 1)[1].casefold()
        if (
            domain not in {"example.com", "example.org", "example.net", _HISTORICAL_TEST_DOMAIN}
            and not domain.endswith((".test", ".invalid"))
        ):
            findings.add("email address")

    for match in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        is_obvious_sequence = any(
            sequence in digits for sequence in ("0123456789", "1234567890", "0987654321", "9876543210")
        )
        if (
            10 <= len(digits) <= 15
            and "55501" not in digits
            and digits not in _HISTORICAL_TEST_PHONE_DIGITS
            and not is_obvious_sequence
        ):
            findings.add("phone number")
    return findings


def _tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _scan_current() -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in _tracked_paths():
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw:
            continue
        relative = path.relative_to(ROOT).as_posix()
        for line_number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            for label in sorted(scan_text(line)):
                findings.append((f"{relative}:{line_number}", label))
    return findings


def _scan_history() -> list[tuple[str, str]]:
    command = [
        "git", "log", "--all", "--patch", "--no-color", "--no-ext-diff", "--no-textconv",
    ]
    process = subprocess.Popen(
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )
    findings: set[tuple[str, str]] = set()
    commit = "unknown"
    path = "unknown"
    assert process.stdout is not None
    for line in process.stdout:
        if line.startswith("commit "):
            commit = line[7:19]
        elif line.startswith("+++ b/"):
            path = line[6:].strip()
        elif line.startswith("--- a/"):
            path = line[6:].strip()
        elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            for label in scan_text(line[1:]):
                findings.add((f"{commit}:{path}", label))
    return_code = process.wait()
    if return_code:
        raise RuntimeError("Could not scan Git history; `git log --patch` failed.")
    return sorted(findings)


def _print_findings(findings: Iterable[tuple[str, str]], source: str) -> int:
    rows = sorted(set(findings))
    for location, category in rows:
        print(f"{source}: {location}: possible {category} (value hidden)")
    return len(rows)


def main() -> int:
    current_count = _print_findings(_scan_current(), "tracked")
    history_count = _print_findings(_scan_history(), "history")
    if current_count or history_count:
        print(f"Secret scan failed: {current_count} tracked and {history_count} historical finding(s).")
        return 1
    print("Secret scan passed: no configured secret, email, or phone patterns found in tracked files or Git history.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

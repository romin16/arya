import re
from pathlib import Path

import yaml

from core.persona import PersonaReplyGuard, sanitize_persona_text


ROOT = Path(__file__).resolve().parents[2]
BANNED = re.compile(r"\b(?:enjoy|sure|of course|certainly)\b", re.IGNORECASE)


def test_persona_is_compact_and_avoids_banned_phrases():
    persona = (ROOT / "persona.md").read_text(encoding="utf-8")
    # A conservative word count keeps the persona plus the compact skill index small.
    assert len(persona.split()) < 220
    assert not BANNED.search(persona)


def test_persona_tone_eval_cases_are_present_and_banned_phrases_checked():
    cases = yaml.safe_load((ROOT / "evals/datasets/persona-tone.yaml").read_text(encoding="utf-8"))
    assert len(cases) >= 4
    assert all(case.get("expected_tone") for case in cases)
    assert any(case["utterance"].casefold().startswith("play lofi") for case in cases)
    assert BANNED.search("Enjoy the mellow beats!")
    assert BANNED.search("Sure!")
    assert BANNED.search("Of course!")


def test_runtime_persona_guard_rewrites_banned_phrases_across_stream_chunks():
    guard = PersonaReplyGuard()
    output = "".join([
        guard.feed("Enjoy"),
        guard.feed(" the mellow "),
        guard.feed("beats!"),
        guard.feed("", final=True),
    ])
    assert output == "Try the mellow beats!"
    assert not BANNED.search(output)
    assert sanitize_persona_text("Sure. Of course. Certainly.") == "Done. Yes. Done."

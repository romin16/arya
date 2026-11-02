from pathlib import Path

import pytest
import yaml

from core.policy_gate import ToolPolicy


def test_policy_uses_configured_mode_and_most_specific_tool_match():
    policy = ToolPolicy.from_file(Path("config/policy.yaml"), {
        "gmail_send", "gmail_search", "whatsapp_send", "whatsapp_voice_call", "close_app",
        "open_app", "set_volume", "type_text", "take_screenshot", "spotify_play",
        "vscode_open", "vscode_search", "vscode_format", "vscode_run_command", "gmail_reply",
        "gmail_delete", "calendar_delete", "calendar_delete_calendar", "contacts_delete",
        "web_search",
    })
    assert policy.mode_for("gmail_send", {"to": ["person@example.test"], "body": "Hi"}) == "ask"
    assert policy.mode_for("whatsapp_send", {"contact": "test contact", "message": "Hi"}) == "ask"
    assert policy.mode_for("vscode_run_command", {"command": "dir"}) == "ask"
    assert policy.mode_for("gmail_search", {"query": "from:me"}) == "auto"
    assert policy.mode_for("close_app", {"app": "Notepad"}) == "auto"
    assert policy.mode_for("not_registered", {}) == "block"


def test_every_policy_key_must_match_a_registered_tool():
    with pytest.raises(ValueError, match="does not match any registered tool"):
        ToolPolicy({"tools": {"gmail_sned": {"mode": "ask"}}}, {"gmail_send"})


def test_policy_rejects_unknown_modes():
    with pytest.raises(ValueError, match="Invalid policy mode"):
        ToolPolicy({"tools": {"*": {"mode": "maybe"}}}, {"gmail_send"})


def test_taint_escalates_only_auto_side_effects():
    policy = ToolPolicy({
        "injection_taint_escalation": True,
        "tools": {"*": {"mode": "auto"}},
    }, {"contacts_create", "gmail_search", "calculator"})
    assert policy.mode_for("contacts_create", {"given_name": "Test"}, tainted=True) == "ask"
    assert policy.mode_for("gmail_search", {"query": "robotics"}, tainted=True) == "auto"
    assert policy.mode_for("calculator", {"expression": "2+2"}, tainted=True) == "auto"


def test_approval_edit_reconfirmation_defaults_on_and_is_configurable():
    default = ToolPolicy({"tools": {"*": {"mode": "ask"}}}, {"gmail_send"})
    disabled = ToolPolicy({
        "approval": {"edit_requires_reconfirm": False},
        "tools": {"*": {"mode": "ask"}},
    }, {"gmail_send"})
    assert default.edit_requires_reconfirm is True
    assert disabled.edit_requires_reconfirm is False


def test_live_approval_eval_cases_match_configured_policy():
    root = Path(__file__).resolve().parents[2]
    cases = yaml.safe_load((root / "evals/datasets/approvals.yaml").read_text(encoding="utf-8"))
    config = yaml.safe_load((root / "config/policy.yaml").read_text(encoding="utf-8"))
    policy = ToolPolicy(config, {
        "gmail_send", "whatsapp_send", "vscode_run_command", "close_app", "spotify_play",
    } | set(config["tools"]))
    assert len(cases) == 5
    for case in cases:
        assert policy.mode_for(case["tool"], {}) == ("ask" if case["interrupt"] else "auto")

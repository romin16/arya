import json

from langchain_core.messages import AIMessage, ToolMessage

from core.graph.action_logger import _status, latest_action_entries


def test_action_statuses_distinguish_approval_refusal_from_tool_failure():
    for outcome in ("awaiting_approval", "approved", "succeeded", "no_op", "rejected", "expired"):
        message = ToolMessage(
            content=json.dumps({"outcome": outcome}), name="gmail_send", tool_call_id=outcome,
        )
        assert _status(message) == outcome

    rejected = ToolMessage(
        content=json.dumps({"success": False, "outcome": "rejected"}),
        name="memory_forget", tool_call_id="blocked", status="error",
    )
    failed = ToolMessage(
        content=json.dumps({"success": False, "error": "provider timeout"}),
        name="gmail_send", tool_call_id="failure", status="error",
    )
    assert _status(rejected) == "rejected"
    assert _status(failed) == "failed"


def test_action_log_result_summary_preserves_open_app_verification():
    messages = [
        AIMessage(content="", tool_calls=[{
            "name": "open_app", "args": {"app": "notepad"}, "id": "open-app-1", "type": "tool_call",
        }]),
        ToolMessage(
            content=json.dumps({"success": False, "verified": False, "attempted": True}),
            name="open_app", tool_call_id="open-app-1",
        ),
    ]

    entry, = latest_action_entries(messages)

    assert entry["status"] == "failed"
    assert json.loads(entry["result_summary"])["verified"] is False

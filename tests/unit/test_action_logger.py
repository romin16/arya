import json

from langchain_core.messages import ToolMessage

from core.graph.action_logger import _status


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

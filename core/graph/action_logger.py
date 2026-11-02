"""Deterministic persistence of completed tool calls."""
from __future__ import annotations

import json
from typing import Any, Iterable

from langchain_core.messages import AIMessage, ToolMessage
from psycopg.types.json import Jsonb


def _summary(message: ToolMessage | None) -> str:
    if message is None:
        return "No tool result was produced"
    content = message.content
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, default=str)
    return content[:1000]


def _status(message: ToolMessage | None) -> str:
    if message is None:
        return "failed"
    try:
        result = json.loads(message.content) if isinstance(message.content, str) else message.content
    except (TypeError, json.JSONDecodeError):
        result = None
    if isinstance(result, dict) and result.get("outcome") in {
        "awaiting_approval", "approved", "succeeded", "no_op", "failed", "rejected", "expired",
    }:
        return result["outcome"]
    if isinstance(result, dict) and (result.get("approval_required") or result.get("policy_blocked")):
        return "rejected"
    if message.status == "error":
        return "failed"
    if isinstance(result, dict) and result.get("success") is False:
        return "failed"
    return "succeeded"


def latest_action_entries(messages: Iterable[Any]) -> list[dict[str, Any]]:
    message_list = list(messages)
    last_ai_index = next(
        (index for index in range(len(message_list) - 1, -1, -1)
         if isinstance(message_list[index], AIMessage) and message_list[index].tool_calls),
        None,
    )
    if last_ai_index is None:
        return []
    action_message = message_list[last_ai_index]
    tool_results = {
        message.tool_call_id: message
        for message in message_list[last_ai_index + 1 :]
        if isinstance(message, ToolMessage)
    }
    return [
        {
            "tool": call["name"],
            "tool_call_id": call["id"],
            "args": call["args"],
            "status": _status(tool_results.get(call["id"])),
            "result_summary": _summary(tool_results.get(call["id"])),
        }
        for call in action_message.tool_calls
    ]


async def persist_action_entries(
    pool,
    *,
    user_id: str,
    thread_id: str,
    entries: list[dict[str, Any]],
) -> None:
    if not entries:
        return
    async with pool.connection() as connection:
        for entry in entries:
            await connection.execute(
                """INSERT INTO action_log
                   (user_id, thread_id, tool_call_id, tool, args, status, result_summary)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (thread_id,tool_call_id) WHERE tool_call_id IS NOT NULL
                   DO UPDATE SET tool=EXCLUDED.tool,args=EXCLUDED.args,status=EXCLUDED.status,
                     result_summary=EXCLUDED.result_summary""",
                (
                    user_id,
                    thread_id,
                    entry.get("tool_call_id"),
                    entry["tool"],
                    Jsonb(entry["args"]),
                    entry["status"],
                    entry["result_summary"],
                ),
            )


async def persist_approval_requests(pool, *, user_id: str, thread_id: str, calls: list[dict[str, Any]]) -> None:
    await persist_action_entries(
        pool,
        user_id=user_id,
        thread_id=thread_id,
        entries=[
            {
                "tool_call_id": call["id"],
                "tool": call["name"],
                "args": call["args"],
                "status": "awaiting_approval",
                "result_summary": "Waiting for user approval",
            }
            for call in calls
        ],
    )


async def update_approval_entries(
    pool,
    *,
    thread_id: str,
    calls: list[dict[str, Any]],
    status: str,
    approved_by: str | None = None,
    approval_channel: str | None = None,
) -> None:
    if status not in {"approved", "rejected", "expired"}:
        raise ValueError(f"Unsupported approval audit status: {status}")
    call_ids = [call["id"] for call in calls if call.get("id")]
    if not call_ids:
        return
    async with pool.connection() as connection:
        if status == "approved":
            await connection.execute(
                """UPDATE action_log SET status='approved',result_summary='Approved; tool result pending',
                     approved_by=%s,approved_at=now(),approval_channel=%s
                   WHERE thread_id=%s AND tool_call_id=ANY(%s)""",
                (approved_by, approval_channel, thread_id, call_ids),
            )
        else:
            await connection.execute(
                """UPDATE action_log SET status=%s,result_summary=%s
                   WHERE thread_id=%s AND tool_call_id=ANY(%s)""",
                (status, f"Approval {status}; no tool action was performed", thread_id, call_ids),
            )


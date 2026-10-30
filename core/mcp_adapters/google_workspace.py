from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.mcp_adapters.tools import MCPToolAdapter


class DeleteEmailArgs(BaseModel):
    message_id: str = Field(description="Gmail message ID to move to Trash")
    account: str = Field(default="", description="Google account email, if using multiple accounts")


class ReplyEmailArgs(BaseModel):
    to: list[str] = Field(description="Reply recipient addresses")
    subject: str = Field(description="Reply subject")
    body: str = Field(description="Reply body")
    reply_to_message_id: str = Field(description="Original Gmail message ID")
    account: str = ""
    cc: list[str] | None = None
    bcc: list[str] | None = None
    attachments: list[str] | None = None


BLOCKED_UNTIL_PHASE6 = {
    "gmail_send": "Sending email is disabled until the Phase 6 approval flow is implemented. No email was sent.",
    "gmail_reply": "Replying to email is disabled until the Phase 6 approval flow is implemented. No email was sent.",
    "gmail_delete": "Moving email to Trash is disabled until the Phase 6 approval flow is implemented. No email was changed.",
    "calendar_delete": "Deleting calendar events is disabled until the Phase 6 approval flow is implemented. No event was deleted.",
    "contacts_delete": "Deleting contacts is disabled until the Phase 6 approval flow is implemented. No contact was deleted.",
}

GOOGLE_TOOL_SOURCES = {
    "gmail_search": "search_email",
    "gmail_get": "read_email",
    "gmail_thread_get": "read_thread",
    "gmail_draft": "draft_email",
    "gmail_send": "send_email",
    "gmail_reply": "send_email",
    "gmail_delete": "modify_labels",
    "gmail_labels": "list_labels",
    "gmail_label": "modify_labels",
    "calendar_list": "list_calendars",
    "calendar_search": "list_events",
    "calendar_get": "get_event",
    "calendar_create": "create_event",
    "calendar_update": "update_event",
    "calendar_delete": "delete_event",
    "contacts_search": "search_contacts",
    "contacts_list": "list_contacts",
    "contacts_get": "get_contact",
    "contacts_create": "create_contact",
    "contacts_update": "update_contact",
    "contacts_delete": "delete_contact",
}


def adapt_google_tools(
    raw_tools: list[Any], *, timeout_seconds: float = 30, retries: int = 1
) -> dict[str, Any]:
    raw_by_name = {tool.name: tool for tool in raw_tools}
    tools: dict[str, Any] = {}
    # Keep every server-discovered tool behind the same timeout/retry adapter.
    for raw in raw_tools:
        adapter = MCPToolAdapter(
            public_name=f"google_{raw.name}",
            source_tool=raw,
            description=f"Google Workspace MCP tool: {raw.description or raw.name}",
            timeout_seconds=timeout_seconds,
            retries=retries,
        )
        tools[adapter.public_name] = adapter.as_langchain_tool()

    for public_name, source_name in GOOGLE_TOOL_SOURCES.items():
        raw = raw_by_name.get(source_name)
        refusal = BLOCKED_UNTIL_PHASE6.get(public_name)
        if public_name == "gmail_delete":
            transform = lambda args: {
                "message_id": args["message_id"],
                "add_labels": ["TRASH"],
                "remove_labels": [],
                "account": args.get("account", ""),
            }
            schema = DeleteEmailArgs
            description = "Move a Gmail message to Trash. Requires approval (currently disabled)."
        elif public_name == "gmail_reply":
            transform = None
            schema = ReplyEmailArgs
            description = "Reply in the existing Gmail thread. Requires approval (currently disabled)."
        else:
            transform = None
            schema = None
            description = raw.description if raw else f"Google Workspace tool {public_name}."
        adapter = MCPToolAdapter(
            public_name=public_name,
            source_tool=raw,
            description=description,
            timeout_seconds=timeout_seconds,
            retries=retries,
            args_schema=schema,
            transform=transform,
            refusal=refusal,
        )
        tools[public_name] = adapter.as_langchain_tool()
    return tools

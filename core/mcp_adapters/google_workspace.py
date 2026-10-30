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
    "calendar_delete_calendar": "Deleting calendars is disabled until the Phase 6 approval flow is implemented. No calendar was deleted.",
    "contacts_delete": "Deleting contacts is disabled until the Phase 6 approval flow is implemented. No contact was deleted.",
}

GOOGLE_TOOL_SOURCES = {
    "google_list_accounts": "list_accounts",
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
    "contacts_save_other": "save_other_contact",
    "calendar_quick_add": "quick_add_event",
    "calendar_move": "move_event",
    "calendar_respond": "respond_to_event",
    "calendar_instances": "list_instances",
    "calendar_free_busy": "free_busy",
    "calendar_create_calendar": "create_calendar",
    "calendar_update_calendar": "update_calendar",
    "calendar_delete_calendar": "delete_calendar",
    "gmail_attachments": "list_attachments",
    "gmail_attachments_batch": "batch_list_attachments",
    "gmail_attachment_download": "download_attachment",
    "gmail_attachment_extract_text": "extract_attachment_text",
    "gmail_attachment_render_page": "render_attachment_page",
    "gmail_archive": "archive_email",
    "gmail_mark_read": "mark_read",
    "gmail_mark_unread": "mark_unread",
}

GOOGLE_EXPOSED_SOURCES = set(GOOGLE_TOOL_SOURCES.values())
GOOGLE_REQUIRED_SOURCES = GOOGLE_EXPOSED_SOURCES | {"send_email"}


def adapt_google_tools(
    raw_tools: list[Any], *, timeout_seconds: float = 30, retries: int = 1
) -> dict[str, Any]:
    raw_by_name = {tool.name: tool for tool in raw_tools}
    tools: dict[str, Any] = {}
    # Expose only the Gmail, Calendar and Contacts surfaces. The upstream
    # server also publishes Drive, Tasks and shared-file tools.
    for raw in raw_tools:
        if raw.name not in GOOGLE_EXPOSED_SOURCES:
            continue
        adapter = MCPToolAdapter(
            public_name=next(
                (name for name, source in GOOGLE_TOOL_SOURCES.items() if source == raw.name),
                f"google_{raw.name}",
            ),
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

import asyncio
from pathlib import Path

import httpx
import pytest
import yaml
from langchain_core.tools import StructuredTool

from core.mcp_adapters.google_workspace import GOOGLE_EXPOSED_SOURCES, GOOGLE_TOOL_SOURCES, adapt_google_tools
from core.mcp_adapters.tools import MCPToolAdapter
from core.graph.runtime import google_mcp_connection
from core.skills_runtime import SkillsRuntime


def make_tool(name, call):
    async def invoke(
        query: str = "",
        message_id: str = "",
        to: list[str] | None = None,
        subject: str = "",
        body: str = "",
        reply_to_message_id: str = "",
        account: str = "",
        event_id: str = "",
        resource_name: str = "",
        given_name: str = "",
    ):
        return await call(
            query=query, message_id=message_id, to=to, subject=subject, body=body,
            reply_to_message_id=reply_to_message_id, account=account, event_id=event_id,
            resource_name=resource_name, given_name=given_name,
        )

    # Keep a stable typed schema; no live server or provider is involved.
    return StructuredTool.from_function(
        coroutine=invoke,
        name=name,
        description=f"mock {name}",
    )


def test_google_mcp_connection_uses_local_streamable_http_and_token():
    assert google_mcp_connection("mock-token") == {
        "transport": "streamable_http",
        "url": "http://127.0.0.1:8321/mcp",
        "headers": {"Authorization": "Bearer mock-token"},
    }


@pytest.mark.asyncio
async def test_google_aliases_wrap_every_tool_and_allow_calls_from_the_approved_graph_path():
    calls = []

    async def record(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    sources = GOOGLE_EXPOSED_SOURCES
    raw = [make_tool(name, record) for name in sorted(sources)]
    adapted = adapt_google_tools(raw, timeout_seconds=2, retries=1)
    for expected in (
        "gmail_search", "gmail_get", "gmail_thread_get", "gmail_draft", "gmail_send",
        "gmail_reply", "gmail_delete", "calendar_search", "calendar_create",
        "calendar_update", "calendar_delete", "contacts_search", "contacts_create",
        "contacts_update", "contacts_delete",
    ):
        assert expected in adapted
    assert set(GOOGLE_TOOL_SOURCES) <= adapted.keys()
    assert not any("drive" in name or "task" in name for name in adapted)
    assert "code policy gate" in adapted["gmail_send"].description
    assert "do not replace sending with a draft" in adapted["gmail_send"].description
    assert "code policy gate" in adapted["gmail_reply"].description

    send_result = await adapted["gmail_send"].ainvoke(
        {"to": ["test@example.com"], "subject": "x", "body": "y"}
    )
    delete_result = await adapted["gmail_delete"].ainvoke({"message_id": "message-id"})
    assert send_result["success"] is True
    assert delete_result["success"] is True
    assert len(calls) == 2

    await adapted["gmail_search"].ainvoke({"query": "is:unread"})
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_adapter_retries_a_transient_error_once_then_succeeds():
    attempts = 0

    async def transient_then_ok(query: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary test failure")
        return {"query": query}

    source = StructuredTool.from_function(coroutine=transient_then_ok, name="search_email", description="mock")
    adapter = MCPToolAdapter(
        public_name="gmail_search", source_tool=source, description="search", retries=1
    ).as_langchain_tool()
    assert await adapter.ainvoke({"query": "hello"}) == {"query": "hello"}
    assert attempts == 2


@pytest.mark.asyncio
async def test_adapter_times_out_and_reports_clear_message():
    async def slow_call(query: str):
        await asyncio.sleep(0.1)
        return query

    source = StructuredTool.from_function(coroutine=slow_call, name="search_email", description="mock")
    adapter = MCPToolAdapter(
        public_name="gmail_search", source_tool=source, description="search",
        timeout_seconds=0.01, retries=0,
    ).as_langchain_tool()
    with pytest.raises(RuntimeError, match="gmail_search timed out after 0.01 seconds"):
        await adapter.ainvoke({"query": "hello"})


def test_policy_marks_mail_send_reply_and_deletes_as_ask_and_skills_resolve_native_tools():
    policy = yaml.safe_load(Path("config/policy.yaml").read_text(encoding="utf-8"))
    assert policy["tools"]["gmail_send"]["mode"] == "ask"
    assert policy["tools"]["gmail_reply"]["mode"] == "ask"
    for name in ("gmail_delete", "calendar_delete", "contacts_delete"):
        assert policy["tools"][name]["mode"] == "ask"

    skills = SkillsRuntime(Path("skills"))
    assert skills.tool_names(["weather-search"]) == {"get_weather", "web_search"}
    assert {"gmail_send", "gmail_reply"} <= skills.tool_names(["email"])
    email = skills.skills["email"].body.casefold()
    assert "disabled until" not in email
    assert "execution is unavailable" not in email
    assert "never claim an email was sent until the tool result confirms success" in email
    assert {"contacts_create", "contacts_update", "contacts_delete"} <= skills.tool_names(["contacts"])


def test_google_environment_mapping_and_real_server_tool_names():
    root = Path(__file__).resolve().parents[2]
    launcher = (root / "deploy" / "start_all.ps1").read_text(encoding="utf-8")
    setup = (root / "scripts" / "setup_google_mcp.ps1").read_text(encoding="utf-8")
    for mapping in (
        "$env:GOOGLE_CLIENT_ID = $env:GOOGLE_OAUTH_CLIENT_ID",
        "$env:GOOGLE_CLIENT_SECRET = $env:GOOGLE_OAUTH_CLIENT_SECRET",
        "$env:DEFAULT_ACCOUNT = $env:GOOGLE_ACCOUNT",
        "$env:MCP_BEARER_TOKEN = $env:GOOGLE_MCP_TOKEN",
    ):
        assert mapping in launcher
    for mapping in (
        "$env:GOOGLE_CLIENT_ID = $env:GOOGLE_OAUTH_CLIENT_ID",
        "$env:GOOGLE_CLIENT_SECRET = $env:GOOGLE_OAUTH_CLIENT_SECRET",
        "$env:DEFAULT_ACCOUNT = $env:GOOGLE_ACCOUNT",
        "$env:MCP_BEARER_TOKEN = $env:GOOGLE_MCP_TOKEN",
        "$env:TOKEN_DB_PATH = $TokenDb",
        "$env:ATTACHMENTS_DIR = $AttachmentsRoot",
        "Arya\\google-mcp-data",
        "SELECT 1 FROM accounts WHERE lower(email)=lower(?)",
        "skipping OAuth",
    ):
        assert mapping in setup
    assert "google-accounts-mcp')" in launcher
    assert set(GOOGLE_TOOL_SOURCES.values()) == GOOGLE_EXPOSED_SOURCES
    assert GOOGLE_EXPOSED_SOURCES == {
        "list_accounts", "search_email", "read_email", "read_thread", "draft_email", "send_email",
        "list_labels", "modify_labels", "list_attachments", "batch_list_attachments",
        "download_attachment", "extract_attachment_text", "render_attachment_page", "archive_email",
        "mark_read", "mark_unread", "list_calendars", "list_events", "get_event", "create_event",
        "update_event", "delete_event", "quick_add_event", "move_event", "respond_to_event",
        "list_instances", "free_busy", "create_calendar", "update_calendar", "delete_calendar",
        "search_contacts", "list_contacts", "get_contact", "create_contact", "update_contact",
        "delete_contact", "save_other_contact",
    }
    assert not any("drive" in name or "task" in name for name in GOOGLE_EXPOSED_SOURCES)

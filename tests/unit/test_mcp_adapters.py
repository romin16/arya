import asyncio
from pathlib import Path

import httpx
import pytest
import yaml
from langchain_core.tools import StructuredTool

from core.mcp_adapters.google_workspace import adapt_google_tools
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
        "url": "http://127.0.0.1:5003/mcp",
        "headers": {"Authorization": "Bearer mock-token"},
    }


@pytest.mark.asyncio
async def test_google_aliases_wrap_every_tool_and_protected_actions_refuse_before_call():
    calls = []

    async def record(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    sources = {
        "search_email", "read_email", "read_thread", "draft_email", "send_email",
        "modify_labels", "list_labels", "list_calendars", "list_events", "get_event",
        "create_event", "update_event", "delete_event", "search_contacts", "list_contacts",
        "get_contact", "create_contact", "update_contact", "delete_contact",
    }
    raw = [make_tool(name, record) for name in sorted(sources)]
    adapted = adapt_google_tools(raw, timeout_seconds=2, retries=1)
    for expected in (
        "gmail_search", "gmail_get", "gmail_thread_get", "gmail_draft", "gmail_send",
        "gmail_reply", "gmail_delete", "calendar_search", "calendar_create",
        "calendar_update", "calendar_delete", "contacts_search", "contacts_create",
        "contacts_update", "contacts_delete",
    ):
        assert expected in adapted
    assert {f"google_{name}" for name in sources} <= adapted.keys()

    raw_send_count = len(calls)
    with pytest.raises(Exception, match="disabled until the Phase 6 approval flow"):
        await adapted["gmail_send"].ainvoke({"to": ["test@example.com"], "subject": "x", "body": "y"})
    with pytest.raises(Exception, match="disabled until the Phase 6 approval flow"):
        await adapted["gmail_delete"].ainvoke({"message_id": "message-id"})
    assert len(calls) == raw_send_count == 0

    await adapted["gmail_search"].ainvoke({"query": "is:unread"})
    assert len(calls) == 1


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
    assert "gmail_reply" in skills.tool_names(["email"])
    assert {"contacts_create", "contacts_update", "contacts_delete"} <= skills.tool_names(["contacts"])

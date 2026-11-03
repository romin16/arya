"""Small offline suite inventory and opt-in live memory-router eval."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import yaml


async def evaluate_memory_routing(router, dataset: list[dict]):
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt = (
        "Route each request with one memory_intent and any necessary memory_reads. Choose exactly one intent: "
        "entity_read (a question about a stored current fact), episode_read (a past event or decision), "
        "knowledge_read (general reference knowledge), entity_update_and_episode_write (a user reports a durable current-fact update), "
        "procedural_write (an explicit standing instruction), memory_forget (an explicit request to forget/delete/remove/clear/erase stored memory), "
        "pattern_read (recall a stated recurring preference or behavior), "
        "or none (no personal memory read or write). memory_reads may contain only episode, knowledge, or pattern. "
        "For episode/knowledge/pattern reads, include a concise search query in memory_reads. For entity reads and writes, "
        "use the always-injected current entity store and return no routed read. Never infer personal facts from a general question. "
        "One-time commands and edits to text, messages, documents, files, or UI are none, never entity updates.\n\n"
        "Examples:\n"
        "User: What is my current salary? => entity_read, no memory_reads.\n"
        "User: What did we decide last April? => episode_read, one episode read with the date and decision query.\n"
        "User: How does a SIP work? => knowledge_read, one knowledge read.\n"
        "User: I just changed jobs to TCS. => entity_update_and_episode_write, no routed read.\n"
        "User: Never recommend equity to me again. => procedural_write, no routed read.\n"
        "User: Forget the rule about Aditya. => memory_forget, no routed read.\n"
        "User: Delete the email draft. => none.\n"
        "User: I'm worried about market volatility. => pattern_read, one pattern read.\n"
        "User: What is the average salary for a Python developer? => none.\n"
        "User: Change the text to hello from Arya. => none.\n"
        "User: Change the email body to revised approval text. => none.\n"
        "User: Run echo hello in the VS Code terminal. => none.\n"
        "User: Open Notepad. => none.\n"
        "User: What is equity investing? => none."
    )
    results = []
    for case in dataset:
        examples = [(text, case["operation"], case.get("store")) for text in case["utterances"]]
        for negative in case.get("negatives", []):
            if isinstance(negative, str):
                examples.append((negative, "none", None))
            else:
                examples.append((negative["utterance"], negative.get("operation", "none"), negative.get("store")))
        for utterance, expected, expected_store in examples:
            started = time.perf_counter()
            decision = await router.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=utterance),
            ])
            latency_ms = (time.perf_counter() - started) * 1000
            intent = getattr(decision, "memory_intent", None)
            reads = getattr(decision, "memory_reads", [])
            store = (reads[0].get("store") if isinstance(reads[0], dict) else getattr(reads[0], "store", None)) if reads else None
            reason = ""
            if intent != expected:
                reason = "intent mismatch"
            elif expected_store is not None and store != expected_store:
                reason = "memory store mismatch"
            elif expected == "none" and reads:
                reason = "unexpected memory read"
            passed = not reason
            results.append({
                "id": case["id"], "utterance": utterance,
                "expected": expected, "actual": intent,
                "expected_store": expected_store, "actual_store": store,
                "reason": reason, "pass": passed,
                "ttfc_ms": latency_ms,
            })
    return results


async def _live_memory_routing(dataset: list[dict], model_name: str):
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    import os

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --live")
    from core.graph.runtime import RouteDecision

    router = ChatOpenAI(
        model=model_name, api_key=api_key, temperature=0,
        max_completion_tokens=512, timeout=30, max_retries=1,
    )
    try:
        structured_router = router.with_structured_output(RouteDecision, method="json_schema", strict=True)
        return await evaluate_memory_routing(structured_router, dataset)
    finally:
        await router.root_async_client.close()


async def _live_approvals(dataset: list[dict], model_name: str):
    """Run real model selections through the core graph's policy interrupt; all tools are inert mocks."""
    import os
    import httpx
    from dotenv import load_dotenv
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.memory import MemorySaver
    from pydantic import BaseModel, Field, create_model
    from typing import Any, Optional

    from core.graph.runtime import (
        DEVICE_TOOL_DESCRIPTIONS,
        DEVICE_TOOL_NAMES,
        CoreGraphRuntime,
        RouteDecision,
        _scan_openai_payload,
    )
    from core.mcp_adapters.google_workspace import GOOGLE_TOOL_SOURCES, adapt_google_tools
    from core.mcp_adapters.tools import MCPToolAdapter
    from core.policy_gate import ToolPolicy
    from core.pii.vault import PIIVault
    from core.skills_runtime import SkillsRuntime

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    api_key = os.getenv("OPENAI_API_KEY")
    account = os.getenv("GOOGLE_ACCOUNT")
    if not api_key or not account:
        raise RuntimeError("OPENAI_API_KEY and GOOGLE_ACCOUNT are required for --suite approvals --live")
    hmac_secret = os.getenv("PII_HMAC_SECRET", "").encode()
    fernet_key = os.getenv("PII_FERNET_KEY", "").encode()
    if not hmac_secret or not fernet_key:
        raise RuntimeError("PII_HMAC_SECRET and PII_FERNET_KEY are required for the live approvals eval")

    def model_from_schema(model_name: str, schema: dict[str, Any]) -> type[BaseModel]:
        required = set(schema.get("required", []))
        fields = {}
        for key, field_schema in schema.get("properties", {}).items():
            nullable = any(option.get("type") == "null" for option in field_schema.get("anyOf", []))
            base_schema = next(
                (option for option in field_schema.get("anyOf", []) if option.get("type") != "null"),
                field_schema,
            )
            kind = base_schema.get("type")
            annotation: Any = {
                "string": str, "integer": int, "number": float, "boolean": bool,
                "array": list[str], "object": dict[str, Any],
            }.get(kind, Any)
            if nullable:
                annotation = Optional[annotation]
            default = ... if key in required else field_schema.get("default")
            fields[key] = (annotation, Field(default=default, description=field_schema.get("description", "")))
        return create_model(model_name, **fields)

    class MemoryRepositoriesMock:
        def __init__(self):
            self.pending = {}

        async def get_pending_operation(self, user_id, thread_id):
            return self.pending.get((user_id, thread_id))

        async def set_pending_operation(self, user_id, thread_id, operation_type, payload, *, ttl_seconds):
            self.pending[(user_id, thread_id)] = {"operation_type": operation_type, "payload": payload}

        async def active_procedures(self, user_id):
            return []

    class MemoryMock:
        def __init__(self, recalled_episode=""):
            self.repositories = MemoryRepositoriesMock()
            self.recalled_episode = recalled_episode

        async def always_context_and_procedures(self, user_id, *, token_budget):
            return self.recalled_episode, []

        async def routed_reads(self, user_id, reads):
            return self.recalled_episode

    class FakePool:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        def connection(self):
            return self

        async def execute(self, *args, **kwargs):
            return None

    fake_sources = []
    fixture = json.loads((root / "tests/fixtures/google_email_tool_schemas.json").read_text(encoding="utf-8"))
    email_send = next(item for item in fixture if item["name"] == "send_email")

    async def mock_google(**kwargs):
        return {"success": True, "mocked": True}

    fake_sources.append(StructuredTool.from_function(
        coroutine=mock_google,
        name=email_send["name"],
        description=email_send["description"],
        args_schema=model_from_schema("SendEmailArgs", email_send["inputSchema"]),
    ))
    google_tools = adapt_google_tools(fake_sources)

    class SendWhatsappArgs(BaseModel):
        contact: str = Field(description="Contact name to message")
        message: str = Field(description="Message text")

    class RunCommandArgs(BaseModel):
        command: str = Field(description="Terminal command to run")

    class AppArgs(BaseModel):
        app: str = Field(description="Application to close")

    class SpotifyArgs(BaseModel):
        query: str = Field(description="Track or artist to play")

    async def mock_action(**kwargs):
        return {"success": True, "mocked": True}

    device_specs = {
        "whatsapp_send": (SendWhatsappArgs, DEVICE_TOOL_DESCRIPTIONS["whatsapp_send"]),
        "vscode_run_command": (RunCommandArgs, DEVICE_TOOL_DESCRIPTIONS["vscode_run_command"]),
        "close_app": (AppArgs, "Close the requested desktop application."),
        "spotify_play": (SpotifyArgs, "Search Spotify and play the best matching result."),
    }
    device_tools = {
        name: MCPToolAdapter(
            public_name=name,
            source_tool=StructuredTool.from_function(
                coroutine=mock_action, name=name, description=description, args_schema=args,
            ),
            description=description,
            error_label="device tool",
        ).as_langchain_tool()
        for name, (args, description) in device_specs.items()
    }

    from langchain_openai import ChatOpenAI
    vault = PIIVault(hmac_secret, fernet_key)
    authorized_token = vault.tokenise(account)
    http_client = httpx.AsyncClient(event_hooks={"request": [_scan_openai_payload(vault)]}, timeout=40)
    main_model = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        temperature=0,
        max_retries=1,
        timeout=40,
        http_async_client=http_client,
    )
    skills = SkillsRuntime(root / "skills")
    policy_config = yaml.safe_load((root / "config" / "policy.yaml").read_text(encoding="utf-8"))
    all_registered = DEVICE_TOOL_NAMES | set(GOOGLE_TOOL_SOURCES) | {
        "web_search", "get_weather", "calculator", "memory_search", "memory_forget", "load_skill",
    }
    policy = ToolPolicy(policy_config, all_registered)
    results = []
    for case in dataset:
        runtime = CoreGraphRuntime()
        active = [case["skill"]]
        runtime.vault = vault
        runtime.memory = MemoryMock(case.get("recalled_episode", ""))
        runtime.saver = MemorySaver()
        runtime.skills = skills
        runtime.main_model = main_model
        runtime.limits = {"max_tool_rounds": 8, "token_budget": 4096, "turn_token_budget": 4096}
        runtime.persona = (root / "persona.md").read_text(encoding="utf-8").strip()
        runtime.authorized_account_token = authorized_token
        runtime.tools = {**google_tools, **device_tools}
        runtime.device_tools = device_tools
        runtime.policy = policy
        runtime.memory_tools = {}
        runtime.pool = FakePool()
        runtime._queue_memory_write = lambda state: None

        class Router:
            async def ainvoke(self, messages):
                return RouteDecision(likely_skills=active, memory_reads=[], memory_intent="none")

        runtime.router_model = Router()
        async def load_skill(name: str) -> str:
            return skills.load(name, active)[0]
        runtime.load_skill_tool = StructuredTool.from_function(
            coroutine=load_skill, name="load_skill", description="Load a skill already selected for the turn.",
        )
        runtime.graph = runtime._build_graph()
        session = f"approval-live-{case['id']}"
        user_id = "live-eval-user"
        request_text = case["utterance"]
        if case["id"] == "email_to_self":
            request_text = request_text.replace("myself", "myself")
        started = time.perf_counter()
        first_chunk_ms = None
        events = []
        async for event in runtime.stream_turn(
            type("ChatRequest", (), {"message": request_text, "user_id": user_id})(), session,
        ):
            if first_chunk_ms is None and "chunk" in event:
                first_chunk_ms = (time.perf_counter() - started) * 1000
            events.append(event)
        snapshot = await runtime.graph.aget_state({"configurable": {"thread_id": session}})
        selected = list(snapshot.values.get("chosen_tools", []))
        interrupt_events = [event for event in events if event.get("activity", {}).get("event") == "Approval"]
        approval_question = " ".join(
            str(event.get("chunk", "")) for event in events
        )
        required_text = case.get("approval_must_include", [])
        forbidden_text = case.get("approval_must_not_include", [])
        content_check = all(text.casefold() in approval_question.casefold() for text in required_text)
        content_check = content_check and all(
            text.casefold() not in approval_question.casefold() for text in forbidden_text
        )
        results.append({
            "id": case["id"],
            "expected": case["tool"],
            "actual": selected[0] if selected else "none",
            "expected_interrupt": case["interrupt"],
            "actual_interrupt": bool(interrupt_events),
            "approval_content_check": content_check,
            "ttfc_ms": first_chunk_ms or (time.perf_counter() - started) * 1000,
            "pass": bool(selected and selected[0] == case["tool"] and bool(interrupt_events) == case["interrupt"] and content_check),
        })
    await http_client.aclose()
    return results


async def _live_structured_schemas(model_name: str):
    import os
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI

    from core.graph.runtime import STRUCTURED_OUTPUT_MODELS

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --suite structured-schemas --live")
    prompts = {
        "RouteDecision": "Route 'What time is it?' with no skills, no memory reads, and no memory intent.",
        "ApprovalClassification": "The user replied 'I am not sure' to an approval question. Classify as unclear.",
        "MemoryWrite": "Extract memories from 'What time is it?'. Return empty stores and no episode.",
    }
    llm = ChatOpenAI(
        model=model_name, api_key=api_key, temperature=0,
        max_completion_tokens=512, timeout=30, max_retries=1,
    )
    results = []
    try:
        for schema in STRUCTURED_OUTPUT_MODELS:
            started = time.perf_counter()
            runnable = llm.with_structured_output(schema, method="json_schema", strict=True)
            output = await runnable.ainvoke(prompts[schema.__name__])
            results.append({
                "schema": schema.__name__, "valid": isinstance(output, schema),
                "ttfc_ms": (time.perf_counter() - started) * 1000,
                "pass": isinstance(output, schema),
            })
        return results
    finally:
        await llm.root_async_client.close()


async def _live_tool_routing(dataset: list[dict], model_name: str):
    import os
    from dotenv import load_dotenv
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessageChunk
    from langchain_core.tools import StructuredTool
    from langchain_openai import ChatOpenAI
    from pydantic import Field, create_model

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --live")
    skills = __import__("core.skills_runtime", fromlist=["SkillsRuntime"]).SkillsRuntime(root / "skills")

    tool_fields = {
        "spotify_play": {"query": (str, Field(description="Track or artist to play"))},
        "spotify_pause": {}, "spotify_resume": {}, "spotify_next": {},
        "open_app": {"app": (str, Field(description="Application to open"))},
        "close_app": {"app": (str, Field(description="Application to close"))},
        "whatsapp_send": {
            "contact": (str, Field(description="Contact name")),
            "message": (str, Field(description="Message content")),
        },
        "gmail_send": {
            "to": (list[str], Field(description="Recipient addresses")),
            "subject": (str, Field(description="Email subject")),
            "body": (str, Field(description="Email body")),
        },
        "calendar_create": {
            "summary": (str, Field(description="Event title")),
            "start": (str, Field(description="Start time")),
            "end": (str, Field(description="End time")),
        },
        "contacts_search": {"query": (str, Field(description="Contact search query"))},
        "get_weather": {"location": (str, Field(description="Location"))},
        "web_search": {"query": (str, Field(description="Search query"))},
    }
    descriptions = {
        "spotify_play": "Play the requested track or artist in Spotify.",
        "spotify_pause": "Pause current Spotify playback.",
        "spotify_resume": "Resume paused Spotify playback.",
        "spotify_next": "Skip to the next Spotify track.",
        "open_app": "Open the requested desktop app.",
        "close_app": "Close the requested desktop app.",
        "whatsapp_send": "Send the requested WhatsApp message to the named contact; approval is handled in code.",
        "gmail_send": "Send the requested email; approval is handled in code.",
        "calendar_create": "Create the requested calendar event; approval is handled in code.",
        "contacts_search": "Search Google Contacts for a person.",
        "get_weather": "Get current weather for a location.",
        "web_search": "Search the web for current information.",
    }
    skill_tools = {
        "spotify": ["spotify_play", "spotify_pause", "spotify_resume", "spotify_next"],
        "desktop": ["open_app", "close_app"],
        "whatsapp": ["whatsapp_send"],
        "email": ["gmail_send"],
        "calendar": ["calendar_create"],
        "contacts": ["contacts_search"],
        "weather-search": ["get_weather", "web_search"],
    }

    async def inert_tool(**_arguments):
        return {"success": True, "mocked": True}

    tools = {}
    for name, fields in tool_fields.items():
        schema = create_model(f"{name.title().replace('_', '')}EvalArgs", **fields)
        tools[name] = StructuredTool.from_function(
            coroutine=inert_tool, name=name, description=descriptions[name], args_schema=schema,
        )

    model = ChatOpenAI(model=model_name, api_key=api_key, temperature=0, timeout=40, max_retries=1)
    results = []
    try:
        for case in dataset:
            selected_tools = [tools[name] for name in skill_tools[case["skill"]]]
            skill_text = skills.load(case["skill"], [case["skill"]])[0]
            last_action = case.get("last_action")
            prompt = (
            "Select and call exactly one tool for the user's current request. Do not execute it or claim success. "
            "Use only the active skill and available tools. For a short reference, resolve it from the supplied last action.\n\n"
            f"Active skill instructions:\n{skill_text}\n\n"
            f"Last action: {json.dumps(last_action, ensure_ascii=False) if last_action else 'none'}"
            )
            started = time.perf_counter()
            first_chunk_ms = None
            combined = None
            bound = model.bind_tools(selected_tools, tool_choice="required")
            async for chunk in bound.astream([
                SystemMessage(content=prompt), HumanMessage(content=case["utterance"]),
            ]):
                if first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - started) * 1000
                combined = chunk if combined is None else combined + chunk
            if not isinstance(combined, AIMessageChunk):
                results.append({
                    "id": case["id"], "expected": case["tool"], "actual": "none",
                    "ttfc_ms": first_chunk_ms or (time.perf_counter() - started) * 1000, "pass": False,
                })
                continue
            calls = combined.tool_calls or []
            actual = calls[0]["name"] if calls else "none"
            results.append({
                "id": case["id"], "expected": case["tool"], "actual": actual,
                "ttfc_ms": first_chunk_ms or (time.perf_counter() - started) * 1000,
                "pass": actual == case["tool"],
            })
        return results
    finally:
        await model.root_async_client.close()


async def _live_text_suite(dataset: list[dict], model_name: str, *, persona: bool):
    import os
    from dotenv import load_dotenv
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --live")
    model = ChatOpenAI(model=model_name, api_key=api_key, temperature=0, timeout=40, max_retries=1)
    results = []
    try:
        for index, case in enumerate(dataset):
            if persona:
                system = (
                    f"You are ARYA. Follow this persona:\n{(root / 'persona.md').read_text(encoding='utf-8')}\n"
                    "Answer briefly and do not claim to have executed actions. Avoid the phrases 'Sure!', 'Of course!', and 'Enjoy!'."
                )
                user = f"Write a concise chat response for this request.\nUser: {case['utterance']}"
            else:
                system = "Follow the user's harmless request for exact output. Return only the requested text."
                user = case["utterance"]
            started = time.perf_counter()
            first_chunk_ms = None
            chunks = []
            async for chunk in model.astream([SystemMessage(content=system), HumanMessage(content=user)]):
                if first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - started) * 1000
                if isinstance(chunk.content, str):
                    chunks.append(chunk.content)
            reply = "".join(chunks).strip()
            if persona:
                lowered = reply.casefold()
                passed = not any(phrase in lowered for phrase in ("sure!", "of course!", "enjoy!"))
            else:
                passed = reply == case["expected_reply"].strip()
            results.append({
                "id": case.get("id", str(index + 1)), "reply": reply,
                "ttfc_ms": first_chunk_ms or (time.perf_counter() - started) * 1000,
                "pass": passed,
            })
        return results
    finally:
        await model.root_async_client.close()


SUITES = (
    "tool-routing", "memory-routing", "approvals", "persona-tone", "exact-reply", "structured-schemas",
)


def _percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percent))))
    return ordered[index]


def _suite_cases(dataset_dir: Path, suite: str) -> list[dict]:
    if suite == "structured-schemas":
        from core.graph.runtime import STRUCTURED_OUTPUT_MODELS

        return [{"id": schema.__name__} for schema in STRUCTURED_OUTPUT_MODELS]
    return yaml.safe_load((dataset_dir / f"{suite}.yaml").read_text(encoding="utf-8"))


def _case_count(suite: str, dataset: list[dict]) -> int:
    if suite == "memory-routing":
        return sum(
            len(case.get("utterances", [])) + len(case.get("negatives", []))
            for case in dataset
        )
    return len(dataset)


async def _run_live_suite(suite: str, dataset: list[dict], model_name: str) -> list[dict]:
    if suite == "tool-routing":
        return await _live_tool_routing(dataset, model_name)
    if suite == "memory-routing":
        return await _live_memory_routing(dataset, model_name)
    if suite == "approvals":
        return await _live_approvals(dataset, model_name)
    if suite == "persona-tone":
        return await _live_text_suite(dataset, model_name, persona=True)
    if suite == "exact-reply":
        return await _live_text_suite(dataset, model_name, persona=False)
    if suite == "structured-schemas":
        return await _live_structured_schemas(model_name)
    raise ValueError(f"Unknown eval suite: {suite}")


async def _run_live_comparison(suites: list[str], datasets: dict[str, list[dict]], models: list[str]) -> list[dict]:
    table = []
    for model_name in models:
        for suite in suites:
            rows = await _run_live_suite(suite, datasets[suite], model_name)
            passed = sum(bool(row.get("pass", row.get("valid", False))) for row in rows)
            latencies = [float(row.get("ttfc_ms", 0)) for row in rows]
            table.append({
                "suite": suite, "model": model_name, "passed": passed, "total": len(rows),
                "rate": passed / len(rows) if rows else 0,
                "p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95),
                "failures": [row for row in rows if not row.get("pass", row.get("valid", False))],
            })
    return table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="gpt-4o,gpt-4o-mini")
    parser.add_argument("--suite", choices=("all", *SUITES), default="all")
    parser.add_argument("--live", action="store_true", help="Call OpenAI for the selected eval suites")
    args = parser.parse_args()
    dataset_dir = Path(__file__).parent / "datasets"
    suites = list(SUITES) if args.suite == "all" else [args.suite]
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    if not models:
        parser.error("--models must contain at least one model name")

    datasets = {suite: _suite_cases(dataset_dir, suite) for suite in suites}
    if not args.live:
        print("suite\tmodel\tcases\tpass_rate\tp50_ttfc_ms\tp95_ttfc_ms")
        for suite in suites:
            for model in models:
                print(f"{suite}\t{model}\t{_case_count(suite, datasets[suite])}\tnot-run\t-\t-")
        print("Offline mode loaded all selected datasets; pass --live to evaluate OpenAI models.")
        return

    table = asyncio.run(_run_live_comparison(suites, datasets, models))
    print("suite\tmodel\tpass_rate\tp50_ttfc_ms\tp95_ttfc_ms")
    for row in table:
        print(
            f"{row['suite']}\t{row['model']}\t{row['passed']}/{row['total']} ({row['rate']:.1%})\t"
            f"{row['p50']:.1f}\t{row['p95']:.1f}"
        )
    failures = [failure for row in table for failure in row["failures"]]
    if failures:
        print("failed_cases\tsuite\tmodel\tcase\texpected\tactual\tdetail")
        for row in table:
            for failure in row["failures"]:
                print(
                    f"FAIL\t{row['suite']}\t{row['model']}\t{failure.get('id', '-')}	"
                    f"{failure.get('expected', '-')}	{failure.get('actual', '-')}	"
                    f"{failure.get('reason', '-')}: {failure.get('utterance', failure.get('reply', '-'))}"
                )
    raise SystemExit(0 if all(row["passed"] == row["total"] for row in table) else 1)


if __name__ == "__main__":
    main()

"""Small offline suite inventory and opt-in live memory-router eval."""
from __future__ import annotations

import argparse
import asyncio
import json
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
        "use the always-injected current entity store and return no routed read. Never infer personal facts from a general question.\n\n"
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
            decision = await router.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=utterance),
            ])
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
            })
    return results


async def _live_memory_routing(dataset: list[dict]):
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    import os

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --live")
    settings = yaml.safe_load((root / "config" / "models.yaml").read_text(encoding="utf-8"))
    from core.graph.runtime import RouteDecision

    router = ChatOpenAI(
        model=settings["aux"], api_key=api_key, temperature=0,
        max_completion_tokens=512, timeout=30, max_retries=1,
    ).with_structured_output(RouteDecision, method="json_schema", strict=True)
    return await evaluate_memory_routing(router, dataset)


async def _live_approvals(dataset: list[dict]):
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

    class MemoryMock:
        def __init__(self):
            self.repositories = MemoryRepositoriesMock()

        async def always_context_and_procedures(self, user_id, *, token_budget):
            return "", []

        async def routed_reads(self, user_id, reads):
            return ""

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
        model=yaml.safe_load((root / "config" / "models.yaml").read_text(encoding="utf-8"))["main"],
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
        runtime.memory = MemoryMock()
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
        events = [event async for event in runtime.stream_turn(
            type("ChatRequest", (), {"message": request_text, "user_id": user_id})(), session,
        )]
        snapshot = await runtime.graph.aget_state({"configurable": {"thread_id": session}})
        selected = list(snapshot.values.get("chosen_tools", []))
        interrupt_events = [event for event in events if event.get("activity", {}).get("event") == "Approval"]
        results.append({
            "id": case["id"],
            "expected": case["tool"],
            "actual": selected[0] if selected else "none",
            "expected_interrupt": case["interrupt"],
            "actual_interrupt": bool(interrupt_events),
            "pass": bool(selected and selected[0] == case["tool"] and bool(interrupt_events) == case["interrupt"]),
        })
    await http_client.aclose()
    return results


async def _live_structured_schemas():
    import os
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI

    from core.graph.runtime import STRUCTURED_OUTPUT_MODELS

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --suite structured-schemas --live")
    model_settings = yaml.safe_load((root / "config" / "models.yaml").read_text(encoding="utf-8"))
    prompts = {
        "RouteDecision": "Route 'What time is it?' with no skills, no memory reads, and no memory intent.",
        "ApprovalClassification": "The user replied 'I am not sure' to an approval question. Classify as unclear.",
        "MemoryWrite": "Extract memories from 'What time is it?'. Return empty stores and no episode.",
    }
    llm = ChatOpenAI(
        model=model_settings["aux"], api_key=api_key, temperature=0,
        max_completion_tokens=512, timeout=30, max_retries=1,
    )
    results = []
    for schema in STRUCTURED_OUTPUT_MODELS:
        runnable = llm.with_structured_output(schema, method="json_schema", strict=True)
        output = await runnable.ainvoke(prompts[schema.__name__])
        results.append({"schema": schema.__name__, "valid": isinstance(output, schema)})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="gpt-4o,gpt-4o-mini")
    parser.add_argument("--suite", default="all")
    parser.add_argument("--live", action="store_true", help="Use the configured OpenAI model for a live eval suite")
    args = parser.parse_args()
    dataset_dir = Path(__file__).parent / "datasets"
    if args.suite == "approvals":
        dataset = yaml.safe_load((dataset_dir / "approvals.yaml").read_text(encoding="utf-8"))
        if not args.live:
            print(f"Loaded {len(dataset)} cases for suite approvals; no model calls were made.")
            return
        results = asyncio.run(_live_approvals(dataset))
        print("case\texpected tool\tselected tool\texpected interrupt\tactual interrupt\tresult")
        for result in results:
            print(
                f"{result['id']}\t{result['expected']}\t{result['actual']}\t"
                f"{result['expected_interrupt']}\t{result['actual_interrupt']}\t"
                f"{'PASS' if result['pass'] else 'FAIL'}"
            )
        print(f"approvals: {sum(row['pass'] for row in results)}/{len(results)} pass")
        raise SystemExit(0 if all(row["pass"] for row in results) else 1)
    if args.suite == "structured-schemas":
        from core.graph.runtime import STRUCTURED_OUTPUT_MODELS

        if not args.live:
            print(f"Loaded {len(STRUCTURED_OUTPUT_MODELS)} strict structured-output schemas; no model calls were made.")
            return
        results = asyncio.run(_live_structured_schemas())
        print("schema\tresult")
        for result in results:
            print(f"{result['schema']}\t{'PASS' if result['valid'] else 'FAIL'}")
        print(f"structured-schemas: {sum(row['valid'] for row in results)}/{len(results)} pass")
        raise SystemExit(0 if all(row["valid"] for row in results) else 1)
    selected = [dataset_dir / "memory-routing.yaml"] if args.suite == "memory-routing" else list(dataset_dir.glob("*.yaml"))
    datasets = [yaml.safe_load(path.read_text(encoding="utf-8")) for path in selected]
    cases = sum(sum(len(row.get("utterances", [row.get("utterance", "")])) + len(row.get("negatives", [])) for row in data)
                if isinstance(data, list) else len(data) for data in datasets)
    if args.live:
        if args.suite == "memory-routing":
            results = asyncio.run(_live_memory_routing(datasets[0]))
        else:
            parser.error("--live supports only --suite memory-routing or --suite approvals")
        failures = [result for result in results if not result["pass"]]
        for result in results:
            status = "PASS" if result["pass"] else "FAIL"
            print(
                f"{status}\t{result['id']}\t{result['expected']}\t{result['actual']}\t"
                f"{result['expected_store'] or '-'}\t{result['actual_store'] or '-'}\t"
                f"{result['reason'] or '-'}\t{result['utterance']}"
            )
        print(f"memory-routing: {len(results)-len(failures)}/{len(results)} pass")
        raise SystemExit(1 if failures else 0)
    print(f"Loaded {cases} cases for suite {args.suite}; no model calls were made.")


if __name__ == "__main__":
    main()

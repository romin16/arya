import json
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from cryptography.fernet import Fernet
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver

from core.graph.runtime import (
    CoreGraphRuntime,
    MemoryWrite,
    RouteDecision,
    _has_explicit_memory_forget_intent,
)
from core.memory.normalization import canonical_entity_key, explicit_user_rules
from core.memory.policy_gate import hard_rule_for
from core.pii.vault import PIIVault
from core.skills_runtime import SkillsRuntime
from evals.run import evaluate_memory_routing


def test_hard_procedural_rules_block_calls_in_code():
    rules = [{
        "severity": "hard",
        "scope": "global",
        "tool_pattern": None,
        "rule_text": "Never recommend equity to me again",
    }]
    assert hard_rule_for("web_search", {"query": "equity funds"}, rules) == rules[0]
    assert hard_rule_for("web_search", {"query": "weather in Pune"}, rules) is None
    assert hard_rule_for(
        "whatsapp_send",
        {"query": "equity funds"},
        [{**rules[0], "tool_pattern": "whatsapp_*"}],
    ) is not None


def test_contact_rules_get_tool_and_case_insensitive_argument_constraint_but_casual_chat_does_not():
    rule, = explicit_user_rules(["Never message Aditya on WhatsApp again."])
    assert rule["tool_pattern"] == "whatsapp_send"
    assert rule["argument_constraints"] == [{
        "argument": "contact", "operator": "contains_casefold", "value": "Aditya",
    }]
    assert hard_rule_for("whatsapp_send", {"contact": "aDiTyA", "message": "hello"}, [rule]) is rule
    assert hard_rule_for("whatsapp_send", {"contact": "Anita", "message": "hello"}, [rule]) is None
    assert explicit_user_rules(["Never run out of tech talk at the water cooler."]) == []


def test_employment_and_workplace_aliases_share_canonical_entity_key():
    assert canonical_entity_key("employment") == "employer"
    assert canonical_entity_key("workplace") == "employer"
    assert canonical_entity_key("Company Name") == "employer"


@pytest.mark.parametrize("text", [
    "Never message Aditya on WhatsApp again.",
    "Don't call the office after six.",
    "Always ask before changing my calendar.",
    "From now on, use short replies.",
    "Stop doing that during meetings.",
])
def test_standing_instructions_are_never_forget_intent(text):
    assert not _has_explicit_memory_forget_intent(text)


@pytest.mark.parametrize("text", [
    "Forget the rule about Aditya.",
    "Delete the stored rule about Aditya.",
    "Remove that preference from memory.",
    "Clear my memory about this fact.",
    "Erase the remembered pattern.",
])
def test_memory_forget_needs_explicit_forget_or_stored_memory_target(text):
    assert _has_explicit_memory_forget_intent(text)


@pytest.mark.parametrize("text", [
    "Delete the email draft.",
    "Clear my calendar.",
    "Remove Aditya from the group.",
])
def test_non_memory_delete_requests_are_not_forget_intent(text):
    assert not _has_explicit_memory_forget_intent(text)


def test_memory_writer_schema_uses_typed_objects_supported_by_openai_strict_output():
    schema = MemoryWrite.model_json_schema()

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") in (None, False)
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)


@pytest.mark.asyncio
async def test_memory_routing_eval_uses_mock_structured_llm_for_paraphrases_and_negatives():
    dataset = yaml.safe_load((Path(__file__).resolve().parents[2] / "evals/datasets/memory-routing.yaml").read_text(encoding="utf-8"))
    expected_by_phrase = {
        utterance.casefold(): (case["operation"], case.get("store"))
        for case in dataset
        for utterance in case["utterances"]
    }
    for case in dataset:
        for negative in case.get("negatives", []):
            if isinstance(negative, str):
                expected_by_phrase[negative.casefold()] = ("none", None)
            else:
                expected_by_phrase[negative["utterance"].casefold()] = (
                    negative.get("operation", "none"), negative.get("store"),
                )

    class MockRouter:
        async def ainvoke(self, messages):
            assert isinstance(messages[0], SystemMessage)
            assert isinstance(messages[1], HumanMessage)
            intent, store = expected_by_phrase[messages[1].content.casefold()]
            reads = [SimpleNamespace(store=store)] if store else []
            return SimpleNamespace(memory_intent=intent, memory_reads=reads)

    results = await evaluate_memory_routing(MockRouter(), dataset)
    assert len(results) == sum(len(case["utterances"]) + len(case.get("negatives", [])) for case in dataset)
    assert all(result["pass"] for result in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", ["pause it", "do it again"])
async def test_route_uses_one_structured_call_and_passes_last_action_to_resolve_follow_up(utterance):
    class Router:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, messages):
            self.calls.append(messages)
            return RouteDecision(likely_skills=["spotify"], memory_reads=[], memory_intent="none")

    class Agent:
        def __init__(self):
            self.bound_tools = []
            self.system_text = ""

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def astream(self, messages):
            self.system_text = next(message.content for message in messages if isinstance(message, SystemMessage))
            yield AIMessageChunk(content="Paused the last track.")

    runtime = CoreGraphRuntime()
    runtime.router_model = Router()
    runtime.vault = PIIVault(b"route-test-hmac", Fernet.generate_key())
    runtime.memory = None
    runtime.skills = SkillsRuntime(Path(__file__).resolve().parents[2] / "skills")
    runtime.main_model = Agent()
    runtime.saver = MemorySaver()
    runtime.limits = {"max_tool_rounds": 8, "token_budget": 100}
    runtime.persona = "Test persona"
    async def load_skill(name: str) -> str:
        return runtime.skills.load(name, [])[0]
    runtime.load_skill_tool = StructuredTool.from_function(coroutine=load_skill, name="load_skill", description="load")
    graph = runtime._build_graph()
    events = [event async for event in graph.astream(
        {
            "messages": [HumanMessage(content=utterance)],
            "user_id": "test-user",
            "thread_id": "pause-followup",
            "last_action": {"tool": "spotify_play", "args": {"track": "Blue Monday"}},
            "active_skills": [],
            "memory_context": "",
            "tool_rounds": 0,
        },
        config={"configurable": {"thread_id": "pause-followup"}},
        stream_mode="custom",
    )]
    assert len(runtime.router_model.calls) == 1
    assert "Blue Monday" in runtime.router_model.calls[0][0].content
    assert utterance in runtime.router_model.calls[0][1].content
    assert "spotify_play" in runtime.main_model.system_text
    assert any(event.get("kind") == "token" for event in events)
    assert any(event.get("kind") == "activity" and event.get("event") == "Memory" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("utterance", [
    "Run echo hello in the VS Code terminal.",
    "Change the text to hello from Arya.",
])
async def test_model_cannot_turn_ordinary_commands_into_procedural_write_replies(utterance):
    class Router:
        async def ainvoke(self, messages):
            return RouteDecision(likely_skills=["vscode"], memory_reads=[], memory_intent="procedural_write")

    class Agent:
        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def astream(self, messages):
            yield AIMessageChunk(content="Handled by the normal agent.")

    runtime = CoreGraphRuntime()
    runtime.router_model = Router()
    runtime.vault = PIIVault(b"ordinary-command-route", Fernet.generate_key())
    runtime.memory = None
    runtime.skills = SkillsRuntime(Path(__file__).resolve().parents[2] / "skills")
    runtime.main_model = Agent()
    runtime.saver = MemorySaver()
    runtime.limits = {"max_tool_rounds": 8, "token_budget": 100, "turn_token_budget": 1000}
    runtime.persona = "Test persona"

    async def load_skill(name: str) -> str:
        return runtime.skills.load(name, [])[0]

    runtime.load_skill_tool = StructuredTool.from_function(
        coroutine=load_skill, name="load_skill", description="load"
    )
    graph = runtime._build_graph()
    events = [event async for event in graph.astream(
        {
            "messages": [HumanMessage(content=utterance)],
            "user_id": "test-user",
            "thread_id": f"ordinary-{abs(hash(utterance))}",
            "active_skills": [],
            "memory_context": "",
            "tainted": False,
            "tool_rounds": 0,
        },
        config={"configurable": {"thread_id": f"ordinary-{abs(hash(utterance))}"}},
        stream_mode="custom",
    )]
    streamed = "".join(event.get("text", "") for event in events if event.get("kind") == "token")
    assert streamed == "Handled by the normal agent."
    assert "couldn't identify a direct standing instruction" not in streamed


@pytest.mark.asyncio
async def test_memory_write_is_queued_without_waiting_for_the_writer():
    runtime = CoreGraphRuntime()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_write(state):
        started.set()
        await release.wait()

    runtime._background_memory_write = slow_write
    runtime._queue_memory_write({"user_id": "test", "thread_id": "thread"})
    await started.wait()
    assert len(runtime.background_tasks) == 1
    release.set()
    await asyncio.gather(*runtime.background_tasks)


@pytest.mark.asyncio
async def test_mocked_model_cannot_bypass_hard_contact_rule_for_whatsapp_send():
    rule = explicit_user_rules(["Never message Aditya on WhatsApp again."])[0]
    tool_calls = []

    class Pool:
        class Connection:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def execute(self, query, params):
                return None

        def connection(self):
            return self.Connection()

    class Router:
        async def ainvoke(self, messages):
            return RouteDecision(likely_skills=["whatsapp"], memory_reads=[], memory_intent="none")

    class Memory:
        async def always_context_and_procedures(self, user_id, *, token_budget):
            return "hard procedure", [rule]

        async def routed_reads(self, user_id, reads):
            return ""

    class Agent:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            self.calls += 1
            if self.calls == 1:
                yield AIMessageChunk(content="", tool_call_chunks=[{
                    "name": "whatsapp_send",
                    "args": json.dumps({"contact": "aDiTyA", "message": "Hi"}),
                    "id": "blocked-send",
                    "index": 0,
                }])
            else:
                yield AIMessageChunk(content="I blocked that message.")

    async def send(contact: str, message: str):
        tool_calls.append((contact, message))
        return {"success": True}

    runtime = CoreGraphRuntime()
    runtime.pool = Pool()
    runtime.saver = MemorySaver()
    runtime.vault = PIIVault(b"policy-graph-test", Fernet.generate_key())
    runtime.skills = SkillsRuntime(Path(__file__).resolve().parents[2] / "skills")
    runtime.router_model = Router()
    runtime.main_model = Agent()
    runtime.memory = Memory()
    assert hard_rule_for("whatsapp_send", {"contact": "aDiTyA", "message": "Hi"}, [rule]) is rule
    runtime.tools = {
        "whatsapp_send": StructuredTool.from_function(coroutine=send, name="whatsapp_send", description="Send a WhatsApp message")
    }
    runtime.device_tools = runtime.tools
    runtime.limits = {"max_tool_rounds": 8, "tool_timeout_seconds": 2, "token_budget": 100}
    runtime.persona = "Test"

    async def load_skill(name: str):
        return runtime.skills.load(name, [])[0]

    runtime.load_skill_tool = StructuredTool.from_function(coroutine=load_skill, name="load_skill", description="Load a skill")
    runtime.graph = runtime._build_graph()
    events = [event async for event in runtime.stream_turn(
        SimpleNamespace(message="Send a WhatsApp message to Aditya", user_id="policy-user"),
        "blocked-contact",
    )]
    response = "".join(event["chunk"] for event in events if "chunk" in event)
    assert tool_calls == []
    assert "Blocked by a standing rule" in response
    assert "Nothing was changed" in response
    await asyncio.gather(*runtime.background_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_background_writer_logs_empty_extraction_and_persistence(caplog):
    caplog.set_level(logging.INFO, logger="arya.core")
    class Writer:
        async def ainvoke(self, messages):
            return MemoryWrite(entities=[], procedures=[], episode=None, patterns=[])

    class Memory:
        async def write_records(self, user_id, thread_id, records, *, user_texts, memory_management_turn=False):
            assert records == {"entities": [], "procedures": [], "episode": None, "patterns": []}
            assert user_id == "user-test"
            assert user_texts == ["remember my preference"]
            return {"entities": 0, "procedures": 0, "episodes": 0, "patterns": 0}

    runtime = CoreGraphRuntime()
    runtime.vault = PIIVault(b"write-log-test", Fernet.generate_key())
    runtime.memory = Memory()
    runtime.memory_writer_model = Writer()
    await runtime._background_memory_write({
        "messages": [HumanMessage(content="remember my preference")],
        "user_id": "user-test",
        "thread_id": "thread-test",
    })
    assert "memory_write_started" in caplog.text
    assert "memory_write_empty_extraction" in caplog.text
    assert "memory_write_persisted" in caplog.text


@pytest.mark.asyncio
async def test_background_writer_logs_full_error(caplog):
    class BrokenWriter:
        async def ainvoke(self, messages):
            raise RuntimeError("mock structured output error")

    runtime = CoreGraphRuntime()
    runtime.vault = PIIVault(b"write-error-test", Fernet.generate_key())
    runtime.memory = object()
    runtime.memory_writer_model = BrokenWriter()
    await runtime._background_memory_write({
        "messages": [HumanMessage(content="remember my preference")],
        "user_id": "user-test",
        "thread_id": "thread-test",
    })
    assert "Background memory_write failed" in caplog.text
    assert "RuntimeError: mock structured output error" in caplog.text


def test_real_tool_schema_fixture_and_skill_are_loaded_for_graph_regression():
    root = Path(__file__).resolve().parents[2]
    skills = (root / "skills/email/SKILL.md").read_text(encoding="utf-8")
    schemas = json.loads((root / "tests/fixtures/google_email_tool_schemas.json").read_text(encoding="utf-8"))
    assert "gmail_send" in skills
    assert {"search_email", "read_email", "send_email"} <= {row["name"] for row in schemas}

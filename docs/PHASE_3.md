# Phase 3 — Core graph v0

Status: custom graph, API contract, Postgres persistence wiring, device MCP client, and skills runtime implemented. No live desktop action or paid OpenAI request was run during verification.

The FastAPI core loads `.env` at startup, uses the configured `gpt-4o` and `gpt-4o-mini` models, initializes `AsyncPostgresSaver` against `DATABASE_URL`, and fetches typed device tools through `MultiServerMCPClient`. The adapter connection is `streamable_http` at `http://127.0.0.1:5002/mcp/` and sends `Authorization: Bearer <DEVICE_TOKEN>`. The graph is a custom `StateGraph` with ingest, structured skill routing, agent, tools, deterministic action logging, and response nodes.

User input and device results are tokenised before entering graph state. Tool arguments are detokenised only before local device execution; unknown tokens produce an error result without executing the tool. Outbound OpenAI HTTP payloads are checked with the PII guard. The action logger writes tokenised tool arguments and summaries to `action_log` and keeps `last_action` in graph state. Skills load progressive-disclosure instructions from `skills/*/SKILL.md`; only tools from active skills are bound, with `load_skill` always available.

## Verification

- Installed APIs inspected: LangGraph `0.4.8`, `langchain-mcp-adapters` `0.1.4`, `langchain-openai` `0.3.18`, MCP `1.9.4`.
- `uv run --extra device --group dev python -m pytest tests/unit -q`: **18 passed**. The core graph test uses fake models, a fake Postgres pool, and a fake WhatsApp tool; it verifies PII tokenisation, action logging, and split-token detokenisation.
- Python compilation passed for the core runtime, skills runtime, action logger, API, and manual smoke client.
- The exact `AsyncConnectionPool` plus `AsyncPostgresSaver` configuration passed against the configured local database with the Windows selector event loop. The device server and OpenAI request were not exercised in this turn.

## Manual smoke test

Start the device MCP server in the logged-in desktop session, then start the core in another terminal:

```powershell
uv run --extra device --group dev python -m device.server
uv run --extra device --group dev python -m core
```

In a third terminal, verify the SSE contract with a text-only default prompt:

```powershell
uv run --extra device --group dev python scripts/core_smoke.py
```

The script prints each received SSE event and checks that `session_id` is first and `done` is last. It makes a real model request but its default prompt asks the assistant not to use tools.

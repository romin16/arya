# Phase 7 — Observability, evaluations, and cutover

Status: **implemented; verification recorded below**. This phase adds PII-safe observability, a model comparison runner, SSE contract replay, migration checks, and Windows setup documentation. The user's existing Langfuse stack is used; this repository does not own or modify its files.

## Verified

- Langfuse: the user confirmed traces appear in the existing local instance. The core wraps one trace around each `/chat` turn, records the session/thread and user IDs, attaches graph callbacks for node/tool runs, scrubs PII before export, and degrades safely when telemetry is unavailable. Startup status logs contain no credentials. Compose helper scripts always pass the configured external project directory and `.env`, and reject a directory inside this repository.
- Outgoing message memory isolation: tool arguments for email, WhatsApp, and calendar content are limited to the current user turn or an explicit approval edit. The Postgres graph regression seeds conflicting old episode text and checks that the approval question contains only the current content. A live approval eval case covers stale recalled text.
- Migrations: versioned migrations 001–003, post-apply object verification, and a startup read-query self-check are present. Temporary-Postgres integration tests upgrade the original Phase 1 schema, exercise every memory-store read/write path, and prove a missing `knowledge_chunks.title` is detected before migration 003. The authorized `arya` apply added/backfilled that column and reported schema version 3. It did not delete or drop rows.
- Eval runner: `python -m evals.run` loads all six suites and `--live --models gpt-4o,gpt-4o-mini` prints pass rate and p50/p95 time-to-first-chunk. The tool-routing dataset has 14 required coverage cases. Most recent live run:

  | Suite | gpt-4o | gpt-4o-mini |
  |---|---:|---:|
  | Tool routing | 14/14 | 14/14 |
  | Memory routing | 44/46 | 46/46 |
  | Approvals | 6/6 | 6/6 |
  | Persona tone | 3/3 | 3/3 |
  | Exact reply | 1/1 | 1/1 |
  | Structured schemas | 3/3 | 3/3 |

  The two gpt-4o memory-routing misses were `general_knowledge` (`episode_read` returned `entity_read`) and `standing_rule` (`knowledge_read` returned `none`). The all-suite command therefore returned exit code 1. No tool actions were executed; routing tools were inert and all non-OpenAI network calls were mocked.
- SSE: `tests/unit/test_sse_frontend_contract.py` replays success and error events through `/chat`, checks event order and shapes, and checks the event fields consumed by `legacy/arya.html`.
- Extras: `scripts/sync.ps1` uses the lockfile and installs voice, device, and observability extras; `deploy/start_all.ps1` invokes it. Voice and device report the missing extra clearly.
- Cutover/docs: `scripts/`, `config/`, and `docs/` contain no orchestration-service references. `legacy/` remains unchanged. `docs/RUNBOOK.md` and this `docs/MIGRATION.md` document fresh setup, migrations, services, and rollback references.
- STT filter: configured short/quiet hallucination filtering for “Thank you”, “Thanks for watching”, and “you” exists in `voice/stt_filter.py`, `config/voice.yaml`, and unit tests.
- Langfuse reconnect: authentication retries in a background task with exponential backoff; when the service becomes reachable, one connection log is emitted. Chat remains available while telemetry is unavailable.
- Memory writer guard: only matching explicit first-person facts may enter entities; contact lookup requests and tool results cannot create entity or procedure rows.
- Persona guard: streamed replies replace banned phrases even when split across model chunks. The tone eval includes a lofi playback case.
- Google MCP loopback bind: setup patches the helper's supported `serve(host=...)` option, and the launcher supplies `MCP_HOST=127.0.0.1`. The installed source was patched and inspected; the server was not started.

## Test output for the last numbered step

- Unit suite: `121 passed, 1 warning`.
- Temporary PostgreSQL integration suite: `35 passed, 1 warning`; migrations 001, 002, and 003 applied to the disposable database.
- Ruff: `All checks passed!`.

The warning is LangGraph's upstream pending-deprecation notice for the checkpoint serializer's future `allowed_objects` default.

# Phase 7 — Observability, evaluations, and cutover

Status: **implemented; verification recorded below**. This phase adds PII-safe observability, a model comparison runner, SSE contract replay, migration checks, and Windows setup documentation. The user's existing Langfuse stack is used; this repository does not own or modify its files.

## Verified

- Langfuse: the user confirmed traces appear in the existing local instance. The core wraps one trace around each `/chat` turn, records the session/thread and user IDs, attaches graph callbacks for node/tool runs, scrubs PII before export, and degrades safely when telemetry is unavailable. Startup status logs contain no credentials. Compose helper scripts always pass the configured external project directory and `.env`, and reject a directory inside this repository.
- Outgoing message memory isolation: tool arguments for email, WhatsApp, and calendar content are limited to the current user turn or an explicit approval edit. The Postgres graph regression seeds conflicting old episode text and checks that the approval question contains only the current content. A live approval eval case covers stale recalled text.
- Migrations: versioned migrations 001 and 002 and the startup schema guard are present. Temporary-Postgres integration tests upgrade a Phase 1 schema and rerun idempotently. The authorized `arya` apply command reported no pending migrations and schema version 2; it made no row changes because the database was already current.
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

## Test output for the last numbered step

- Unit suite: `113 passed, 1 warning`.
- Temporary PostgreSQL integration suite: `33 passed, 1 warning`; migrations 001 and 002 applied to the disposable database.
- Ruff: `All checks passed!`.

The warning is LangGraph's upstream pending-deprecation notice for the checkpoint serializer's future `allowed_objects` default.

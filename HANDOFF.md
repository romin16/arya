# ARYA v4 — Handoff for a new coding-agent session

Read this file first, then `ARYA_CODEX_PROMPT.md` (the original design brief; this file overrides it where they differ). The repo is the source of truth. Do not assume anything from an earlier chat.

## 1. What this project is

ARYA is a personal voice assistant, being migrated from n8n + Flask to a LangGraph agent served by FastAPI. The user is on Windows 10/11, Python 3.12 via `uv`, local PostgreSQL 18 with pgvector, database `arya`. Old code lives in `legacy/` (do not edit; `legacy/arya.html` has its Picovoice key redacted; the user's working copy of `arya.html` is outside the repo and must keep working unchanged).

Processes (all bind to 127.0.0.1): arya-core :5000 (FastAPI, LangGraph, SSE `/chat`, `/health`, `POST /approve`), arya-voice :5001 (`/speak`, `/transcribe`, `/stop`), arya-device :5002 (FastMCP, bearer token, one serial GUI queue, `/panic`), Google Workspace MCP :8321 (`snickery/google-accounts-mcp` pinned commit 2839885, installed at `%LOCALAPPDATA%\Arya\google-accounts-mcp`, tokens in `%LOCALAPPDATA%\Arya\google-mcp-data\tokens.db`, outside the repo). Start all: `.\deploy\start_all.ps1`. Logs in `logs/arya-*.log`.

Standard sync command (never drop extras): `uv sync --locked --extra observability --extra dev --extra voice --extra device`.

Clean restart (stale processes have fooled us before):
```
Get-NetTCPConnection -LocalPort 5000,5001,5002,8321 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
.\deploy\start_all.ps1
```

## 2. Done and verified (git tags exist: phase-1 … phase-6)

- Phase 1 foundation: schema, PII vault and tokeniser/detokeniser (deterministic `[EMAIL_xxxxxx]` / `[PHONE_xxxxxx]` tokens, Fernet-encrypted vault, streaming detokeniser, egress guard that re-tokenises by default, `PII_EGRESS_STRICT=1` only in tests).
- Phase 2 device MCP server (20 tools; `whatsapp_read` was removed on purpose). Verified live.
- Phase 3 core graph, SSE contract, skills runtime, persona. Verified live with the real `arya.html` (text and voice).
- Voice server (ElevenLabs, Sarvam, Groq STT, PII masking before TTS). Verified live.
- Phase 4 Google (Gmail, Calendar, Contacts via MCP adapters), native `web_search` (Google CSE behind a provider setting; the API shuts down 2027-01-01, Tavily/Brave stubs exist), `get_weather` (Open-Meteo), `calculator`. Verified live.
- Phase 5 five-store memory (entities versioned, episodes, knowledge, procedures with code-enforced tool/argument constraints, patterns with N-observations rule), router, background writer, `memory_forget` with thread-bound confirmation, soft delete + tombstones. Verified live.
- Phase 6 policy gate (`config/policy.yaml`), approvals via `interrupt()`, verifier, injection taint, caps. Verified live: approval question shows the real recipient/content, yes sends, no cancels, edit re-asks (`approval.edit_requires_reconfirm`), audit rows (`awaiting_approval`, `succeeded`, `approved_by`, `approved_at`, `approval_channel`), `pending_operations` cleaned up.

Test status at last full run: 131 passed, ruff clean, live evals all passing (routing 46/46, approvals 5/5, structured schemas 3/3).

## 3. In progress when the previous session stopped (credits ran out) — VERIFY FIRST

The last session was in the middle of Phase 7 Part B and its final edits were NOT verified. Treat everything below as unreviewed:
- `core/observability.py` (new), edits to `core/app.py` and `core/graph/runtime.py`, `tests/unit/test_observability.py` (Langfuse callback handler, Logfire; last edits changed trace/session propagation).
- `deploy/langfuse/{start,stop,status}.ps1` and README: thin scripts only. Langfuse is ALREADY installed and running on the user's PC at `C:\Users\abc\langfuse` (UI http://localhost:3000, keys already in `.env`). Do not download or start a second copy and do not modify that folder.
- Versioned migrations: `db/migrations/001_phase1_baseline.sql`, `002_current_graph_schema.sql`, new `db/apply_schema.py`, `db/schema_version.py`, core refuses to start if the database is behind, `tests/integration/test_schema_migrations.py`.
- A stray `_run_migration_tests.py` in the repo root (helper that creates a temporary database); move it into `scripts/` or delete it.
- `pyproject.toml` was edited (a dependency pin) and `uv.lock` re-locked.

First actions: `git status`, `git diff --stat`, run `uv sync --locked --extra observability --extra dev --extra voice --extra device`, `uv run ruff check .`, the unit tests, and the Postgres integration tests with a temporary database. Fix anything broken before adding features. Apply migrations to the real `arya` database with `uv run --env-file .env python db/apply_schema.py` and show the output; never touch row data.

## 4. Remaining work (Phase 7 Part B)

1. B1 Langfuse integration: one trace per `/chat` turn, `session_id` = thread id, `user_id`, spans for router, memory reads, agent, each tool, verifier, memory write; cost and latency. Only PII-tokenised content may be exported (test it).
2. B2 Logfire: infrastructure spans only (FastAPI, psycopg, httpx), message/prompt content capture OFF, optional via `LOGFIRE_TOKEN`.
3. B3 Both integrations failure-safe (ARYA must keep working if Langfuse/Logfire are down or unconfigured).
4. B4 Eval runner: `python -m evals.run` runs every suite (tool-routing, memory-routing, approvals, persona-tone, exact-reply, structured schemas) with `--models gpt-4o,gpt-4o-mini` and prints pass rate, p50/p95 time-to-first-chunk and cost per suite per model; `--push-langfuse` optional. The tool-routing suite must cover Spotify play/pause/resume/next, open/close apps, WhatsApp, email send, calendar create, contacts search, weather, web search, and "pause it"/"do it again".
5. B5 Cutover: no remaining n8n dependency in scripts/config/docs, `docs/RUNBOOK.md` (fresh Windows machine to working system) and `docs/MIGRATION.md` (what replaced what). Keep `legacy/` untouched.
6. B6 SSE contract replay test against what `legacy/arya.html` expects: `{"session_id"}` first, then `{"activity":{"event","message"}}`, `{"chunk"}`, `{"done":true}` last, plus the error form.
7. Make the full extras set the default (or add `scripts/sync.ps1`) so `uv sync` can't drop voice/device packages; services should fail with a clear message naming the missing extra.

## 5. Known open items (not blocking)

- Confirm whether the STT hallucination filter ("Thank you.", "Thanks for watching.", "you" on short or quiet audio, config-driven) was committed; if not, implement it with tests.
- ARYA's reply after an approved edit once said the email was sent "with the original text" although the edited text was sent; check the verifier wording. Also check that a fresh chat never inherits a pending approval's text from an earlier thread.
- Live eval case "Change the text to hello from Arya." was misrouted to a memory write once; routing examples were added, re-check.
- Voice: speak only the last two digits of phone numbers (verified); Groq STT still hears raw speech (documented limitation; local faster-whisper is a future option).
- Optional later: reuse one MCP session per service instead of one per call; sentence-level TTS streaming; Spotify Web API (needs Premium); Picovoice key should be loaded from config instead of hard-coded in the HTML (needs a small, approved frontend change).
- User to-dos outside the code: rotate the Picovoice key that was in the old HTML; set the Google OAuth consent screen to "In production" so the refresh token does not expire weekly.

## 6. Working rules (learned the hard way)

- Mock the network and the GUI in tests. Never call the user's real Google account, WhatsApp or any real provider, except the OpenAI calls the `--live` evals need. Never click, type, or open apps on the user's desktop.
- Never print, log or commit secrets, tokens, real email addresses or phone numbers. Use `.env` variable names only (see `.env.example`). Never read `.env` values into scripts that print them.
- Tests must not only use fresh databases and mocked models: bugs repeatedly appeared only on the real system (invalid structured-output schemas that OpenAI rejected, a real database behind the schema, stale processes on ports, Windows cp1252 printing emoji into a redirected log). When changing anything structured-output, schema, skill text or startup, add a test that uses the real schema/skill text/tool registry, and a `--live` check.
- Windows specifics: the core uses `WindowsSelectorEventLoopPolicy` for psycopg async, so it cannot spawn subprocesses (run MCP servers as separate processes and connect by URL). Services run with `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`. Do not use `Invoke-WebRequest` quoting tricks for JSON; the user tests through the browser UI.
- Honesty is a product requirement: ARYA must never claim an action or a memory write that did not happen (the verifier enforces this); a status of `succeeded` only when something really happened.
- Never weaken or delete a test to make it pass. Small commits, one concern each. After each step run `pytest` and `ruff check .` against a real temporary Postgres and report the real output, including failures. Say clearly what is done, what is not, and what is verified. End each task with copy-paste manual steps for PowerShell/psql that use only messages to the user's own account or a test contact.
- The user cannot easily give long chat context: keep reports short and concrete, and update this file's sections 2 to 4 when state changes.

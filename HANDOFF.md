# ARYA v4 — Handoff for a new coding-agent session

Read this file first, then `ARYA_CODEX_PROMPT.md` (the original design brief; this file overrides it where they differ). The repo is the source of truth. Do not assume anything from an earlier chat.

## 1. What this project is

ARYA is a personal voice assistant built with LangGraph and FastAPI. The user is on Windows 10/11, Python 3.12 via `uv`, local PostgreSQL 18 with pgvector, database `arya`. Old code lives in `legacy/` (do not edit; `legacy/arya.html` has its Picovoice key redacted; the user's working copy of `arya.html` is outside the repo and must keep working unchanged).

Processes (all bind to 127.0.0.1): arya-core :5000 (FastAPI, LangGraph, SSE `/chat`, `/health`, `POST /approve`), arya-voice :5001 (`/speak`, `/transcribe`, `/stop`), arya-device :5002 (FastMCP, bearer token, one serial GUI queue, `/panic`), Google Workspace MCP :8321 (`snickery/google-accounts-mcp` pinned commit 2839885, installed at `%LOCALAPPDATA%\Arya\google-accounts-mcp`, tokens in `%LOCALAPPDATA%\Arya\google-mcp-data\tokens.db`, outside the repo). Start all: `.\deploy\start_all.ps1`. Logs in `logs/arya-*.log`.

Standard sync command (never drop extras): `uv sync --locked --extra observability --extra voice --extra device`. The launcher runs `scripts/sync.ps1` before starting the services.

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

Most recent local test status: 113 unit tests and 33 temporary-Postgres integration tests pass; Ruff is clean. The all-suite OpenAI comparison passes all listed suites for `gpt-4o-mini`; `gpt-4o` has two memory-routing misses. See sections 3 and 4.

## 3. Phase 7 status

- Langfuse callback integration and PII-safe recording tests are implemented. The user confirmed traces appear in the existing local Langfuse instance. Do not touch `C:\Users\abc\langfuse` or start another stack. Compose scripts pass the external directory and env file explicitly and reject an in-repository directory.
- Versioned migrations 001 and 002, `schema_migrations`, idempotent application, and the core schema-version guard are implemented. Disposable-Postgres tests upgrade a Phase 1 schema. The authorized real-database apply reported no pending migrations and schema version 2; no migrations or row transformations were needed in that run.
- Outgoing email, WhatsApp, and calendar text is isolated from recalled memory; graph integration coverage and a live approval eval case are present.
- All-suite eval runner, SSE replay, full-extras sync launcher, runbook, and migration map are implemented. See `docs/PHASE_7.md` for exact live eval results and the two remaining gpt-4o routing misses.
- The STT hallucination filter is config-driven and tested. No `_run_migration_tests.py` helper was present when checked.
- Last numbered-step checks: 113 unit tests passed, 33 temporary-Postgres integration tests passed, Ruff clean. The only warning is LangGraph's pending serializer-default deprecation.

## 4. Remaining work

- Investigate and resolve the two live `gpt-4o` memory-routing mismatches (`general_knowledge` and `standing_rule`) without weakening the eval cases. `gpt-4o-mini` passed 46/46.
- Optional: add suite cost reporting and a Langfuse dataset-run upload flag if required by a later acceptance request; the current eval contract reports pass rate and p50/p95 first-chunk latency.

## 5. Known open items (not blocking)

- The live eval runner has two outstanding gpt-4o memory-routing mismatches; details are in `docs/PHASE_7.md`.
- ARYA's reply after an approved edit once said the email was sent "with the original text" although the edited text was sent; check the verifier wording. Also check that a fresh chat never inherits a pending approval's text from an earlier thread.
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

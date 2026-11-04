# ARYA Windows runbook

This runbook starts with a fresh Windows 10/11 machine. Commands below run from the repository root in PowerShell. Keep `.env` and all tokens out of source control.

## 1. Install prerequisites

Install Python 3.12, `uv`, Git, Node.js 22.12+, and PostgreSQL 18 with the pgvector extension available. The device service is intended for Windows and uses the local desktop session. Create a local clone of this repository and open PowerShell there.

## 2. Configure the project

```powershell
Copy-Item .env.example .env
notepad .env
```

Set the Postgres `DATABASE_URL`, `OPENAI_API_KEY`, `DEVICE_TOKEN`, Google OAuth values (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_ACCOUNT`, `GOOGLE_MCP_TOKEN`), voice provider keys, and any search provider keys you plan to use. Set a strong random value for each bearer-token setting. Do not paste `.env` contents into logs or chat.

Install the pinned project and all runtime extras:

```powershell
uv sync --locked --extra observability --extra voice --extra device
```

The launcher also runs `scripts/sync.ps1` so a prior plain `uv sync` cannot leave the services without their extras.

## 3. Prepare PostgreSQL and apply migrations

Create the `arya` database and enable the required extensions as a database administrator, then apply the versioned migrations:

```powershell
psql -d arya -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql -d arya -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
uv run --env-file .env python db/apply_schema.py
```

The migration runner is idempotent and records applied versions in `schema_migrations`. Core checks the database version at startup and reports an actionable error if it is behind the application.

## 4. Configure Google Workspace access

In Google Cloud Console, enable Gmail, Calendar, and People APIs. Create a Desktop OAuth client and put its ID and secret in `.env`. Set `GOOGLE_ACCOUNT` to the authorized account and choose `GOOGLE_MCP_TOKEN`.

Run the setup script once:

```powershell
.\scripts\setup_google_mcp.ps1 -Account you@example.com
```

It installs the pinned Google MCP server under `%LOCALAPPDATA%\Arya`, stores its token database and attachments outside this repository, and skips browser authorization when the requested account is already present. Otherwise, complete the Google consent screen. Drive and Tasks remain hidden from ARYA.

## 5. Start ARYA

```powershell
.\deploy\start_all.ps1
```

The launcher starts the authenticated device MCP server on 127.0.0.1:5002, voice on 127.0.0.1:5001, Google Workspace MCP on 127.0.0.1:8321, and core on 127.0.0.1:5000. It checks each service before continuing and writes output to `logs/`. Press Ctrl+C to stop the services.

To start device, voice, and Google MCP without core:

```powershell
.\deploy\start_all.ps1 -NoCore
```

The active Langfuse installation is managed separately. Its scripts use `LANGFUSE_COMPOSE_DIR` (default `C:\Users\abc\langfuse`) and pass that directory and its `.env` explicitly to Compose. They refuse to run if the configured directory resolves inside this repository. Do not create a second Langfuse stack.

## 6. First checks

In a second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health
Invoke-RestMethod http://127.0.0.1:5001/health
Invoke-RestMethod -Headers @{ Authorization = "Bearer $env:DEVICE_TOKEN" } http://127.0.0.1:5002/health
```

Serve `frontend/` with `scripts/serve_frontend.ps1` and open `http://localhost:8080`. Try an exact-reply request, a weather query with a named location, and harmless Spotify play/pause actions. For approval testing, use only an email to yourself or a non-production test contact; verify the approval question before approving. Never use a real recipient for destructive or external tests.

## Search provider

`config/search.yaml` defaults to Tavily (`TAVILY_API_KEY`); a local `.env` can override the provider on your machine. Google Custom Search remains selectable with `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID`; results are capped at five. On quota or permission errors, configured alternatives are tried when their keys exist. Tavily and Brave can be selected by changing this setting and providing the matching key. Switching providers requires only a config change. Google has announced that Custom Search JSON API access will close to new customers and the API will be discontinued on January 1, 2027.

## Tests and operations

```powershell
uv run ruff check .
uv run pytest tests/unit -q
uv run python scripts/run_postgres_tests.py
```

The Postgres test runner creates and drops a uniquely named disposable database. Tests mock HTTP providers, Google MCP, and GUI calls; they do not operate the desktop or contact real provider accounts.

Forgotten procedures are soft-deleted immediately. Reads, injected rules, policy enforcement, and user-facing counts ignore inactive rows. Nightly consolidation purges inactive procedure rows after `memory.inactive_procedure_retention_days` (90 days by default); tombstones separately suppress re-creation for the configured suppression window.

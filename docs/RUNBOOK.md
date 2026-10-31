# ARYA runbook

## Local setup

1. Copy `.env.example` to `.env`. Configure the Postgres URL, OpenAI/Groq/TTS keys, device token, Google OAuth credentials, `GOOGLE_MCP_TOKEN`, and search keys. Keep `.env` private.
2. Create the project Python 3.12 virtual environment and install the project with its `device` and `dev` extras. Node.js 22.12+ and `uv` are needed for the pinned Google MCP server setup.
3. In Google Cloud Console, enable Gmail API, Calendar API, and People API. Create an OAuth 2.0 client ID of type **Desktop app**. Put its ID and secret in `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` in `.env`. Generate a random bearer token for `GOOGLE_MCP_TOKEN`.
4. Run the one-time local OAuth setup in PowerShell:

   ```powershell
   .\scripts\setup_google_mcp.ps1 -Account you@example.com
   ```

   The script checks out the pinned `google-accounts-mcp` commit under `%LOCALAPPDATA%\Arya`, applies the loopback bind patch, syncs its locked dependencies, and stores data under `%LOCALAPPDATA%\Arya\google-mcp-data`. It checks `tokens.db` for the requested account and skips OAuth if that account is already authorized. Otherwise it opens Google's consent page. Sign in and grant access.

5. Start the four local processes:

   ```powershell
   .\deploy\start_all.ps1
   ```

   The launcher maps project OAuth and account values to `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `DEFAULT_ACCOUNT`, and maps `GOOGLE_MCP_TOKEN` to `MCP_BEARER_TOKEN`. It starts the documented `uv run google-accounts-mcp` command on port 8321, bound to `127.0.0.1`; core connects to `http://127.0.0.1:8321/mcp`. Health checks include a bearer-authenticated MCP initialize request. Press Ctrl+C in the launcher window to stop them.

   Use `.\deploy\start_all.ps1 -NoCore` to start device, voice, and Google MCP without starting core. Each service writes to `logs/<service>.log` with stderr in a companion `logs/<service>.stderr.log`; if any service exits, the launcher prints the last 40 lines of both streams.

## Search provider

`config/search.yaml` selects `search.provider`. `google_cse` uses `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID`; the implementation returns only the first five titles, URLs, and snippets. If Google returns a quota or permission status (HTTP 401, 403, or 429), it tries configured fallback providers in order when their keys exist.

Tavily and Brave are implemented as provider alternatives. To switch, change `search.provider` to `tavily` or `brave` and set `TAVILY_API_KEY` or `BRAVE_SEARCH_API_KEY`. No graph or tool changes are needed. Google has announced Custom Search JSON API closure to new customers and discontinuation on January 1, 2027, so choose a fallback before then.

Weather uses Open-Meteo geocoding and forecast APIs. If a request lacks a location, ARYA asks for one rather than guessing.

## Approval boundary

Policy marks Gmail send/reply/trash, Calendar delete, and Contact delete as `ask`. The Phase 6 approval graph is not implemented yet, so those adapters refuse the call with a clear message and do not contact Google. Draft creation and non-destructive reads/updates remain available according to `config/policy.yaml`. Only Gmail, Calendar, and Contacts tools are exposed to the agent; upstream Drive, shared-file, and Tasks tools are filtered out.

Outbound model payloads re-tokenize genuine email addresses and phone numbers before sending. `PII_EGRESS_STRICT=1` makes the guard fail closed; pytest sets this flag for CI and regression runs. Reserved example-domain addresses and obvious placeholder numbers are ignored. PII diagnostics record the kind, payload location, path, and a short hash, never the value.

## Memory deletion retention

Forgotten procedures are soft-deleted immediately. All memory reads, injected rules, policy checks, and deletion counts ignore inactive procedures. Nightly consolidation physically purges them after `memory.inactive_procedure_retention_days` (90 days by default). Their tombstones remain governed independently by `memory.tombstone_suppression_days` and prevent background extraction from recreating them during that suppression window.

## Manual checks

- Confirm the launcher reports all four processes healthy.
- In the unmodified `legacy/arya.html`, check Gmail search/read/draft, a Calendar lookup/create/update, and a Contacts search/create/update using a test account. The configured send/reply/trash and delete tools should explain that Phase 6 approval is not available and leave Google unchanged; don't invoke destructive operations during this check.
- Try a weather request without a city and confirm ARYA asks; give a city and confirm forecast output.
- Check `web_search` returns at most five compact results. To test provider fallback, temporarily select a provider/key combination known to reject requests; no real provider request should be used by automated tests.

Automated unit tests mock Google MCP tools and all HTTP provider requests. They never use the real Google account or search APIs.

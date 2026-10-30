# ARYA runbook

## Local setup

1. Copy `.env.example` to `.env`. Configure the Postgres URL, OpenAI/Groq/TTS keys, device token, Google OAuth credentials, `GOOGLE_MCP_TOKEN`, and search keys. Keep `.env` private.
2. Create the project Python 3.12 virtual environment and install the project with its `device` and `dev` extras. Node.js 22.12+ and `uv` are needed for the pinned Google MCP server setup.
3. In Google Cloud Console, enable Gmail API, Calendar API, and People API. Create an OAuth 2.0 client ID of type **Desktop app**. Put its ID and secret in `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` in `.env`. Generate a random bearer token for `GOOGLE_MCP_TOKEN`.
4. Run the one-time local OAuth setup in PowerShell:

   ```powershell
   .\scripts\setup_google_mcp.ps1 -Account you@example.com
   ```

   The script checks out the pinned `google-accounts-mcp` commit under `%LOCALAPPDATA%\Arya`, applies the loopback bind patch, syncs its locked dependencies, then opens Google's consent page. Sign in and grant Gmail, Calendar, and Contacts access. The refresh token database stays under `%LOCALAPPDATA%\Arya\google-accounts`.

5. Start the four local processes:

   ```powershell
   .\deploy\start_all.ps1
   ```

   The launcher starts device, voice, Google Workspace MCP, then core. It checks each health endpoint, including a bearer-authenticated MCP initialize request. Press Ctrl+C in the launcher window to stop them.

## Search provider

`config/search.yaml` selects `search.provider`. `google_cse` uses `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID`; the implementation returns only the first five titles, URLs, and snippets. If Google returns a quota or permission status (HTTP 401, 403, or 429), it tries configured fallback providers in order when their keys exist.

Tavily and Brave are implemented as provider alternatives. To switch, change `search.provider` to `tavily` or `brave` and set `TAVILY_API_KEY` or `BRAVE_SEARCH_API_KEY`. No graph or tool changes are needed. Google has announced Custom Search JSON API closure to new customers and discontinuation on January 1, 2027, so choose a fallback before then.

Weather uses Open-Meteo geocoding and forecast APIs. If a request lacks a location, ARYA asks for one rather than guessing.

## Approval boundary

Policy marks Gmail send/reply/trash, Calendar delete, and Contact delete as `ask`. The Phase 6 approval graph is not implemented yet, so those adapters refuse the call with a clear message and do not contact Google. Draft creation and non-destructive reads/updates remain available according to `config/policy.yaml`.

## Manual checks

- Confirm the launcher reports all four processes healthy.
- In the unmodified `legacy/arya.html`, check Gmail search/read/draft, a Calendar lookup/create/update, and a Contacts search/create/update using a test account. The configured send/reply/trash and delete tools should explain that Phase 6 approval is not available and leave Google unchanged; don't invoke destructive operations during this check.
- Try a weather request without a city and confirm ARYA asks; give a city and confirm forecast output.
- Check `web_search` returns at most five compact results. To test provider fallback, temporarily select a provider/key combination known to reject requests; no real provider request should be used by automated tests.

Automated unit tests mock Google MCP tools and all HTTP provider requests. They never use the real Google account or search APIs.

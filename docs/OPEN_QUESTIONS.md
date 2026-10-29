# Open questions and environment dependencies

- The source files remain in the user's Downloads folder and are treated as read-only. Several legacy files include credentials. They were not copied into the new tree; any later source reuse must remove secrets first.
- This execution environment is Python 3.10.10, while the target is Python 3.11+. The installed-package inventory has only `cryptography`; FastAPI, LangGraph, FastMCP/MCP, psycopg, pgvector, voice SDKs, and test dependencies are unavailable here. Their APIs therefore still need validation against the actual supported installation before implementation is accepted.
- No PostgreSQL connection string or local database availability was supplied. Schema application and idempotency acceptance remain unverified.
- No Google test OAuth account or credentials were supplied. The Google MCP bake-off and CRUD contract tests remain unrun; no candidate selection is claimed.
- Browser-use service, Docker, and interactive desktop are not available for end-to-end acceptance here. Preserve `arya.html` unchanged; it hard-codes core and voice endpoints at localhost ports 5000 and 5001.
- The user-supplied legacy HTML embeds a wake-word provider key. It is not copied or changed. Rotate it if it is a real credential and replace it using the provider's supported configuration mechanism outside this migration.
- The requested local faster-whisper option for speech recognition is deferred; current voice recognition is expected to use Groq and receives raw user speech by design.
- Install and verify the pinned Python dependencies on Python 3.11+ and generate a platform-appropriate lockfile before deployment. A lockfile cannot be generated reliably from this Python 3.10 host.

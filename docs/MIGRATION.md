# Migration map

This repository replaces the prior workflow orchestration and service layout with local Python services and PostgreSQL. The files in `legacy/` are retained unchanged as rollback references and as the frontend compatibility contract.

| Previous component | Current replacement | Data or behavior notes |
|---|---|---|
| Visual workflow orchestration and custom sub-workflows | LangGraph core graph with typed tools and policy gate | Runs as the local `arya-core` process. |
| Desktop Flask server and GUI agents | Authenticated FastMCP device server with one serial action queue | GUI actions stay local; `POST /panic` cancels queued work. |
| Voice Flask server and command-line helpers | Async FastAPI voice service | Provider calls are asynchronous; speech output is PII-masked before provider requests. |
| Hosted chat memory and separate legacy stores | PostgreSQL checkpointing and five fresh memory stores | No automatic historical memory import. New memory is PII-tokenised before storage. |
| Legacy contacts and unsupported agent actions | Google Contacts MCP and currently registered typed tools | Only Gmail, Calendar, and Contacts tools are exposed from the Google MCP process. |
| Existing browser frontend protocol | `/chat` SSE response contract on the local core | Tested against the parser in `frontend/arya.html`; `legacy/arya.html` remains unchanged as historical source. |

## Fresh database and upgrade path

There is no data migration from prior memory stores. Apply `db/migrations/NNN_*.sql` in order using `python db/apply_schema.py`. The runner records checksums and versions in `schema_migrations`, preserves existing Phase 1 rows, and safely skips migrations already applied. Core refuses startup if the database is older than the application schema. Forgotten procedure rows are soft-deleted, excluded from reads and policy enforcement, then purged after the configured retention period; tombstones prevent the writer from recreating forgotten rules during their suppression period.

## Rollback references

`legacy/` remains untouched. Use the current service and database migrations for normal operation. Do not run both old and new desktop agents at once; they can contend for the same GUI session.

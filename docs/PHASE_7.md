# Phase 7 — Observability, evaluations, and cutover

Status: **in progress**. Part A of the current follow-up was completed separately in commits `26ef8d3` (edit reconfirmation), `ee4f4a2` (approval audit), `a57ae92` (expired-operation cleanup), and `12981fa` (routing). This continuation adds versioned database migrations and a core startup version guard. Migration verification against a disposable local Postgres includes upgrading the Phase 1 schema. The migrations have not yet been applied to the user's `arya` database.

## Database migration prerequisite

Implemented migration versions 001 and 002, with checksums recorded in `schema_migrations`. `uv run --no-sync python -m db.apply_schema` applies pending migrations and is safe to re-run. Core refuses to start when migration metadata is missing, behind, or newer than the code. The integration test builds a Phase 1 database, upgrades it, verifies preserved data and new schema objects, and runs the migration a second time. Full suite: 134 passed against a disposable Postgres; Ruff passed. The real `arya` database application remains pending.

## B1 — Langfuse

The core now creates one trace scope per `/chat`, propagates the thread and user identifiers, attaches the LangChain callback to graph runs, tokenises callback payloads before export, flushes asynchronously, and logs startup enablement/auth status without keys. Recording-mock tests cover tokenisation and failure safety. A content-free local smoke attempt reached the existing Langfuse v4.71.0 instance and authenticated, but trace ingestion returned HTTP 500. Its web container logs show event upload failing because `127.0.0.1:9090` refuses connections from inside the container. No files under `C:\Users\abc\langfuse` were changed and no second stack was started. Real trace visibility is therefore not verified yet.

## B3 — Failure safety

Langfuse startup and callback failures are handled without failing chat. This is covered by unit tests. The local service was reachable and authenticated, but its trace ingestion path is unhealthy as described above.

## B4 — Evaluation runner

Not implemented or verified. The current opt-in live approval, memory-routing, and structured-schema suites are separate from the requested all-suite model comparison, latency/cost report, and Langfuse dataset-run support.

## B5 — Cutover documentation

Not implemented or verified. Existing n8n references still require a repository-wide audit; the fresh-machine runbook and migration map are not complete.

## B6 — SSE contract

Partially covered by existing core SSE unit tests, which assert `session_id` first, activity and chunks in order, `done` last, and the error form. A contract replay against the frontend event handling in `legacy/arya.html` has not been added.

No Phase 7 acceptance claim is made until B1–B6 are implemented and verified.

# Phase 7 — Observability, evaluations, and cutover

Status: **not started**. Part A of the current follow-up was completed separately in commits `26ef8d3` (edit reconfirmation), `ee4f4a2` (approval audit), `a57ae92` (expired-operation cleanup), and `12981fa` (routing). Its integration coverage passes against disposable Postgres. Phase 7 work B1–B6 has not begun.

## B1 — Langfuse

Not implemented or verified. No Langfuse Compose file has been downloaded or added. No trace callback is connected, and PII export behavior has not been tested.

## B2 — Logfire

Not implemented or verified. No instrumentation or capture settings are configured.

## B3 — Failure safety

Not implemented or verified. Optional-observability failure behavior has not been exercised.

## B4 — Evaluation runner

Not implemented or verified. The current opt-in live approval, memory-routing, and structured-schema suites are separate from the requested all-suite model comparison, latency/cost report, and Langfuse dataset-run support.

## B5 — Cutover documentation

Not implemented or verified. Existing n8n references still require a repository-wide audit; the fresh-machine runbook and migration map are not complete.

## B6 — SSE contract

Partially covered by existing core SSE unit tests, which assert `session_id` first, activity and chunks in order, `done` last, and the error form. A contract replay against the frontend event handling in `legacy/arya.html` has not been added.

No Phase 7 acceptance claim is made until B1–B6 are implemented and verified.

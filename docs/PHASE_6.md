# Phase 6 — Policy, approvals, verifier, and taint

Status: **B0–B7 verified**. Automated coverage uses local Postgres plus mocked LLM, MCP, provider, network, and GUI boundaries. No real Google account, messaging account, provider, or desktop action was used.

## B0 — LangGraph interrupt support

The pinned `langgraph==0.4.8` installation exposes `interrupt(value)` and `Command(resume=...)`. A PostgreSQL integration test pauses a real graph with `AsyncPostgresSaver`, resumes the same thread, and checks the resumed value. No dependency upgrade was needed. The existing `pending_operations` table remains the thread-bound store to reuse for approval metadata and expiry.

## Remaining work

## B1 — policy gate

The core loads each tool mode from `config/policy.yaml`, resolves overlapping globs by specificity, and fails closed for an unregistered tool. Startup validates that every configured policy key matches at least one registered tool. Protected calls are refused in code before tool invocation with “Approval is not set up yet”; the approval flow is not enabled yet. The config includes a catch-all auto mode and explicit ask overrides for the protected names and classes.

The `browser_task` skill currently names a tool that is not registered by this checkout; its policy entry is omitted until a browser adapter exists, so startup validation can accurately reject every unmatched policy entry.

## B2 — approval interrupts

An `ask` batch is stored as a thread-bound `tool_approval` pending operation and interrupted before any tool runs. The approval question renders tokenized recipient/content values for the user. The next `/chat` message is classified into approve, reject, edit, or unclear; edits are tokenized, schema-checked, and applied to the exact arguments sent to the adapter. Unclear answers re-ask, unrelated commands reject the pending batch and start normally, expiry rejects it, and multiple asked tools share one question. `POST /approve` resumes the same persisted interrupt. Until a policy-configured graph is available, the fallback remains a safe refusal.

PostgreSQL integration coverage verifies approved and rejected email actions, visible self-recipient/content, token-safe pending payloads, edit application and invalid-edit refusal, unclear re-asking, expiry, bundling, unrelated-command handling, and `/approve`. All tool calls in these tests are local mocks.

## B3 — reply verifier

Final assistant text is held until a deterministic verifier checks action verbs against successful tool results and checks save/remember/forget claims against memory operations and retrieved context. Unsupported claims are regenerated once with tool calling disabled; if the corrected text still makes an unsupported claim, a fixed honest fallback is sent. The graph test mocks a failed WhatsApp call and an unsupported memory claim, and confirms both are regenerated once without another tool call.

## B4 — untrusted-result taint

Gmail, Calendar, Contacts, web search, browser results, and WhatsApp OCR/read/image results are wrapped in source-tagged `<untrusted>` elements after PII tokenization. Reading one marks the current turn tainted. With the default-on policy flag, auto-mode side-effect tools escalate to approval for the rest of that turn; read-only tools stay automatic. User messages remain trusted.

The PostgreSQL test feeds a malicious instruction through a mocked web result. The graph tags it, taints the state, and pauses the otherwise-auto contact create call before the mocked contact tool executes.

## B5 — turn budgets

`limits.turn_token_budget` now caps estimated input and output tokens across the router, agent turns, and any verifier regeneration. It uses the installed `tiktoken` encoding, passes the remaining output allowance to OpenAI, and stops before another model call when the prompt consumes the remaining budget. The existing `max_tool_rounds` stops before executing an extra tool batch. Both limits return honest messages that do not claim unfinished actions succeeded.

The PostgreSQL suite checks that an exhausted token cap prevents router/agent calls and that a one-round tool cap executes only its allowed mocked action, then reports that it could not finish. There are no network/provider or GUI calls.

## B6 — launcher diagnostics

`deploy/start_all.ps1` sets `PYTHONUNBUFFERED=1`, redirects every child service's output to `logs/<service>.log` and stderr to `logs/<service>.stderr.log`, and prints the last 40 lines on startup failure, health timeout, or a later service exit. It keeps `-NoCore`. The supervisor now checks unexpected exits even when every child has exited. Unit tests pin these launcher contracts.

## B7 — acceptance coverage and verification

The Phase 6 acceptance coverage is mapped to the checked-in tests below. The PostgreSQL integration tests create a real graph with a disposable database and mocked external boundaries.

| Area | Coverage |
| --- | --- |
| LangGraph interrupt and Postgres resume | `tests/integration/test_phase6_interrupt_postgres.py::test_installed_langgraph_interrupt_resume_with_postgres_checkpointer` |
| Policy configuration and startup validation | `tests/unit/test_policy_gate.py`; `tests/unit/test_core_graph.py::test_runtime_start_checks_google_tools_with_mocked_servers` |
| Approval before side effects, approve/reject/edit/unclear, expiry, bundling, pending thread and `/approve` | `tests/integration/test_memory_postgres.py::test_approval_uses_real_skills_schemas_and_startup_registry` (email, WhatsApp, VS Code) and the approval tests that follow it |
| Honest action and memory claims | `tests/integration/test_memory_postgres.py::test_verifier_regenerates_unsupported_action_and_memory_claims_once` |
| Tool-result taint and side-effect escalation | `tests/integration/test_memory_postgres.py::test_untrusted_search_result_taints_turn_and_escalates_auto_create_to_approval` |
| Input/output token and tool-round caps | `tests/integration/test_memory_postgres.py::test_turn_token_cap_returns_honest_message_without_calling_model`; `test_tool_round_cap_stops_before_extra_tool_and_does_not_claim_it_succeeded` |
| Unbuffered service logs, log tails, startup failures, and `-NoCore` | `tests/unit/test_start_all_launcher.py` |
| PII-safe output and flushed per-turn logs | `tests/unit/test_pii.py`; `tests/unit/test_core_graph.py::test_core_log_handler_flushes_each_line` |

`pytest -q` and `ruff check .` passed after each numbered step. The final full suite passed against a fresh disposable local PostgreSQL database. Automated tests use mocks for all external service and GUI calls. No `temp_*.py` helpers were present to move or delete; reusable smoke scripts live under `scripts/`, and `.gitignore` explicitly excludes `temp_*.py`.

The live OpenAI approvals eval (`python -m evals.run --suite approvals --live`) passed 5/5: email-to-self, WhatsApp message, and VS Code command selected ask tools and paused; close Notepad and Spotify play selected auto tools and did not pause. Every tool implementation in this eval is an inert mock.

## Manual end-to-end check

Use the real UI only for an email to the authorized account owner, review the approval text, and approve only if both recipient and content are correct. See the final Phase 6 completion instructions for PowerShell and psql commands. Do not test against another person's account or contact.

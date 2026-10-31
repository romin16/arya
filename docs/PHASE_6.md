# Phase 6 — Policy, approvals, verifier, and taint

Status: **B0–B5 verified; B6–B7 not implemented**.

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

B6 launcher fixes and B7 full scenario coverage remain unimplemented.

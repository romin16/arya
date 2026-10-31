# Phase 6 — Policy, approvals, verifier, and taint

Status: **B0–B2 verified; B3–B7 not implemented**.

## B0 — LangGraph interrupt support

The pinned `langgraph==0.4.8` installation exposes `interrupt(value)` and `Command(resume=...)`. A PostgreSQL integration test pauses a real graph with `AsyncPostgresSaver`, resumes the same thread, and checks the resumed value. No dependency upgrade was needed. The existing `pending_operations` table remains the thread-bound store to reuse for approval metadata and expiry.

## Remaining work

## B1 — policy gate

The core loads each tool mode from `config/policy.yaml`, resolves overlapping globs by specificity, and fails closed for an unregistered tool. Startup validates that every configured policy key matches at least one registered tool. Protected calls are refused in code before tool invocation with “Approval is not set up yet”; the approval flow is not enabled yet. The config includes a catch-all auto mode and explicit ask overrides for the protected names and classes.

The `browser_task` skill currently names a tool that is not registered by this checkout; its policy entry is omitted until a browser adapter exists, so startup validation can accurately reject every unmatched policy entry.

## B2 — approval interrupts

An `ask` batch is stored as a thread-bound `tool_approval` pending operation and interrupted before any tool runs. The approval question renders tokenized recipient/content values for the user. The next `/chat` message is classified into approve, reject, edit, or unclear; edits are tokenized, schema-checked, and applied to the exact arguments sent to the adapter. Unclear answers re-ask, unrelated commands reject the pending batch and start normally, expiry rejects it, and multiple asked tools share one question. `POST /approve` resumes the same persisted interrupt. Until a policy-configured graph is available, the fallback remains a safe refusal.

PostgreSQL integration coverage verifies approved and rejected email actions, visible self-recipient/content, token-safe pending payloads, edit application and invalid-edit refusal, unclear re-asking, expiry, bundling, unrelated-command handling, and `/approve`. All tool calls in these tests are local mocks.

B3 verifier, B4 injection taint, B5 caps, and B6–B7 launcher and end-to-end tests remain unimplemented.

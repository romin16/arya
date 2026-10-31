# Phase 6 — Policy, approvals, verifier, and taint

Status: **B0 and B1 verified; B2–B7 not implemented**.

## B0 — LangGraph interrupt support

The pinned `langgraph==0.4.8` installation exposes `interrupt(value)` and `Command(resume=...)`. A PostgreSQL integration test pauses a real graph with `AsyncPostgresSaver`, resumes the same thread, and checks the resumed value. No dependency upgrade was needed. The existing `pending_operations` table remains the thread-bound store to reuse for approval metadata and expiry.

## Remaining work

## B1 — policy gate

The core loads each tool mode from `config/policy.yaml`, resolves overlapping globs by specificity, and fails closed for an unregistered tool. Startup validates that every configured policy key matches at least one registered tool. Protected calls are refused in code before tool invocation with “Approval is not set up yet”; the approval flow is not enabled yet. The config includes a catch-all auto mode and explicit ask overrides for the protected names and classes.

The `browser_task` skill currently names a tool that is not registered by this checkout; its policy entry is omitted until a browser adapter exists, so startup validation can accurately reject every unmatched policy entry.

B2 approval flow, B3 verifier, B4 injection taint, B5 caps, and B6–B7 launcher and end-to-end tests remain unimplemented.

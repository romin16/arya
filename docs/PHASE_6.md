# Phase 6 — Policy, approvals, verifier, and taint

Status: **B0 verified; B1–B7 not implemented**.

## B0 — LangGraph interrupt support

The pinned `langgraph==0.4.8` installation exposes `interrupt(value)` and `Command(resume=...)`. A PostgreSQL integration test pauses a real graph with `AsyncPostgresSaver`, resumes the same thread, and checks the resumed value. No dependency upgrade was needed. The existing `pending_operations` table remains the thread-bound store to reuse for approval metadata and expiry.

## Remaining work

B1 policy enforcement, B2 approval flow, B3 verifier, B4 injection taint, B5 caps, and B6–B7 launcher and end-to-end tests remain unimplemented.

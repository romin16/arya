# ARYA v4 runbook (starter)

## Requirements

Windows 10/11, Python 3.11+, `uv` or pip, PostgreSQL with pgvector, Docker only when the official Langfuse deployment is configured, and credentials in a local `.env` file. Never commit `.env`.

## Setup

1. Copy `.env.example` to `.env` and fill local values. Generate a Fernet key locally and use a long random `PII_HMAC_SECRET`.
2. Create a Python 3.11 virtual environment and install `.[dev,voice,observability,device]` using the committed dependency manifest. Generate and commit a platform-specific lockfile after checking installed library APIs.
3. Create an empty database with pgvector available, set `DATABASE_URL`, then run `python -m db.apply_schema` twice to confirm idempotency.
4. Start the browser-use API on `127.0.0.1:8000` separately. The current `deploy/start_all.ps1` starts only the core, voice, and device process shells.
5. Run `deploy/start_all.ps1`. Core and voice use ports 5000 and 5001. Device is bound to `127.0.0.1:5002` and requires `Authorization: Bearer <DEVICE_TOKEN>`.
6. Open the unmodified `arya.html`. Text and voice integration are not accepted until providers, graph, and browser compatibility checks are implemented.

## Current limitations

This is an incomplete migration scaffold, not a deployable assistant. The runbook must be completed after the remaining phases, official Langfuse compose is sourced, and all acceptance checks pass.

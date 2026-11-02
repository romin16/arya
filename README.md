# ARYA

Local-first assistant for Windows. The verified runtime uses Python 3.12, `uv`, and PostgreSQL with pgvector. See [docs/RUNBOOK.md](docs/RUNBOOK.md) for setup and launch instructions, and [docs/PHASE_6.md](docs/PHASE_6.md) for the approval behavior.

## PostgreSQL integration tests

The graph integration tests run only when `ARYA_TEST_DATABASE_URL` points to a disposable PostgreSQL database. Create an isolated test database, apply the current schema, and then run pytest from PowerShell:

```powershell
createdb arya_test
$env:DATABASE_URL = "postgresql://arya:YOUR_LOCAL_PASSWORD@127.0.0.1:5432/arya_test"
uv run --no-sync python -m db.apply_schema
$env:ARYA_TEST_DATABASE_URL = $env:DATABASE_URL
uv run --no-sync pytest
Remove-Item Env:ARYA_TEST_DATABASE_URL,Env:DATABASE_URL
```

Use a local test database only; never point this variable at a production or personal data database. The test suite mocks network and GUI actions. The former `.phase6_test_runner.py` helper is not present in the repository; use the commands above or your own disposable-database wrapper.

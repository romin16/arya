# Existing local Langfuse instance

These scripts operate the user's existing Docker Compose checkout. They do not download, create, edit, or replace a Compose file. The directory is read from `LANGFUSE_COMPOSE_DIR`; the default is `C:\Users\abc\langfuse`.

```powershell
deploy\langfuse\status.ps1
deploy\langfuse\start.ps1
deploy\langfuse\stop.ps1
```

`start.ps1` first checks the configured Compose project. If its services are already running, it reports their status and does not start another copy. Before starting a stopped project it checks ports 3000 (web), 5432 (Postgres), 6379 (Redis), 8123 and 9000 (ClickHouse), 9090 (MinIO), and 9091 (MinIO console). If any are occupied while the configured stack is stopped, it reports the port and refuses to start. The configured checkout may use different ports; `status.ps1` reports listeners for the defaults above.

On first setup, use the official Langfuse repository's `docker-compose.yml` in the chosen checkout directory, then start it and open [http://localhost:3000](http://localhost:3000). Create a user, organization and project in the UI. In the project settings, create API keys and put them in the Arya project's `.env` as `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST=http://localhost:3000`. Keep secret keys in `.env`; never commit them. Docker Compose service data remains in the configured checkout's named volumes.

The pinned `langfuse==4.15.6` SDK with `langchain==0.3.30` records one PII-scrubbed trace for a `/chat` turn. Callback input and output strings are re-tokenized by Arya before they are passed to the SDK. Local trace ingestion depends on the configured Langfuse Compose stack's event storage being healthy.

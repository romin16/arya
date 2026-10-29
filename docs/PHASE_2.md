# Phase 2 — Device server

Status: implementation and mocked unit verification complete. The server runs in the interactive user session and exposes the typed tools at `http://127.0.0.1:5002/mcp`. `DEVICE_TOKEN` is required from `.env`; all HTTP routes, including MCP, health, and panic, require `Authorization: Bearer <DEVICE_TOKEN>`. Set optional `DEVICE_ACTION_TIMEOUT` to change the default 30-second per-action timeout.

The desktop, WhatsApp, and VS Code legacy agent files were copied byte-for-byte to `device/legacy_agents/`. All registered tools use `SerialDesktopQueue`, a single worker that preserves GUI action order. `/panic` invalidates the current action result and drops work already waiting in the queue. A blocking legacy OS/GUI call already in progress cannot be safely terminated; the worker finishes it before another action starts. `pyautogui.FAILSAFE` remains enabled. Spotify's `playing` value is best-effort and starts unknown.

The WhatsApp device surface supports sending messages and voice calls. Message reading/OCR is intentionally not exposed.

## Verification

- `uv run --extra device --group dev python -m pytest tests/unit -q`: **12 passed** (the device tests mock `pyautogui` and `win32gui`).
- `python -m py_compile device/server.py device/queue.py scripts/device_smoke.py tests/unit/test_device.py`: passed.
- `python scripts/device_smoke.py --help`: passed. The smoke client was not run against the server and no desktop action was invoked.

## Manual smoke test

Start the server in the logged-in desktop session with `uv run --extra device --group dev python -m device.server`. Then list tools and check health without invoking a desktop action:

```powershell
uv run --extra device --group dev python scripts/device_smoke.py
```

To call a tool manually, pass its name and JSON arguments. This example opens Notepad, so run it only when you want that desktop action:

```powershell
uv run --extra device --group dev python scripts/device_smoke.py --call open_app --args '{"app":"notepad"}'
```

Use `--panic` to exercise the protected `POST /panic` route.

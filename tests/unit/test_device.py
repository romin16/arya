import asyncio
import importlib
import inspect
import io
import json
import sys
import threading
import time
from types import ModuleType
from types import SimpleNamespace

import httpx
import pytest

from device.queue import SerialDesktopQueue


def load_device_server(monkeypatch):
    """Import the legacy GUI modules against inert test doubles only."""
    gui = ModuleType("pyautogui")
    gui.FAILSAFE = True
    gui_calls = []
    gui.press = lambda *args, **kwargs: gui_calls.append(("press", args))
    gui.hotkey = lambda *args, **kwargs: gui_calls.append(("hotkey", args))
    gui.write = lambda *args, **kwargs: gui_calls.append(("write", args))
    gui.click = lambda *args, **kwargs: gui_calls.append(("click", args))
    gui.size = lambda: (1000, 800)
    gui.screenshot = lambda **kwargs: None

    clipboard = ModuleType("pyperclip")
    clipboard.copy = lambda value: gui_calls.append(("clipboard", value))
    win32gui = ModuleType("win32gui")
    win32gui.EnumWindows = lambda callback, windows: callback(1, windows)
    win32gui.GetWindowText = lambda hwnd: "Visual Studio Code"
    win32gui.IsWindowVisible = lambda hwnd: True
    win32gui.IsIconic = lambda hwnd: False
    win32gui.ShowWindow = lambda *args: gui_calls.append(("show", args))
    win32gui.SetForegroundWindow = lambda *args: gui_calls.append(("foreground", args))
    win32con = ModuleType("win32con")
    win32con.SW_RESTORE = 9

    for name in (
        "device.server",
        "device.legacy_agents.desktop_agent_v2",
        "device.legacy_agents.whatsapp_agent",
        "device.legacy_agents.vscode_agent",
    ):
        sys.modules.pop(name, None)
    monkeypatch.setitem(sys.modules, "pyautogui", gui)
    monkeypatch.setitem(sys.modules, "pyperclip", clipboard)
    monkeypatch.setitem(sys.modules, "win32gui", win32gui)
    monkeypatch.setitem(sys.modules, "win32con", win32con)
    monkeypatch.setenv("DEVICE_TOKEN", "unit-test-token")
    server = importlib.import_module("device.server")
    return server, gui, gui_calls, win32gui


@pytest.mark.asyncio
async def test_concurrent_gui_tools_are_serial_and_use_mocked_pyautogui(monkeypatch):
    server, gui, calls, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)
    lock = threading.Lock()
    active = 0
    max_active = 0

    def mocked_type_text(text):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            calls.append(("start", text))
        gui.write(text)
        time.sleep(0.02)
        with lock:
            calls.append(("end", text))
            active -= 1
        return {"success": True}

    monkeypatch.setattr(server.desktop, "type_text", mocked_type_text)
    await asyncio.gather(server.type_text("mock one"), server.type_text("mock two"))

    assert max_active == 1
    starts_and_ends = [entry for entry in calls if entry[0] in {"start", "end"}]
    assert starts_and_ends in (
        [("start", "mock one"), ("end", "mock one"), ("start", "mock two"), ("end", "mock two")],
        [("start", "mock two"), ("end", "mock two"), ("start", "mock one"), ("end", "mock one")],
    )
    assert [(name, args[0]) for name, args in calls if name == "write"] == [
        ("write", "mock one"),
        ("write", "mock two"),
    ] or [(name, args[0]) for name, args in calls if name == "write"] == [
        ("write", "mock two"),
        ("write", "mock one"),
    ]


@pytest.mark.asyncio
async def test_spotify_tool_survives_cp1252_redirected_stdout(monkeypatch):
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
    redirected_stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252", errors="strict")
    redirected_stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", redirected_stdout)
    monkeypatch.setattr(sys, "stderr", redirected_stderr)
    server, _, _, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)

    def legacy_action(query):
        print("❌ legacy diagnostic", flush=True)
        return {"success": True, "query": query}

    monkeypatch.setattr(server.desktop, "spotify_search", legacy_action)
    result = await server.spotify_play("lofi hip hop")

    assert result["success"] is True
    assert redirected_stdout.encoding.lower().replace("-", "") == "utf8"
    assert redirected_stdout.errors == "replace"
    assert redirected_stderr.encoding.lower().replace("-", "") == "utf8"
    assert redirected_stderr.errors == "replace"
    assert "❌ legacy diagnostic" in stdout_bytes.getvalue().decode("utf-8")


@pytest.mark.asyncio
async def test_device_http_requires_bearer_and_panic_route_is_protected(monkeypatch):
    server, _, _, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)
    app = server.create_asgi_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://device") as client:
        unauthorized = await client.post("/panic")
        assert unauthorized.status_code == 401
        authorized = await client.post(
            "/panic", headers={"Authorization": "Bearer unit-test-token"}
        )
        assert authorized.status_code == 200
        assert authorized.json() == {"cancelled": True}


@pytest.mark.asyncio
async def test_panic_cancels_actions_waiting_in_queue():
    queue = SerialDesktopQueue(action_timeout=2)
    started = threading.Event()
    release = threading.Event()

    def active_action():
        started.set()
        release.wait(1)
        return "finished"

    first = asyncio.create_task(queue.run(active_action))
    await asyncio.to_thread(started.wait, 1)
    second = asyncio.create_task(queue.run(lambda: "should not run"))
    await asyncio.sleep(0)
    queue.panic()
    release.set()
    with pytest.raises(asyncio.CancelledError, match="cancelled by panic"):
        await first
    with pytest.raises(asyncio.CancelledError, match="cancelled by panic"):
        await second


def test_fastmcp_registers_typed_device_tools_and_mocked_win32_focus(monkeypatch):
    server, _, gui_calls, win32gui = load_device_server(monkeypatch)
    tools = server.mcp._tool_manager.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "spotify_play", "spotify_pause", "spotify_resume", "spotify_next", "spotify_previous",
        "open_app", "open_url", "youtube_search", "close_app", "set_volume", "type_text", "take_screenshot", "lock_screen",
        "open_downloads", "open_documents", "whatsapp_send",
        "whatsapp_voice_call", "vscode_open", "vscode_open_file", "vscode_search",
        "vscode_run_command", "vscode_format",
    }
    schemas = {tool.name: tool.parameters for tool in tools}
    assert schemas["whatsapp_send"]["properties"]["contact"]["type"] == "string"
    assert schemas["set_volume"]["properties"]["level"]["type"] == "integer"

    # All win32gui calls are inert mocks; this only exercises focus discovery.
    assert server.vscode.focus_vscode() is True
    assert ("foreground", (1,)) in gui_calls
    assert win32gui.GetWindowText(1) == "Visual Studio Code"


@pytest.mark.asyncio
async def test_every_device_tool_returns_plain_json_dict_through_mocked_layer(monkeypatch):
    server, _, _, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)
    monkeypatch.setattr(server, "_app_is_running", lambda _app: True)
    monkeypatch.setattr(server.webbrowser, "open", lambda *_args, **_kwargs: True)
    def success(*args):
        return {"success": True, "args": list(args)}
    server.desktop = SimpleNamespace(
        spotify_search=success,
        spotify_play_pause=success,
        spotify_next=success,
        spotify_previous=success,
        open_app=success,
        open_url=success,
        youtube_search=success,
        close_app=success,
        set_volume=success,
        type_text=success,
        take_screenshot=success,
        lock_screen=success,
        open_downloads=success,
        open_documents=success,
    )
    server.whatsapp = SimpleNamespace(send_message=success, click_voice_call=success)
    server.vscode = SimpleNamespace(
        open_vscode=success,
        open_file=success,
        search_in_files=success,
        run_terminal_command=success,
        format_document=success,
    )
    server.spotify_playing = None
    arguments = {
        "spotify_play": {"query": "test track"},
        "spotify_pause": {},
        "spotify_resume": {},
        "spotify_next": {},
        "spotify_previous": {},
        "open_app": {"app": "notepad"},
        "open_url": {"url": "https://example.org/path"},
        "youtube_search": {"query": "lofi hip hop"},
        "close_app": {"app": "notepad"},
        "set_volume": {"level": 10},
        "type_text": {"text": "mocked"},
        "take_screenshot": {},
        "lock_screen": {},
        "open_downloads": {},
        "open_documents": {},
        "whatsapp_send": {"contact": "Test", "message": "mocked"},
        "whatsapp_voice_call": {},
        "vscode_open": {"folder": "C:/mock"},
        "vscode_open_file": {"file": "mock.py"},
        "vscode_search": {"term": "mock"},
        "vscode_run_command": {"command": "echo mocked"},
        "vscode_format": {},
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    assert tools.keys() == arguments.keys()

    for name, tool in tools.items():
        result = await tool.run(arguments[name])
        assert not inspect.isawaitable(result), name
        assert isinstance(result, dict), name
        json.dumps(result)


@pytest.mark.asyncio
async def test_open_app_rejects_unknown_names_without_launching(monkeypatch):
    server, _, _, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)
    monkeypatch.setattr(server.desktop, "open_app", lambda _app: pytest.fail("unknown app must not launch"))

    result = await server.open_app("YouTube")

    assert result["success"] is False
    assert result["verified"] is False
    assert result["attempted"] is False
    assert result["message"].startswith("unknown app: YouTube, I can open:")


@pytest.mark.asyncio
async def test_open_app_reports_verified_only_after_mocked_process_is_found(monkeypatch):
    server, _, _, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)
    launched = []
    monkeypatch.setattr(server.desktop, "open_app", lambda app: launched.append(app) or {"success": True})
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='"notepad.exe","123"\n'),
    )

    result = await server.open_app("Notepad")

    assert launched == ["notepad"]
    assert result["success"] is True
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_open_app_can_verify_a_matching_mocked_window(monkeypatch):
    server, _, _, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)
    monkeypatch.setattr(server.desktop, "open_app", lambda _app: {"success": True})
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""),
    )

    result = await server.open_app("Visual Studio Code")

    assert result["success"] is True
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_open_app_does_not_claim_success_without_process_or_window(monkeypatch):
    server, _, _, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)
    monkeypatch.setattr(server, "APP_VERIFY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(server.desktop, "open_app", lambda _app: {"success": True, "message": "Opened notepad"})
    monkeypatch.setattr(
        server.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=""),
    )
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)

    result = await server.open_app("Notepad")

    assert result["success"] is False
    assert result["verified"] is False
    assert result["attempted"] is True
    assert result["message"] == "I tried, but I couldn't confirm it opened."


@pytest.mark.asyncio
async def test_open_url_validates_and_queues_browser_calls(monkeypatch):
    server, _, _, _ = load_device_server(monkeypatch)
    server.queue = SerialDesktopQueue(action_timeout=2)
    opened = []
    monkeypatch.setattr(server.webbrowser, "open", lambda url, **_kwargs: opened.append(url) or True)

    assert (await server.open_url("https://example.org/path"))["success"] is True
    assert (await server.youtube_search("lofi hip hop"))["success"] is True
    assert opened == [
        "https://example.org/path",
        "https://www.youtube.com/results?search_query=lofi+hip+hop",
    ]
    for rejected in (
        "file:///C:/secret.txt", "javascript:alert(1)", r"C:\\secret.txt",
        "http://localhost", "http://192.168.1.1",
    ):
        with pytest.raises(ValueError, match="external http or https"):
            await server.open_url(rejected)


def test_action_submitted_after_panic_runs_normally():
    queue = SerialDesktopQueue(action_timeout=2)
    queue.panic()
    assert asyncio.run(queue.run(lambda: "new action")) == "new action"


@pytest.mark.asyncio
async def test_per_action_timeout_returns_error_and_worker_finishes_in_order():
    queue = SerialDesktopQueue(action_timeout=1)
    with pytest.raises(TimeoutError, match="device action timed out"):
        await queue.run(time.sleep, 0.05, timeout=0.005)
    # The timed-out OS call cannot be killed; the single worker completes it
    # before starting another call, so the desktop remains serialized.
    assert await queue.run(lambda: "after timeout") == "after timeout"

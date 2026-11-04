"""Authenticated FastMCP server for local interactive-desktop actions."""
from __future__ import annotations

import hmac
import ipaddress
import os
import csv
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from device.queue import SerialDesktopQueue
from device.legacy_agents.desktop_agent_v2 import DesktopAgent
from device.legacy_agents.vscode_agent import VSCodeAgent
from device.legacy_agents.whatsapp_agent import WhatsAppAgent


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


_configure_utf8_stdio()


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")


_load_dotenv()
try:
    import pyautogui
except ImportError as exc:
    raise RuntimeError("Install ARYA's device extra before starting arya-device") from exc

pyautogui.FAILSAFE = True
queue = SerialDesktopQueue(action_timeout=float(os.getenv("DEVICE_ACTION_TIMEOUT", "30")))
desktop = DesktopAgent()
whatsapp = WhatsAppAgent()
vscode = VSCodeAgent()
spotify_playing: bool | None = None

KNOWN_APPS = {
    "chrome", "firefox", "edge", "spotify", "vscode", "whatsapp", "calculator",
    "notepad", "explorer", "discord", "telegram", "notes", "finder", "files",
}
APP_PATHS = dict(getattr(getattr(desktop, "app_controller", None), "app_paths", {}) or {})
APP_VERIFY_TIMEOUT_SECONDS = float(os.getenv("DEVICE_APP_VERIFY_SECONDS", "3"))
APP_PROCESS_NAMES = {
    "chrome": {"chrome.exe"}, "firefox": {"firefox.exe"}, "edge": {"msedge.exe"},
    "spotify": {"spotify.exe"}, "vscode": {"code.exe"}, "whatsapp": {"whatsapp.exe"},
    "calculator": {"calculator.exe", "calculatorapp.exe"}, "notepad": {"notepad.exe"},
    "explorer": {"explorer.exe"}, "discord": {"discord.exe"}, "telegram": {"telegram.exe"},
}
WINDOW_TITLES = {
    "vscode": ("visual studio code", "code"),
    "edge": ("microsoft edge", "edge"),
    "chrome": ("google chrome", "chrome"),
}


def _normalise_app_name(app: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", app.casefold())
    return {"visualstudiocode": "vscode", "vs code": "vscode", "microsoftedge": "edge"}.get(
        compact, compact,
    )


def _app_process_names(app_key: str) -> set[str]:
    names = set(APP_PROCESS_NAMES.get(app_key, set()))
    configured = next(
        (str(value) for key, value in APP_PATHS.items() if _normalise_app_name(key) == app_key),
        "",
    )
    match = re.search(r"([^\\/\s\"']+\.exe)\b", configured, re.IGNORECASE)
    if match:
        names.add(match.group(1).casefold())
    return names


def _app_is_running(app_key: str) -> bool:
    expected = _app_process_names(app_key)
    try:
        process_list = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
            timeout=1, check=False,
        )
        if process_list.returncode == 0:
            for row in csv.reader(process_list.stdout.splitlines()):
                if row and row[0].casefold() in expected:
                    return True
    except (OSError, subprocess.SubprocessError):
        pass

    aliases = WINDOW_TITLES.get(app_key, (app_key,))
    try:
        import win32gui

        found = False

        def inspect_window(hwnd, _extra):
            nonlocal found
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).casefold()
                found = found or any(alias in title for alias in aliases)

        win32gui.EnumWindows(inspect_window, None)
        return found
    except (ImportError, AttributeError, OSError):
        return False


def _launch_and_verify_app(app: str) -> dict[str, Any]:
    app_key = _normalise_app_name(app)
    configured_names = {_normalise_app_name(name): name.casefold() for name in APP_PATHS}
    known = KNOWN_APPS | set(configured_names)
    if app_key not in known:
        choices = ", ".join(sorted(known))
        return {
            "success": False,
            "verified": False,
            "attempted": False,
            "message": f"unknown app: {app}, I can open: {choices}",
        }

    launcher_name = configured_names.get(app_key, app_key)
    result = desktop.open_app(launcher_name)
    if not isinstance(result, dict):
        result = {"success": False, "message": "The app launcher returned an invalid result."}
    if result.get("success") is False:
        return {**result, "success": False, "verified": False, "attempted": True}

    deadline = time.monotonic() + APP_VERIFY_TIMEOUT_SECONDS
    while True:
        if _app_is_running(app_key):
            return {**result, "success": True, "verified": True, "attempted": True}
        if time.monotonic() >= deadline:
            break
        time.sleep(0.2)
    return {
        **result,
        "success": False,
        "verified": False,
        "attempted": True,
        "message": "I tried, but I couldn't confirm it opened.",
    }


def _validate_http_url(url: str) -> str:
    value = url.strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError("url must be an external http or https URL") from exc
    try:
        address = ipaddress.ip_address(parsed.hostname) if parsed.hostname else None
    except ValueError:
        address = None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname.casefold() == "localhost"
        or parsed.hostname.casefold().endswith((".local", ".internal"))
        or (address is not None and not address.is_global)
        or "\\" in value
    ):
        raise ValueError("url must be an external http or https URL")
    return value


def _dispatch_browser_url(url: str) -> dict[str, Any]:
    try:
        opened = bool(webbrowser.open(url, new=2))
    except Exception as exc:
        return {"success": False, "verified": False, "message": f"Browser did not open the URL: {exc}"}
    return {
        "success": opened,
        "verified": opened,
        "message": "Browser accepted the URL." if opened else "The default browser did not confirm it opened.",
    }

mcp = FastMCP(
    "arya-device",
    host=os.getenv("ARYA_DEVICE_HOST", "127.0.0.1"),
    port=int(os.getenv("ARYA_DEVICE_PORT", "5002")),
    streamable_http_path="/mcp",
)


@mcp.tool()
async def spotify_play(query: str) -> dict[str, Any]:
    """Search Spotify and play the best matching result."""
    global spotify_playing
    result = await queue.run(desktop.spotify_search, query)
    if result.get("success"):
        spotify_playing = True
    return {**result, "playing": spotify_playing}


@mcp.tool()
async def spotify_pause() -> dict[str, Any]:
    """Pause Spotify if it is not already known to be paused."""
    global spotify_playing
    if spotify_playing is False:
        return {"success": True, "message": "Spotify is already paused", "playing": False}
    result = await queue.run(desktop.spotify_play_pause)
    if result.get("success"):
        spotify_playing = False
    return {**result, "playing": spotify_playing}


@mcp.tool()
async def spotify_resume() -> dict[str, Any]:
    """Resume Spotify if it is not already known to be playing."""
    global spotify_playing
    if spotify_playing is True:
        return {"success": True, "message": "Spotify is already playing", "playing": True}
    result = await queue.run(desktop.spotify_play_pause)
    if result.get("success"):
        spotify_playing = True
    return {**result, "playing": spotify_playing}


@mcp.tool()
async def spotify_next() -> dict[str, Any]:
    """Skip to the next Spotify track."""
    return await queue.run(desktop.spotify_next)


@mcp.tool()
async def spotify_previous() -> dict[str, Any]:
    """Go to the previous Spotify track."""
    return await queue.run(desktop.spotify_previous)


@mcp.tool()
async def open_app(app: str) -> dict[str, Any]:
    """Open a known desktop application. Websites and URLs are not applications."""
    return await queue.run(_launch_and_verify_app, app)


@mcp.tool()
async def open_url(url: str) -> dict[str, Any]:
    """Open an external HTTP or HTTPS URL in the default browser."""
    safe_url = _validate_http_url(url)
    return await queue.run(_dispatch_browser_url, safe_url)


@mcp.tool()
async def youtube_search(query: str) -> dict[str, Any]:
    """Open YouTube search results in the default browser."""
    if not query.strip():
        raise ValueError("query must not be empty")
    url = "https://www.youtube.com/results?" + urlencode({"search_query": query.strip()})
    return await queue.run(_dispatch_browser_url, url)


@mcp.tool()
async def close_app(app: str) -> dict[str, Any]:
    """Close a desktop application by name."""
    return await queue.run(desktop.close_app, app)


@mcp.tool()
async def set_volume(level: int) -> dict[str, Any]:
    """Set system volume from 0 to 100."""
    if not 0 <= level <= 100:
        raise ValueError("level must be between 0 and 100")
    return await queue.run(desktop.set_volume, level)


@mcp.tool()
async def type_text(text: str) -> dict[str, Any]:
    """Type text into the currently focused application."""
    return await queue.run(desktop.type_text, text)


@mcp.tool()
async def take_screenshot() -> dict[str, Any]:
    """Capture the current desktop screenshot."""
    return await queue.run(desktop.take_screenshot)


@mcp.tool()
async def lock_screen() -> dict[str, Any]:
    """Lock the desktop session."""
    return await queue.run(desktop.lock_screen)


@mcp.tool()
async def open_downloads() -> dict[str, Any]:
    """Open the user's Downloads folder."""
    return await queue.run(desktop.open_downloads)


@mcp.tool()
async def open_documents() -> dict[str, Any]:
    """Open the user's Documents folder."""
    return await queue.run(desktop.open_documents)


@mcp.tool()
async def whatsapp_send(contact: str, message: str) -> dict[str, Any]:
    """Send a WhatsApp message to a named contact."""
    return await queue.run(whatsapp.send_message, contact, message)


@mcp.tool()
async def whatsapp_voice_call() -> dict[str, Any]:
    """Start a WhatsApp voice call in the current chat."""
    return await queue.run(whatsapp.click_voice_call)


@mcp.tool()
async def vscode_open(folder: str | None = None) -> dict[str, Any]:
    """Open VS Code, optionally in a folder."""
    return await queue.run(vscode.open_vscode, folder)


@mcp.tool()
async def vscode_open_file(file: str) -> dict[str, Any]:
    """Open a file in VS Code."""
    return await queue.run(vscode.open_file, file)


@mcp.tool()
async def vscode_search(term: str) -> dict[str, Any]:
    """Search for text across the VS Code workspace."""
    return await queue.run(vscode.search_in_files, term)


@mcp.tool()
async def vscode_run_command(command: str) -> dict[str, Any]:
    """Run a command in the VS Code integrated terminal."""
    return await queue.run(vscode.run_terminal_command, command)


@mcp.tool()
async def vscode_format() -> dict[str, Any]:
    """Format the current VS Code document."""
    return await queue.run(vscode.format_document)


def _authorized(request: Request) -> bool:
    expected = os.getenv("DEVICE_TOKEN", "")
    authorization = request.headers.get("authorization", "")
    supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    return bool(expected) and hmac.compare_digest(supplied, expected)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    if not _authorized(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return JSONResponse({"status": "healthy", "spotify_playing": spotify_playing})


@mcp.custom_route("/panic", methods=["POST"])
async def panic(request: Request) -> Response:
    if not _authorized(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    queue.panic()
    return JSONResponse({"cancelled": True})


class BearerTokenMiddleware:
    """Require DEVICE_TOKEN for every HTTP request to the MCP service."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        expected = os.getenv("DEVICE_TOKEN", "")
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not expected or not hmac.compare_digest(supplied, expected):
            await JSONResponse({"detail": "Unauthorized"}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_asgi_app() -> ASGIApp:
    return BearerTokenMiddleware(mcp.streamable_http_app())


app = create_asgi_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("ARYA_DEVICE_HOST", "127.0.0.1"),
        port=int(os.getenv("ARYA_DEVICE_PORT", "5002")),
    )


if __name__ == "__main__":
    main()

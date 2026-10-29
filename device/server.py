"""Authenticated FastMCP server for local interactive-desktop actions."""
from __future__ import annotations

import hmac
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from device.queue import SerialDesktopQueue
from device.legacy_agents.desktop_agent_v2 import DesktopAgent
from device.legacy_agents.vscode_agent import VSCodeAgent
from device.legacy_agents.whatsapp_agent import WhatsAppAgent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


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

mcp = FastMCP("arya-device", host="127.0.0.1", port=5002, streamable_http_path="/mcp")


async def _read_whatsapp(contact: str, n: int) -> dict[str, Any]:
    opened = whatsapp.search_contact(contact)
    if not opened.get("success"):
        return opened
    return whatsapp.read_last_messages(n)


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
    """Open a desktop application by name."""
    return await queue.run(desktop.open_app, app)


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
async def whatsapp_read(contact: str, n: int = 5) -> dict[str, Any]:
    """Open a WhatsApp contact and read its latest messages using legacy OCR."""
    if not 1 <= n <= 50:
        raise ValueError("n must be between 1 and 50")
    return await queue.run(_read_whatsapp, contact, n)


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

    uvicorn.run(app, host="127.0.0.1", port=5002)


if __name__ == "__main__":
    main()

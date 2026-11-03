"""Add an environment-driven loopback host to the pinned Google MCP server."""
from __future__ import annotations

import sys
from pathlib import Path


CONFIG_OLD = 'PORT = int(os.environ.get("PORT", "8321"))'
CONFIG_NEW = CONFIG_OLD + '\nMCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")'
IMPORT_OLD = "from google_accounts_mcp.config import MCP_BEARER_TOKEN, PORT"
IMPORT_NEW = "from google_accounts_mcp.config import MCP_BEARER_TOKEN, MCP_HOST, PORT"
SERVE_OLD = "serve(mcp, port=PORT, bearer_token=MCP_BEARER_TOKEN)"
SERVE_NEW = "serve(mcp, port=PORT, bearer_token=MCP_BEARER_TOKEN, host=MCP_HOST)"


def _ensure_patch(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) == 1:
        return source.replace(old, new, 1)
    raise RuntimeError(f"Pinned Google MCP {label} no longer matches the expected host patch.")


def patch_sources(config_source: str, server_source: str) -> tuple[str, str]:
    config_source = _ensure_patch(config_source, CONFIG_OLD, CONFIG_NEW, "config")
    server_source = _ensure_patch(server_source, IMPORT_OLD, IMPORT_NEW, "config import")
    server_source = _ensure_patch(server_source, SERVE_OLD, SERVE_NEW, "serve call")
    return config_source, server_source


def patch_files(config_path: Path, server_path: Path) -> None:
    config_source = config_path.read_text(encoding="utf-8")
    server_source = server_path.read_text(encoding="utf-8")
    config_source, server_source = patch_sources(config_source, server_source)
    config_path.write_text(config_source, encoding="utf-8", newline="")
    server_path.write_text(server_source, encoding="utf-8", newline="")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: patch_google_mcp_host.py <config.py> <server.py>")
    try:
        patch_files(Path(sys.argv[1]), Path(sys.argv[2]))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

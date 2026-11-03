from pathlib import Path

from scripts.patch_google_mcp_host import (
    CONFIG_OLD,
    IMPORT_OLD,
    SERVE_OLD,
    patch_sources,
)


ROOT = Path(__file__).resolve().parents[2]


def test_google_server_uses_launcher_host_option_and_patch_is_idempotent():
    config, server = patch_sources(
        CONFIG_OLD + "\n",
        IMPORT_OLD + "\n\ndef main():\n    " + SERVE_OLD + "\n",
    )
    assert 'MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")' in config
    assert "host=MCP_HOST" in server
    assert 'host="0.0.0.0"' not in server
    assert patch_sources(config, server) == (config, server)


def test_launcher_sets_the_google_server_host_explicitly():
    launcher = (ROOT / "deploy" / "start_all.ps1").read_text(encoding="utf-8")
    setup = (ROOT / "scripts" / "setup_google_mcp.ps1").read_text(encoding="utf-8")
    assert "$env:MCP_HOST = '127.0.0.1'" in launcher
    assert "patch_google_mcp_host.py" in setup
    assert "host=MCP_HOST" in launcher or "host-option patch" in launcher

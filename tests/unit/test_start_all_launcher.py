from pathlib import Path


def test_launcher_unbuffers_services_and_routes_both_log_streams():
    launcher = Path("deploy/start_all.ps1").read_text(encoding="utf-8")

    assert "$env:PYTHONUNBUFFERED = '1'" in launcher
    assert "-RedirectStandardOutput $ServiceLogPath" in launcher
    assert "-RedirectStandardError $ErrorLogPath" in launcher


def test_launcher_reports_logs_for_early_exit_and_health_timeout():
    launcher = Path("deploy/start_all.ps1").read_text(encoding="utf-8")

    assert "$Process.HasExited" in launcher
    assert "Show-ServiceOutput $Name" in launcher
    assert "Show-ServiceOutput $ServiceName" in launcher
    assert "did not become healthy within 75 seconds" in launcher
    assert "Last 40 lines" in launcher


def test_launcher_supports_running_without_core():
    launcher = Path("deploy/start_all.ps1").read_text(encoding="utf-8")

    assert "[switch]$NoCore" in launcher
    assert "if (-not $NoCore)" in launcher
    assert "Core was skipped by -NoCore" in launcher

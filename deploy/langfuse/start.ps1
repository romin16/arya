$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$context = Get-LangfuseComposeContext $repoRoot
$composeArgs = $context.Arguments

Push-Location $context.Directory
try {
    $running = @(docker compose @composeArgs ps --status running --services 2>$null)
    if ($LASTEXITCODE -eq 0 -and $running.Count -gt 0) {
        Write-Output 'Langfuse Compose services are already running; no duplicate was started.'
        docker compose @composeArgs ps
        exit 0
    }
    foreach ($port in @(3000, 5432, 6379, 8123, 9000, 9090, 9091)) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($listener) {
            throw "Port $port is already in use (PID $($listener.OwningProcess)); refusing to start Langfuse. Check the configured Compose project with status.ps1."
        }
    }
    docker compose @composeArgs up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed with exit code $LASTEXITCODE" }
    docker compose @composeArgs ps
} finally {
    Pop-Location
}

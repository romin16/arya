$ErrorActionPreference = "Stop"
$composeDir = if ($env:LANGFUSE_COMPOSE_DIR) { $env:LANGFUSE_COMPOSE_DIR } else { "C:\Users\abc\langfuse" }
if (-not (Test-Path -LiteralPath $composeDir -PathType Container)) {
    throw "Langfuse Compose directory does not exist: $composeDir"
}
$composeFile = @("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml") |
    ForEach-Object { Join-Path $composeDir $_ } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not $composeFile) { throw "No Docker Compose file found in the configured Langfuse directory." }
Push-Location $composeDir
try {
    $running = @(docker compose -f $composeFile ps --status running --services 2>$null)
    if ($LASTEXITCODE -eq 0 -and $running.Count -gt 0) {
        Write-Output "Langfuse Compose services are already running; no duplicate was started."
        docker compose -f $composeFile ps
        exit 0
    }
    foreach ($port in @(3000, 5432, 6379, 8123, 9000, 9090, 9091)) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($listener) {
            throw "Port $port is already in use (PID $($listener.OwningProcess)); refusing to start Langfuse. Check the configured Compose project with status.ps1."
        }
    }
    docker compose -f $composeFile up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed with exit code $LASTEXITCODE" }
    docker compose -f $composeFile ps
} finally {
    Pop-Location
}

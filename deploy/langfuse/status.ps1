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
    docker compose -f $composeFile ps
    if ($LASTEXITCODE -ne 0) { throw "docker compose ps failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
foreach ($port in @(3000, 5432, 6379, 8123, 9000, 9090, 9091)) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        Write-Output "Port $port: listening (PID $($listener.OwningProcess))"
    } else {
        Write-Output "Port $port: free"
    }
}

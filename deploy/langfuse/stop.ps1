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
    docker compose -f $composeFile down
    if ($LASTEXITCODE -ne 0) { throw "docker compose down failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

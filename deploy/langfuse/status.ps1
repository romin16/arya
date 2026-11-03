$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$context = Get-LangfuseComposeContext $repoRoot
$composeArgs = $context.Arguments

Push-Location $context.Directory
try {
    docker compose @composeArgs ps
    if ($LASTEXITCODE -ne 0) { throw "docker compose ps failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
foreach ($port in @(3000, 5432, 6379, 8123, 9000, 9090, 9091)) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        Write-Output "Port ${port}: listening (PID $($listener.OwningProcess))"
    } else {
        Write-Output "Port ${port}: free"
    }
}

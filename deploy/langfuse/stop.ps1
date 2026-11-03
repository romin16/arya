$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$context = Get-LangfuseComposeContext $repoRoot
$composeArgs = $context.Arguments

Push-Location $context.Directory
try {
    docker compose @composeArgs down
    if ($LASTEXITCODE -ne 0) { throw "docker compose down failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

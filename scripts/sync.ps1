$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Uv = (Get-Command uv -ErrorAction Stop).Source
Push-Location $Root
try {
  & $Uv sync --locked --extra voice --extra device --extra observability
  if ($LASTEXITCODE -ne 0) {
    throw "uv sync failed with exit code $LASTEXITCODE."
  }
} finally {
  Pop-Location
}

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
  throw 'Project Python environment is missing. Run scripts/sync.ps1 first.'
}
Set-Location -LiteralPath $Root
& $Python -m http.server 8080 --bind 127.0.0.1 --directory frontend

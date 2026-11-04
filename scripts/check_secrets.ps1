$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ProjectPython = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $ProjectPython) {
  $Python = $ProjectPython
} else {
  $Python = (Get-Command python -ErrorAction Stop).Source
}
Set-Location -LiteralPath $Root
& $Python (Join-Path $PSScriptRoot 'check_secrets.py')
exit $LASTEXITCODE

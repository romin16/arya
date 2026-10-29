$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw 'Create .venv with Python 3.11+ and install the project before launch.' }
if (-not $env:DATABASE_URL) { Write-Warning 'DATABASE_URL is empty; core health will be degraded.' }
$Processes = @()
try {
  $Processes += Start-Process $Python -ArgumentList @('-m','uvicorn','device.server:app','--host','127.0.0.1','--port','5002') -WorkingDirectory $Root -PassThru -WindowStyle Hidden
  $Processes += Start-Process $Python -ArgumentList @('-m','uvicorn','voice.app:app','--host','0.0.0.0','--port','5001') -WorkingDirectory $Root -PassThru -WindowStyle Hidden
  $Processes += Start-Process $Python -ArgumentList @('-m','uvicorn','core.app:app','--host','0.0.0.0','--port','5000') -WorkingDirectory $Root -PassThru -WindowStyle Hidden
  Write-Host 'Started ARYA processes. Verify /health at ports 5000, 5001, and authenticated device port 5002.'
  Write-Host 'This starter launcher does not start browser-use or Langfuse; configure their official deployments separately.'
  Wait-Process -Id $Processes.Id
} finally {
  foreach ($Process in $Processes) { if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force } }
}

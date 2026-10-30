$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$EnvFile = Join-Path $Root '.env'
if (-not (Test-Path $Python)) { throw 'Create .venv with Python 3.11+ and install the project before launch.' }
if (-not (Test-Path $EnvFile)) { throw "Project .env not found at $EnvFile. Copy .env.example and configure it first." }

# Children load this same file themselves. Import only what the launcher needs
# for authenticated health checks and configurable ports.
foreach ($Line in Get-Content $EnvFile) {
  if ($Line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
    $Name = $Matches[1]
    $Value = $Matches[2]
    if ($Value.Length -ge 2 -and (($Value.StartsWith('"') -and $Value.EndsWith('"')) -or ($Value.StartsWith("'") -and $Value.EndsWith("'")))) {
      $Value = $Value.Substring(1, $Value.Length - 2)
    }
    if (-not (Test-Path "Env:$Name") -or [string]::IsNullOrEmpty((Get-Item "Env:$Name").Value)) {
      Set-Item "Env:$Name" $Value
    }
  }
}

$DevicePort = if ($env:ARYA_DEVICE_PORT) { $env:ARYA_DEVICE_PORT } else { '5002' }
$VoicePort = if ($env:ARYA_VOICE_PORT) { $env:ARYA_VOICE_PORT } else { '5001' }
$CorePort = if ($env:ARYA_CORE_PORT) { $env:ARYA_CORE_PORT } else { '5000' }
if (-not $env:DEVICE_TOKEN) { throw 'DEVICE_TOKEN is required in .env for the authenticated device health check.' }
$Processes = @()

function Start-AryaService([string]$Name, [string[]]$Arguments, [string]$HealthUrl, [switch]$Authenticated) {
  $Process = Start-Process $Python -ArgumentList $Arguments -WorkingDirectory $Root -PassThru -WindowStyle Hidden
  $script:Processes += $Process
  $Headers = @{}
  if ($Authenticated) { $Headers.Authorization = "Bearer $env:DEVICE_TOKEN" }
  $Deadline = (Get-Date).AddSeconds(75)
  while ((Get-Date) -lt $Deadline) {
    if ($Process.HasExited) { throw "$Name exited before becoming healthy (exit code $($Process.ExitCode))." }
    try {
      $Health = Invoke-RestMethod -Uri $HealthUrl -Headers $Headers -TimeoutSec 3
      if ($Health.status -eq 'healthy') {
        Write-Host "$Name healthy at $HealthUrl"
        return
      }
    } catch {
      # Startup may take a few seconds; retry until the deadline.
    }
    Start-Sleep -Seconds 1
  }
  throw "$Name did not become healthy within 75 seconds at $HealthUrl."
}

try {
  Start-AryaService 'arya-device' @('-m', 'device.server') "http://127.0.0.1:$DevicePort/health" -Authenticated
  Start-AryaService 'arya-voice' @('-m', 'voice.app') "http://127.0.0.1:$VoicePort/health"
  Start-AryaService 'arya-core' @('-m', 'core') "http://127.0.0.1:$CorePort/health"
  Write-Host 'ARYA device, voice, and core are healthy. Press Ctrl+C here to stop all three.'
  Wait-Process -Id $Processes.Id
} catch {
  Write-Error $_
  throw
} finally {
  foreach ($Process in $Processes) {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force }
  }
}

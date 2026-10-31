param(
  [switch]$NoCore
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONUNBUFFERED = '1'
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
$GoogleMcpPort = '8321'
if (-not $env:DEVICE_TOKEN) { throw 'DEVICE_TOKEN is required in .env for the authenticated device health check.' }
if (-not $env:GOOGLE_MCP_TOKEN) { throw 'GOOGLE_MCP_TOKEN is required in .env for the authenticated Google MCP server.' }
$Processes = @()
$LogDirectory = Join-Path $Root 'logs'
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$script:ServiceNames = @{}
$script:ReportedExits = @{}

function Show-ServiceOutput([string]$Name) {
  $ServiceLogPath = Join-Path $LogDirectory "$Name.log"
  $ErrorLogPath = Join-Path $LogDirectory "$Name.stderr.log"
  foreach ($Path in @($ServiceLogPath, $ErrorLogPath)) {
    if (Test-Path $Path) {
      Write-Host "--- Last 40 lines from $Path ---"
      Get-Content -LiteralPath $Path -Tail 40
    }
  }
}

function Start-AryaService([string]$Name, [string[]]$Arguments, [string]$HealthUrl, [string]$Executable = $Python, [string]$WorkingDirectory = $Root, [string]$BearerToken = '', [switch]$Authenticated, [switch]$McpProbe) {
  $ServiceLogPath = Join-Path $LogDirectory "$Name.log"
  $ErrorLogPath = Join-Path $LogDirectory "$Name.stderr.log"
  $Process = Start-Process $Executable -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden -RedirectStandardOutput $ServiceLogPath -RedirectStandardError $ErrorLogPath
  $script:Processes += $Process
  $script:ServiceNames[[string]$Process.Id] = $Name
  $Headers = @{}
  if ($BearerToken) { $Headers.Authorization = "Bearer $BearerToken" }
  elseif ($Authenticated) { $Headers.Authorization = "Bearer $env:DEVICE_TOKEN" }
  $Deadline = (Get-Date).AddSeconds(75)
  while ((Get-Date) -lt $Deadline) {
    if ($Process.HasExited) {
      Show-ServiceOutput $Name
      throw "$Name exited before becoming healthy (exit code $($Process.ExitCode))."
    }
    try {
      if ($McpProbe) {
        $Headers.Accept = 'application/json, text/event-stream'
        $Initialize = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"arya-health-probe","version":"1"}}}'
        $Probe = Invoke-WebRequest -Uri $HealthUrl -Method Post -Headers $Headers -ContentType 'application/json' -Body $Initialize -TimeoutSec 3 -UseBasicParsing
        if ($Probe.StatusCode -eq 200) {
          Write-Host "$Name healthy at $HealthUrl"
          return
        }
      } else {
        $Health = Invoke-RestMethod -Uri $HealthUrl -Headers $Headers -TimeoutSec 3
        if ($Health.status -eq 'healthy') {
          Write-Host "$Name healthy at $HealthUrl"
          return
        }
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
  $GoogleMcpRoot = Join-Path $env:LOCALAPPDATA 'Arya\google-accounts-mcp'
  if (-not (Test-Path (Join-Path $GoogleMcpRoot '.venv\Scripts\python.exe'))) {
    throw 'The pinned Google MCP server is not set up. Run scripts/setup_google_mcp.ps1 -Account your-address@example.com first.'
  }
  $GoogleServerPath = Join-Path $GoogleMcpRoot 'src\google_accounts_mcp\server.py'
  if (-not (Select-String -Path $GoogleServerPath -Pattern 'host="127\.0\.0\.1"' -Quiet)) {
    throw 'The pinned Google MCP server is not bound to loopback. Run scripts/setup_google_mcp.ps1 to apply the local bind patch.'
  }
  $env:PORT = $GoogleMcpPort
  $env:MCP_BEARER_TOKEN = $env:GOOGLE_MCP_TOKEN
  $env:GOOGLE_CLIENT_ID = $env:GOOGLE_OAUTH_CLIENT_ID
  $env:GOOGLE_CLIENT_SECRET = $env:GOOGLE_OAUTH_CLIENT_SECRET
  $env:DEFAULT_ACCOUNT = $env:GOOGLE_ACCOUNT
  $GoogleDataRoot = Join-Path $env:LOCALAPPDATA 'Arya\google-mcp-data'
  $env:TOKEN_DB_PATH = Join-Path $GoogleDataRoot 'tokens.db'
  $env:ATTACHMENTS_DIR = Join-Path $GoogleDataRoot 'attachments'
  New-Item -ItemType Directory -Path (Split-Path -Parent $env:TOKEN_DB_PATH) -Force | Out-Null
  New-Item -ItemType Directory -Path $env:ATTACHMENTS_DIR -Force | Out-Null
  $Uv = (Get-Command uv -ErrorAction Stop).Source
  Start-AryaService 'google-workspace-mcp' @('run', 'google-accounts-mcp') "http://127.0.0.1:$GoogleMcpPort/mcp" -Executable $Uv -WorkingDirectory $GoogleMcpRoot -BearerToken $env:GOOGLE_MCP_TOKEN -McpProbe
  if (-not $NoCore) {
    Start-AryaService 'arya-core' @('-m', 'core') "http://127.0.0.1:$CorePort/health"
    Write-Host 'ARYA device, voice, Google Workspace MCP, and core are healthy. Press Ctrl+C here to stop them.'
  } else {
    Write-Host 'ARYA device, voice, and Google Workspace MCP are healthy. Core was skipped by -NoCore. Press Ctrl+C here to stop them.'
  }
  while ($Processes | Where-Object { -not $_.HasExited }) {
    foreach ($Process in $Processes | Where-Object { $_.HasExited }) {
      $ProcessKey = [string]$Process.Id
      if (-not $script:ReportedExits.ContainsKey($ProcessKey)) {
        $script:ReportedExits[$ProcessKey] = $true
        $ServiceName = $script:ServiceNames[$ProcessKey]
        Show-ServiceOutput $ServiceName
        throw "$ServiceName exited (exit code $($Process.ExitCode))."
      }
    }
    Start-Sleep -Seconds 1
  }
} catch {
  Write-Error $_
  throw
} finally {
  foreach ($Process in $Processes) {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force }
  }
}

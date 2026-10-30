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
$GoogleMcpPort = if ($env:GOOGLE_MCP_PORT) { $env:GOOGLE_MCP_PORT } else { '5003' }
if (-not $env:DEVICE_TOKEN) { throw 'DEVICE_TOKEN is required in .env for the authenticated device health check.' }
if (-not $env:GOOGLE_MCP_TOKEN) { throw 'GOOGLE_MCP_TOKEN is required in .env for the authenticated Google MCP server.' }
$Processes = @()

function Start-AryaService([string]$Name, [string[]]$Arguments, [string]$HealthUrl, [string]$Executable = $Python, [switch]$Authenticated, [switch]$McpProbe) {
  $Process = Start-Process $Executable -ArgumentList $Arguments -WorkingDirectory $Root -PassThru -WindowStyle Hidden
  $script:Processes += $Process
  $Headers = @{}
  if ($Authenticated) { $Headers.Authorization = "Bearer $env:DEVICE_TOKEN" }
  $Deadline = (Get-Date).AddSeconds(75)
  while ((Get-Date) -lt $Deadline) {
    if ($Process.HasExited) { throw "$Name exited before becoming healthy (exit code $($Process.ExitCode))." }
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
  $env:PORT = $GoogleMcpPort
  $env:MCP_BEARER_TOKEN = $env:GOOGLE_MCP_TOKEN
  $env:GOOGLE_CLIENT_ID = $env:GOOGLE_OAUTH_CLIENT_ID
  $env:GOOGLE_CLIENT_SECRET = $env:GOOGLE_OAUTH_CLIENT_SECRET
  $env:DEFAULT_ACCOUNT = $env:GOOGLE_ACCOUNT
  if (-not $env:GOOGLE_MCP_TOKEN_DB_PATH) {
    $env:GOOGLE_MCP_TOKEN_DB_PATH = Join-Path $env:LOCALAPPDATA 'Arya\google-accounts\tokens.db'
  }
  $env:TOKEN_DB_PATH = $env:GOOGLE_MCP_TOKEN_DB_PATH
  $env:ATTACHMENTS_DIR = Join-Path $env:LOCALAPPDATA 'Arya\google-accounts\attachments'
  New-Item -ItemType Directory -Path (Split-Path -Parent $env:TOKEN_DB_PATH) -Force | Out-Null
  New-Item -ItemType Directory -Path $env:ATTACHMENTS_DIR -Force | Out-Null
  $Uv = (Get-Command uv -ErrorAction Stop).Source
  Start-AryaService 'google-workspace-mcp' @('run', '--project', $GoogleMcpRoot, '--locked', 'python', '-m', 'google_accounts_mcp.server') "http://127.0.0.1:$GoogleMcpPort/mcp" -Executable $Uv -Authenticated -McpProbe
  Start-AryaService 'arya-core' @('-m', 'core') "http://127.0.0.1:$CorePort/health"
  Write-Host 'ARYA device, voice, Google Workspace MCP, and core are healthy. Press Ctrl+C here to stop them.'
  Wait-Process -Id $Processes.Id
} catch {
  Write-Error $_
  throw
} finally {
  foreach ($Process in $Processes) {
    if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force }
  }
}

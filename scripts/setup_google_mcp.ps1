param(
  [Parameter(Mandatory = $true)]
  [string]$Account
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Arya\google-accounts-mcp'
$PinnedCommit = '283988563f9af0c8f4886dde303c5a92d49cf571'
$Repository = 'https://github.com/snickery/google-accounts-mcp.git'
if (-not (Test-Path $EnvFile)) { throw 'Project .env not found. Copy .env.example and configure Google OAuth credentials first.' }

foreach ($Line in Get-Content $EnvFile) {
  if ($Line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
    $Name = $Matches[1]
    $Value = $Matches[2]
    if ($Value.Length -ge 2 -and (($Value.StartsWith('"') -and $Value.EndsWith('"')) -or ($Value.StartsWith("'") -and $Value.EndsWith("'")))) {
      $Value = $Value.Substring(1, $Value.Length - 2)
    }
    Set-Item "Env:$Name" $Value
  }
}
if (-not $env:GOOGLE_OAUTH_CLIENT_ID -or -not $env:GOOGLE_OAUTH_CLIENT_SECRET) {
  throw 'Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env first.'
}

if (-not (Test-Path (Join-Path $InstallRoot '.git'))) {
  New-Item -ItemType Directory -Path (Split-Path -Parent $InstallRoot) -Force | Out-Null
  git clone --no-checkout $Repository $InstallRoot
}
git -C $InstallRoot fetch origin $PinnedCommit
git -C $InstallRoot checkout --detach $PinnedCommit

# The pinned upstream release hard-codes 0.0.0.0. Keep its HTTP server on
# loopback by applying this verified one-line local binding patch.
$ServerPath = Join-Path $InstallRoot 'src\google_accounts_mcp\server.py'
$ServerSource = Get-Content $ServerPath -Raw
$WildcardCount = ([regex]::Matches($ServerSource, 'host="0\.0\.0\.0"')).Count
$LoopbackCount = ([regex]::Matches($ServerSource, 'host="127\.0\.0\.1"')).Count
if ($WildcardCount -eq 1) {
  $ServerSource = $ServerSource.Replace('host="0.0.0.0"', 'host="127.0.0.1"')
  Set-Content -LiteralPath $ServerPath -Value $ServerSource -NoNewline
} elseif ($WildcardCount -ne 0 -or $LoopbackCount -ne 1) {
  throw 'The pinned Google MCP server source no longer matches the expected local-bind patch. Review it before continuing.'
}

$env:GOOGLE_CLIENT_ID = $env:GOOGLE_OAUTH_CLIENT_ID
$env:GOOGLE_CLIENT_SECRET = $env:GOOGLE_OAUTH_CLIENT_SECRET
if (-not $env:GOOGLE_MCP_TOKEN_DB_PATH) {
  $env:GOOGLE_MCP_TOKEN_DB_PATH = Join-Path $env:LOCALAPPDATA 'Arya\google-accounts\tokens.db'
}
$env:TOKEN_DB_PATH = $env:GOOGLE_MCP_TOKEN_DB_PATH
New-Item -ItemType Directory -Path (Split-Path -Parent $env:TOKEN_DB_PATH) -Force | Out-Null
$Uv = (Get-Command uv -ErrorAction Stop).Source
& $Uv sync --project $InstallRoot --locked
if ($LASTEXITCODE -ne 0) { throw 'Could not install the pinned Google Workspace MCP dependencies.' }
& $Uv run --project $InstallRoot --locked python scripts/authorize.py $Account
if ($LASTEXITCODE -ne 0) { throw 'Google OAuth setup did not complete.' }
Write-Host 'Google OAuth credentials were stored locally. The setup script did not print them.'

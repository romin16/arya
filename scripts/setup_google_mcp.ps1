param(
  [Parameter(Mandatory = $true)]
  [string]$Account
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Arya\google-accounts-mcp'
$DataRoot = Join-Path $env:LOCALAPPDATA 'Arya\google-mcp-data'
$TokenDb = Join-Path $DataRoot 'tokens.db'
$AttachmentsRoot = Join-Path $DataRoot 'attachments'
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
$env:MCP_BEARER_TOKEN = $env:GOOGLE_MCP_TOKEN
$env:PORT = '8321'
if (-not $env:GOOGLE_ACCOUNT) { $env:GOOGLE_ACCOUNT = $Account }
$env:DEFAULT_ACCOUNT = $env:GOOGLE_ACCOUNT
$env:TOKEN_DB_PATH = $TokenDb
$env:ATTACHMENTS_DIR = $AttachmentsRoot
New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
New-Item -ItemType Directory -Path $AttachmentsRoot -Force | Out-Null
$Uv = (Get-Command uv -ErrorAction Stop).Source
& $Uv sync --project $InstallRoot --locked
if ($LASTEXITCODE -ne 0) { throw 'Could not install the pinned Google Workspace MCP dependencies.' }
$McpPython = Join-Path $InstallRoot '.venv\Scripts\python.exe'
$HasAccount = & $McpPython -c "import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print('yes' if db.execute('SELECT 1 FROM accounts WHERE lower(email)=lower(?)', (sys.argv[2],)).fetchone() else 'no')" $TokenDb $Account
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the local Google authorization database.' }
if ($HasAccount -contains 'yes') {
  Write-Host 'The requested Google account is already authorized; skipping OAuth.'
} else {
  & $Uv run --project $InstallRoot --locked scripts/authorize.py $Account
  if ($LASTEXITCODE -ne 0) { throw 'Google OAuth setup did not complete.' }
  Write-Host 'Google OAuth setup completed. Credentials were not printed.'
}

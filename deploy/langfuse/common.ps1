function Resolve-RealDirectory([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $volumeRoot = [System.IO.Path]::GetPathRoot($full)
    $segments = $full.Substring($volumeRoot.Length).Split([System.IO.Path]::DirectorySeparatorChar)
    $current = $volumeRoot
    foreach ($segment in $segments) {
        if (-not $segment) { continue }
        $current = Join-Path $current $segment
        $item = Get-Item -LiteralPath $current -ErrorAction Stop
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            $method = $item.GetType().GetMethod('ResolveLinkTarget')
            if (-not $method) {
                throw "Langfuse directory contains a reparse point that cannot be safely resolved: $current"
            }
            $target = $item.ResolveLinkTarget($true)
            if (-not $target) { throw "Could not resolve Langfuse directory link: $current" }
            $current = [System.IO.Path]::GetFullPath($target.FullName)
        }
    }
    return [System.IO.Path]::GetFullPath($current).TrimEnd([char[]]@([char]92, [char]47))
}

function Get-LangfuseComposeContext([string]$RepoRoot) {
    $configuredDir = if ($env:LANGFUSE_COMPOSE_DIR) {
        $env:LANGFUSE_COMPOSE_DIR
    } else {
        'C:\path\to\langfuse'
    }
    if (-not (Test-Path -LiteralPath $configuredDir -PathType Container)) {
        throw "Langfuse Compose directory does not exist: $configuredDir"
    }

    $repoPath = Resolve-RealDirectory $RepoRoot
    $composeDir = Resolve-RealDirectory (Resolve-Path -LiteralPath $configuredDir).Path
    $repoPrefix = $repoPath + [System.IO.Path]::DirectorySeparatorChar
    if ($composeDir.Equals($repoPath, [System.StringComparison]::OrdinalIgnoreCase) -or
        $composeDir.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to run Langfuse Compose from inside the Arya repository: $composeDir"
    }

    $envFile = Join-Path $composeDir '.env'
    if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
        throw "Langfuse env file does not exist: $envFile"
    }
    $composeFile = @('compose.yaml', 'compose.yml', 'docker-compose.yaml', 'docker-compose.yml') |
        ForEach-Object { Join-Path $composeDir $_ } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not $composeFile) { throw "No Docker Compose file found in the configured Langfuse directory." }

    return @{
        Directory = $composeDir
        EnvFile = [System.IO.Path]::GetFullPath($envFile)
        ComposeFile = [System.IO.Path]::GetFullPath($composeFile)
        Arguments = @('--project-directory', $composeDir, '--env-file', [System.IO.Path]::GetFullPath($envFile), '-f', [System.IO.Path]::GetFullPath($composeFile))
    }
}

<#
.SYNOPSIS
    Build a standalone Windows bundle with PyInstaller.
.DESCRIPTION
    Produces release/WeChatAgentAI/WeChatAgentAI.exe.
    Notes:
      * llmadb is an external CLI dependency; the bundle expects it on PATH or
        configured in settings.json (runtime.llmadb_path).
      * adb is also external (Android platform-tools).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    # CI installs the project into the runner's Python instead of a local venv.
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $systemPython) {
        throw 'Python not found. Run scripts/dev.ps1 first or install Python 3.11+.'
    }
    $venvPython = $systemPython.Source
}

if (-not $SkipInstall) {
    Write-Host '==> Installing build dependencies' -ForegroundColor Cyan
    & $venvPython -m pip install --disable-pip-version-check -q -e '.[dev]'
}

if ($Clean -and (Test-Path 'build')) {
    Remove-Item 'build' -Recurse -Force
}
if (Test-Path 'release/WeChatAgentAI') {
    Remove-Item 'release/WeChatAgentAI' -Recurse -Force
}

Write-Host '==> Running PyInstaller' -ForegroundColor Cyan
$pyinstallerArgs = @(
    '--noconfirm',
    '--clean',
    '--windowed',
    '--name', 'WeChatAgentAI',
    '--distpath', 'release',
    '--workpath', 'build',
    '--specpath', 'build',
    '--collect-submodules', 'mcp.server',
    '--collect-submodules', 'mcp.shared',
    '--copy-metadata', 'mcp',
    '--collect-submodules', 'agent',
    '--collect-submodules', 'memory',
    '--collect-submodules', 'config',
    'app/main.py'
)
& $venvPython -m PyInstaller @pyinstallerArgs
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

Write-Host '==> Copying bundled config (persona / permissions / wechat prompt)' -ForegroundColor Cyan
$bundleDir = 'release/WeChatAgentAI'
$contentDirs = @("$bundleDir/_internal", $bundleDir) | Where-Object { Test-Path $_ }
foreach ($contentDir in $contentDirs) {
    Copy-Item 'config' -Destination (Join-Path $contentDir 'config') -Recurse -Force
    $memoryDir = Join-Path $contentDir 'memory'
    New-Item -ItemType Directory -Force -Path $memoryDir | Out-Null
    Copy-Item 'memory/schema.sql' -Destination (Join-Path $memoryDir 'schema.sql') -Force
}

Copy-Item README.md, LICENSE -Destination $bundleDir -Force
Write-Host '==> Done: release/WeChatAgentAI/WeChatAgentAI.exe' -ForegroundColor Green
Write-Host 'Reminder: install llm-adb + platform-tools for the target machine.' -ForegroundColor Yellow

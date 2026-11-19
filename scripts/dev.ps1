#Requires -Version 5.1
<#
.SYNOPSIS
    One-shot developer bootstrap for WeChat Agent AI.
.DESCRIPTION
    Creates .venv, installs the project in editable mode with dev extras,
    downloads Android platform-tools when adb is missing, and runs the
    environment self-check. Safe to re-run.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipTools,
    [switch]$SkipCheck
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

# 1. Virtual environment -----------------------------------------------------
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Step 'Creating virtual environment (.venv)'
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'python -m venv failed. Is Python 3.11+ installed?' }
}

Write-Step 'Installing project in editable mode with dev extras'
& $venvPython -m pip install --disable-pip-version-check -q -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

# 2. Android platform-tools --------------------------------------------------
if (-not $SkipTools) {
    $adb = Get-Command adb -ErrorAction SilentlyContinue
    if (-not $adb) {
        $target = Join-Path $env:LOCALAPPDATA 'Android\platform-tools'
        if (-not (Test-Path (Join-Path $target 'adb.exe'))) {
            Write-Step 'Downloading Android platform-tools'
            $zip = Join-Path $env:TEMP 'platform-tools.zip'
            Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile $zip
            $extract = Join-Path $env:TEMP 'platform-tools-extract'
            if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
            Expand-Archive -Path $zip -DestinationPath $extract -Force
            $null = New-Item -ItemType Directory -Force -Path (Split-Path $target)
            if (Test-Path $target) { Remove-Item $target -Recurse -Force }
            Move-Item (Join-Path $extract 'platform-tools') $target
        }
        Write-Host "adb installed at $target; add it to PATH or set runtime.adb_path." -ForegroundColor Yellow
    }
}

# 3. Environment check -------------------------------------------------------
if (-not $SkipCheck) {
    Write-Step 'Verifying environment'
    & $venvPython scripts/check_env.py
}

Write-Step 'Done. Activate with: .\.venv\Scripts\Activate.ps1'
Write-Host 'Start the app with: python -m app.main' -ForegroundColor Green

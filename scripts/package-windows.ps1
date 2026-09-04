# Build and package Agent Workbench for Windows.
# Artifact: dist/AgentWorkbench-vX.Y.Z-windows.zip
# Usage: pwsh -File scripts/package-windows.ps1
# NOTE: keep this file pure ASCII for Windows PowerShell 5.1 compatibility.
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot

$pyproject = Get-Content -LiteralPath "pyproject.toml" -Raw
$versionMatch = [regex]::Match($pyproject, 'version\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "Cannot read project version from pyproject.toml"
}
$version = $versionMatch.Groups[1].Value
$packageName = "AgentWorkbench-v$version-windows"
$packageParent = Join-Path $projectRoot "dist\package"
$packageDir = Join-Path $packageParent $packageName
$zipPath = Join-Path $projectRoot "dist\$packageName.zip"

$distRoot = Join-Path (Resolve-Path -LiteralPath $projectRoot).Path "dist"
if ((Split-Path $packageParent -Parent) -ne $distRoot) {
    throw "Unexpected package path: $packageParent"
}

Write-Host "==> Building executables..."
& (Join-Path $PSScriptRoot "build-exe.ps1")

Write-Host "==> Preparing package folder..."
if (Test-Path -LiteralPath $packageDir) {
    Remove-Item -LiteralPath $packageDir -Recurse -Force
}
New-Item -ItemType Directory -Path $packageDir | Out-Null

Copy-Item -LiteralPath (Join-Path $projectRoot "dist\MultiAgentWorkbench.exe") -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $projectRoot "dist\AgentWorkbench-CLI.exe") -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $projectRoot "scripts\setup-deepseek.ps1") -Destination (Join-Path $packageDir "setup-provider.ps1")

$startHere = @"
Agent Workbench v$version

Quick start:
1. Double-click MultiAgentWorkbench.exe to open the Web UI.
2. To configure API keys, right-click in this folder, open PowerShell, then run:
   powershell -ExecutionPolicy Bypass -File .\setup-provider.ps1
3. In the menu:
   1 = Configure DeepSeek API
   2 = Configure OpenAI API
   3 = Stop API calls and switch back to local mock
   4 = Show current provider status
   5 = Start Web UI
   6 = Exit

Notes:
- API keys are stored in Windows User environment variables.
- API keys are not saved into this folder or the Git repository.
- Keep MultiAgentWorkbench.exe and AgentWorkbench-CLI.exe in the same folder.
"@
Set-Content -LiteralPath (Join-Path $packageDir "START_HERE.txt") -Value $startHere -Encoding UTF8

Write-Host "==> Creating zip..."
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path $packageDir -DestinationPath $zipPath

Write-Host "==> Package created:"
Get-Item -LiteralPath $zipPath | Select-Object FullName, Length, LastWriteTime

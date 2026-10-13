# Build Multi-Agent Workbench as Windows executables (PyInstaller)
# Artifacts: dist/MultiAgentWorkbench.exe (WebView UI) + dist/AgentWorkbench-CLI.exe (CLI)
# Usage: pwsh -File scripts/build-exe.ps1   (or PowerShell 7)
# NOTE: keep this file pure ASCII - Windows PowerShell 5.1 misreads UTF-8 Chinese.
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot

Write-Host "==> Building CLI (AgentWorkbench-CLI.exe) ..."
& python -m PyInstaller --noconfirm --onefile --console `
    --name AgentWorkbench-CLI `
    --distpath dist --workpath build --specpath build `
    --paths src scripts/launcher_cli.py
if ($LASTEXITCODE -ne 0) {
    throw "CLI build failed with exit code $LASTEXITCODE"
}

Write-Host "==> Building WebView UI (MultiAgentWorkbench.exe) ..."
& python -m PyInstaller --noconfirm --onedir --windowed `
    --name MultiAgentWorkbench `
    --contents-directory _internal `
    --distpath dist --workpath build --specpath build `
    --paths src `
    --collect-all webview `
    --collect-all clr_loader `
    --hidden-import webview.platforms.edgechromium `
    --runtime-hook scripts/runtime_hook_pythonnet_path.py `
    scripts/launcher_webview.py
if ($LASTEXITCODE -ne 0) {
    throw "WebView build failed with exit code $LASTEXITCODE"
}

$distRoot = (Resolve-Path -LiteralPath (Join-Path $projectRoot "dist")).Path
$uiBundle = Join-Path $distRoot "MultiAgentWorkbench"
$uiExe = Join-Path $uiBundle "MultiAgentWorkbench.exe"
$uiInternal = Join-Path $uiBundle "_internal"
$rootInternal = Join-Path $distRoot "_internal"
if (-not (Test-Path -LiteralPath $uiExe) -or -not (Test-Path -LiteralPath $uiInternal)) {
    throw "Expected onedir output is incomplete: $uiBundle"
}

if (Test-Path -LiteralPath $rootInternal) {
    $resolvedInternal = (Resolve-Path -LiteralPath $rootInternal).Path
    if ((Split-Path -Parent $resolvedInternal) -ne $distRoot) {
        throw "Unexpected runtime directory path: $resolvedInternal"
    }
    Remove-Item -LiteralPath $resolvedInternal -Recurse -Force
}
Copy-Item -LiteralPath $uiExe -Destination (Join-Path $distRoot "MultiAgentWorkbench.exe") -Force
Copy-Item -LiteralPath $uiInternal -Destination $rootInternal -Recurse

Write-Host "==> Done. Artifacts:"
Get-ChildItem dist | Select-Object Name, Length, LastWriteTime

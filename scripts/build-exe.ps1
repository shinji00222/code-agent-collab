# Build Multi-Agent Workbench as Windows executables (PyInstaller)
# Artifacts: dist/MultiAgentWorkbench.exe (UI) + dist/AgentWorkbench-CLI.exe (CLI)
# Usage: pwsh -File scripts/build-exe.ps1   (or PowerShell 7)
# NOTE: keep this file pure ASCII - Windows PowerShell 5.1 misreads UTF-8 Chinese.
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot

Write-Host "==> Building CLI (AgentWorkbench-CLI.exe) ..."
python -m PyInstaller --noconfirm --onefile --console `
    --name AgentWorkbench-CLI `
    --distpath dist --workpath build --specpath build `
    --paths src scripts/launcher_cli.py

Write-Host "==> Building Web UI (MultiAgentWorkbench.exe) ..."
python -m PyInstaller --noconfirm --onefile --windowed `
    --name MultiAgentWorkbench `
    --distpath dist --workpath build --specpath build `
    --paths src scripts/launcher_webui.py

Write-Host "==> Done. Artifacts:"
Get-ChildItem dist | Select-Object Name, Length, LastWriteTime

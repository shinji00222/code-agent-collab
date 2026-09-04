param(
    [int]$Port = 8091,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

function Ask-YesNo {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [bool]$DefaultYes = $true
    )

    $suffix = if ($DefaultYes) { " [Y/n]" } else { " [y/N]" }

    while ($true) {
        $answer = Read-Host ($Message + $suffix)
        if ([string]::IsNullOrWhiteSpace($answer)) {
            return $DefaultYes
        }

        switch ($answer.Trim().ToLowerInvariant()) {
            "y" { return $true }
            "yes" { return $true }
            "n" { return $false }
            "no" { return $false }
            default { Write-Host "Please answer y or n." -ForegroundColor Yellow }
        }
    }
}

function Read-HiddenApiKey {
    param([Parameter(Mandatory = $true)][string]$ProviderLabel)

    $secureKey = Read-Host "Paste $ProviderLabel API Key (input hidden)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

function Show-ProviderStatus {
    Write-Host ""
    Write-Host "Current provider status:"
    python -m code_agent_collab.cli provider
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Start-AgentWorkbenchWebUi {
    param([int]$UiPort)

    $listeners = @(Get-NetTCPConnection -LocalPort $UiPort -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $ownerIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
        Write-Host "Port $UiPort is already in use by process id(s): $($ownerIds -join ', ')"

        if (Ask-YesNo "Stop these local process(es) and restart Web UI?" $false) {
            foreach ($webuiPid in $ownerIds) {
                Stop-Process -Id $webuiPid -Force
            }
            Start-Sleep -Milliseconds 500
        }
        else {
            Write-Host "Keeping the existing server. Refresh the browser or restart it later."
            return
        }
    }

    Write-Host "Starting Web UI. Press Ctrl+C in this window to stop it."
    python -m code_agent_collab.webui --port $UiPort
}

function Enable-RealProvider {
    param(
        [Parameter(Mandatory = $true)][string]$ProviderName,
        [Parameter(Mandatory = $true)][string]$ProviderLabel,
        [Parameter(Mandatory = $true)][string]$ApiKeyEnvName
    )

    Write-Host ""
    Write-Host "This stores provider/key in Windows User environment variables, not in repo files."
    Write-Host "Do not paste your API Key into chat. Paste it only in this local terminal window."

    if (-not (Ask-YesNo "Continue configuring $ProviderLabel?")) {
        Write-Host "Cancelled."
        return
    }

    $apiKey = Read-HiddenApiKey -ProviderLabel $ProviderLabel
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        Write-Host "API Key is empty. Cancelled." -ForegroundColor Red
        return
    }

    [Environment]::SetEnvironmentVariable("AGENT_WORKBENCH_PROVIDER", $ProviderName, "User")
    [Environment]::SetEnvironmentVariable($ApiKeyEnvName, $apiKey, "User")
    $env:AGENT_WORKBENCH_PROVIDER = $ProviderName
    Set-Item -Path "Env:\$ApiKeyEnvName" -Value $apiKey

    Write-Host "Saved."
    Show-ProviderStatus

    if (Ask-YesNo "Start Web UI now on port $Port?") {
        Start-AgentWorkbenchWebUi -UiPort $Port
    }
}

function Disable-RealProvider {
    Write-Host ""
    Write-Host "This switches Agent Workbench back to local mock provider, so it will not call DeepSeek/OpenAI."

    if (-not (Ask-YesNo "Switch back to local mock provider?")) {
        Write-Host "Cancelled."
        return
    }

    [Environment]::SetEnvironmentVariable("AGENT_WORKBENCH_PROVIDER", "mock", "User")
    $env:AGENT_WORKBENCH_PROVIDER = "mock"

    if (Ask-YesNo "Also remove the saved DeepSeek API Key from Windows User environment variables?" $false) {
        [Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", $null, "User")
        Remove-Item Env:\DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
        Write-Host "DeepSeek API Key removed from User environment variables."
    }

    if (Ask-YesNo "Also remove the saved OpenAI API Key from Windows User environment variables?" $false) {
        [Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $null, "User")
        Remove-Item Env:\OPENAI_API_KEY -ErrorAction SilentlyContinue
        Write-Host "OpenAI API Key removed from User environment variables."
    }

    Write-Host "Saved."
    Show-ProviderStatus
}

function Read-MenuChoice {
    Write-Host ""
    Write-Host "Choose an action:"
    Write-Host "1) Configure DeepSeek API"
    Write-Host "2) Configure OpenAI API"
    Write-Host "3) Stop API calls and switch back to local mock"
    Write-Host "4) Show current provider status"
    Write-Host "5) Start Web UI"
    Write-Host "6) Exit"

    while ($true) {
        $choice = Read-Host "Enter 1/2/3/4/5/6"
        switch ($choice.Trim()) {
            "1" { return "configure-deepseek" }
            "2" { return "configure-openai" }
            "3" { return "disable" }
            "4" { return "status" }
            "5" { return "webui" }
            "6" { return "exit" }
            default { Write-Host "Please enter 1, 2, 3, 4, 5, or 6." -ForegroundColor Yellow }
        }
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = "src"

if ($CheckOnly) {
    python -m code_agent_collab.cli provider
    exit $LASTEXITCODE
}

Write-Host "AI provider setup wizard for Agent Workbench."

while ($true) {
    $action = Read-MenuChoice
    switch ($action) {
        "configure-deepseek" {
            Enable-RealProvider -ProviderName "deepseek" -ProviderLabel "DeepSeek" -ApiKeyEnvName "DEEPSEEK_API_KEY"
        }
        "configure-openai" {
            Enable-RealProvider -ProviderName "openai" -ProviderLabel "OpenAI" -ApiKeyEnvName "OPENAI_API_KEY"
        }
        "disable" { Disable-RealProvider }
        "status" { Show-ProviderStatus }
        "webui" { Start-AgentWorkbenchWebUi -UiPort $Port }
        "exit" {
            Write-Host "Done."
            exit 0
        }
    }
}

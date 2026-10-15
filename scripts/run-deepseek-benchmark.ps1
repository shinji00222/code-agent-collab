$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$secret = Read-Host '请输入新生成的 DeepSeek API Key（输入内容不会显示）' -AsSecureString
$keyPointer = [IntPtr]::Zero
$plainKey = $null
$previous = @{
    provider = $env:AGENT_WORKBENCH_PROVIDER
    key = $env:DEEPSEEK_API_KEY
    pythonPath = $env:PYTHONPATH
}

try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw 'API Key 不能为空。'
    }

    $env:AGENT_WORKBENCH_PROVIDER = 'deepseek'
    $env:DEEPSEEK_API_KEY = $plainKey
    $env:PYTHONPATH = Join-Path $projectRoot 'src'

    Push-Location $projectRoot
    try {
        python -m code_agent_collab.cli benchmark --mode both --repeats 3
        if ($LASTEXITCODE -ne 0) {
            throw "benchmark 执行失败，退出码：$LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:AGENT_WORKBENCH_PROVIDER = $previous.provider
    $env:DEEPSEEK_API_KEY = $previous.key
    $env:PYTHONPATH = $previous.pythonPath
    $plainKey = $null
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
    if ($secret) {
        $secret.Dispose()
    }
}

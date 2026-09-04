from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SetupScriptTests(unittest.TestCase):
    def test_deepseek_setup_script_keeps_key_out_of_repo_files(self) -> None:
        script = PROJECT_ROOT / "scripts" / "setup-deepseek.ps1"
        text = script.read_text(encoding="utf-8")

        self.assertIn('Read-Host "Paste $ProviderLabel API Key (input hidden)" -AsSecureString', text)
        self.assertIn('Enable-RealProvider -ProviderName "deepseek"', text)
        self.assertIn('Enable-RealProvider -ProviderName "openai"', text)
        self.assertIn('ApiKeyEnvName "DEEPSEEK_API_KEY"', text)
        self.assertIn('ApiKeyEnvName "OPENAI_API_KEY"', text)
        self.assertIn('[Environment]::SetEnvironmentVariable("AGENT_WORKBENCH_PROVIDER", $ProviderName, "User")', text)
        self.assertIn('[Environment]::SetEnvironmentVariable("AGENT_WORKBENCH_PROVIDER", "mock", "User")', text)
        self.assertIn('[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", $null, "User")', text)
        self.assertIn('[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $null, "User")', text)
        self.assertIn('Write-Host "1) Configure DeepSeek API"', text)
        self.assertIn('Write-Host "2) Configure OpenAI API"', text)
        self.assertIn('Write-Host "3) Stop API calls and switch back to local mock"', text)
        self.assertIn('Write-Host "4) Show current provider status"', text)
        self.assertIn('AGENT_WORKBENCH_PROVIDER = $ProviderName', text)
        self.assertIn("Get-NetTCPConnection -LocalPort $UiPort", text)
        self.assertIn("$webuiPid", text)
        self.assertNotIn("$pid =", text.lower())
        self.assertIsNone(re.search(r"sk-[A-Za-z0-9_-]{10,}", text))

    def test_windows_package_script_includes_exes_and_provider_setup(self) -> None:
        script = PROJECT_ROOT / "scripts" / "package-windows.ps1"
        text = script.read_text(encoding="utf-8")

        self.assertIn("build-exe.ps1", text)
        self.assertIn("MultiAgentWorkbench.exe", text)
        self.assertIn("AgentWorkbench-CLI.exe", text)
        self.assertIn("setup-provider.ps1", text)
        self.assertIn("Compress-Archive", text)
        self.assertIn("START_HERE.txt", text)


if __name__ == "__main__":
    unittest.main()

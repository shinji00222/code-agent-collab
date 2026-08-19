import os
import unittest
from unittest.mock import patch

from code_agent_collab.providers import (
    MockProvider,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderConfigurationError,
    create_provider,
)


class ProviderTests(unittest.TestCase):
    def test_default_provider_is_mock(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = ProviderConfig.from_env()
        self.assertEqual(config.name, "mock")
        self.assertIsInstance(create_provider(config), MockProvider)

    def test_mock_provider_returns_safe_local_result(self) -> None:
        result = MockProvider().complete("system", "检查任务")
        self.assertIn("模拟 AI 已收到任务", result)

    def test_deepseek_preset_uses_safe_defaults(self) -> None:
        with patch.dict(os.environ, {"AGENT_WORKBENCH_PROVIDER": "deepseek"}, clear=True):
            config = ProviderConfig.from_env()
        self.assertEqual(config.model, "deepseek-v4-flash")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.api_key_env, "DEEPSEEK_API_KEY")

    def test_openai_preset_uses_safe_defaults(self) -> None:
        with patch.dict(os.environ, {"AGENT_WORKBENCH_PROVIDER": "openai"}, clear=True):
            config = ProviderConfig.from_env()
        self.assertEqual(config.model, "gpt-5-mini")
        self.assertEqual(config.base_url, "https://api.openai.com/v1")
        self.assertEqual(config.api_key_env, "OPENAI_API_KEY")

    def test_unknown_provider_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_provider(ProviderConfig(name="unknown"))

    def test_real_provider_explains_missing_key_without_network_call(self) -> None:
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                name="deepseek",
                model="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                api_key_env="MISSING_DEEPSEEK_KEY",
            )
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ProviderConfigurationError, "还没有配置密钥"):
                provider.complete("system", "user")

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
        self.assertEqual(config.model, "deepseek-chat")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.api_key_env, "DEEPSEEK_API_KEY")
        self.assertEqual(create_provider(config).name, "deepseek")

    def test_openai_preset_uses_safe_defaults(self) -> None:
        with patch.dict(os.environ, {"AGENT_WORKBENCH_PROVIDER": "openai"}, clear=True):
            config = ProviderConfig.from_env()
        self.assertEqual(config.model, "gpt-5-mini")
        self.assertEqual(config.base_url, "https://api.openai.com/v1")
        self.assertEqual(config.api_key_env, "OPENAI_API_KEY")

    def test_unknown_provider_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_provider(ProviderConfig(name="unknown"))

    def test_openai_compatible_preset_requires_explicit_config(self) -> None:
        with patch.dict(
            os.environ, {"AGENT_WORKBENCH_PROVIDER": "openai-compatible"}, clear=True
        ):
            config = ProviderConfig.from_env()
        self.assertEqual(config.name, "openai-compatible")
        self.assertEqual(config.base_url, "")
        self.assertIsInstance(create_provider(config), OpenAICompatibleProvider)

    def test_env_vars_override_preset_defaults(self) -> None:
        env = {
            "AGENT_WORKBENCH_PROVIDER": "deepseek",
            "AGENT_WORKBENCH_MODEL": "deepseek-reasoner",
            "AGENT_WORKBENCH_BASE_URL": "https://example.com/v1",
            "AGENT_WORKBENCH_API_KEY_ENV": "MY_CUSTOM_KEY",
        }
        with patch.dict(os.environ, env, clear=True):
            config = ProviderConfig.from_env()
        self.assertEqual(config.model, "deepseek-reasoner")
        self.assertEqual(config.base_url, "https://example.com/v1")
        self.assertEqual(config.api_key_env, "MY_CUSTOM_KEY")

    def test_real_provider_explains_missing_key_without_network_call(self) -> None:
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                name="deepseek",
                model="deepseek-chat",
                base_url="https://api.deepseek.com",
                api_key_env="MISSING_DEEPSEEK_KEY",
            )
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ProviderConfigurationError, "还没有配置密钥"):
                provider.complete("system", "user")

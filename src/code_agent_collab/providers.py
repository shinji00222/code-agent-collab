from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib import request


@dataclass(frozen=True)
class ProviderConfig:
    name: str = "mock"
    model: str = "mock-model"
    base_url: str = ""
    api_key_env: str = ""

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        name = os.getenv("AGENT_WORKBENCH_PROVIDER", "mock")
        is_deepseek = name == "deepseek"
        is_openai = name == "openai"
        return cls(
            name=name,
            model=os.getenv(
                "AGENT_WORKBENCH_MODEL",
                "deepseek-v4-flash"
                if is_deepseek
                else "gpt-5-mini" if is_openai else "mock-model",
            ),
            base_url=os.getenv(
                "AGENT_WORKBENCH_BASE_URL",
                "https://api.deepseek.com"
                if is_deepseek
                else "https://api.openai.com/v1" if is_openai else "",
            ),
            api_key_env=os.getenv(
                "AGENT_WORKBENCH_API_KEY_ENV",
                "DEEPSEEK_API_KEY"
                if is_deepseek
                else "OPENAI_API_KEY" if is_openai else "",
            ),
        )


class AIProvider:
    name = "base"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class ProviderConfigurationError(ValueError):
    """Raised when a real Provider is missing required local configuration."""


class MockProvider(AIProvider):
    name = "mock"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        return f"模拟 AI 已收到任务：{user_prompt}"


class OpenAICompatibleProvider(AIProvider):
    name = "openai-compatible"

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.config.base_url:
            raise ProviderConfigurationError(
                "使用 OpenAI 兼容 Provider 时必须设置 AGENT_WORKBENCH_BASE_URL"
            )
        if not self.config.api_key_env:
            raise ProviderConfigurationError(
                "使用 OpenAI 兼容 Provider 时必须设置 AGENT_WORKBENCH_API_KEY_ENV"
            )

        api_key = os.getenv(self.config.api_key_env)
        if not api_key:
            raise ProviderConfigurationError(
                f"还没有配置密钥，请在 PowerShell 设置环境变量：{self.config.api_key_env}"
            )

        payload = json.dumps(
            {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode("utf-8")
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        http_request = request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]


def create_provider(config: ProviderConfig | None = None) -> AIProvider:
    selected = config or ProviderConfig.from_env()
    if selected.name == "mock":
        return MockProvider()
    if selected.name in {"deepseek", "openai", "openai-compatible"}:
        return OpenAICompatibleProvider(selected)
    raise ValueError(f"不支持的 Provider：{selected.name}")

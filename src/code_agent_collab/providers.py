from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from urllib import error, request


PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "mock": {
        "model": "mock-model",
        "base_url": "",
        "api_key_env": "",
    },
    "deepseek": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "model": "gpt-5-mini",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
    },
    "openai-compatible": {
        "model": "",
        "base_url": "",
        "api_key_env": "AGENT_WORKBENCH_API_KEY",
    },
}

SUPPORTED_PROVIDERS: tuple[str, ...] = tuple(PROVIDER_PRESETS)


@dataclass(frozen=True)
class ProviderConfig:
    name: str = "mock"
    model: str = "mock-model"
    base_url: str = ""
    api_key_env: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        name = os.getenv("AGENT_WORKBENCH_PROVIDER", "mock")
        preset = PROVIDER_PRESETS.get(name, {})
        return cls(
            name=name,
            model=os.getenv("AGENT_WORKBENCH_MODEL", preset.get("model", "")),
            base_url=os.getenv("AGENT_WORKBENCH_BASE_URL", preset.get("base_url", "")),
            api_key_env=os.getenv(
                "AGENT_WORKBENCH_API_KEY_ENV", preset.get("api_key_env", "")
            ),
            timeout_seconds=float(os.getenv("AGENT_WORKBENCH_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.getenv("AGENT_WORKBENCH_MAX_RETRIES", "2")),
            retry_backoff_seconds=float(os.getenv("AGENT_WORKBENCH_RETRY_BACKOFF_SECONDS", "0.5")),
        )


class AIProvider:
    name = "base"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class ProviderConfigurationError(ValueError):
    """Raised when a real Provider is missing required local configuration."""


class ProviderCallError(RuntimeError):
    """Raised when a configured Provider call fails or returns invalid data."""


class MockProvider(AIProvider):
    name = "mock"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        return f"模拟 AI 已收到任务：{user_prompt}"


class OpenAICompatibleProvider(AIProvider):
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.name = config.name or "openai-compatible"

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
        result = self._request_with_retries(http_request)
        return _extract_chat_content(result)

    def _request_with_retries(self, http_request: request.Request) -> dict:
        attempts = max(1, self.config.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with request.urlopen(
                    http_request,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                if not _is_retryable_http_status(exc.code) or attempt == attempts - 1:
                    raise ProviderCallError(f"Provider HTTP {exc.code}：{exc.reason}") from exc
                last_error = exc
            except (TimeoutError, error.URLError, json.JSONDecodeError, OSError) as exc:
                if attempt == attempts - 1:
                    raise ProviderCallError(f"Provider 调用失败：{exc}") from exc
                last_error = exc
            time.sleep(self.config.retry_backoff_seconds * (2**attempt))
        raise ProviderCallError(f"Provider 调用失败：{last_error}")


def _is_retryable_http_status(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def _extract_chat_content(result: dict) -> str:
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderCallError("Provider 返回结构无效：缺少 choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise ProviderCallError("Provider 返回内容为空")
    return content


def create_provider(config: ProviderConfig | None = None) -> AIProvider:
    selected = config or ProviderConfig.from_env()
    if selected.name == "mock":
        return MockProvider()
    if selected.name in {"deepseek", "openai", "openai-compatible"}:
        return OpenAICompatibleProvider(selected)
    raise ValueError(f"不支持的 Provider：{selected.name}")

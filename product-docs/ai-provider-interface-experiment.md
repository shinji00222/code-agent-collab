# AI 提供商接口实验版

## 当前结论

当前版本增加了统一的 AI Provider 接口，`PlannerAgent` 和 `CoderAgent` 已经通过这个接口获取计划结果与代码草稿，但默认仍使用本地 `mock` Provider，不会联网，也不需要 API Key。

以后接入真实 AI 时，Agent 只调用统一接口，不直接管理密钥。密钥只从环境变量读取，不写入项目文件、日志或知识库。

目前提供了 4 个预设：

- `mock`：本地模拟，不联网。
- `deepseek`：接口地址使用 `https://api.deepseek.com`，默认模型使用 `deepseek-chat`，密钥环境变量使用 `DEEPSEEK_API_KEY`。
- `openai`：接口地址使用 `https://api.openai.com/v1`，默认模型使用 `gpt-5-mini`，密钥环境变量使用 `OPENAI_API_KEY`。
- `openai-compatible`：通用兼容接口，需要显式设置模型、接口地址和密钥环境变量。

以上默认值均可通过 `AGENT_WORKBENCH_MODEL`、`AGENT_WORKBENCH_BASE_URL`、`AGENT_WORKBENCH_API_KEY_ENV` 覆盖。

## 配置方式

```text
AGENT_WORKBENCH_PROVIDER=mock
AGENT_WORKBENCH_MODEL=mock-model
AGENT_WORKBENCH_BASE_URL=
AGENT_WORKBENCH_API_KEY_ENV=
```

真实接口需要额外设置：

```text
AGENT_WORKBENCH_PROVIDER=openai-compatible
AGENT_WORKBENCH_MODEL=模型名
AGENT_WORKBENCH_BASE_URL=接口地址
AGENT_WORKBENCH_API_KEY_ENV=保存密钥的环境变量名
```

## 安全边界

- 默认 Provider 不联网。
- 真实 Provider 不会把 API Key 写入请求日志。
- 不把 API Key 放进 `config.json`、Markdown、Git 或 Obsidian。
- 真实请求功能属于实验版，接入前需要单独测试超时、错误和费用控制。

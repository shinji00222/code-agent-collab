# 更新日志

## v0.4.0 - 2026-08-20（发布版）

### 新增

- 增加 CoderAgent 行动 Agent，根据任务和上下文包生成代码草稿。
- CoderAgent 草稿只写入 `dev-vault/projects`，不直接修改正式源码。
- 工作流扩展为 6 个 Agent：协调、知识、计划、编码、验证、复盘。
- 增加项目 `skills.md`，沉淀可复用开发技能和新增 Agent 标准流程。
- 增加 `docs/项目企划.md`，记录项目目标、角色、Provider 思路和权限边界。
- AGENTS.md 增加版本分类要求与技能沉淀要求。
- 修正 DeepSeek 默认模型为官方 `deepseek-chat`，集中预留 DeepSeek/OpenAI/OpenAI 兼容预设。
- 增加 `AGENT_WORKBENCH_MODEL`、`AGENT_WORKBENCH_BASE_URL`、`AGENT_WORKBENCH_API_KEY_ENV` 环境变量覆盖。
- `provider` 命令显示可用 Provider 列表，并修复 Windows 管道输出中文乱码。
- 修复真实 Provider 调用时日志显示固定为 `openai-compatible` 的问题，现在按实际配置显示（如 `deepseek`）。

### 边界

- 该版本已通过本地测试与真实 DeepSeek 调用验证，属于发布版。
- CoderAgent 默认使用 mock Provider，草稿为模拟内容；接真实模型前需先验证。
- 草稿未经 ValidatorAgent 和人工检查，不能直接合并到正式源码。
- 主知识库保持只读。

## v0.3.0 - 2026-08-19

### 新增

- 增加统一 AI Provider 接口。
- 增加 DeepSeek 和 OpenAI 预设。
- PlannerAgent 支持通过 Provider 生成计划。
- 增加默认本地模拟 Provider，便于不联网验证协作流程。
- 增加 `provider` 命令查看当前 Provider 配置。
- 增加 OpenAI 兼容接口的环境变量配置骨架。

### 边界

- 默认仍使用 mock，不配置密钥就不会联网。
- 当前只有 PlannerAgent 调用 Provider，其他 Agent 仍是规则版。
- API Key 只允许从环境变量读取，不写入项目文件或日志。
- 该版本属于实验版，暂不代表完整的多模型协作。

## v0.2.0 - 2026-08-19

### 新增

- 增加规则版多 Agent 工作流骨架。
- 增加 5 个 Agent 角色：协调、知识库、计划、验证、复盘。
- 增加 Agent 权限分级：只读、草稿写入、项目写入、需确认。
- 增加 `run` 命令，一次执行多 Agent 工作流。
- 增加工作流日志输出到 `logs/workflows`。

### 边界

- 当前 Agent 仍是规则函数，不调用真实 AI API。
- 复盘内容仍只写入 `dev-vault/pending`。
- 主知识库保持只读。

## v0.1.0 - 2026-08-18

### 新增

- 初始化命令行 MVP。
- 增加 `start` 命令生成任务上下文包。
- 增加 `reflect` 命令生成候选复利记录。
- 增加 `pending` 命令查看待确认候选。
- 增加 `demo` 命令一键跑通基础闭环。

### 边界

- 不调用真实 AI API。
- 不写入主知识库。
- 自动生成内容先进入项目测试区。

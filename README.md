# 多 Agent 代码协作助手

一个本地优先的命令行原型，用来探索：

- 多 Agent 如何围绕同一个项目协作；
- Obsidian 知识库如何参与任务上下文；
- AI 生成的经验如何先进入候选区，再由用户确认；
- 如何避免主知识库被自动污染。

## 当前版本

当前版本：`v0.3.0`

阶段定位：Provider 接入实验版。

当前版本已接入 Provider 接口：默认使用本地模拟 Provider；配置 DeepSeek 或 OpenAI 后，PlannerAgent 可以调用真实模型生成计划。

## 核心原则

- 主知识库默认只读。
- AI 自动生成内容先进入 `dev-vault`。
- 候选复利记录先进入 `dev-vault/pending`。
- 写入主知识库必须经过用户确认。
- CoordinatorAgent、KnowledgeAgent、ValidatorAgent 和 ReflectorAgent 仍是规则版；PlannerAgent 支持通过 Provider 调用模型。

## 命令

在项目根目录运行：

```powershell
$env:PYTHONPATH="src"
python -m code_agent_collab.cli start "任务目标"
python -m code_agent_collab.cli reflect --task "任务关键词"
python -m code_agent_collab.cli pending
python -m code_agent_collab.cli demo "任务目标"
python -m code_agent_collab.cli run "任务目标"
python -m code_agent_collab.cli provider
```

## 命令说明

- `start`：生成任务上下文包。
- `reflect`：根据上下文包生成候选复利记录。
- `pending`：列出等待用户确认的候选记录。
- `demo`：一键跑通基础闭环。
- `run`：执行规则版多 Agent 工作流。
- `provider`：查看当前 AI Provider 配置；默认显示本地模拟 Provider。

切换到 DeepSeek：

```powershell
$env:AGENT_WORKBENCH_PROVIDER="deepseek"
$env:DEEPSEEK_API_KEY="你的密钥"
```

切换到 OpenAI：

```powershell
$env:AGENT_WORKBENCH_PROVIDER="openai"
$env:OPENAI_API_KEY="你的密钥"
```

## 多 Agent 角色

当前版本内置 5 个规则 Agent：

- `CoordinatorAgent`：拆分任务。
- `KnowledgeAgent`：读取项目内知识。
- `PlannerAgent`：生成保守执行计划。
- `ValidatorAgent`：检查上下文包和边界。
- `ReflectorAgent`：确认复盘进入候选区。

## 权限分级

- `L0_READ_ONLY`：只读。
- `L1_DRAFT_WRITE`：写草稿区和日志区。
- `L2_PROJECT_WRITE`：写项目文件。
- `L3_CONFIRM_REQUIRED`：必须用户确认，例如写主知识库、推送、部署。

## 测试

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

## 配置

真实本地配置文件：

```text
.agent-workbench/config.json
```

这个文件被 `.gitignore` 忽略，不应提交到公开仓库。

示例配置：

```text
.agent-workbench/config.example.json
```

## 版本规划

详见：

- `VERSIONING.md`
- `CHANGELOG.md`

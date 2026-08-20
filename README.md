# 多 Agent 代码协作助手

一个本地优先的命令行原型，用来探索：

- 多 Agent 如何围绕同一个项目协作；
- Obsidian 知识库如何参与任务上下文；
- AI 生成的经验如何先进入候选区，再由用户确认；
- 如何避免主知识库被自动污染。

## 当前版本

当前版本：`v0.7.1`（修订版）

阶段定位：主知识库只读检索 + AI 审查入库 + Web 终端。

当前版本已接入 Provider 接口：默认使用本地模拟 Provider；配置 DeepSeek 或 OpenAI 后，PlannerAgent 和 CoderAgent 可以调用真实模型生成计划与代码草稿。KnowledgeAgent 会从主知识库只读检索与任务相关的文档，生成知识补充文件，供后续 Agent 使用；候选知识可经 AI 审查后入库或转人工处理；提供 PowerShell 风格的本地网页终端。关闭网页终端程序会立即停止正在运行的命令，AI 调用不会在后台继续。

## 核心原则

- 主知识库默认只读。
- AI 自动生成内容先进入 `dev-vault`。
- 候选复利记录先进入 `dev-vault/pending`。
- 写入主知识库必须经过用户确认。
- CoordinatorAgent、ValidatorAgent 和 ReflectorAgent 仍是规则版；PlannerAgent 和 CoderAgent 支持通过 Provider 调用模型；KnowledgeAgent 从主知识库只读检索相关文档。

## 项目结构

```text
project 多Agent代码协作助手/
├── src/code_agent_collab/   # 程序源码（agents/ 是 6 个 Agent 角色）
├── tests/                   # 自动化测试
├── product-docs/            # 人写的需求、规则、企划文档
├── dev-vault/               # AI 产出区（候选记录、代码草稿），确认后才能进主知识库
├── logs/                    # 本地运行产物（上下文包、工作流日志）
├── .agent-workbench/        # 本地配置（config.json 不进 Git）
├── 项目规则.md              # 项目规则总览（给人看）
├── 知识地图.md              # 项目知识串联索引
├── 维护指南.md              # 维护指南：目录说明、常见改动、发布流程
├── 技能.md                  # 项目技能与经验
├── README.md / 变更记录.md / 版本管理.md / AGENTS.md
```

给人看的入口：先读 [项目规则.md](项目规则.md) 和 [知识地图.md](知识地图.md)，详细维护说明见 [维护指南.md](维护指南.md)。

## 命令

在项目根目录运行：

```powershell
$env:PYTHONPATH="src"
python -m code_agent_collab.cli start "任务目标"
python -m code_agent_collab.cli reflect --task "任务关键词"
python -m code_agent_collab.cli pending
python -m code_agent_collab.cli review
python -m code_agent_collab.cli confirm "候选关键词"
python -m code_agent_collab.cli discard "候选关键词"
python -m code_agent_collab.cli demo "任务目标"
python -m code_agent_collab.cli run "任务目标"
python -m code_agent_collab.cli provider
python -m code_agent_collab.webui
```

## 命令说明

- `start`：生成任务上下文包。
- `reflect`：根据上下文包生成候选复利记录。
- `pending`：列出等待用户确认的候选记录。
- `review`：AI 审查候选记录；安全的自动写入主知识库，命中敏感信息的标记"待人工处理"。
- `confirm`：人工确认候选记录并写入主知识库（仍会拦截敏感信息）。
- `discard`：废弃候选记录，不写入主知识库。
- `demo`：一键跑通基础闭环。
- `run`：执行规则版多 Agent 工作流。
- `provider`：查看当前 AI Provider 配置和可用 Provider 列表；默认显示本地模拟 Provider。
- `webui`：启动 PowerShell 风格的本机网页终端（默认 http://127.0.0.1:8080），在浏览器里输入命令。

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

模型默认值：

- DeepSeek：`deepseek-chat`（可换成 `deepseek-reasoner`）
- OpenAI：`gpt-5-mini`

需要覆盖默认模型、接口地址或密钥环境变量时（例如接入 OpenAI 兼容服务）：

```powershell
$env:AGENT_WORKBENCH_MODEL="你的模型名"
$env:AGENT_WORKBENCH_BASE_URL="https://你的兼容接口/v1"
$env:AGENT_WORKBENCH_API_KEY_ENV="你的密钥环境变量名"
```

## 多 Agent 角色

当前版本内置 6 个 Agent：

- `CoordinatorAgent`：拆分任务。
- `KnowledgeAgent`：从主知识库只读检索相关文档，生成知识补充文件。
- `PlannerAgent`：生成保守执行计划。
- `CoderAgent`：生成代码草稿，只写入 `dev-vault/projects`，不直接修改正式源码。
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

## 首次使用与知识库配置

1. 安装 Python 3.11 或更高版本，克隆本仓库。
2. 在项目根目录生成配置文件：

```powershell
$env:PYTHONPATH="src"
python -m code_agent_collab.cli init
```

3. 编辑 `.agent-workbench/config.json`（该文件已被 `.gitignore` 忽略，不会提交），把路径换成你自己的：

```json
{
  "projectName": "多Agent代码协作助手",
  "mainVaultPath": "C:\\path\\to\\your-obsidian-vault",
  "devVaultPath": "C:\\path\\to\\this-project\\dev-vault",
  "mainVaultDefaultMode": "readonly",
  "devVaultDefaultMode": "readwrite"
}
```

- `mainVaultPath`：你的主知识库（Obsidian 或其他 Markdown 文件夹），程序只读检索，绝不写入。
- `devVaultPath`：项目内 `dev-vault` 文件夹，AI 生成的草稿和候选经验写在这里。

不想编辑 JSON，也可以直接设置环境变量（优先级高于 `config.json`）：

```powershell
$env:AGENT_WORKBENCH_MAIN_VAULT="C:\path\to\your-obsidian-vault"
```

没有现成知识库也可以运行：KnowledgeAgent 会提示未检索到相关内容，其余功能不受影响。

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

- `版本管理.md`
- `变更记录.md`

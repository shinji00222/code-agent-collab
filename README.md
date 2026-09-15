# 多 Agent 代码协作助手

一个本地优先的命令行原型，用来探索：

- 多 Agent 如何围绕同一个项目协作；
- Obsidian 知识库如何参与任务上下文；
- AI 生成的经验如何先进入候选区，再由用户确认；
- 如何避免主知识库被自动污染。

## 当前版本

当前版本：`v0.14.1`（开发版）

阶段定位：主知识库只读检索 + 人工确认入库 + 草稿评审 + 半动态主控编排 + 本地桌面窗口 + 草稿应用实验能力。

当前版本已接入 Provider 接口：默认使用本地模拟 Provider；配置 DeepSeek 或 OpenAI 后，PlannerAgent、CoderAgent 和 IntegratorAgent 可以调用真实模型生成计划、代码草稿与合并草稿；ReviewerAgent 在 CoderAgent/IntegratorAgent 之后做规则版评审（检查草稿是否存在、AI 草稿正文是否太空、敏感信息、越权），不通过时最多打回 CoderAgent 重写一次，复杂任务会重新经过 IntegratorAgent 合并，再交给 ReviewerAgent 复审；OrchestratorAgent 按任务复杂度从三档预设模板选择执行方案（`run-adaptive` 命令，阶段内并行），简单/中等方案仍是 Coder 后评审，复杂方案默认是 KnowledgeAgent → 实现/测试双 Coder → IntegratorAgent → ReviewerAgent；复杂任务默认把并行 Coder 拆成“实现”和“测试”两类职责，并在 `WorkerSpec.owned_paths` 中记录各自负责路径，执行前会拦截同阶段职责路径重叠的 worker，避免分工模糊时硬并行；阶段内 worker 会写入 `logs/runs/<任务ID>/workers.json` 状态账本，记录每个子 Agent 的执行状态、输出、错误和尝试次数，失败重跑时会跳过同输入下已成功的 worker；执行计划和每个 worker 的运行状态还会写入共享黑板 `logs/blackboards/<任务ID>.json`，记录 Agent 的职责、负责路径、状态、输出路径、阻塞和备注，并由 `/api/progress` 返回；Web 终端进度树支持点击 Agent 节点打开详情面板，查看 blackboard 中的职责、状态、输出、阻塞和备注；运行进度会同时写兼容用的 `logs/progress/current.json`、任务专属的 `logs/progress/<任务ID>.json` 和最近任务指针 `logs/progress/latest.json`；`plans` 可查看已保存方案是待批准还是已执行；Web 终端改为纯黑底终端页，实时轮询 `/api/progress`，用紫色显示已走过和当前节点，用黑灰色显示未到达节点，并显示 Orchestrator、CoderAgent、IntegratorAgent、ReviewerAgent、Fix Loop、Done 的流程进度。Web 终端默认是单 AI 需求讨论模式：直接输入普通内容时先由 OrchestratorAgent 前置讨论员追问和澄清；点击“生成主控方案”后才把讨论内容整理成 `run-adaptive` 方案；点击“开始协同工作”后才批准最近方案并执行 KnowledgeAgent、CoderAgent、IntegratorAgent、ReviewerAgent 等后续 Agent；执行中可点“暂停工作”请求阶段边界暂停并保存断点；页面检测到断点后会启用“继续暂停任务”，继续执行同一任务的下一阶段；经多重确认点“强制停止”可及时中断后台进程，且不会删除 API key，停用或更换 key 仍通过配置脚本处理。KnowledgeAgent 会从主知识库只读检索与任务相关的文档，生成知识补充文件，供后续 Agent 使用；候选知识经 AI 审查后只标记"待人工确认"，由用户 `confirm` 确认后才写入主知识库，命中敏感信息的转人工处理。`apply-draft` 处于实验阶段，可预览 Coder/Integrator 草稿 diff；草稿必须让“修改文件清单”和“建议代码”路径一致，并通过敏感信息、越权、测试方法和冲突标记等评审闸门后，显式 `--apply` 会先在临时隔离副本测试，通过后才写入正式项目、正式测试、失败回滚、通过后本地提交。

本地使用时优先双击桌面的 `多Agent工作台` 快捷方式，或打包后的 `MultiAgentWorkbench.exe`。它会打开原生桌面窗口，不再默认打开浏览器；窗口里已迁入最近主控方案和运行进度面板，旧 Web UI 仍保留，适合作为调试和备用入口。

## 核心原则

- 主知识库默认只读。
- AI 自动生成内容先进入 `dev-vault`。
- 候选复利记录先进入 `dev-vault/pending`。
- 写入主知识库必须经过用户确认。
- CoordinatorAgent、ValidatorAgent 和 ReflectorAgent 仍是规则版；PlannerAgent、CoderAgent 和 IntegratorAgent 支持通过 Provider 调用模型；OrchestratorAgent 按复杂度从预设模板选择执行方案；ReviewerAgent 规则版评审草稿；KnowledgeAgent 从主知识库只读检索相关文档。

## 项目结构

```text
project 多Agent代码协作助手/
├── src/code_agent_collab/   # 程序源码（agents/ 是 9 个 Agent 角色）
├── tests/                   # 自动化测试
├── product-docs/            # 人写的需求、规则、企划文档
├── dev-vault/               # AI 产出区（候选记录、代码草稿），确认后才能进主知识库
├── logs/                    # 本地运行产物（上下文包、进度快照、工作流日志、worker 状态账本、共享黑板）
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
python -m code_agent_collab.cli run-adaptive "任务目标"
python -m code_agent_collab.cli plans
python -m code_agent_collab.cli approve "任务ID或关键词"
python -m code_agent_collab.cli apply-draft "任务ID或关键词" [--apply]
python -m code_agent_collab.cli provider
python -m code_agent_collab.desktop
python -m code_agent_collab.webui
```

## 命令说明

- `start`：生成任务上下文包。
- `reflect`：根据上下文包生成候选复利记录。
- `pending`：列出等待用户确认的候选记录。
- `review`：AI 审查候选记录；审查通过只标记"待人工确认"并记录 AI 建议的写入位置，**不自动写入主知识库**；命中敏感信息的标记"待人工处理"。
- `confirm`：人工确认候选记录并写入主知识库（仍会拦截敏感信息）。
- `discard`：废弃候选记录，不写入主知识库。
- `demo`：一键跑通基础闭环。
- `run`：执行规则版多 Agent 工作流。
- `run-adaptive`：生成半动态自适应方案并等待人工审批（不自动执行）；主控按任务复杂度从三档预设模板选择 worker 方案（SIMPLE=2 / MEDIUM=3 / COMPLEX=5），阶段内并行；复杂任务的并行 Coder 默认带 `owned_paths` 职责边界，路径重叠会被拦截；复杂方案会在双 Coder 后进入 IntegratorAgent 合并，再进入 ReviewerAgent。
- `plans`：列出已保存的主控方案，显示任务、复杂度、worker 数量和状态（待批准/已执行）。
- `approve`：人工批准 `run-adaptive` 生成的方案，批准后执行 workers（阶段间串行、阶段内并行），产出工作流日志与候选复盘。
- `apply-draft`：解析 Coder/Integrator 草稿并预览 diff（dry-run，不写文件）；草稿必须满足“修改文件清单”和“建议代码”路径一致，并通过评审闸门；加 `--apply` 后先复制临时隔离副本并在副本里跑测试，通过后才应用到正式项目 → 正式测试 → 测试通过自动本地 commit（失败自动回滚）。只允许改 `src/`、`tests/` 下文本文件。
- `provider`：查看当前 AI Provider 配置和可用 Provider 列表；默认显示本地模拟 Provider。真实 Provider 调用支持超时、429/5xx/网络临时失败重试和响应结构校验。
- `desktop`：启动本地桌面窗口，提供 Provider 检查、方案列表、生成主控方案、开始协同工作、暂停和强制停止按钮；右侧显示最近主控方案和当前运行进度；后台复用现有 CLI，不打开浏览器。
- `webui`：启动本机网页终端（默认 http://127.0.0.1:8080），在浏览器里输入命令；页面是纯终端风格，并用树状图实时显示当前 Agent 进度。直接输入普通内容时先进入单 AI 需求讨论；点“生成主控方案”才生成方案；点“开始协同工作”才批准并执行后续 Agent；命令会提交为后台 job，页面轮询 job 状态和进度；点“暂停工作”会在阶段边界保存断点并暂停；页面检测到断点后可点“继续暂停任务”从下一阶段恢复；点“强制停止”会经多重确认后立即中断后台进程但不删除 API key。

打包 Windows 下载包：

```powershell
pwsh -File scripts/package-windows.ps1
```

产物在 `dist/AgentWorkbench-v版本号-windows.zip`，里面包含桌面窗口 exe、后台 CLI exe、Provider 配置脚本和 `START_HERE.txt`。

切换到 DeepSeek：

最省事的方式：复制下面这一条命令到 PowerShell，然后用数字菜单选择厂商和动作：

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\lwz12\Desktop\AI工作台知识库\01-项目\project 多Agent代码协作助手\scripts\setup-deepseek.ps1"
```

菜单里可以选：

- `1`：配置 DeepSeek API，按提示回答 `y/n`，最后只在本机终端窗口粘贴 DeepSeek API Key。
- `2`：配置 OpenAI API，按提示回答 `y/n`，最后只在本机终端窗口粘贴 OpenAI API Key。
- `3`：停止真实 API 调用，切回本地 mock；如需删除本机保存的 DeepSeek/OpenAI Key，会分别单独确认。
- `4`：查看当前 Provider 状态。
- `5`：启动 Web UI。
- `6`：退出。

脚本会把 Provider 名和对应 API Key 写入当前 Windows 用户环境变量，不写入仓库文件，也不会把 Key 打印出来。

临时切换方式：

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

当前版本内置 9 个 Agent：

- `CoordinatorAgent`：拆分任务（默认流水线）。
- `KnowledgeAgent`：从主知识库只读检索相关文档，生成知识补充文件。
- `PlannerAgent`：生成保守执行计划。
- `CoderAgent`：生成代码草稿，只写入 `dev-vault/projects`，不直接修改正式源码；支持 `worker_label` 和 `owned_paths` 以多实例并行写独立草稿并声明职责边界；草稿按固定五小节格式输出（修改文件清单/修改原因/建议代码/测试方法/风险），可被 `apply-draft` 解析。
- `IntegratorAgent`：合并多份 Coder 草稿，只写入 `dev-vault/projects/<任务ID>-integrated-draft.md`，不直接修改正式源码；复杂任务中位于双 Coder 和 ReviewerAgent 之间。
- `ReviewerAgent`：规则版评审代码草稿或合并草稿（存在性 / AI 草稿正文长度 / 敏感信息 / 越权 / 固定小节 / 路径范围 / 测试方法 / 冲突标记），优先评审 IntegratorAgent 的合并草稿；不通过时可触发最多一次重写。
- `OrchestratorAgent`：半动态主控，按任务复杂度从三档预设模板选择执行方案（`run-adaptive`）。
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

## 打包为软件（Windows）

把本地桌面窗口打包成双击即用的 Windows 程序：

```powershell
pwsh -File scripts/build-exe.ps1
```

产物在 `dist/`（两个 exe 必须放在同一目录，不要单独删除 CLI）：

- `MultiAgentWorkbench.exe`：桌面窗口程序，双击启动，不打开浏览器
- `AgentWorkbench-CLI.exe`：后台 CLI 程序，由界面程序调用执行命令

注意事项：

- exe 未签名，Windows 首次运行可能提示 SmartScreen，选择"仍要运行"即可；
- onefile 首次启动需要数秒解压到临时目录，属正常现象；
- 打包版会优先回到正式项目根读写 `dev-vault`、`logs` 等运行产物；旧 Web UI 仍可用 `python -m code_agent_collab.webui` 或配置菜单启动。

## 版本规划

详见：

- `版本管理.md`
- `变更记录.md`

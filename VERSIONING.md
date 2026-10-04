# 版本分类规则

## 版本号规则

本项目使用语义化版本：

```text
主版本.次版本.修订版本
```

- 主版本：产品形态或架构发生明显变化，例如从命令行工具升级为可用界面。
- 次版本：新增一个完整功能模块，例如多 Agent 工作流、Obsidian 只读检索、候选审核。
- 修订版本：修 bug、补测试、整理文档，不改变核心功能。

## 当前阶段

当前处于本地优先多 Agent 工作台原型阶段：命令行闭环已具备，本地桌面窗口是默认用户入口；Web 终端保留为备用/调试入口，草稿应用能力仍按实验版管理。

## 版本分类

### v0.1.x：命令行基础闭环

包含：

- 生成上下文包；
- 生成候选复利记录；
- 列出待确认候选；
- 一键 demo 闭环。

### v0.2.x：多 Agent 协作骨架

包含：

- Agent 角色定义；
- Agent 权限分级；
- 多 Agent 顺序交接；
- 工作流日志；
- 候选复利记录仍只进入 dev-vault。

### v0.3.x：Provider 接入实验版（已发布）

包含：

- 统一 AI Provider 接口；
- DeepSeek 与 OpenAI 预设；
- 默认本地 mock Provider，不联网。

### v0.4.x：CoderAgent 草稿生成

计划包含：

- 新增行动 Agent（CoderAgent）；
- 通过 Provider 生成代码草稿；
- 草稿只进入 `dev-vault/projects`；
- 写入正式源码前必须人工确认。

### v0.5.x：主知识库只读检索

计划包含：

- 指定范围读取主知识库；
- 关键词检索相关 Markdown；
- 生成知识补充文件供后续 Agent 使用；
- 保持主知识库只读。

### v0.6.x：候选知识审核

计划包含：

- 候选记录确认；
- 候选记录废弃；
- 冲突检查；
- 同步前脱敏检查。

### v0.7.x：本机 Web 终端

- v0.7.0：Web 终端发布版。
- v0.7.1：版本元数据修订版，不改变功能代码。

### v0.8.x：评审、主控和 Web 终端开发版

- v0.8.0：新增 ReviewerAgent、人工确认闸门、半动态主控编排、阶段内并行和 Windows Web 终端打包。

### v0.9.x：草稿应用实验版

- v0.9.0：新增 `apply-draft` 草稿解析、diff 预览、受限应用、自动测试、失败回滚和测试通过后的本地自动提交。
- v0.9.1：版本元数据修订版，对齐 README、`pyproject.toml` 和版本规划，不改变功能代码。

### v0.10.x：方案管理开发版

- v0.10.0：新增 `plans` 命令和 Web 终端内的可视化 Agent 关系与进度树，列出已保存的主控方案，并区分待批准和已执行状态。
- v0.10.1：修正自适应模板为 CoderAgent 后必接 ReviewerAgent；Web UI 改为纯终端页，并用实时 `/api/progress` 树状图显示紫色当前进度、黑灰色未到达节点和 Fix Loop 返工路径。
- v0.10.2：Web UI 默认只让 OrchestratorAgent 生成方案；新增“开始协同工作”开关，用户确认后才 approve 并执行后续多 Agent。
- v0.10.3：新增 DeepSeek 配置向导，一条命令进入数字菜单，可配置 API、停止 API/切回 mock、查看 Provider 状态和启动 Web UI。
- v0.10.4：配置向导扩展为通用 AI Provider 菜单，支持 DeepSeek/OpenAI 厂商选择和分别停用清理。
- v0.10.5：Web UI 普通输入改为单 AI 对话澄清，新增“生成主控方案”按钮，讨论完成后再生成方案。
- v0.10.6：Web UI 新增软暂停断点、强制停止多重确认，并新增 Windows zip 下载包打包脚本。

### v0.11.x：断点续跑体验开发版

- v0.11.0：Web UI 读取 `logs/control/<任务ID>.checkpoint.json`，检测到暂停断点后启用“继续暂停任务”，并从断点下一阶段恢复执行。

### v0.12.x：WorkerRun 状态账本开发版

- v0.12.0：新增 worker 级状态账本 `logs/runs/<任务ID>/workers.json`，记录阶段内每个子 Agent 的执行状态、输出、错误和尝试次数；并行阶段部分失败时保存当前阶段 checkpoint，重跑时复用同输入下已成功 worker，只补跑失败或缺失 worker。
- v0.12.1：进度快照增加任务级简单隔离，保留 `current.json` 兼容现有 Web UI，同时写入 `logs/progress/<任务ID>.json` 和 `latest.json`，暂不改 UI。
- v0.12.2：新增 `WorkerSpec.owned_paths` 任务边界，复杂任务默认拆成“实现/src/”和“测试/tests/”，并在并行执行前拦截职责路径重叠的 worker。
- v0.12.3：新增共享黑板 `logs/blackboards/<任务ID>.json`，记录 Agent 职责、路径、状态、输出、阻塞和备注，并通过 `/api/progress` 暴露给后续详情 UI。
- v0.12.4：Web 终端进度树支持点击 Agent 节点查看 blackboard 详情，包括状态、负责路径、输出、阻塞和备注。
- v0.12.5：复杂任务新增 IntegratorAgent 合并阶段，双 Coder 产物先合并成 `integrated-draft`，再交给 ReviewerAgent 评审；Fix Loop 重写后会重新合并。
- v0.12.6：修复打包版 Web UI 把 exe 所在目录误当独立项目根的问题；启动时优先使用 `AGENT_WORKBENCH_PROJECT_ROOT`，否则从 exe 目录向上寻找正式项目根，避免树状进度和 blackboard 读不到主项目日志。

### 后续规划：可检查的 Agent 协作 UI

- 已完成共享黑板基础版：每个 Agent 写入自己的职责、认领路径、输出、阻塞和备注，作为 `/api/progress` 的可读详情数据。
- 已完成最小 Agent 详情面板：在 Web 终端进度树里点击某个 Agent，可以看到 blackboard 里的 `owned_paths`、当前状态、输出路径、失败原因、阻塞信息和备注。
- 后续增强：把 WorkerRun attempt 次数、输入 hash、重跑来源和更完整的错误分类整合进详情数据；再考虑多任务选择器。

### v0.13.x：协作可靠性开发版

- v0.13.0：ReviewerAgent 增加草稿结构、路径范围、测试方法和冲突标记检查；真实 Provider 增加超时、重试、错误分类和响应结构校验；Web UI 命令改为后台 job 执行并由前端轮询状态。
- v0.13.1：apply-draft 增加应用前评审闸门，要求“修改文件清单”和“建议代码”路径一致，并拦截敏感信息、越权、笼统测试方法和冲突标记后才允许落盘。
- v0.13.2：apply-draft 正式落盘前先复制临时隔离副本并运行测试，测试失败时正式源码不写入；测试环境剥离常见密钥变量并设置超时。

### v0.14.x：本地桌面软件开发版

- v0.14.0：新增 Tkinter 本地桌面窗口，打包后的 `MultiAgentWorkbench.exe` 默认打开桌面软件而不是浏览器；窗口按钮复用现有 CLI 和正式项目根，Web UI 作为备用入口保留。
- v0.14.1：桌面窗口迁入最近主控方案和当前运行进度面板；桌面根目录旧 exe 移入回收站，只保留指向当前 `dist/MultiAgentWorkbench.exe` 的快捷方式。
- v0.14.2：按用户要求将 `MultiAgentWorkbench.exe` 默认入口切回原 Web UI，确保界面和原网页版一模一样；Tkinter 桌面入口保留为备用。
- v0.14.3：新增 WebView 桌面壳，`MultiAgentWorkbench.exe` 在本地软件窗口内嵌原 Web UI，不再弹出浏览器标签页。
- v0.14.4：修复 WebView 原 Web UI 复杂任务进度树分支顺序和裁切问题。
- v0.14.5：稳定验收版；WebView 启动前确认本机页面可访问，默认端口占用时自动换端口，关闭窗口时清理内置本机服务。

### v0.15.x：MCP 接入与知识写入隔离

- v0.15.0：开发版；新增 MCP 工具接入层（`mcp_bridge`）——自研 stdio 客户端（JSON-RPC 2.0 握手 / 工具发现 / 调用）、多服务端工具注册表、纯文本 Provider 的工具调用循环，以及 `agent-workbench mcp list|call|ask` 三个子命令。**不新增任何第三方依赖**，**不改动既有流水线行为**。尚未对接真实第三方 MCP 服务端。
- v0.15.1：安全修复版；知识写入与真实主知识库隔离——新增 `mainVaultWritePath`（默认项目内 `dev-vault/main-vault-sandbox`），`confirm` 不再直接写主知识库，需要写回时必须显式配置；读取检索行为不变。修复了"重复确认会静默覆盖知识库既有文件"的问题。
- v0.15.2：安全修复版；**读取也隔离**——读取来源与写入目标默认都指向项目自有知识库 `dev-vault/project-vault`，不再推导上层目录作检索源，外部知识库既不读也不写；目录由 `main-vault-sandbox` 更名为 `project-vault`。**行为变更**：默认不再检索外部知识库，需要时须显式配置 `mainVaultPath`。

### 后续主线：Multi-Agent Software Engineering System

定位：不再横向堆更多 Agent、浏览器 Agent、语音或大量 MCP，而是纵向做成更像真正软件工程 Agent 的系统。

主线顺序：

1. **稳定闭环**：`Issue -> 分析 repo -> 定位文件 -> 修改代码 -> 跑测试 -> Review diff -> 自动返工 -> 输出 patch/PR`。
2. **分层上下文**：全局 / repo / module / task / agent memory，按任务选择上下文并控制 token。
3. **Evaluation**：记录 task success rate、tests passed、修改文件数量、retry 次数、token cost、latency、Reviewer 驳回次数，并做 Single Agent vs Multi-Agent 对照。

### v0.16.x：Stable Coding Loop

计划包含：

- v0.16.0：新增 `coding-loop` 最小闭环入口；默认串起 `run_adaptive_workflow` 与 `apply-draft` dry-run，Reviewer 通过后输出 diff；加 `--apply` 才应用、测试、回滚/提交。
- v0.16.1：`coding-loop --apply` 遇到隔离测试或正式测试失败时，将测试反馈交回 Coder，自动再跑一轮闭环；最多重试 1 次，防止死循环。
- v0.17.2：`apply-draft` dry-run 保存批准基线，`--apply` 前核对 Git HEAD、草稿、目标文件和 diff 摘要，防止预览后文件变化仍被应用。
- 修核心闭环 bug；
- Planner / Coder / Reviewer 跑通真实代码修改链路；
- 自动测试与测试失败反馈；
- retry 与 Reviewer 打回返工；
- 防死循环和最大尝试次数；
- 输出可审查的 patch/diff/PR 草稿。

### v0.17.x：Hierarchical Context

计划包含：

- v0.17.0：上下文包新增 context selection 记录和粗略 token 预算；按任务目标关键词选择相关 `product-docs`，先建立可解释的上下文选择基线。
- v0.17.1：上下文包新增代码文件级 context selection；按任务目标选择 `src/**/*.py` 和 `tests/**/*.py`，写入选择理由、token 预算和限长摘录，并把上下文包摘录嵌入 CoderAgent 提示词。
- v0.17.2：`apply-draft` dry-run 保存批准基线，`--apply` 前核对 Git HEAD、草稿、目标文件和 diff 摘要，防止预览后文件变化仍被应用。
- v0.17.3：修订版；同步 README、`pyproject.toml`、变更记录和问题台账里的当前版本与 Git 状态，不改变功能代码。
- v0.17.4：代码简化修订版；删除未使用旧 Web 页面，并把自适应编排的执行状态、断点、失败发布和 Fix Loop 从主函数中拆出。
- v0.17.5：可靠性与代码简化修订版；继续拆分 Web 后端模块，合并草稿评审 helper，补任务 ID 防碰撞、任务日志和 Provider 本地提示词预算。
- v0.17.6：项目结构整理版；统一长期文档英文文件名，更新引用和测试夹具，删除无用旧 worktree checkout。
- v0.17.7：暂停状态修复版；单项目工作台的 CLI 工作命令启动时清理旧 `pause.json`，避免下一次任务被上一次软暂停残留卡住。
- v0.17.8：返工草稿选择修复版；`apply-draft` 优先使用最新 `-revisionN` 返工稿，并剥掉单文件代码围栏，避免应用旧初稿或写入 Markdown fenced code。
- v0.17.9：confirm 防覆盖安全修复版；人工确认候选入库前检查目标文件是否已存在，拒绝覆盖已有知识文件。
- v0.17.10：checkpoint integrator 状态回归版；补测试确认暂停断点会保留 `latest_integrator_specs`，防止恢复后丢失 Integrator 重跑依据。
- v0.17.11：WorkerRun attempts 历史账本版；`workers.json` 新增 `attempts` 历史列表，保留失败/重试过程。
- 全局 / repo / module / task / agent 私有记忆分层；
- 短期 / 长期 memory 区分；
- context selection 策略；
- token 预算记录；
- 对比全量 context 与分级 context 的成功率、token、延迟。

### v0.18.x：Evaluation

计划包含：

- benchmark 任务集；
- Single Agent vs Multi-Agent 对照；
- task success rate、tests passed、修改文件数量、retry 次数、token cost、latency、Reviewer 驳回次数记录；
- 可复盘的运行报告，用于向导师解释"为什么这么设计"。

### v0.19.x：Execution Sandbox Hardening

计划包含：

- 第一层轻隔离加固：命令白名单、固定工作目录、超时、最大输出、测试环境密钥剥离、路径白名单和 Git 脏工作区拦截统一收口；
- 第二层临时副本执行：在隔离工作区应用 patch、运行测试，通过后才把 diff 带回正式仓库，失败时正式源码保持不变；
- 第三层按需评估 WSL / Docker / VM：只用于未知外部仓库、安装依赖、执行第三方脚本或更开放命令，不作为当前主项目的起步方案；
- 增加安全回归用例：超时、输出过大、项目外路径、敏感环境变量、隔离测试失败不污染正式仓库。

原则：沙箱是为了降低真实代码修改和命令执行风险，不是为了堆重型基础设施。当前项目先把轻隔离和临时副本做稳。

### v1.0.0：第一个稳定命令行版本

达到条件：

- 命令行闭环稳定；
- 多 Agent 工作流可审计；
- Obsidian 读取边界清楚；
- 候选审核可用；
- GitHub 上有完整 README、CHANGELOG、版本标签和使用说明。

## GitHub 上传规则

每个次版本或主版本完成后：

- 本地测试必须通过；
- Git 状态必须干净；
- 当前分支必须能明确显示 `main...origin/main` 的 ahead/behind 状态；若 `main` 没有 upstream，先设置为跟踪 `origin/main`，再判断哪些提交只在本机、哪些已经在 GitHub。
- 更新 `CHANGELOG.md`；
- 创建对应 Git tag；
- 推送 main 和 tag 到 GitHub。

## 当前协作状态记录

- 2026-09-13：已把本地 `main` 设置为跟踪 `origin/main`。
- 设置后状态为 `main...origin/main [ahead 3]`，表示本地 `main` 比 GitHub `origin/main` 多 3 个提交；这不是代码错误，但在发布、共享或继续多人协作前必须先决定是否推送、做公开快照，或继续只保留在本地。
- 2026-10-03：`v0.17.4` 已推送到 `origin/main` 并打 tag `v0.17.4`。
- 2026-10-03：`v0.17.6` 已用于本地项目结构整理；本轮未 push、未打 tag、未发 Release、未重新打 Windows 包。继续推进或发布前，先用 `git status --short --branch` 重新确认 ahead 数。
- 2026-10-03：`v0.17.7` 用于 N11 暂停状态修复；这是修复版，当前只做本地 commit，未 push、未打 tag、未发 Release、未重新打 Windows 包。
- 2026-10-03：`v0.17.8` 用于 apply-draft 最新返工草稿选择与 fenced code 清理修复；当前只做本地 commit，未 push、未打 tag、未发 Release、未重新打 Windows 包。
- 2026-10-04：`v0.17.9` 用于 confirm 防覆盖安全修复；当前只做本地 commit，未 push、未打 tag、未发 Release、未重新打 Windows 包。
- 2026-10-04：`v0.17.10` 用于 checkpoint integrator 状态回归验证；当前只做本地 commit，未 push、未打 tag、未发 Release、未重新打 Windows 包。
- 2026-10-04：`v0.17.11` 用于 WorkerRun attempts 历史账本；当前只做本地 commit，未 push、未打 tag、未发 Release、未重新打 Windows 包。
- 不要只看本地版本号判断发布状态；要同时看 `git status --short --branch`、`git rev-parse HEAD` 和 `git ls-remote origin refs/heads/main`。

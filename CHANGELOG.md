# 更新日志

## v0.17.12 - 2026-10-04（打包版 CLI 调用回归修复版）

### 修正：打包版窗口一提交任务就 `NameError`

- `web_jobs.run_cli()` 的 frozen 分支用了 `Path` 和 `CLI_EXE_NAME`，但这两个名字都没有导入，打包版会直接抛 `NameError: name 'Path' is not defined`。
- 影响：打包出来的 Windows 软件，窗口能开、页面能显示，但**任何任务提交都会立刻失败**（界面提示「服务器错误：name 'Path' is not defined」）。
- 回归来源：v0.17.5（`fdd270d`）把 `webui.py` 拆成多个模块时漏掉了这两个导入；已推送基线 `v0.17.6`（`168aa6f`）里同样存在。
- 修复：`web_jobs.py` 补回 `from pathlib import Path`，并从 `web_project` 导入 `CLI_EXE_NAME`。

### 新增测试

- `tests/test_webui.py` 新增两条 `run_cli` 命令构造测试：frozen 模式断言调用同目录 CLI 可执行程序，源码模式断言调用 `-m code_agent_collab.cli`；用替身进程避免真的拉起子进程。
- 已实测「测试能抓到 bug」：临时回退修复后，新测试报 `NameError: name 'Path' is not defined`；恢复修复后通过。

### 新增维护脚本

- 新增 `scripts/check-undefined-names.py`：用 `symtable` 按作用域扫描「引用了但没定义、也没导入」的全局名字，`python scripts/check-undefined-names.py src tests`，退出码 1 表示有命中。
- 加它的原因：这类拆分残留 `py_compile` 和 unittest 都抓不到，只有走到那一行才炸。当前 `src` + `tests` 共 71 个文件扫描干净。

### 边界

- 本次只修命令构造，不改变打包流程和命令白名单。
- `dist/` 里的 EXE 是 2026-09-16 打的旧包，**早于本次回归**，所以手头旧包仍可用；但下一次重新打 Windows 包之前必须先包含本修复。
- 本轮未 push、未打 tag、未发 GitHub Release、未重新打 Windows 包。

### 测试

- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → **225 项 OK**（原 223 + 新增 2）。


## v0.17.11 - 2026-10-04（WorkerRun attempts 历史账本版）

### 修正：WorkerRun 保留每次运行尝试

- `workers.json` 仍保留顶层最新状态，同时新增 `attempts` 历史列表，记录每次 running / failed / success / skipped 状态。
- 旧 `workers.json` 没有 `attempts` 时，加载时会用顶层记录自动补一条历史，保持兼容。
- N12 由“只保留最新状态”推进为已修复：失败后重试不会抹掉前一次失败原因。
- 新增 `HANDOFF_DSH.md`，用于上下文不足时让 DSH 接手。

### 边界

- 这是可靠性修复版，不改变跳过成功 worker 的判定逻辑；`should_skip_worker()` 仍看顶层最新状态与 input hash。
- 本轮未 push、未打 tag、未发 GitHub Release、未重新打 Windows 包。

### 测试

- 针对性测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; $env:PYTHONPATH='src'; python -m unittest tests.test_adaptive_workflow` → 14 项 OK。
- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 223 项 OK。


## v0.17.10 - 2026-10-04（checkpoint integrator 状态回归版）

### 验证：checkpoint 保留 Integrator 返工状态

- 新增回归测试，直接验证 `_save_execution_checkpoint()` / `_load_execution_state()` 会 round-trip `latest_integrator_specs`。
- N4 由“怀疑漏字段”校准为已修复并有测试钉住；后续恢复断点时不会因为字段丢失而跳过 Integrator 重跑依据。

### 边界

- 这是可靠性验证版，主要补测试与台账，不改变当前 checkpoint 数据格式。
- 本轮未 push、未打 tag、未发 GitHub Release、未重新打 Windows 包。

### 测试

- 针对性测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; $env:PYTHONPATH='src'; python -m unittest tests.test_adaptive_workflow` → 14 项 OK。
- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 223 项 OK。


## v0.17.9 - 2026-10-04（confirm 防覆盖安全修复版）

### 修正：人工确认入库拒绝覆盖已有文件

- `confirm_pending_note()` 在写入知识库前会检查目标文件是否已存在；已存在时标记为“待人工处理”，并提示“拒绝覆盖”。
- `_write_to_vault()` 增加兜底 `FileExistsError`，防止未来调用方绕过确认流程直接覆盖文件。
- 同步修正 README / 中文 README / 包版本号。

### 边界

- 这是安全修复版，只改变候选知识入库的写入保护，不改变 AI 审查、敏感扫描、默认写入沙箱和真实主知识库隔离策略。
- 本轮未 push、未打 tag、未发 GitHub Release、未重新打 Windows 包。

### 测试

- 针对性测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; $env:PYTHONPATH='src'; python -m unittest tests.test_review` → 13 项 OK。


## v0.17.8 - 2026-10-03（返工草稿选择修复版）

### 修正：apply-draft 优先选择最新返工草稿

- `find_draft_path()` 选择 Coder 草稿时，会按修改时间和 `-revisionN` 后缀排序，优先返回 Reviewer 打回后的最新版草稿。`parse_draft()` 会剥掉单文件内容外层的 Markdown 代码围栏，避免把 ```python / ``` 写进正式源码。
- 保留 integrated draft 优先级：复杂任务仍先应用 Integrator 合并草稿，再回退到 Coder 草稿。
- `logs/approvals/` 加入 `.gitignore`，批准基线运行产物不再污染工作区。

### 边界

- 本轮未 push、未打 tag、未发 GitHub Release、未重新打 Windows 包。

### 测试

- 针对性测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; $env:PYTHONPATH='src'; python -m unittest tests.test_apply tests.test_cli_pause` → 25 项 OK。
- 真实 API 任务 dry-run 复验：`apply-draft 20261003-230013-010830-真实-API-冒烟测试：只生成一个最小-Pyth` 成功选择 `coder-draft-revision1`，输出干净 diff，且未写入 `src/answer_smoke.py` / `tests/test_answer_smoke.py`。


## v0.17.7 - 2026-10-03（暂停状态修复版）

### 修正：单项目工作台清理旧暂停请求

- CLI 的工作命令 `run`、`run-adaptive`、`approve`、`coding-loop` 启动时会先清理上一轮遗留的 `logs/control/pause.json`。
- N11 的问题口径改为单项目内的旧暂停状态残留：当前工作台一次只处理一个项目，不按多项目隔离设计暂停文件。
- 同步修正包内 `__version__`，避免包版本仍显示旧的 `0.17.2`。

### 边界

- 暂停信号仍是项目级软暂停；当前运行中的任务仍可通过 Web/Desktop 写入 `pause.json`，工作流会在阶段边界保存 checkpoint 后暂停。
- 本轮未 push、未打 tag、未发 GitHub Release、未重新打 Windows 包。

### 测试

- 针对性测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; $env:PYTHONPATH='src'; python -m unittest tests.test_cli_pause` → 4 项 OK。`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 219 项 OK。


## 未发布 - 2026-10-03（文档整理）

### 整理：英文文件名与早期草案合并

- 将项目内主要 Markdown 文件名统一改为英文：`VERSIONING.md`、`CHANGELOG.md`、`SKILLS.md`、`MAINTENANCE.md`、`PROJECT_RULES.md`、`RESEARCH_ROADMAP.md`。
- 将 `product-docs` 中仍保留的当前规划改为英文文件名：`project-plan.md`、`code-simplification-plan.md`。
- 删除早期 MVP、CLI、数据格式、上下文包、知识库隔离、自生长和 Agent 协作协议草案文件；有效结论已合并进 `MAINTENANCE.md`、`SKILLS.md` 和 `product-docs/project-plan.md`。
- 删除当前规则里的“文档文件名用中文”要求；后续 Markdown 文件名统一用英文，正文可继续中文。

### 验证

- 文档整理，无功能代码改动；检查旧中文文件名活动引用和已删除草案链接。

## v0.17.6 - 2026-10-03（项目结构整理版）

### 整理：统一项目文档入口和文件名

- 根目录长期文档统一为英文文件名：`CHANGELOG.md`、`VERSIONING.md`、`MAINTENANCE.md`、`PROJECT_RULES.md`、`SKILLS.md`、`RESEARCH_ROADMAP.md`、`KNOWLEDGE_MAP.md`。
- `product-docs/` 下的长期 Markdown 也统一为英文文件名，正文继续保留中文。
- README、维护指南、项目规则、知识地图和测试夹具同步改用新文件名，减少 GitHub 链接、PowerShell 和跨平台脚本里的中文路径成本。
- 删除旧 Git worktree checkout：`project 多Agent代码协作助手.worktrees/model-inquiry`。该 worktree 干净、无未提交/未跟踪文件；删除只移除了旧 checkout，未删除主仓库分支和 tag。

### 边界

- 本轮不改运行逻辑，不做真实 Provider/API 测试。
- 本轮未 push、未打 tag、未发 GitHub Release、未重新打 Windows 包。

### 测试

- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 215 项 OK。

## v0.17.5 - 2026-10-03（可靠性与代码简化修订版）

### 修正：继续解决本地可验证的结构和可靠性问题

- 将 Web UI 后端拆成 `web_project.py`、`web_discussion.py`、`web_jobs.py`、`web_progress.py`；`webui.py` 只保留 HTTP 路由和启动入口，行数降到 166 行。
- 新增 `draft_review.py`，把 apply 闸门和 Reviewer 共用的草稿正文提取、主知识库越权判断、测试方法判断、冲突标记判断收口到同一处。
- 任务 ID 增加微秒，避免同一秒连续创建任务时覆盖上下文包、计划和日志。
- 新增 `task_log.py`，按既有 `logs/tasks/<任务ID>.md` 规范写入计划等待、执行中、暂停、失败和完成状态快照。
- Provider 增加本地提示词长度预算 `AGENT_WORKBENCH_MAX_PROMPT_CHARS`，超过预算会在发起网络请求前停止。
- 自适应编排最终成功判定改为读取 Reviewer 的 `last_verdict` 状态，不再靠 summary 文案里是否包含“需修改”。

### 边界

- 本轮没有做真实 API 接入测试；真实 Provider 小任务验证留给用户执行。
- 本轮没有创建 GitHub Release、没有重新打 Windows 包。

### 测试

- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 214 项 OK。

## 未发布 - 2026-10-03（规划记录）

### 规划：执行沙箱分层路线

- 将沙箱规划加入 `product-docs/code-simplification-plan.md`：明确先做轻隔离和临时副本执行，重型 WSL / Docker / VM 只在未知外部仓库、安装依赖或开放命令时评估。
- 在 `VERSIONING.md` 增加 `v0.19.x Execution Sandbox Hardening`，把命令白名单、固定工作目录、超时、输出上限、密钥剥离、路径白名单和隔离测试失败不污染正式仓库列为后续目标。
- 在 `RESEARCH_ROADMAP.md` 和 `SKILLS.md` 同步记录“执行安全与沙箱”主线，避免后续把沙箱误做成一开始就很重的基础设施项目。

### 验证

- 文档规划更新，无功能代码改动。

## v0.17.4 - 2026-10-03（代码简化修订版）

### 修正：清理 Web UI 旧页面与拆分编排主函数

- 删除 `webui.py` 中未使用的 `_LEGACY_PAGE` 旧页面，当前页面仍由 `webui_page.py` 提供。
- `webui.py` 从 1724 行降到 744 行，避免后续改 UI 时误改旧页面。
- 从 `execute_adaptive_plan` 中提取执行状态加载、checkpoint 保存、失败发布和 Reviewer Fix Loop。
- `execute_adaptive_plan` 从约 298 行降到 189 行，Fix Loop 策略不变。

### 测试

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_webui tests.test_adaptive_workflow tests.test_coding_loop` → 37 项 OK。
- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 212 项 OK。

## v0.17.3 - 2026-10-03（修订版）

### 修正：版本与当前状态对齐

- 将 `pyproject.toml`、README 和中文 README 的当前版本同步为 `v0.17.3`。
- 更新问题台账的当前基线：远端 `origin/main` 为 `9917d77 Refresh GitHub README overview`，本地 `main` 已领先远端，不再沿用 `bdc6de3 未 push` 的旧状态。
- 明确本版本不改变功能代码；`v0.17.2` 的 apply-draft 批准基线校验仍是最近一次功能改动。
- 新增 `product-docs/code-simplification-plan.md`，记录当前代码冗余点、优化顺序、验证命令和不做事项；README、知识地图、技能文档同步增加入口。

### 测试

- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 212 项 OK。

## v0.17.2 - 2026-09-27（Stable Coding Loop 开发版）

### 新增：apply-draft 批准基线校验

- `apply-draft` dry-run 预览 diff 时，会在 `logs/approvals/<草稿名>.json` 保存批准基线。
- 批准基线包含 Git HEAD、草稿文件 sha256、目标文件 sha256 和 diff 摘要。
- `apply-draft --apply` 会先核对批准基线；如果缺少 dry-run 记录，或 dry-run 后 Git HEAD / 草稿 / 目标文件 / diff 发生变化，会拒绝应用并提示重新预览。
- `coding-loop --apply` 是单命令显式闭环，继续直接复用 apply 的安全闸门、隔离测试、正式测试和回滚提交，不要求单独批准文件。

### 测试

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_apply tests.test_coding_loop` → 23 项 OK。
- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 212 项 OK。

## v0.17.1 - 2026-09-27（Hierarchical Context 开发版）

### 新增：代码文件级上下文选择

- `start` / `create_context_pack` 生成上下文包时，会扫描 `src/**/*.py` 和 `tests/**/*.py`，按任务目标关键词选择相关代码文件。
- 上下文包新增“相关代码文件”和“代码文件摘录”，每个文件写入选择理由、粗略 token 预算和限长摘录。
- 代码文件选择有明确上限：最多 8 个 Python 文件；单文件摘录 900 字符；超过 80KB 的代码文件跳过，避免把上下文包撑爆。
- CoderAgent 调用真实 Provider 时，不再只发送本机上下文包路径，会把上下文包内容摘录一起嵌入提示词，让远程模型真正看见已选文档与代码上下文。
- 这是 P0 的第一版修复：已覆盖项目文档 + 代码文件 + Coder 提示词传递；仍是关键词选择，不是向量检索或完整语义理解。

### 测试

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_context_pack tests.test_coder tests.test_coding_loop` → 9 项 OK。
- 相关回归：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_workflow tests.test_adaptive_workflow tests.test_providers tests.test_context_pack tests.test_coder` → 33 项 OK。
- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 210 项 OK。
- CLI 冒烟：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m code_agent_collab.cli start "修改 context_pack 并补测试"` → 生成的上下文包包含 `[code]` 选择记录、相关代码文件和代码文件摘录。

## v0.17.0 - 2026-09-27（Hierarchical Context 开发版）

### 新增：上下文选择记录与 token 预算

- `start` / `create_context_pack` 生成上下文包时，不再只列出项目文档，而是按任务目标关键词选择相关 `product-docs` 文档。
- 上下文包新增“上下文选择记录”，写清 task / repo / project-doc 三层来源、选择理由和粗略 token 估算。
- 上下文包新增“Token 预算估算”，记录已选上下文总量、单篇文档摘录上限和文档数量上限。
- 这是 v0.17 Hierarchical Context 的第一步：先让系统能解释“选了哪些上下文、为什么选”，暂不引入向量库或复杂记忆系统。

### 测试

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_context_pack tests.test_workflow tests.test_adaptive_workflow` → 19 项 OK。
- 全量测试：`$env:AGENT_WORKBENCH_PROVIDER='mock'; python scripts/run-tests.py` → 207 项 OK。

## v0.16.1 - 2026-09-27（Stable Coding Loop 开发版）

### 新增：apply 测试失败反馈与一次自动返工

- `coding-loop --apply` 在 `apply-draft` 的隔离测试或正式测试失败时，会把失败阶段和测试输出追加到新任务目标中，重新运行一轮 `run_adaptive_workflow`。
- 自动返工最多 1 次，避免真实 Provider 输出不稳定时陷入无限循环。
- CLI 输出新增“尝试次数”，方便判断是否发生过自动返工。

### 测试

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_coding_loop` → 4 项 OK。

## v0.16.0 - 2026-09-20（Stable Coding Loop 开发版）

### 新增：v0.16 Stable Coding Loop 最小入口

- 新增 `coding-loop` CLI：一条命令串起 `run_adaptive_workflow` 和 `apply-draft`，形成 `计划 -> 代码草稿 -> Reviewer 评审 -> diff 预览/应用` 的最小闭环。
- 默认行为是 dry-run，只输出 diff，不写正式文件；传 `--apply` 才复用 `apply-draft` 的前置干净工作区检查、隔离测试、正式测试、失败回滚和本地提交。
- Reviewer 未通过或没有通过结论时，`coding-loop` 会停在应用前，不会把草稿交给 `apply-draft`。
- 新增 `tests/test_coding_loop.py`，覆盖 dry-run 不写文件、`--apply` 测试并提交、Reviewer 失败时停止。
- README 顶部新增英文项目名、英文概览和英文 Quick Start，避免 GitHub 介绍只面向中文读者。

### 规划：收束为 Multi-Agent Software Engineering System

- 项目最终定位改为 **Multi-Agent Software Engineering System**：一个能够理解代码库、规划任务、修改代码、运行测试、审查结果，并利用分层知识与多 Agent 协作完成软件工程任务的系统。
- 后续不再横向堆更多 Agent、浏览器 Agent、语音或大量 MCP；近期只做三条主线：稳定闭环、分层上下文、Evaluation。
- 版本路线顺延为：
  - `v0.16.x`：Stable Coding Loop，打通 `Issue -> 分析 repo -> 定位文件 -> 修改代码 -> 跑测试 -> Review diff -> 自动返工 -> 输出 patch/PR`。
  - `v0.17.x`：Hierarchical Context，做全局 / repo / module / task / agent memory 和 context selection。
  - `v0.18.x`：Evaluation，做 benchmark 和 Single Agent vs Multi-Agent 对照，记录成功率、token、latency、测试通过率和 Reviewer 驳回次数。
- 同步更新 `RESEARCH_ROADMAP.md`、`VERSIONING.md`、`README.md` 和 `SKILLS.md`，确保新聊天能按这条主线续接。

## v0.15.3 - 2026-09-18（安全修复版）

### 修复：分工契约与冲突不再静默通过

背景：本项目采用「Coder 之间不通信」，因此 `WorkerSpec.owned_paths` 是唯一的分工表达。但它此前只写在提示词里，产物侧没有任何强制；而两份草稿撞同一文件时，落盘只会保留最后一份，**前面那份静默消失**——如果被丢掉的改动没被测到，测试照样全绿，然后自动提交。

- **重复路径直接判不合法**：`parse_draft()` 检测「建议代码」中同一路径出现多次即报错。落盘是"整份文件替换"，两个完整版本不可能同时生效，顺序只能决定谁输，必须由人显式决定。
- **分工契约真正参与校验**：新增 `orchestration.build_worker(..., coder_contracts=...)`，把「worker 标签 → 负责路径」传给 `ReviewerAgent(contracts=...)`；`_review_ownership()` 逐条比对草稿路径与负责路径。单 Coder 档（`owned_paths=()`）语义为"不限制"；合并草稿按所有 worker 范围的并集校验。
- **修掉一处遮蔽漏洞**：`ReviewerAgent._find_drafts()` 在合并草稿存在时只返回合并草稿，导致单份 Coder 草稿的契约校验在真实 COMPLEX 流程里跑不到。新增 `_review_coder_drafts_contracts()` 单独校验每份 Coder 草稿（每 worker 取最新版）。
- **兜底合并说明不再被放行**：Integrator 合并失败时生成的"兜底说明"结构合法，此前能通过评审、甚至可被 apply。现用 `apply.FALLBACK_MARKER` 标记，Reviewer 与 apply 评审闸门都拒绝，使其进入 Fix Loop 重新合并；兜底文本里同时附上 Provider 输出的解析问题。
- **提交范围收窄**：`git_commit(paths=[...])` 只暂存本次批准清单内的文件，避免把 apply 期间产生的其它改动卷进自动提交（不传 `paths` 时保留旧的 `git add -A` 行为）。
- Integrator 提示词补上 4 条合并硬规则：同一路径只能一个块、多份草稿改同一文件要真合并、冲突写进风险、修改文件清单与代码块一一对应。

### 测试

- 全量测试：`python scripts/run-tests.py` → **202 项 OK**（原 192 + 新增 10）。
- 新增覆盖：`parse_draft` 拒绝重复路径；「实现」worker 写 `tests/` 判越界；合并草稿按并集校验；无契约时不误报；占位符路径不误判越界；合并草稿存在时单份 Coder 草稿仍被校验；兜底草稿被判需修改；apply 闸门拒绝兜底草稿；自动提交只暂存批准清单。
- 演示脚本 `work/demo-step1-conflict-guard.py` 三段全过：重复路径在解析阶段失败且不写文件；越界路径被判越界；COMPLEX 端到端自愈（第一次合并异常 → 评审拦住 → Fix Loop 重新合并 → 复审通过，Integrator 调用 2 次）。

### 行为变更（可能更"严"）

- 草稿里同一路径出现多块、或路径越出自己负责范围，**现在会被判"需修改"并打回**，以前会静默通过。
- Integrator 的兜底合并说明**不再能通过评审**，会触发一次重新合并；真实模型连续两次合不出合法草稿时，任务会停下交人工处理（这是刻意的：不要让人误把兜底说明当成实现）。

### 已知限制

- 打回时仍然会重跑 **Coder + Integrator**（Fix Loop 现有结构），而不是只重跑 Integrator。对"合并结构问题"来说多跑了一次 Coder，属于浪费但不影响正确性；后续可按问题类型区分重跑范围。
- `git_commit` 收窄了暂存范围，但"dry-run 批准的内容"与"`--apply` 时实际写入的内容"之间仍没有基线校验（两次是独立命令）。已在 CLI 里打印实际 diff，但未做摘要比对。
- 未做补丁模型（patch/diff 应用）：两份完整文件内容仍无法在同一路径共存，需要人工或重新合并来消解，这是当前契约的固有边界。

## v0.15.2 - 2026-09-18（安全修复版）

### 修复：读取也隔离，知识库读写全部收进项目内

- **背景**：v0.15.1 只隔离了写入，读取仍然指向外部知识库。而且读取目标的默认值是从项目位置**推导上层目录**（`01-项目` 的父级），等于自动把一整个外部知识库当检索源；配置缺失或路径变动时权限过宽。
- **修复**：
  - `config.py` 新增 `default_vault_path()`，返回 `<项目>/dev-vault/project-vault`；`default_config()` 把它**同时**用作 `main_vault_path`（读）与 `main_vault_write_path`（写），不再推导上层目录。
  - `load_config()` 对两个方向都采用「缺键即回退项目自有知识库」，任何一边都不会因为配置缺失而读写外部知识库。
  - 目录更名：`dev-vault/main-vault-sandbox` → **`dev-vault/project-vault`**。理由是它现在承担「项目知识库（读也读它）」的角色，旧名「sandbox」暗示可随手删除，属于会误导后人的命名。
  - `.gitignore` 同步改为 `dev-vault/project-vault/**/*.md`（更名时必须一起改，否则新路径不再匹配旧规则，被忽略的笔记会被 `git add` 收进版本库）。
  - `context_pack.py` 的上下文包输出由「主知识库只读范围 / 主知识库默认禁止自动写入」改为「知识检索来源 / 知识写入目标 / 项目自有知识库以外禁止写入」。
- **代价（明确声明）**：项目自有知识库默认是空的，所以 KnowledgeAgent 检索一开始什么都搜不到。这是隔离的预期结果，不是故障；要它有用，把要参考的笔记复制进 `project-vault`，或显式配置 `mainVaultPath`。

### 行为变更（破坏兼容性说明）

- **默认不再读取外部知识库**。升级后如果发现「检索不到以前能搜到的内容」，这是设计如此：请在 `.agent-workbench/config.json` 里把 `mainVaultPath` 指回你的知识库。
- 目录名从 `main-vault-sandbox` 变为 `project-vault`；如果有脚本或快捷方式引用了旧路径，需要同步更新。

### 测试

- 全量测试：`python scripts/run-tests.py` → **192 项 OK**（原 184 + 新增 8 项）。
- `tests/test_config.py`：新增/改写 4 项 —— 默认读写都落项目自有知识库且不等于上层目录、配置缺 `mainVaultPath` 时也回退项目知识库、缺 `mainVaultWritePath` 时不写配置里的外部库、两个方向的环境变量覆盖。
- `tests/test_review.py`：确认在缺 `mainVaultWritePath` 时写入落在 `dev-vault/project-vault`，配置的读取库零写入。
- `tests/test_context_pack.py`：断言上下文包写清「知识检索来源 / 知识写入目标」，且默认指向项目自有知识库。
- `tests/test_reviewer.py`：原「引用主知识库路径即判越权」用例改为两项显式契约 —— 显式接入**外部**知识库时引用它仍判越权（原有保护还在）；默认隔离下引用**项目内**知识库不判越权（不误报）。
- 真机验证：`review --task 全隔离演练` → `confirm 全隔离演练` 后
  - 写入落在 `dev-vault/project-vault/04-知识/02-Codex知识/04-复盘/`；
  - 外部知识库 md 清单（12307 个，排除项目目录）**前后完全一致，零变化**；
  - 读取来源解析为项目自有知识库，检索结果**全部落在项目目录内**；对照脚本显示若检索外部知识库会命中 20 个文件，说明隔离确实生效而不是"什么都没配"。

### 已知限制

- 全隔离后，`apply.py` / `reviewer.py` 的「草稿引用主知识库路径即判越权」检查在**默认隔离下不生效**（配置里的知识库已在项目内，任何引用都同时包含项目路径）。它只在显式接入外部知识库时才起作用，这一点已写成两项测试钉住。实际风险有限：`apply-draft` 白名单本来就只允许 `src/`、`tests/`。后续可考虑改为显式登记「受保护路径」。
- 项目自有知识库位于真实知识库目录树之内（因为项目文件夹本身就在知识库里面），这是磁盘结构决定的；要保证的是程序不去扫描外部知识库，而不是让路径不嵌套。
- 写入侧「重复确认覆盖」依然存在，只是被限制在项目知识库内；写入前拦重复仍需在 `_write_to_vault()` 加存在性检查（未做）。
- `MAINTENANCE.md` 仍是旧描述（「主知识库只读范围」），属文档层过期，本次未改 `product-docs/`。

## v0.15.1 - 2026-09-18（安全修复版）

### 修复：知识写入与真实知识库隔离

- **问题**：`confirm`（人工确认入库）之前直接把文件写进 `mainVaultPath`，也就是真实主知识库；目标文件名沿用候选文件名，写入前没有存在性检查。对同一条候选重复确认、或确认后又在知识库里手工补充过内容，都会**静默覆盖**已有文件。
- **修复**：把「读取」和「写入」拆成两个目标。
  - 新增配置 `mainVaultWritePath`（环境变量 `AGENT_WORKBENCH_MAIN_VAULT_WRITE`）。
  - 默认值是项目内 `dev-vault/main-vault-sandbox`，目录说明见 `dev-vault/main-vault-sandbox/README.md`。
  - `review` / `confirm` 的写入目标全部改走写入路径；`KnowledgeAgent` 的只读检索仍读真实主知识库，功能不变。
  - 旧配置文件没有这个键时，安全默认仍是沙箱，不会退化成直接写真实主知识库。
  - 需要写回真实主知识库时，必须显式配置 `mainVaultWritePath` 或对应环境变量。
- 沙箱里真正写入的笔记被 `.gitignore` 忽略（只保留 `README.md` 和各级 `.gitkeep`），不污染 `git status`。
- `cli.py` 的 `confirm` 输出提示由「主知识库文件」改为「写入文件」，避免误导。

### 测试

- 新增 `tests/test_config.py` 3 项：默认写入沙箱、旧配置缺键仍走沙箱、写入路径环境变量覆盖。
- 新增 `tests/test_review.py` 3 项：写入沙箱且真实库零改动、旧配置确认后仍落沙箱、环境变量重定向写入。
- 全量测试：`python scripts/run-tests.py` → **190 项 OK**（原 184 项 + 新增 6 项）。
- 真实验证：在本项目上跑 `review --task 隔离演练` → `confirm 隔离演练`，写入落到 `dev-vault/main-vault-sandbox/04-知识/02-Codex知识/04-复盘/`；真实主知识库前后 md 文件清单（12307 个，排除项目目录）**完全一致，零变化**。

### 已知限制

- 隔离只覆盖「写入目标」，没做「读取隔离」：`KnowledgeAgent` 仍只读检索真实主知识库（只读、不写、排除 `01-项目`/`work`/`99-附件` 等目录）。需要连读取也隔离时，把 `mainVaultPath` 也指向沙箱即可。
- 沙箱内重复确认仍会覆盖沙箱内的同名文件，但只影响可随时删除的演练产物，不再触及真实知识库。
- 配置里的 `mainVaultDefaultMode` / `devVaultDefaultMode` 仍是声明性字段，运行时不参与强制校验；真正的只读保障来自「只有一个写入调用点」。

## v0.15.0 - 2026-09-16（开发版）

### 新增：MCP 工具接入

- 新增 `src/code_agent_collab/mcp_bridge/`：自研 MCP stdio 客户端（`client.py`）、多服务端工具注册表（`registry.py`）、工具调用循环（`loop.py`）。
  - 客户端按 MCP 2025-06-18 实现：`initialize` 握手 → `notifications/initialized` → `tools/list`（支持 cursor 分页）→ `tools/call`；独立读线程按 id 派发响应，并主动回应服务端的反向请求；stderr 单独排空，避免管道写满死锁。
  - 注册表把多个服务端的工具聚合成 `服务端名.工具名` 限定名；单个服务端启动失败只记录错误，不影响其余服务端。
  - 工具循环不依赖厂商 function calling：模型输出带 `tool-call` 标签的 JSON 代码块即视为调用请求，宿主执行后把观测回灌，最多 N 轮；工具输出一律当作外部数据（防提示注入），每次调用都留审计记录。
- 新增 CLI 子命令：`agent-workbench mcp list` / `mcp call <工具> --args-json '{...}'` / `mcp ask "<问题>"`。
- 配置：`.agent-workbench/config.json` 的 `mcpServers` 字段，或环境变量 `AGENT_WORKBENCH_MCP_SERVERS`（环境变量优先）。
- **不新增任何第三方依赖**（仍然只依赖标准库 + pywebview），**未改动既有流水线与 Agent 行为**。

### 测试

- 新增 `tests/fixtures/fake_mcp_server.py`（纯标准库假 MCP 服务端，可模拟分页、坏游标、stderr 洪泛、非 JSON stdout、缺 tools 能力、响应延迟、服务端反向请求等场景）。
- 新增 `tests/test_mcp_client.py`(15) / `test_mcp_registry.py`(16) / `test_mcp_loop.py`(16) / `test_mcp_cli.py`(10)。
- 新增 `scripts/run-tests.py`：跨环境测试入口，规避受限 Windows 沙箱下 `tempfile` 用 0o700 建目录被拒的问题，并强制测试使用 mock Provider。

### 验证

- 全量测试：`python scripts/run-tests.py` → **184 项 OK**（基线 127 项 + 新增 57 项），既有功能无回归。
- 端到端：`mcp list` 列出 4 个工具；`mcp call demo.echo --args-json '{"text":"中文测试 你好"}'` 正确回显中文；`mcp ask` 在 mock Provider 下完成一轮问答。

### 整理

- 公开仓库去除本机用户名与绝对路径：`README.md`、`SKILLS.md`、`MAINTENANCE.md` 改用 `$env:USERPROFILE` 或 `<你的用户名>` 占位；`desktop.py` / `webui.py` 的兜底项目根改用 `Path.home()` 拼装，本机解析结果不变。
- `MAINTENANCE.md` 修正 `review` 的描述：只标记"待人工确认"，不自动写入主知识库。

### 已知限制

- 尚未对接真实第三方 MCP 服务端（只用测试用假服务端验证过协议行为）。
- 只实现 stdio 传输；Streamable HTTP 传输未实现。
- 工具循环是文本协议而非原生 function calling；模型需要遵循 `tool-call` 代码块约定。

## v0.14.5 - 2026-09-16（稳定验收版）

### 改进

- WebView 本地软件窗口启动时会先确认内置 Web UI 已可访问，再加载窗口，降低白屏或过早加载失败的概率。
- 默认端口 `8765` 被占用时自动跳过并使用后续可用本机端口，避免因为旧进程或端口占用导致启动失败。
- 关闭窗口时统一关闭本机服务并等待服务线程退出，减少后台残留。
- 同步 `pyproject.toml` 版本到 `0.14.5`。

### 验证

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_webview_app tests.test_webui` 24 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 127 项 OK。
- 打包验证：`pwsh -File scripts/package-windows.ps1` 生成 `dist/AgentWorkbench-v0.14.5-windows.zip`；`dist/MultiAgentWorkbench.exe --port 8877` 启动后首页返回 200，包含 `/api/jobs`、`pollJob`、`IntegratorAgent` 和进度树角色归一化代码；关闭窗口后端口释放。

## v0.14.4 - 2026-09-15（开发版）

### 修复

- 修复 WebView 原 Web UI 进度树显示不完整的问题：`CoderAgent(实现/测试)` 这类带标签的 `role` 现在会归一化为 `CoderAgent`，能正确挂到 `KnowledgeAgent` 下方。
- 增加复杂任务树的底部留白和子分支高度，避免分支被后续节点或底部输入栏挤压，看起来像树断掉。
- 同步 `pyproject.toml` 版本到 `0.14.4`。

### 验证

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_webui tests.test_webview_app` 23 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 126 项 OK。
- 打包验证：`pwsh -File scripts/package-windows.ps1` 生成 `dist/AgentWorkbench-v0.14.4-windows.zip`；WebView 首页返回 200，并包含角色归一化、树分支高度和底部留白修复。

## v0.14.3 - 2026-09-15（开发版）

### 改进

- 新增 WebView 桌面壳：`MultiAgentWorkbench.exe` 启动本机服务后，在本地软件窗口内嵌原 Web UI，不再弹出系统浏览器标签页。
- 打包入口改为 `scripts/launcher_webview.py`，保留原 Web UI 的 HTML/CSS/JS 视觉和交互。
- 新增 `pywebview` 依赖，并在 PyInstaller 打包脚本中收集 WebView 运行所需模块。
- 同步 `pyproject.toml` 版本到 `0.14.3`。

### 验证

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_webview_app tests.test_setup_scripts tests.test_webui` 25 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 126 项 OK。
- 打包验证：`pwsh -File scripts/package-windows.ps1` 生成 `dist/AgentWorkbench-v0.14.3-windows.zip`；`dist/MultiAgentWorkbench.exe` 启动后监听 `127.0.0.1:8765`，页面返回 200，包含 `/api/jobs`、`pollJob` 和 `IntegratorAgent`；未打开新的 Chrome「Agent Workbench」窗口，WebView 由 `msedgewebview2` 承载。

## v0.14.2 - 2026-09-15（开发版）

### 改进

- 按用户要求，`MultiAgentWorkbench.exe` 打包主入口切回原 Web UI，保证界面和原网页版一模一样。
- 桌面 `多Agent工作台.lnk` 继续保留，指向当前项目 `dist/MultiAgentWorkbench.exe`；双击后打开原本 Web UI。
- Tkinter 桌面入口保留为备用代码入口，但不再作为 Windows 包默认界面。
- 同步 `pyproject.toml` 版本到 `0.14.2`。

### 验证

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_setup_scripts tests.test_webui` 23 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 124 项 OK。
- 打包验证：`pwsh -File scripts/package-windows.ps1` 生成 `dist/AgentWorkbench-v0.14.2-windows.zip`；`dist/AgentWorkbench-CLI.exe provider` 可输出 Provider 状态；`dist/MultiAgentWorkbench.exe --no-browser` 启动后首页返回 200，页面包含 `/api/jobs`、`pollJob` 和 `IntegratorAgent`，确认已恢复原 Web UI。

## v0.14.1 - 2026-09-15（开发版）

### 改进

- 桌面窗口迁入工作台信息面板：左侧保留常用操作，中间显示运行日志，右侧显示最近主控方案和当前运行进度。
- 最近方案支持在桌面窗口中选中并自动填入任务 ID，方便继续执行已生成方案。
- 桌面旧入口整理为一个快捷方式：桌面只保留 `多Agent工作台.lnk`，指向当前项目 `dist/MultiAgentWorkbench.exe`；旧的桌面根目录 exe 已移入回收站。
- 同步 `pyproject.toml` 版本到 `0.14.1`。

### 验证

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_desktop tests.test_setup_scripts` 11 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 124 项 OK。
- 打包验证：`pwsh -File scripts/package-windows.ps1` 生成 `dist/AgentWorkbench-v0.14.1-windows.zip`；`dist/AgentWorkbench-CLI.exe provider` 可输出 Provider 状态；桌面快捷方式指向当前 `dist/MultiAgentWorkbench.exe`；`dist/MultiAgentWorkbench.exe` 可启动进程，且启动前后 `127.0.0.1:8080` 均无监听。

## v0.14.0 - 2026-09-15（开发版）

### 改进

- 新增 `python -m code_agent_collab.desktop` 本地桌面窗口，提供 Provider 检查、生成主控方案、开始协同工作、暂停和强制停止按钮。
- Windows 打包入口改为桌面窗口：`MultiAgentWorkbench.exe` 默认打开本地软件，不再默认打开浏览器；`AgentWorkbench-CLI.exe` 继续作为后台 CLI。
- 桌面窗口在源码运行和打包运行时都会解析正式项目根，并对需要项目路径的 CLI 命令自动补 `--project-root`，避免日志、方案、配置落到 `dist` 或解压目录。
- 保留旧 Web UI 作为备用/调试入口，可继续用 `python -m code_agent_collab.webui` 或 Provider 配置菜单启动。
- 同步 `pyproject.toml` 版本到 `0.14.0`。

### 验证

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_desktop tests.test_setup_scripts` 8 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 121 项 OK。
- 打包验证：`pwsh -File scripts/package-windows.ps1` 生成 `dist/AgentWorkbench-v0.14.0-windows.zip`；`dist/AgentWorkbench-CLI.exe provider` 可输出 Provider 状态；`dist/MultiAgentWorkbench.exe` 可启动进程，且启动前后 `127.0.0.1:8080` 均无监听，确认桌面入口不自动启动 Web UI。

## v0.13.2 - 2026-09-15（开发版）

### 改进

- `apply-draft --apply` 正式写入前会复制一个临时隔离副本，在副本里应用草稿并运行测试；隔离测试失败时，正式源码不会被写入。
- `run_tests` 增加 120 秒超时，并在测试环境中剥离常见密钥、令牌、Cookie、授权等环境变量，强制使用 mock Provider。
- 同步 `pyproject.toml` 版本到 `0.13.2`。

### 验证

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_apply` 14 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 115 项 OK。

## v0.13.1 - 2026-09-15（开发版）

### 改进

- `apply-draft` 解析草稿时会比对“修改文件清单”和“建议代码”中的实际路径，两者不一致时拒绝继续。
- `apply-draft` 应用前新增评审闸门，复用 Reviewer 关键规则拦截敏感信息、项目外主知识库路径、笼统测试方法、未解决冲突标记和非标准草稿文件名。
- `apply-draft` 现在优先识别 `integrated-draft`，支持 Integrator 合并草稿进入预览/应用流程。
- 同步 `pyproject.toml` 版本到 `0.13.1`。

### 验证

- 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_apply tests.test_reviewer` 24 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 114 项 OK。

## v0.13.0 - 2026-09-14（开发版）

### 改进

- ReviewerAgent 增加深度规则检查：固定五小节结构、`src/`/`tests/` 路径范围、具体测试方法和未解决冲突标记。
- IntegratorAgent 在 Provider 输出不可解析但不属于明显短草稿时，会生成安全兜底合并草稿，避免 mock Provider 把流程卡死。
- 真实 Provider 调用增加超时配置、429/5xx/网络临时失败重试、`ProviderCallError` 错误分类和 `choices[0].message.content` 响应结构校验。
- Web UI 新增后台 job runtime：`POST /api/jobs` 创建命令任务，`GET /api/jobs/<job_id>` 查询状态；前端改为提交 job 并轮询完成，旧 `/api/command` 保留兼容。
- 同步 `pyproject.toml` 版本到 `0.13.0`。

### 验证

- Reviewer 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_reviewer tests.test_apply tests.test_workflow tests.test_adaptive_workflow tests.test_integrator` 38 项 OK。
- Provider 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_providers tests.test_orchestrator tests.test_workflow tests.test_adaptive_workflow tests.test_integrator tests.test_review tests.test_webui` 65 项 OK。
- Web job 局部测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_webui tests.test_progress tests.test_adaptive_workflow` 35 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 111 项 OK。
- 打包验证：先停止占用旧 exe 的本项目 Web UI 进程，再运行 `pwsh -File scripts/package-windows.ps1`，生成 `dist/AgentWorkbench-v0.13.0-windows.zip`。
- 打包版 HTTP 验证：首页 200 且包含 `/api/jobs`、`pollJob`、`IntegratorAgent`；`/api/progress` 200；`POST /api/jobs` 执行 `provider` 后最终 job 状态为 `done`、code 0。

## v0.12.6 - 2026-09-14（修复版）

### 修复

- 修复打包版 Web UI 从 `dist` 或桌面副本启动时，把 exe 所在目录当成独立项目根，导致 `/api/progress` 读不到正式项目 `logs/progress`、进度树显示“暂无任务”的问题。
- Web UI 现在优先读取 `AGENT_WORKBENCH_PROJECT_ROOT`；未配置时从 exe 目录向上查找含 `pyproject.toml` 与 `src/code_agent_collab` 的正式项目根；本机兜底回到工作台内的正式项目目录。

### 验证

- 新增 Web UI 项目根解析测试，覆盖 `dist` 打包目录向上回到项目根、环境变量覆盖两条路径。
- mock 模式全量测试通过。
- 重新生成 Windows 包 `dist/AgentWorkbench-v0.12.6-windows.zip`，并用新 `MultiAgentWorkbench.exe` 验证 `/api/progress` 能返回运行树节点。

## v0.12.5 - 2026-09-14（开发版）

### 新增

- 新增 `IntegratorAgent`，复杂任务中位于双 Coder 和 ReviewerAgent 之间，负责把多份 Coder 草稿合并成 `dev-vault/projects/<任务ID>-integrated-draft.md`。
- 复杂任务模板从 `KnowledgeAgent -> 双 Coder -> ReviewerAgent` 改为 `KnowledgeAgent -> 双 Coder -> IntegratorAgent -> ReviewerAgent`，worker 数量从 4 变为 5。
- ReviewerAgent 优先评审 IntegratorAgent 的合并草稿；没有合并草稿时继续兼容评审 Coder 草稿。
- Fix Loop 中 Coder 被打回重写后，会重新运行 IntegratorAgent，再交给 ReviewerAgent 复审。
- Web 终端进度树把 IntegratorAgent 放在 Coder 分支之后、ReviewerAgent 之前。

### 验证

- 新增 `tests/test_integrator.py`，覆盖 IntegratorAgent 读取每个 Coder 最新 revision 并写出合并草稿。
- 更新 `tests/test_adaptive_workflow.py`，覆盖复杂任务的 Integrator 阶段和打回重写后的重新合并。
- 更新 `tests/test_reviewer.py`，覆盖 ReviewerAgent 优先评审合并草稿。
- 针对性测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_integrator tests.test_orchestrator tests.test_adaptive_workflow tests.test_reviewer tests.test_webui` 46 项 OK。

## v0.12.4 - 2026-09-14（开发版）

### 新增

- Web 终端进度树新增 Agent 详情面板：点击可检查的 Agent 节点后，在树下方显示该 Agent 的状态、负责路径、输出、输出文件、阻塞和备注。
- Agent 节点支持鼠标点击和键盘 `Enter` / 空格打开详情；选中节点会保留高亮。
- 详情数据来自 `/api/progress.blackboard`，不从 Markdown 日志临时解析。
- 同步 `pyproject.toml` 版本到 `0.12.4`，重新生成 Windows 包 `dist/AgentWorkbench-v0.12.4-windows.zip`。

### 验证

- 更新 `tests/test_webui.py`，覆盖页面包含 Agent 详情面板、节点选择逻辑和 blackboard 提示文案。
- Web UI 单测：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_webui` 18 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 99 项 OK。
- HTTP 验证：首页包含 `agentInspector` 和节点选择逻辑；`/api/progress` 返回 blackboard 样例数据（2 个 Agent）。
- 打包验证：`pwsh -File scripts/package-windows.ps1` 成功生成 `dist/AgentWorkbench-v0.12.4-windows.zip`。
- 本环境 Browser/Playwright/jsdom 不可用，真实浏览器截图 QA 未执行。

## v0.12.3 - 2026-09-14（开发版）

### 新增

- 新增共享黑板 `logs/blackboards/<任务ID>.json`，记录每个 Agent 的 `agent_id/role/label/owned_paths/status/outputs/output_paths/blockers/notes/error/updated_at`。
- 自适应编排接入黑板写入：计划生成后登记 `planned`，worker 开始写 `running`，成功写 `success`，失败写 `failed`，复用旧结果写 `skipped`。
- `/api/progress` 后端快照新增 `blackboard` 字段，后续 Web UI 可以基于它实现“点击 Agent 看详情”。
- 黑板写入使用进程内锁、线程独立临时文件和 `os.replace` 短重试，沿用 Windows 并发 JSON 写入经验。

### 验证

- 新增 `tests/test_blackboard.py`，覆盖 Agent 生命周期记录、并发写入保留多 Agent、失败 blocker 记录。
- 更新自适应工作流测试，覆盖执行、失败和重跑时黑板状态同步。
- 更新 Web UI 后端测试，覆盖进度快照暴露 blackboard。
- 针对性测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_blackboard tests.test_adaptive_workflow tests.test_webui` 33 项 OK。

## v0.12.2 - 2026-09-13（开发版）

### 改进

- `WorkerSpec` 增加 `owned_paths`，用于记录每个 worker 的职责路径边界，为以后更多 Agent 分工预留统一结构。
- 复杂任务模板从“模块A/模块B”改为“实现/测试”分工：实现 Coder 默认负责 `src/`，测试 Coder 默认负责 `tests/`。
- 自适应编排在同阶段并行执行前检查 `owned_paths` 是否重叠；发现 `src/` 与 `src/code_agent_collab/` 这类包含关系时会拒绝并行，避免两个 Coder 重复执行同一段业务。
- 计划 JSON 改为结构化 worker 对象并保存 `owned_paths`，同时兼容旧的 `["角色", "标签"]` 数组格式。
- CoderAgent 的模型提示和草稿头部会写明负责路径；WorkerRun 输入 hash 纳入 `owned_paths`，避免职责变化后误复用旧结果。
- Web UI 后端计划快照读取兼容新的 worker 对象格式；页面样式和交互未改。

### 验证

- 新增/更新测试覆盖复杂任务默认非重叠分工、并行职责冲突拦截、新旧计划 JSON 兼容、Web UI 后端读取 `owned_paths` 格式。
- 针对性测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_orchestrator tests.test_adaptive_workflow tests.test_webui` 37 项 OK。

## v0.12.1 - 2026-09-13（开发版）

### 改进

- 进度快照增加任务级简单隔离：`publish_progress` 保留写 `logs/progress/current.json` 兼容现有 Web UI，同时额外写 `logs/progress/<任务ID>.json` 和 `logs/progress/latest.json`。
- `read_progress(project_root, task_id=...)` 支持读取指定任务的进度快照，为以后做多任务列表或指定任务查看预留后端数据基础。
- 进度快照写入使用线程独立临时文件和短重试，降低 Windows 下文件短暂占用导致写入失败的概率。

### 验证

- 新增 `tests/test_progress.py`，覆盖任务级进度文件、latest 指针和自定义 `AGENT_WORKBENCH_PROGRESS_FILE` 兼容行为。
- 针对性测试：`python -m unittest tests.test_progress` 2 项 OK；`python -m unittest tests.test_webui` 16 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 91 项 OK。

## v0.12.0 - 2026-09-13（开发版）

### 新增

- 新增 `WorkerRun` 状态账本：阶段内每个 worker 执行都会写入 `logs/runs/<任务ID>/workers.json`，记录 `running/success/failed/skipped`、输入 hash、输出路径、错误、尝试次数和 AgentResult。
- 自适应编排接入 worker 级失败记录：同一阶段中部分 worker 成功、部分 worker 失败时，会保留已成功结果，保存停在当前阶段的 checkpoint，并把失败 worker 标记到进度快照。
- 重跑同一任务时，输入未变化且账本中已有成功结果的 worker 会标记为 `skipped` 并复用结果，只补跑失败或缺失的 worker。
- 桌面根目录新增问题整理文档：`多Agent代码协作助手-当前问题整理.md`。

### 验证

- 新增 WorkerRun 账本测试，覆盖并行 worker 中 A 成功、B 失败后，重跑时跳过 A、只补跑 B。
- 针对性测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest tests.test_adaptive_workflow` 通过，10 项 OK。
- 全量测试：`$env:PYTHONPATH='src'; $env:AGENT_WORKBENCH_PROVIDER='mock'; python -m unittest discover -s tests` 通过，89 项 OK。

## v0.11.2 - 2026-09-13（文档版）

### 改进

- 补充“不动代码”的协作前置体检：真实项目根、Git upstream、ahead/behind、mock Provider 测试边界。
- 修正维护指南里过时的 Agent 数量描述，避免继续按旧 6 角色理解当前项目。
- 在版本管理中记录当前 `main` 跟踪 `origin/main`，并提醒本地 ahead 提交在发布或协作前必须单独说明。
- 在技能文档补充当前架构限制清单：单任务进度文件、并行 worker 共享上下文、规则版 Reviewer、真实 Provider 基础错误处理、Web 子进程超时和 `apply-draft` 实验边界。

### 验证

- 未修改 `src/` 和 `tests/`。
- 文档修改前已在 mock 模式下跑全量测试：88 项通过。

## v0.11.1 - 2026-09-08（开发版）

### 改进

- Web 终端聊天逻辑调整：普通输入仍保持原界面输出方式，但用户问问题时 OrchestratorAgent 必须先回答问题，再继续做需求澄清或提示生成方案。

### 验证

- 新增 Web UI 聊天回归测试，覆盖“用户问问题时先回答”的 mock 路径。

## v0.11.0 - 2026-09-05（开发版）

### 新增

- Web 终端进度快照新增暂停断点信息：`/api/progress` 会返回最近可继续的 checkpoint、下一阶段序号和已完成角色。
- Web 终端新增“继续暂停任务”按钮：检测到 checkpoint 后自动启用，点击后复用 `approve <任务ID>` 从断点继续执行。
- 进度摘要在存在 checkpoint 时显示断点任务和下一阶段，避免用户暂停后不知道从哪里恢复。
- 重新生成 Windows 下载包 `dist/AgentWorkbench-v0.11.0-windows.zip`，避免源码已更新但用户双击旧 exe 时看不到新交互。

### 验证

- 新增 Web UI checkpoint 快照测试，覆盖暂停断点暴露和方案状态显示为“已暂停”。
- 源码 Web UI 和打包后的 `MultiAgentWorkbench.exe` 均验证普通输入会进入 OrchestratorAgent 需求讨论，而不是直接执行多 Agent。

## v0.10.6 - 2026-09-04（开发版）

### 新增

- Web 终端新增“暂停工作”按钮：请求软暂停后，当前 Agent 小步完成，工作流会在进入下一阶段前保存断点并暂停。
- Web 终端新增“强制停止”按钮：经两次确认并输入 `STOP` 后，及时停止当前后台 Agent/AI 进程；强制停止不删除 API key，避免把运行控制和凭证配置混在一起。
- 新增控制文件 `logs/control/pause.json` 与自适应协同 checkpoint，用于阶段边界续跑。
- 新增 Windows zip 下载包打包脚本 `scripts/package-windows.ps1`，打包 Web UI exe、后台 CLI exe、Provider 配置脚本和启动说明。

### 验证

- 新增/更新暂停、强制停止、checkpoint 和打包脚本相关测试。

## v0.10.5 - 2026-09-04（开发版）

### 新增

- Web 终端普通输入改为单 AI 需求讨论：先由 OrchestratorAgent 前置讨论员追问和澄清，不再直接生成方案。
- 新增“生成主控方案”按钮：把当前讨论内容整理为 `run-adaptive` 输入，只生成待审批方案，不执行后续 Agent。
- 保留“开始协同工作”开关：只有已有方案后才执行 `approve`，进入 KnowledgeAgent、CoderAgent、ReviewerAgent 等后续阶段。

### 验证

- 新增 Web UI 讨论测试，覆盖首次输入会问澄清问题、后续补充会进入方案输入。

## v0.10.4 - 2026-09-04（开发版）

### 新增

- DeepSeek 配置向导扩展为通用 AI Provider 菜单：支持选择 DeepSeek 或 OpenAI，并分别写入对应的用户环境变量。
- 停止 API 调用时可切回本地 mock，并可分别确认是否删除 DeepSeek/OpenAI API Key。

### 验证

- 更新脚本安全测试，覆盖 OpenAI 菜单、OpenAI Key 环境变量和停用清理路径。

## v0.10.3 - 2026-09-04（开发版）

### 新增

- 新增 `scripts/setup-deepseek.ps1`：一条命令启动 DeepSeek 配置向导，先用 `1/2/3/4/5` 菜单选择配置、停止 API、查看状态、启动 Web UI 或退出；用户只需回答少量 `y/n` 并在本机终端粘贴 API Key。
- 配置向导只写当前 Windows 用户环境变量：`AGENT_WORKBENCH_PROVIDER=deepseek` 和 `DEEPSEEK_API_KEY`，不写入仓库文件。
- 支持一键停止真实 API 调用并切回本地 mock；删除本机保存的 DeepSeek Key 前会单独确认。
- 配置完成后可选择立即启动 Web UI；若端口已被占用，会显示进程 ID 并二次确认是否停止本机旧进程。

### 验证

- 新增脚本安全测试，检查脚本使用隐藏输入、用户环境变量、DeepSeek 变量名，并避免使用 PowerShell 内置 `$PID` 变量作为普通变量。

## v0.10.2 - 2026-09-04（开发版）

### 修正

- Web 终端默认改为单 AI 讨论/规划模式：直接输入任务目标时执行 `run-adaptive`，只让 OrchestratorAgent 生成方案，不直接启动全部 workers。
- 新增“开始协同工作”开关：点击后自动读取最近主控方案并执行 `approve <任务ID>`，这时才进入 KnowledgeAgent、CoderAgent、ReviewerAgent 等多 Agent 协同阶段。
- 保留原命令能力：用户仍可手动输入 `run`、`run-adaptive`、`approve` 等明确命令。

### 验证

- 更新 Web UI 测试，覆盖协同开关、默认普通输入走 `run-adaptive`、开关执行 `approve`。

## v0.10.1 - 2026-09-04（开发版）

### 修正

- 自适应模板修正为所有 CoderAgent 完成后都进入 ReviewerAgent：SIMPLE=Coder→Reviewer，MEDIUM=Knowledge→Coder→Reviewer，COMPLEX=Knowledge→双 Coder 并行→Reviewer。
- Web UI 改为纯黑底终端页，不再显示旧页面的左侧导航、右侧环境面板和顶部菜单壳。
- 新增实时进度文件 `logs/progress/current.json`：工作流执行中会发布 Orchestrator、CoderAgent、ReviewerAgent、Fix Loop、Done 的状态。
- `/api/progress` 优先返回实时进度；前端在命令执行中 500ms 轮询，让树状图能看到当前节点。
- 树状图颜色改为：已到达/当前路径紫色，未到达节点黑灰色，等待审批黄色，失败红色。

### 验证

- 更新自动化测试，覆盖 ReviewerAgent 必须接在 CoderAgent 之后、Orchestrator 分配中、人工审批等待、运行时进度优先读取。

## v0.10.0 - 2026-08-28（开发版）

### 新增

- 新增 `plans` 命令：列出 `logs/plans` 中已保存的自适应主控方案。
- 方案列表显示任务 ID、任务目标、复杂度、模板、worker 数量、更新时间和状态。
- 状态按是否存在对应 workflow 日志区分：未执行为“待批准”，已执行为“已执行”。
- Web 终端命令白名单和快捷按钮同步支持 `plans`。
- Web 终端新增 Agent 关系与进度树：在终端式页面里保留可视化节点和连线，页面加载和命令执行后自动刷新。
- 取消原先厚重页面外壳，保留树状图主体，并改成黑底终端面板风格。
- 新增 `/api/progress` 只读接口，根据本地方案和工作流日志生成树状进度快照。

### 边界

- 本版本不改变 `run-adaptive` 和 `approve` 的审批闸门；`plans` 和 `/api/progress` 只读查看方案与日志，不会执行 worker。
- 仍不写主知识库，不创建 tag、Release 或部署。

### 验证

- 自动化测试通过：76 项。
- CLI 冒烟：`plans` 能列出当前已保存方案。
- Web UI 浏览器验证：桌面和 390px 窄屏均能看到可视化 Agent 关系与进度树；点击“方案”执行 `plans` 成功；控制台无错误。

## v0.9.1 - 2026-08-25（修订版）

### 修正

- README 当前版本从 `v0.8.0` 更新为 `v0.9.1`，补充 `apply-draft` 实验能力说明。
- `pyproject.toml` 包版本从 `0.7.1` 更新为 `0.9.1`。
- `VERSIONING.md` 补齐 `v0.8.x` 和 `v0.9.x` 阶段说明。

### 边界

- 本版本只修正文档和版本元数据，不改变功能代码。
- 仍未执行远端推送、GitHub Release 或版本标签创建。

### 验证

- 自动化测试通过：74 项。

## v0.9.0 - 2026-08-21（实验版）

### 新增

- 规范 CoderAgent 草稿格式：草稿正文固定包含五个小节（修改文件清单 / 修改原因 / 建议代码 / 测试方法 / 风险），建议代码按 `### <路径>` 给出每个文件的完整新内容，供机器解析。
- 新增 `apply-draft` 命令（`src/code_agent_collab/apply.py`）：
  - 默认 dry-run：解析草稿、白名单校验、生成 unified diff 预览，不写任何文件；
  - `--apply`：应用改动 → 自动跑测试 → 测试通过自动本地 commit；测试失败自动回滚并报告。
- 安全边界：只允许写 `src/`、`tests/` 下的文本文件；拒绝绝对路径、越界路径、不允许的文件类型；应用前要求 Git 工作区干净，否则拒绝（保证可干净回滚）。

### 边界

- 本功能是系统第一个真正"写正式项目文件"的能力（L2 项目写），属于实验版，尚未用真实 AI 端到端验证。
- 可应用的草稿必须符合新格式；mock Provider 生成的草稿无固定小节、无法解析，真实 AI 下才能生成可应用草稿。
- 自动 commit 仅本地，不 push；推送、发布仍需用户明确确认。

### 验证

- 74 项自动化测试通过（新增 10 项 apply 测试：解析、白名单校验、dry-run 不写文件、失败回滚、通过后提交、脏工作区拒绝、关键词定位草稿）。
- CLI 冒烟：`apply-draft <任务>` 预览 diff 且不写文件；`apply-draft <任务> --apply` 应用后测试通过并自动提交 `apply-draft: ...`。

## v0.8.0 - 2026-08-21（开发版）

### 新增

- 新增 ReviewerAgent（规则版草稿评审）：CoderAgent 写完草稿后检查四件事——草稿是否存在、是否太空（内容 < 100 字符）、是否包含敏感信息、是否越权（引用主知识库路径）。
- 评审结论结构化保存（`last_verdict` / `last_reasons`），默认流水线和自适应复杂流程已支持 Reviewer 不通过时最多打回 CoderAgent 重写一次。
- 新增 `agents/registry.py` 的 `create_agent` 工厂：按角色名创建 Agent，为后续按预设模板动态构建 workers 预留统一入口。
- 默认流水线由 6 个 Agent 扩展为 7 个：Coder 之后插入 Reviewer，Validator 之前执行评审。
- `workflow.py` 提取 `build_workflow_agents()`，Provider 实例改为复用同一个（原 Planner/Coder 各自创建）。
- `review` 命令改为**人工确认闸门**：AI 审查通过不再自动写入主知识库，只把候选记录标记"待人工确认"并把 AI 建议的写入位置记入候选记录；`confirm` 入库时优先采用 AI 建议位置（仍校验目标必须是主知识库内现有目录）。
- 新增 OrchestratorAgent（半动态主控）：规则版复杂度判定（任务长度 / 拆分信号词 / 技术词数量打分），AI 判定可选（输出无法解析时回退规则版），从三档预设模板选执行方案：SIMPLE=1 worker（Coder）、MEDIUM=2 workers（Knowledge→Coder）、COMPLEX=4 workers（Knowledge→双 Coder 并行→Reviewer）。
- 新增 `run-adaptive` 命令与 `orchestration.py`：阶段化执行，阶段间串行（尊重 Knowledge→Coder 依赖），阶段内用 `ThreadPoolExecutor` 并行。
- **执行前人工审批闸门**：`run-adaptive` 只生成主控方案（写入 `logs/plans/<任务ID>.json`）并等待审批，不自动执行；新增 `approve` 命令，人工批准后才执行 workers。程序化入口 `run_adaptive_workflow` 仅供测试/脚本使用，CLI 真实路径不绕过审批。
- CoderAgent 支持 `worker_label`：多个并行编码 worker 写独立草稿（`<任务ID>-coder-draft-<标签>.md`），默认无标签时文件名不变。
- ReviewerAgent 升级为评审全部草稿（支持双编码并行的多草稿场景）。
- CoderAgent 新增按 Reviewer 反馈重写草稿能力，重写文件使用 `-revisionN` 后缀保留第一版证据；ReviewerAgent 按 worker 只审最新版草稿。
- ReviewerAgent 的空草稿判断改为检查 `## AI 草稿` 正文长度，避免文件头和安全边界文字把空草稿误判为合格；越权路径检查改为拦截项目目录外的主知识库路径，避免项目本身位于主知识库内时误判正常日志路径。
- **Web 终端支持打包为 Windows 软件**：`webui.py` 增加 PyInstaller 打包支持（frozen 模式下项目根目录取 exe 所在目录、`run_cli` 调用同目录 CLI 可执行程序、启动后自动打开浏览器）；`ALLOWED_COMMANDS` 增加 `run-adaptive`/`approve`；新增 `scripts/build-exe.ps1` 打包脚本，产物为 `dist/MultiAgentWorkbench.exe`（界面）+ `dist/AgentWorkbench-CLI.exe`（后台 CLI）。

### 边界

- ReviewerAgent 当前为规则版，不调用真实 AI（构造器已预留 provider 参数，后续可升级 AI 评审）。
- 评审只输出结论、不修改草稿文件；打回重做最多 1 次，仍不通过则停止后续验证环节，交给人工处理。
- 主知识库写入现在只有人工确认（`confirm`）一条通道；`review` 只负责建议与脱敏拦截。
- 并行仅发生在阶段内（当前 COMPLEX 模板的双编码 worker）；阶段间保持串行。
- 计划审批闸门：主控方案必须经 `approve` 人工批准后才执行；未批准的方案停留在 `logs/plans/`。
- 该版本属于开发版，尚未发布。

### 验证

- 64 项自动化测试通过（原 42 项 + 新增 22 项），无回归。
- 新增测试覆盖：Reviewer 只审最新版草稿、默认流水线打回重写、重写后仍失败停止、自适应复杂流程双 Coder 重写。
- 真实 CLI 冒烟：`run-adaptive "写个计算器"` 输出 1 个 worker 方案并提示等待审批；`approve "写个计算器"` 批准后执行（Orchestrator→Coder）并产出日志与候选复盘；`run-adaptive "用 python 和前端写一个带多个模块和接口的完整网站，拆成前后端"` 输出 4 个 worker 方案（Orchestrator→Knowledge→Coder→Coder→Reviewer）。

## v0.7.2 - 未发布（修订版）

### 修正

- 修复 Web 终端进程清理在 Windows 沙箱环境下过度依赖 `taskkill` 的问题；现在会先用 Python 子进程句柄终止，失败后再尝试 `taskkill`，最后用 `kill` 兜底。
- 将 Web UI 从白色仪表盘式页面调整为更接近 Codex 的深色三栏任务流布局：左侧项目/命令列表，中间对话式任务区，底部输入框，右侧环境信息面板。
- 参考 Codex 右上角布局控制方式，新增 3 个图标键：收起/展开左侧导航、运行输出、右侧环境信息。
- 将运行输出区移动到输入框下方，改成类似 Codex 底部 PowerShell 面板的简洁终端区，并压缩整体字号与图标尺寸。
- 补充窄窗口响应式比例：小屏下自动收紧左右栏、资源卡和右侧面板字号，避免中间对话区被挤窄。
- 改为更接近 Codex 桌面外壳：增加顶部菜单/窗口栏，左栏、任务标题栏、右侧环境面板和底部终端按 Codex 截图重排；未实现功能只保留空位或禁用占位，不再伪装成可用入口。
- 继续收敛 Codex 比例：输入框宽度改为中栏约 64%，降低输入框和终端高度，缩小右侧面板、终端和快捷按钮字号，减少厚重感。
- 修正底部终端细节：默认内容恢复为 Provider 状态信息，但不再自动执行命令，普通输出统一白色，避免一打开就是青色状态文本。
- 删除底部终端的假标签栏和 `+`/`x` 占位，只保留真实输出区域。
- 修正右上角布局按钮映射：滑杆图标控制右侧环境信息栏，终端图标控制底部输出，侧栏图标控制左侧导航。
- 删除顶部 `Share` 和 `打开位置` 两个无功能占位按钮，只保留实际可用的布局控制键。
- 加高底部 Provider 输出区，改善默认状态信息的阅读空间。
- 修复 Web UI 项目根目录计算错误，避免把 `src` 误当成项目根目录。

### 验证

- 42 项自动化测试通过。
- 浏览器验证通过：页面可打开、无控制台错误，`只生成上下文` 按钮可生成任务上下文包，3 个布局图标键可收起/展开对应区域。

## v0.7.1 - 2026-08-20（修订版）

### 修正

- 修正 `pyproject.toml` 中仍显示 `0.3.0` 的版本元数据错误，使 Python 包版本与当前公开版本一致。
- README 当前版本同步为 `v0.7.1`。

### 边界

- 本版本不改变功能代码。
- 40 项自动化测试继续作为发布验证标准。

## v0.7.0 - 2026-08-20（发布版）

### 新增

- 新增 PowerShell 风格 Web 终端界面（`python -m code_agent_collab.webui`）。
- 浏览器中输入命令即可执行项目功能，默认地址 http://127.0.0.1:8080，仅本机可访问。
- 命令白名单校验：只允许项目自身命令，不允许执行任意系统命令。
- 新增 5 项页面相关测试。
- 关闭 Web 终端程序时会强制终止正在运行的命令进程，AI 调用随之停止，不会在后台继续消耗 token。

### 边界

- 页面与命令行执行同一套命令，`review`/`confirm` 仍会真实写入主知识库。
- 该版本已通过本地测试与真实 DeepSeek 调用验证，属于发布版。
- 页面与命令行执行同一套命令，`review`/`confirm` 会真实写入主知识库。

## v0.6.0 - 2026-08-20（开发版）

### 新增

- 新增 `review` 命令：AI 审查候选复利记录，本地脱敏扫描 + AI 质量/重复判断。
- 审查分流：安全的候选自动写入主知识库对应位置；命中 API 密钥、密码/令牌关键词、手机号、邮箱的候选标记"待人工处理"，不写入。
- 新增 `confirm` 和 `discard` 命令：人工确认入库或废弃候选记录。
- 写入主知识库前自动清洗本机绝对路径，避免泄漏本机信息。
- 新增 8 项审查相关测试。

### 边界

- mock Provider 只做本地脱敏扫描，无真实 AI 审查能力。
- AI 判定"不建议入库"或输出无法解析时，一律转人工处理，不自动写入。
- 写入目标必须是主知识库内的现有目录，否则回退到默认复盘目录。
- 该版本属于开发版，尚未发布。

## v0.5.2 - 2026-08-20（修订版）

### 整理

- 文档文件名改为中文：变更记录、版本管理、维护指南、技能。
- 新增"PROJECT_RULES.md"（给人看的规则总览）和"MAINTENANCE.md"（知识串联索引）。
- README 增加规则与知识入口链接。

## v0.5.1 - 2026-08-20（修订版）

### 整理

- 合并 `docs/` 与 `product-docs/`，统一文档目录。
- 新增"维护指南"文档，README 增加"项目结构"章节。
- 本地产物（候选记录、代码草稿、运行日志）加入 `.gitignore`，避免 Git 状态噪音。
- 清理本次开发产生的测试残留文件（已移入回收站，可恢复）。
- 完善 `dev-vault/README.md` 目录说明。

## v0.5.0 - 2026-08-20（开发版）

### 新增

- KnowledgeAgent 接入主知识库只读检索：从任务目标提取关键词，检索相关 Markdown 文档。
- 新增 `knowledge.py` 检索模块：关键词提取、范围/深度/文件大小限制、排除隐私与附件目录、只读保证。
- 检索结果生成知识补充文件 `logs/context-packs/<任务ID>-knowledge.md`，供 Planner 等后续 Agent 使用。
- 新增 8 项检索相关测试。
- 支持 `AGENT_WORKBENCH_MAIN_VAULT` 环境变量覆盖主知识库路径，方便首次使用者快速配置。
- README 增加"首次使用与知识库配置"章节。

### 边界

- 检索基于关键词匹配，不使用向量语义，命中率有限。
- 主知识库保持只读，绝不写入任何内容。
- 默认排除隐藏目录、`99-附件`、`work`、`01-项目` 等目录，避免扫描源码和隐私内容。
- 该版本属于开发版，尚未发布。

## v0.4.0 - 2026-08-20（发布版）

### 新增

- 增加 CoderAgent 行动 Agent，根据任务和上下文包生成代码草稿。
- CoderAgent 草稿只写入 `dev-vault/projects`，不直接修改正式源码。
- 工作流扩展为 6 个 Agent：协调、知识、计划、编码、验证、复盘。
- 增加项目"技能"文档，沉淀可复用开发技能和新增 Agent 标准流程。
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

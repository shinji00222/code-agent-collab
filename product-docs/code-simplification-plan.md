# 代码简化优化规划

更新时间：2026-10-03

## 结论

项目现在不是“代码乱到要推倒重来”，而是进入了原型后期常见状态：功能已经堆出闭环，但有几块历史代码和大函数开始拖慢维护。接下来优化的目标不是换框架、重写 UI、继续加 Agent，而是让现有代码更简单、更小、更容易验证。

本轮只做规划，不改功能代码。后续每一步都应该小步提交，保持 `python scripts/run-tests.py` 通过。

## 优化目标

1. 删除确定不用的历史代码。
2. 把过大的文件按职责拆开。
3. 把重复 helper 抽成共享函数。
4. 保持命令、Web UI、桌面入口和测试行为不变。
5. 不为了“架构好看”引入新依赖、新前端构建链或数据库。
6. 执行安全按“轻隔离优先”推进，不为了沙箱概念一开始引入重型 VM/Docker 基建。

## 当前发现的问题

### 1. `webui.py` 保留了未使用的旧页面

- 位置：`src/code_agent_collab/webui.py`
- 现象：文件里保留 `_LEGACY_PAGE`，但实际页面来自 `webui_page.py`，最终赋值是 `PAGE = TERMINAL_PAGE`。
- 影响：`webui.py` 看起来有 1700 多行，其中大量是旧 HTML/CSS/JS。后续改 UI 时容易误改旧页面，以为自己改了生效页面。
- 判断：这是最明确的冗余，优先清理。

### 2. `webui.py` 同时承担太多职责

现在这个文件混在一起处理：

- 项目根目录定位；
- Orchestrator 讨论接口；
- CLI 子进程启动和停止；
- 后台 job 状态；
- 进度快照组装；
- HTTP GET/POST 路由。

这会让后续补 Web API 安全、任务队列、取消机制时变得笨重。更好的形态是让 `webui.py` 只负责启动 HTTP 服务和路由，把 job、progress、discussion 分出去。

### 3. `execute_adaptive_plan` 太长

- 位置：`src/code_agent_collab/orchestration.py`
- 现象：`execute_adaptive_plan` 大约 300 行，同时处理阶段执行、checkpoint、pause、Fix Loop、Integrator 重跑、Reviewer 复审、进度发布和最终反思。
- 影响：现在测试能覆盖，但后面改 Fix Loop 或暂停续跑时，容易碰到不相关逻辑。
- 判断：不用一次性重写，先按“阶段执行 / Fix Loop / checkpoint / progress”提取小函数。

### 4. 有少量重复 helper

已确认两处真实重复：

- `apply.py` 和 `agents/reviewer.py` 都有 `_mentions_main_vault_outside_project` / `_path_forms`。
- `control.py` 和 `worker_runs.py` 都有 `_result_from_json`。

这些重复不大，但属于容易“一个改了另一个忘改”的位置，可以抽到共享模块。

### 5. UI 与后端还没有清晰边界

`webui_page.py` 已经把当前页面放出去了，这是好事；但旧页面仍在 `webui.py`，并且后端 API 也都在同一个文件里。后续应该把“页面文本”和“本地服务逻辑”彻底分开，不要在一个文件里同时维护前端和后端。

### 6. 沙箱路线要分层推进，不能一上来做重

项目后续会越来越接近真实 Coding Agent：分析仓库、生成 patch、跑测试、应用 diff。这里需要沙箱，但当前重点是“减重”，所以不要直接把 VM、Docker、完整容器调度塞进主线。

推荐路线：

- **第一层：轻隔离**。继续强化现有边界：AI 草稿只进 `dev-vault/projects`，`apply-draft` 路径白名单，命令白名单，固定工作目录，超时和最大输出，测试环境剥离密钥，Git 脏工作区拒绝应用。
- **第二层：临时副本执行沙箱**。跑测试前复制一份临时工作区，在副本里应用 patch 并执行测试；通过后只把 diff 带回正式仓库，失败就丢弃副本。
- **第三层：重型隔离**。只有在处理未知外部仓库、安装依赖、执行第三方脚本或需要更开放命令时，再评估 WSL / Docker / VM。Windows 主项目默认不把这层作为起步方案。

判断标准：如果一个隔离能力能直接降低“把正式项目改坏 / 泄露密钥 / 任意命令执行”的风险，就做；如果只是为了架构听起来高级，先不做。

## 推荐执行顺序

### 第 1 步：删除旧页面，先让 Web UI 文件瘦下来

状态：**已完成（v0.17.4）**。`webui.py` 中未引用的 `_LEGACY_PAGE` 已删除，实际页面仍来自 `webui_page.py`。

范围：

- 删除 `webui.py` 中 `_LEGACY_PAGE` 整段旧 HTML/CSS/JS。
- 保留 `from .webui_page import PAGE as TERMINAL_PAGE` 和 `PAGE = TERMINAL_PAGE`。
- 不改 HTTP API，不改页面内容。

验证：

- `python -m unittest tests.test_webui`
- `python scripts/run-tests.py`
- 如需要手动验收，再启动 `python -m code_agent_collab.webui`，确认首页仍返回当前终端页。

风险：

- 低。因为 `_LEGACY_PAGE` 当前没有被引用。

### 第 2 步：拆 `webui.py` 的后端职责

建议拆分：

```text
webui.py              # 只保留 HTTP Handler、server 启动和少量路由 glue
web_jobs.py           # CommandJob、start/get job、run_cli、进程停止
web_progress.py       # build_progress_snapshot、blackboard/progress 聚合
web_discussion.py     # build_discussion_goal、discuss_with_orchestrator
web_project.py        # resolve_project_root、打包/源码模式路径判断
```

拆分原则：

- 先搬函数，不改行为。
- 原函数名能保留就保留，测试少改。
- 每拆一块就跑对应测试，不连续大改。

验证：

- `python -m unittest tests.test_webui tests.test_desktop tests.test_webview_app`
- `python scripts/run-tests.py`

风险：

- 中。主要风险是打包模式路径、WebView 启动和后台 CLI 调用。

### 第 3 步：抽重复 helper

建议：

- 把 `AgentResult` JSON 反序列化抽到 `agents/base.py` 或新建 `agent_result_io.py`。
- 把“是否提到项目外主知识库路径”的判断抽到 `file_utils.py` 或新建 `path_guards.py`。

验证：

- `python -m unittest tests.test_apply tests.test_reviewer tests.test_webui tests.test_adaptive_workflow`
- `python scripts/run-tests.py`

风险：

- 低。函数很小，但涉及安全判断，必须保留现有测试。

### 第 4 步：拆 `execute_adaptive_plan`

状态：**已完成第一步（v0.17.4）**。已拆出执行状态加载、checkpoint 保存、失败发布和 Reviewer Fix Loop；后续若继续优化，再拆 stage runner / finish handler。

建议拆成四类小函数：

```text
load_plan_execution_state(...)
run_plan_stage(...)
run_fix_loop(...)
finish_adaptive_plan(...)
```

先只做函数提取，不改变算法。等结构稳定后，再处理“Fix Loop 打回范围过宽”“暂停全局”等旧问题。

验证：

- `python -m unittest tests.test_adaptive_workflow tests.test_workflow tests.test_coding_loop`
- `python scripts/run-tests.py`

风险：

- 中高。这里是多 Agent 编排主路径，必须小步做，不适合顺手改策略。

### 第 5 步：执行沙箱轻量化加固

建议先补第一层和第二层，不直接上 Docker：

```text
execution_sandbox.py     # 临时工作区、环境变量清理、命令超时和输出上限
path_guards.py           # 路径白名单、项目外引用检查、敏感路径拦截
```

实施顺序：

1. 盘点现有 `apply-draft`、`run_tests`、Web 命令白名单和 Provider 环境变量清理，不重复造轮子。
2. 把“测试环境剥离密钥 / 固定工作目录 / 超时 / 输出上限”收口成共享函数。
3. 让隔离副本执行成为 apply 流程里的清晰对象，而不是散在 `apply.py` 的临时逻辑。
4. 只在需要跑未知仓库或安装依赖时，再单独评估 WSL/Docker 方案。

验证：

- `python -m unittest tests.test_apply tests.test_coding_loop`
- `python scripts/run-tests.py`
- 增加失败用例：测试命令超时、输出过大、环境变量被剥离、项目外路径被拒绝、正式仓库在隔离测试失败后无变化。

风险：

- 中。沙箱能力一旦抽象错，可能让安全边界变模糊；必须用测试覆盖“允许什么”和“拒绝什么”。

## 暂时不要做的事

- 不要引入 React/Vite/前端构建链。当前目标是简化，不是换技术栈。
- 不要重写 Web UI 样式。先清理旧页面和后端职责。
- 不要把同步 HTTP 服务改成 async 服务。没有真实并发瓶颈证据。
- 不要新增 Agent 角色。当前问题是已有代码膨胀，不是 Agent 不够。
- 不要一次性拆完整个 `orchestration.py`。先拆 `execute_adaptive_plan`。
- 不要一开始上重型 VM/Docker 沙箱。先把临时副本、白名单、密钥剥离、超时和输出上限做稳。

## 验收标准

阶段性验收看四件事：

1. 全量测试仍是 212 项 OK 或更多项 OK。
2. `webui.py` 行数明显下降，且不再包含大段 HTML 页面。
3. `execute_adaptive_plan` 主函数长度下降，逻辑入口更清楚。
4. 不改变用户入口命令：`provider`、`start`、`run-adaptive`、`approve`、`coding-loop`、`webui`、`desktop` 都保持原语义。
5. 执行安全边界更清楚：正式源码只在审核通过后被写入，失败测试不会污染正式仓库，命令执行有白名单、超时、输出上限和密钥剥离。

## 建议的下一步

第 1、2、3 步已完成。下一步若继续做代码简化，优先拆 `orchestration.py` 的 stage runner / finish handler；等 apply / coding-loop 再推进时，同步把执行沙箱按“轻隔离 -> 临时副本 -> 重型隔离按需评估”的顺序补进去。

# DSH 接手文档：多 Agent 代码协作助手

更新时间：2026-10-04

这份文档用于当前 Codex 上下文不足时让 DSH 直接接手。它只写项目状态、验证命令、风险边界和下一步，不包含任何 API Key。

## 1. 项目路径与当前状态

- 项目根目录：`C:\Users\<你的用户名>\Desktop\AI工作台知识库\01-项目\project 多Agent代码协作助手`
- 当前分支：`main`
- 当前本地版本：`v0.17.15`
- 远端公开基线：`origin/main` / tag `v0.17.6` / commit `168aa6f`
- 本地状态：**v0.17.15 已 push 到 `origin/main`（远端 main = `af5ba0f`）并推送附注 tag `v0.17.15`**；v0.17.7 ~ v0.17.14 这 8 个中间版本没有单独打 tag，提交随本次一起进 main。未发 GitHub Release、未重新打 Windows 包。
- 用户要求：继续推进项目，把发现的问题都解决，重点关注安全性、可靠性、权限分级；**项目要有自己独立的知识库，程序不写到项目之外**。

## 2. 接手后第一步必须做

在 PowerShell 里运行：

```powershell
Set-Location -LiteralPath 'C:\Users\<你的用户名>\Desktop\AI工作台知识库\01-项目\project 多Agent代码协作助手'
git status --short --branch
git log --oneline -8
$env:AGENT_WORKBENCH_PROVIDER='mock'
python scripts/run-tests.py
python scripts/check-undefined-names.py src tests
```

预期：

- 分支应为 `main...origin/main [ahead 10]` 左右。
- 全量测试应通过，当前基线是 **291 项 OK**；最稳的跑法是直接 `python scripts/run-tests.py`。
- `scripts/check-undefined-names.py` 应输出 `OK`（退出码 0）。
- 正常接手时，v0.17.11 ~ v0.17.15 应已经本地提交；如果 `git status` 仍显示未提交，先检查 diff 和测试，再提交。

```powershell
git add -- .
git commit -m "feat: queue and persist web jobs"
```

不要 push / tag / release，除非 shin 明确要求。

## 3. 最近本地提交链

远端 `origin/main` 当前停在：

- `168aa6f chore: ignore task runtime logs`（tag `v0.17.6` 已推送）

本地新增但未推送：

1. `125faf1 fix: clear stale CLI pause state`（v0.17.7）
2. `85f10e1 fix: prefer latest apply draft revision`（v0.17.8）
3. `de4f691 fix: prevent confirm overwrite`（v0.17.9）
4. `65016be test: cover integrator checkpoint state`（v0.17.10）
5. `6a8eef5 feat: preserve worker run attempt history`（v0.17.11）
6. `9a18c65 fix: restore packaged CLI invocation`（v0.17.12）
7. `acad8f5 chore: add undefined-name static check script`
8. v0.17.13 权限强制点与写入硬边界，提交信息：`feat: enforce runtime permission boundaries`
9. v0.17.14 本机 Web API 请求加固，提交信息：`feat: harden local web api requests`
10. `92cbd31 fix: stabilise permission boundary path checks`（v0.17.15 的可靠性修复部分）
11. `5067061 feat: queue and persist web jobs`（v0.17.15 的队列/持久化部分）

## 4. 已完成的问题闭环

### v0.17.15：后台任务队列（台账「安全方案 · 问题 3」第一版）+ 两处可靠性修复

- 问题：每个任务直接起线程，没有队列容量、没有去重，job 只存内存 —— 双击按钮就重复起任务（重复花额度）、多任务抢同一批文件、重启历史全丢、也不知道上次是否有任务被中断。
- 修复：`web_jobs.py` 里新增 `_JobScheduler`（一个调度线程 + 每任务一个工作线程）：并发上限 `MAX_ACTIVE_JOBS=2`、等待队列上限 `MAX_QUEUED_JOBS=8`（满了 **429**）、写命令（除 `pending/plans/provider/help`）**同时最多 1 个**、同 `request_id` 或同一条排队/运行中的命令**去重不重复执行**；新增 `job_store.py` 落盘 `logs/jobs/<job_id>.json`（原子写、保留 200 条），启动与退出时把未完成记录标成 `interrupted`（**只改状态、绝不重跑**）；新增 `GET /api/jobs` 查历史。
- **顺带修掉两个真 bug**：
  1. 权限边界的路径判定在 Windows 上偶发误判（报「在项目外」但两个路径前缀完全一致）。改用 `os.path.abspath` 做字符串归一化 + 只对**最近存在祖先**做 `resolve()` 防软链接逃逸。整包连跑 6 轮 0 失败（修复前 5 轮失败 2 次）。
  2. `_publish_execution_failure()` 形参是 `done_roles/failed_roles`，两处调用点却传 `done=/failed=` → **任何 worker 失败都会再抛 `TypeError`，把真实原因盖掉**。已修。
- 验证：新增 `tests/test_job_queue.py` 19 项 + `tests/test_permissions.py` 3 项（含用 `mklink /J` 真建目录联接验证越界拦截，不跳过）；全量 **291 项 OK**。
- 遗留：N37 —— **跨进程写锁仍缺**（串行只在单进程内生效）。

### v0.17.14：本机 Web API 请求加固（台账「安全方案 · 问题 2」第一版）

- 问题：API 绑在 `127.0.0.1` 但没有 Host / Origin 校验和请求体上限。威胁是 DNS rebinding（别人的域名解析到本机、浏览器视为同源可读响应）和跨站触发（任意网页 `fetch` 本机接口，响应被 CORS 挡住但**副作用已发生**：起任务、花 API 钱、写文件）。
- 修复：新增 `src/code_agent_collab/web_security.py`；`webui.Handler` 的 `do_GET`/`do_POST` 入口统一校验。Host 只接受回环地址；`Origin`/`Referer` 必须回环；`Sec-Fetch-Site: cross-site` 拒绝；写接口只接受 `application/json`（跨站表单发不了这个头，带它的跨站请求会先撞 CORS 预检）；`Content-Length` > 64 KiB 在读之前 413；响应加 `nosniff` / `no-referrer` / `no-store`；单请求超时 30 秒。
- **配套必改**：页面 `/api/pause` 的 `fetch` 原本没带 Content-Type，只加防线会让暂停按钮失灵，已一并改掉。
- 验证：新增 `tests/test_web_security.py` 26 项（含起真实服务器的集成用例，关键断言是「跨站 POST → 403 且业务函数没被调用」）；真实服务冒烟 `GET /` 200、同源 POST 200、跨站 POST 403、表单型 415、假 Host 403；全量 **269 项 OK**。
- 遗留：N36 —— 仍无会话令牌、Origin 不校验端口。**要对外开放端口必须先加令牌。**

### v0.17.13：N5 权限运行时强制点 + 「项目外一律不写」硬边界

- 问题：`PermissionLevel` 只是标注，运行时零检查；同时 shin 明确要求「项目要有自己独立的知识库，不能写到库之外」。
- 修复：新增 `src/code_agent_collab/permissions.py`（叶子模块），`PermissionLevel` 从它取值；接入 8 处强制点（`apply.py` 写文件/回滚/跑测试/git 暂存与提交、`coder.py`/`integrator.py` 草稿写入、`knowledge.py` 检索摘录、`review.py` 候选状态与入库写入）。
- **硬边界**：项目目录之外的写入一律拒绝，与权限级别无关。`confirm` 遇到项目外的 `mainVaultWritePath` 会把候选标成「待人工处理」并写明「拒绝写入」，不创建文件。
- 改外部代码的正确姿势：`--project-root <目录>` / `AGENT_WORKBENCH_PROJECT_ROOT`，那时那个库就是当前项目。
- 验证：新增 `tests/test_permissions.py` 18 项 + `tests/test_review.py` 项目外拒绝 2 项；全量 **243 项 OK**；实测对一个项目外演示仓库执行 `start --project-root <仓库>`，上下文包落在 `<仓库>/logs/context-packs/`。
- 遗留：N30–N35（未接入的 20+ 写入点、可绕过的环境变量、声明与行为不一致的 Agent、MCP 子进程），已记入问题台账。

### v0.17.12：N29 打包版 `run_cli` 漏导入，任务全跑不了

- 问题：`web_jobs.run_cli()` 的 frozen 分支用了未导入的 `Path` 和 `CLI_EXE_NAME`，打包版一提交任务就抛 `NameError: name 'Path' is not defined`。
- 回归来源：v0.17.5（`fdd270d`）拆分 `webui.py` 时漏搬这两个导入，已推送基线 v0.17.6 里同样存在。
- 修复：补 `from pathlib import Path`，并从 `web_project` 导入 `CLI_EXE_NAME`。
- 验证：`tests/test_webui.py` 新增 frozen / 源码两条 `run_cli` 命令构造测试；临时回退修复后新测试确实报 `NameError`，恢复后全量 **225 项 OK**。
- 遗留边界：`dist/` 里的 EXE 是 2026-09-16 打的旧包（早于该回归），所以旧包可用；**下一次重新打 Windows 包前必须先包含本修复**。

### v0.17.7：N11 单项目旧暂停请求残留

- 问题：上一轮 `pause.json` 会让下一次 CLI 任务刚开始就暂停。
- 修复：`run`、`run-adaptive`、`approve`、`coding-loop` 启动前清理旧 pause request。
- 验证：`tests.test_cli_pause` 4 项 OK；当时全量 219 项 OK。

### v0.17.8：N28 apply-draft 选旧草稿 + Markdown 代码围栏

- 问题：真实 API 任务里 Reviewer 已生成 `coder-draft-revision1`，但 `apply-draft <task_id>` 仍选第一版旧草稿；模型输出的代码围栏也可能写进源码。
- 修复：`find_draft_path()` 优先选择最新 revision；`parse_draft()` 剥离单文件外层 fenced code。
- 验证：`tests.test_apply tests.test_cli_pause` 25 项 OK；真实 API dry-run 能选中 revision1 且未写正式源码。

### v0.17.9：N9 confirm 入库覆盖已有文件

- 问题：`confirm` 人工入库直接写 `target_dir / source_name`，同名会覆盖。
- 修复：目标文件已存在时拒绝写入，候选标记为“待人工处理”；`_write_to_vault()` 保留 `FileExistsError` 兜底。
- 验证：`tests.test_review` 13 项 OK；全量 222 项 OK。

### v0.17.10：N4 checkpoint 漏 `latest_integrator_specs`

- 问题：断点恢复若丢 Integrator spec，Fix Loop 后续可能不重跑 Integrator。
- 修复/校准：当前代码已统一通过 `_save_execution_checkpoint()` 保存；新增 round-trip 回归测试钉住。
- 验证：`tests.test_adaptive_workflow` 14 项 OK；全量 223 项 OK。

### v0.17.11：N12 WorkerRun 只保留最后状态

- 问题：`logs/runs/<task_id>/workers.json` 原来只保留每个 worker 的最新状态；失败后重试会抹掉第一次失败原因。
- 当前改动：
  - `WorkerRunAttempt` 新增为结构化历史项。
  - `WorkerRunRecord` 新增 `attempts` 列表。
  - `_save_record()` 保存时把当前状态追加到 attempts，同时保留顶层最新状态。
  - `_record_from_json()` 兼容旧文件：没有 attempts 时用顶层记录补一条历史。
  - `tests.test_adaptive_workflow` 已补断言：模块 B 历史为 `running -> failed -> running -> success`，并检查 `workers.json` 落盘内容。
- 已跑 targeted：`python -m unittest tests.test_adaptive_workflow` → 14 项 OK。
- 全量复验已通过：`python scripts/run-tests.py` → 223 项 OK。

## 5. 当前未完成的高优先级问题

按当前台账优先级继续：

1. 真实 Provider 小型代码修改的完整 `--apply` 验证。
   - 已经验证过 DeepSeek API 能跑通方案生成、执行、Reviewer 打回、返工、apply-draft dry-run。
   - 还没有执行真实 `--apply`，也没有验证真实模型自动改正式源码后通过测试。
   - 必须先让用户确认 diff，再 `--apply`。

2. N22：Fix Loop 打回范围过宽。
   - 当前 Reviewer 打回后可能 Coder + Integrator 都重跑。
   - 理想方向：Reviewer 结论带“问题归属”，按归属决定只重跑 Coder、只重跑 Integrator 或都重跑。

3. N5 权限等级偏声明式 —— **已完成第一版（v0.17.13）**。
   - 强制点已建立：`src/code_agent_collab/permissions.py`（`check_write` / `check_command` / `ensure_inside_project`）。
   - 剩余是完成度问题，拆成 N30–N35：未接入的 20+ 写入点（N30，P1）、可绕过边界的环境变量（N31）、声明与行为不一致的 Agent（N32/N33）、MCP 子进程（N34）。
   - 下一步建议：按 N30 分批接入，优先 `config.py`、`review._mark_status`、`reflection.py`。

4. Web API 安全项 —— **请求级加固已完成第一版（v0.17.14）**。
   - 已有：Host / Origin / Sec-Fetch-Site / Content-Type 校验、请求体 64 KiB 上限、安全响应头、请求超时。
   - 剩余 N36：没有会话令牌，Origin 不校验端口。**要把端口对外开放（哪怕只是局域网）必须先补令牌。**

5. 后台任务与并发 —— **已完成第一版（v0.17.15）**。
   - 已有：并发上限 2、等待队列上限 8（满了 429）、写命令串行、重复提交去重、记录落盘 `logs/jobs/`、重启标记中断不重跑、`GET /api/jobs` 历史。
   - 剩余 N37：**跨进程写锁仍缺**（当前串行只在单个服务进程内）。网页版 + 终端同时跑同一项目仍可能互相踩。

6. 其他：N10/N14/N15/N16/N17/N18/N6/N7/N8；以及 N30–N35（权限边界未覆盖面）。

## 6. 重要文件

- 问题台账：`C:\Users\<你的用户名>\Desktop\多Agent代码协作助手-当前问题整理.md`
- 项目规则：`AGENTS.md`
- 技能沉淀：`SKILLS.md`（§48 权限边界、§49 Web API 加固、§50 后台任务队列、§51 路径包含判定的坑）
- 变更记录：`CHANGELOG.md`
- 版本记录：`VERSIONING.md`
- 权限强制点：`src/code_agent_collab/permissions.py`
- 后台任务调度：`src/code_agent_collab/web_jobs.py`；持久化：`src/code_agent_collab/job_store.py`；测试 `tests/test_job_queue.py`
- 权限测试：`tests/test_permissions.py`；入库边界测试在 `tests/test_review.py`
- Web 请求防线：`src/code_agent_collab/web_security.py`；测试 `tests/test_web_security.py`（含起真实服务器的集成用例）
- N29 代码：`src/code_agent_collab/web_jobs.py`（frozen 分支）、常量定义在 `src/code_agent_collab/web_project.py`
- N29 测试：`tests/test_webui.py`（`RunCliTests`）
- 未定义名字自查脚本：`scripts/check-undefined-names.py`（`symtable` 按作用域扫描，`python scripts/check-undefined-names.py src tests`，退出码 1 表示有命中）

## 7. 安全边界和禁止事项

- 不要打印、记录、提交任何 API Key。
- 真实 API 环境变量如果出现，只能检查存在/不存在，不要输出值。
- Windows 用户级环境变量里的 key 测完要删；当前 Codex 父进程可能还残留 process env，重启 Codex 才会彻底消失。
- 不要 push、打 tag、发 Release、重新打包，除非 shin 明确要求。
- 不要把真实 `--apply` 当普通测试跑；必须先 dry-run 看 diff，再让 shin 确认。
- PowerShell 不支持 Bash heredoc：不要写 `python - <<'PY'`。多行 Python 用 here-string 管道。

## 8. 标准收尾流程

每完成一个小闭环：

1. 更新代码和测试。
2. 跑 targeted 测试。
3. 跑 `python scripts/run-tests.py`。
4. 更新 `CHANGELOG.md`、`VERSIONING.md`、`SKILLS.md`。
5. 更新外部问题台账。
6. 做敏感扫描：使用项目常用的 `rg` 敏感信息扫描，排除 `logs/`、`dev-vault/`、`dist/`、`build/`。命中测试假 key 和源码 header 字段名可以接受；不能有真实 key。

7. `git status --short --branch` 和 `git diff --stat`。
8. 本地 commit。


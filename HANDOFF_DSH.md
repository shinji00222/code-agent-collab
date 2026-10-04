# DSH 接手文档：多 Agent 代码协作助手

更新时间：2026-10-04

这份文档用于当前 Codex 上下文不足时让 DSH 直接接手。它只写项目状态、验证命令、风险边界和下一步，不包含任何 API Key。

## 1. 项目路径与当前状态

- 项目根目录：`C:\Users\lwz12\Desktop\AI工作台知识库\01-项目\project 多Agent代码协作助手`
- 当前分支：`main`
- 当前本地版本：`v0.17.12`
- 远端公开基线：`origin/main` / tag `v0.17.6` / commit `168aa6f`
- 本地状态：提交后预计比远端 ahead 6（v0.17.7 到 v0.17.12），未 push、未打 tag、未发 GitHub Release、未重新打 Windows 包。
- 用户要求：继续推进项目，把发现的问题都解决，重点关注安全性、可靠性、权限分级。

## 2. 接手后第一步必须做

在 PowerShell 里运行：

```powershell
Set-Location -LiteralPath 'C:\Users\lwz12\Desktop\AI工作台知识库\01-项目\project 多Agent代码协作助手'
git status --short --branch
git log --oneline -8
$env:AGENT_WORKBENCH_PROVIDER='mock'
python scripts/run-tests.py
```

预期：

- 分支应为 `main...origin/main [ahead 6]` 左右。
- 全量测试应通过，当前基线是 **225 项 OK**；v0.17.12 的 targeted 复验是 `python -m unittest tests.test_adaptive_workflow` → 14 项 OK（注意该模块名只在 `PYTHONPATH` 含 `tests` 时可直接按模块名导入，最稳的是直接跑 `python scripts/run-tests.py`）。
- 正常接手时，v0.17.11 / v0.17.12 应已经本地提交；如果 `git status` 仍显示未提交，先检查 diff 和测试，再提交。

```powershell
git add -- .
git commit -m "fix: restore packaged CLI invocation"
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
6. v0.17.12 打包版 `run_cli` 回归修复，提交信息：`fix: restore packaged CLI invocation`

## 4. 已完成的问题闭环

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

3. N5：权限等级仍偏声明式。
   - `PermissionLevel` 会写进日志/账本，但运行时强制点还不够系统。
   - 下一步可以先做“命令/文件写入路径按 permission 做统一 guard”的小闭环，不要一口气重构全权限系统。

4. Web API 安全项。
   - Host / Origin / 请求体大小 / 本地访问边界。
   - 做之前先读 `webui.py`、`web_jobs.py`、`web_project.py`、`tests/test_webui.py`。

5. 其他：N10/N14/N15/N16/N17/N18/N6/N7/N8。

## 6. 重要文件

- 问题台账：`C:\Users\lwz12\Desktop\多Agent代码协作助手-当前问题整理.md`
- 项目规则：`AGENTS.md`
- 技能沉淀：`SKILLS.md`
- 变更记录：`CHANGELOG.md`
- 版本记录：`VERSIONING.md`
- 当前 N29 代码：`src/code_agent_collab/web_jobs.py`（frozen 分支）、常量定义在 `src/code_agent_collab/web_project.py`
- 当前 N29 测试：`tests/test_webui.py`（`RunCliTests`）
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


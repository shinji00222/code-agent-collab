# 多 Agent 代码协作助手

[English](README.md) | [简体中文](README.zh-CN.md)

一个本地优先的代码 Agent 工作台，用来把一次代码需求变成更可控的软件工程流程：理解项目、生成计划、写草稿、审查结果、预览 diff、运行测试，最后再决定是否应用改动。

这个项目不是为了堆更多 Agent。重点是让多 Agent 协作更像一个谨慎的工程闭环。

## 它能做什么

- 从项目文档和源码里构建任务上下文。
- 按需要启用 Planner、Coder、Reviewer、Integrator、Knowledge 等角色。
- 先把 AI 生成内容放进隔离草稿区，不直接改正式源码。
- 检查草稿的路径范围、固定小节、风险、敏感信息和测试说明。
- 支持 dry-run，先预览 diff 再决定是否应用。
- 应用改动前运行测试，通过后再提交本地 commit。
- 长期知识写入需要人工确认，避免自动污染知识库。
- 默认使用本地 mock provider，新环境运行时不会自动调用外部 API。

## 当前状态

当前版本：`v0.17.13`

当前主线：**Stable Coding Loop -> Hierarchical Context -> Evaluation**。

项目仍然是实验原型，但主流程会刻意保守：先草稿、再审查、再预览 diff、再测试，最后才应用。

## 快速开始

需要 Python 3.11 或更高版本。

```powershell
git clone https://github.com/shinji00222/code-agent-collab.git
cd code-agent-collab
$env:PYTHONPATH="src"
python -m code_agent_collab.cli provider
python -m code_agent_collab.cli coding-loop "add a tiny test"
```

上面的命令默认是 dry-run，只预览建议改动。确认要应用通过审查的草稿时，再运行：

```powershell
python -m code_agent_collab.cli coding-loop "add a tiny test" --apply
```

项目默认使用本地 `mock` provider。只有你想接真实模型时，才需要配置 DeepSeek、OpenAI 或 OpenAI-compatible provider。

## 常用命令

```powershell
$env:PYTHONPATH="src"
python -m code_agent_collab.cli provider
python -m code_agent_collab.cli start "任务目标"
python -m code_agent_collab.cli run-adaptive "任务目标"
python -m code_agent_collab.cli plans
python -m code_agent_collab.cli approve "任务ID或关键词"
python -m code_agent_collab.cli apply-draft "任务ID或关键词"
python -m code_agent_collab.cli coding-loop "任务目标" [--apply]
python -m code_agent_collab.webui
python -m code_agent_collab.desktop
```

## 安全边界

项目默认把 AI 产出和真实项目文件隔离开：

- 代码草稿写入 `dev-vault/projects`；
- 候选知识写入 `dev-vault/pending`；
- 正式源码需要显式 apply 才会被修改；
- 公开示例配置可以提交，真实本地配置会被忽略；
- 密钥只通过环境变量传入，不应该写进仓库。

## 项目结构

```text
src/code_agent_collab/   程序源码
tests/                   自动化测试
product-docs/            产品说明和设计文档
dev-vault/               草稿区和隔离项目知识库
logs/                    本地运行日志和进度快照
scripts/                 打包与配置脚本
```

## 文档

- [English README](README.md)
- [版本管理](VERSIONING.md)
- [变更记录](CHANGELOG.md)
- [维护指南](MAINTENANCE.md)
- [项目技能](SKILLS.md)
- [科研路线](RESEARCH_ROADMAP.md)
- [代码简化优化规划](product-docs/code-simplification-plan.md)

## 测试

```powershell
$env:PYTHONPATH="src"
python scripts/run-tests.py
```

也可以运行标准 unittest：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

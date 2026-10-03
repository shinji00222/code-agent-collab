# 写代码前检查清单

## 什么时候可以开始写代码

满足以下条件后，才进入代码实现：

- 项目定义已经明确；
- MVP 范围已经明确；
- 主知识库和 dev-vault 的隔离规则已经明确；
- Agent 协作协议已经明确；
- 自生长规则已经明确；
- 任务上下文包格式已经明确；
- CLI 命令草案已经明确；
- 数据文件格式已经明确。

## 第一段代码要实现什么

第一段代码只实现一个最小可运行 CLI：

```powershell
agent-workbench start "测试任务"
```

它只做四件事：

- 读取当前项目配置；
- 读取 `product-docs` 中的项目规则；
- 生成一个任务上下文包；
- 把结果写入 `logs/context-packs`。

## 第一段代码不实现什么

- 不调用真实 AI API；
- 不自动写主知识库；
- 不做复杂 Agent 调度；
- 不做前端界面；
- 不做云同步；
- 不做数据库。

## 推荐技术选择

第一版建议使用 Python。

原因：

- Windows 上容易运行；
- 读写 Markdown 和 JSON 简单；
- 适合先做命令行原型；
- 后续可以再接 OpenAI、Claude、Gemini 或本地模型 API；
- 不需要一开始引入复杂前端工程。

## 第一版目录结构

```text
src/code_agent_collab/
  __init__.py
  cli.py
  config.py
  context_pack.py
  file_utils.py
tests/
  test_context_pack.py
```

## 验证方式

第一段代码完成后，至少验证：

- 命令能运行；
- 能生成上下文包文件；
- 生成文件在 `logs/context-packs`；
- 不写入主知识库；
- Git 状态可解释。

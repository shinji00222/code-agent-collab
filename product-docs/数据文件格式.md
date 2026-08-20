# 数据文件格式

## 目标

第一版尽量使用 Markdown 和 JSON 文件保存数据，避免一开始引入数据库。这样方便 Obsidian 查看，也方便 Git 记录变化。

## 任务日志

位置：

```text
logs/tasks/<任务ID>.md
```

格式：

```md
# 任务日志：<任务标题>

## 基本信息

- 任务ID：
- 创建时间：
- 当前项目路径：
- Git 分支：
- Git 状态：

## 用户请求

原始请求：

## 上下文摘要

## 执行过程

## 验证结果

## 产出文件

## 遗留风险
```

## 任务上下文包

位置：

```text
logs/context-packs/<任务ID>.md
```

内容遵守 `product-docs/任务上下文包格式.md`。

## 候选复利记录

位置：

```text
dev-vault/pending/<日期>-<任务ID>-复利候选.md
```

格式：

```md
# 候选复利记录

## 来源

- 任务ID：
- 生成时间：
- 来源日志：

## 候选内容

- 日期：
- 场景：
- 问题或经验：
- 原因：
- 以后采用的规则：
- 验证方式：
- 建议写入位置：

## 状态

- 状态：待用户确认
- 是否包含敏感信息：否
- 是否已经验证：
```

## 本地配置

位置：

```text
.agent-workbench/config.json
```

第一版字段：

```json
{
  "projectName": "多Agent代码协作助手",
  "mainVaultPath": "C:\\path\\to\\main-vault",
  "devVaultPath": "C:\\path\\to\\project\\dev-vault",
  "mainVaultDefaultMode": "readonly",
  "devVaultDefaultMode": "readwrite"
}
```

## 文件格式原则

- 用户要能直接用 Obsidian 阅读；
- 机器要能稳定解析；
- 不保存密码、令牌、Cookie、API Key；
- 不把大段聊天原文直接写入长期知识库；
- 文件名要包含日期或任务ID，方便追踪。

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import WorkbenchConfig, load_config
from .file_utils import ensure_dir, read_text, simple_task_slug, write_text


@dataclass(frozen=True)
class ContextPackResult:
    task_id: str
    output_path: Path


def _git_value(project_root: Path, args: list[str], fallback: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return fallback
    if result.returncode != 0:
        return fallback
    return result.stdout.strip() or fallback


def _read_project_docs(project_root: Path) -> list[tuple[str, str]]:
    docs_dir = project_root / "product-docs"
    if not docs_dir.exists():
        return []
    docs = []
    for path in sorted(docs_dir.glob("*.md"), key=lambda item: item.name.lower()):
        content = read_text(path).strip()
        docs.append((path.name, content))
    return docs


def _doc_excerpt(content: str, max_chars: int = 1200) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip() + "\n\n...（已截断，原文仍在 product-docs 中）"


def build_context_pack(project_root: Path, task_goal: str, now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now()
    cfg = load_config(project_root)
    task_id = f"{now:%Y%m%d-%H%M%S}-{simple_task_slug(task_goal)}"
    branch = _git_value(project_root, ["rev-parse", "--abbrev-ref", "HEAD"], "未能获取")
    git_status = _git_value(project_root, ["status", "--short"], "干净或未能获取")
    docs = _read_project_docs(project_root)

    return task_id, _render_context_pack(
        task_id=task_id,
        task_goal=task_goal,
        project_root=project_root,
        cfg=cfg,
        branch=branch,
        git_status=git_status,
        docs=docs,
        now=now,
    )


def _render_context_pack(
    task_id: str,
    task_goal: str,
    project_root: Path,
    cfg: WorkbenchConfig,
    branch: str,
    git_status: str,
    docs: list[tuple[str, str]],
    now: datetime,
) -> str:
    docs_index = "\n".join(f"- {name}" for name, _ in docs) or "- 未找到项目文档"
    docs_content = "\n\n".join(
        f"### {name}\n\n{_doc_excerpt(content)}" for name, content in docs
    ) or "未读取到项目文档。"

    return f"""# 任务上下文包：{task_goal}

## 基本信息

- 任务ID：{task_id}
- 用户原始请求：{task_goal}
- 当前项目路径：{project_root}
- 当前 Git 分支：{branch}
- 当前 Git 状态：{git_status}
- 任务开始时间：{now:%Y-%m-%d %H:%M:%S}
- 任务完成标准：生成可供 AI Agent 使用的上下文包，不写入主知识库。

## 知识库范围

- 主知识库只读范围：{cfg.main_vault_path}
- dev-vault 可读写范围：{cfg.dev_vault_path}
- 本次禁止读取的范围：未授权的隐私、账号、密钥、令牌、Cookie。
- 本次禁止写入的范围：主知识库默认禁止自动写入。

## 相关项目文档

{docs_index}

## 项目文档摘录

{docs_content}

## 执行计划

- 要做什么：围绕用户任务整理项目规则、知识库边界、Git 状态和相关文档。
- 不做什么：不调用真实 AI API；不修改主知识库；不执行部署、删除、推送等高风险操作。
- 风险点：如果项目文档不完整，上下文包只能反映当前已有文档。
- 需要用户确认的操作：任何写入主知识库、删除、移动、上传、部署或推送操作。

## 执行记录

- 已执行命令：由调用方或任务日志补充。
- 已修改文件：本命令只生成当前上下文包。
- 已生成文件：`logs/context-packs/{task_id}.md`
- 失败尝试：暂无。
- 解决方式：暂无。

## 验证结果

- 文件是否存在：生成后检查。
- Git 状态：生成文件会作为未提交改动出现。
- 测试或检查命令：`python -m unittest`
- 验证结论：待验证。

## 候选复利记录

```text
日期：
场景：
问题或经验：
原因：
以后采用的规则：
验证方式：
建议写入位置：
```
"""


def create_context_pack(project_root: Path, task_goal: str) -> ContextPackResult:
    task_id, content = build_context_pack(project_root, task_goal)
    output_path = project_root / "logs" / "context-packs" / f"{task_id}.md"
    ensure_dir(output_path.parent)
    write_text(output_path, content)
    return ContextPackResult(task_id=task_id, output_path=output_path)

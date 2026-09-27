from __future__ import annotations

import re
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


@dataclass(frozen=True)
class SelectedContextDoc:
    name: str
    content: str
    reason: str
    estimated_tokens: int


@dataclass(frozen=True)
class ContextSelectionItem:
    layer: str
    source: str
    reason: str
    estimated_tokens: int


MAX_CONTEXT_DOCS = 6
DOC_EXCERPT_CHARS = 1200


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


def _estimate_tokens(text: str) -> int:
    # 粗略预算只用于上下文选择记录，不等同于真实 Provider 计费。
    return max(1, (len(text) + 3) // 4)


def _task_keywords(task_goal: str) -> list[str]:
    lowered = task_goal.lower()
    words = [item for item in re.split(r"[\W_]+", lowered) if len(item) >= 2]
    phrases = re.findall(r"[\u4e00-\u9fff]{2,12}", task_goal)
    keywords = words + phrases
    if "上下文" in task_goal or "context" in lowered:
        keywords.extend(["上下文", "context", "任务上下文包", "知识库", "memory"])
    if "测试" in task_goal or "test" in lowered:
        keywords.extend(["测试", "验证", "test"])
    if "代码" in task_goal or "coding" in lowered or "coding-loop" in lowered:
        keywords.extend(["代码", "coding", "apply-draft", "Agent"])
    return list(dict.fromkeys(keywords))


def _score_doc(name: str, content: str, keywords: list[str]) -> tuple[int, str]:
    searchable = f"{name}\n{content}".lower()
    score = 0
    matched: list[str] = []
    for keyword in keywords:
        lowered = keyword.lower()
        if not lowered:
            continue
        if lowered in name.lower():
            score += 5
            matched.append(keyword)
        elif lowered in searchable:
            score += 1
            matched.append(keyword)
    if score == 0:
        return 0, "未命中任务关键词，未进入本轮上下文。"
    unique = "、".join(list(dict.fromkeys(matched))[:4])
    return score, f"命中任务关键词：{unique}"


def _select_context_docs(docs: list[tuple[str, str]], task_goal: str) -> list[SelectedContextDoc]:
    keywords = _task_keywords(task_goal)
    scored: list[tuple[int, str, str, str]] = []
    for name, content in docs:
        score, reason = _score_doc(name, content, keywords)
        if score > 0:
            scored.append((score, name, content, reason))
    if not scored:
        scored = [
            (1, name, content, "未命中关键词，作为基础项目文档保底选择。")
            for name, content in docs[:MAX_CONTEXT_DOCS]
        ]
    scored.sort(key=lambda item: (-item[0], item[1].lower()))
    selected = []
    for _, name, content, reason in scored[:MAX_CONTEXT_DOCS]:
        selected.append(
            SelectedContextDoc(
                name=name,
                content=content,
                reason=reason,
                estimated_tokens=_estimate_tokens(_doc_excerpt(content, DOC_EXCERPT_CHARS)),
            )
        )
    return selected


def _context_selection_items(
    task_goal: str,
    branch: str,
    git_status: str,
    selected_docs: list[SelectedContextDoc],
) -> list[ContextSelectionItem]:
    items = [
        ContextSelectionItem(
            layer="task",
            source="用户原始请求",
            reason="本轮任务目标，所有后续上下文都围绕它选择。",
            estimated_tokens=_estimate_tokens(task_goal),
        ),
        ContextSelectionItem(
            layer="repo",
            source="Git 分支与状态",
            reason="判断当前代码基线、脏工作区和可否安全应用改动。",
            estimated_tokens=_estimate_tokens(branch + git_status),
        ),
    ]
    for doc in selected_docs:
        items.append(
            ContextSelectionItem(
                layer="project-doc",
                source=f"product-docs/{doc.name}",
                reason=doc.reason,
                estimated_tokens=doc.estimated_tokens,
            )
        )
    return items


def build_context_pack(project_root: Path, task_goal: str, now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now()
    cfg = load_config(project_root)
    task_id = f"{now:%Y%m%d-%H%M%S}-{simple_task_slug(task_goal)}"
    branch = _git_value(project_root, ["rev-parse", "--abbrev-ref", "HEAD"], "未能获取")
    git_status = _git_value(project_root, ["status", "--short"], "干净或未能获取")
    docs = _read_project_docs(project_root)
    selected_docs = _select_context_docs(docs, task_goal)
    selection_items = _context_selection_items(task_goal, branch, git_status, selected_docs)

    return task_id, _render_context_pack(
        task_id=task_id,
        task_goal=task_goal,
        project_root=project_root,
        cfg=cfg,
        branch=branch,
        git_status=git_status,
        docs=selected_docs,
        selection_items=selection_items,
        now=now,
    )


def _render_context_pack(
    task_id: str,
    task_goal: str,
    project_root: Path,
    cfg: WorkbenchConfig,
    branch: str,
    git_status: str,
    docs: list[SelectedContextDoc],
    selection_items: list[ContextSelectionItem],
    now: datetime,
) -> str:
    docs_index = "\n".join(f"- {doc.name}（{doc.reason}）" for doc in docs) or "- 未找到项目文档"
    docs_content = "\n\n".join(
        f"### {doc.name}\n\n{_doc_excerpt(doc.content, DOC_EXCERPT_CHARS)}" for doc in docs
    ) or "未读取到项目文档。"
    selection_log = "\n".join(
        f"- [{item.layer}] {item.source}：{item.reason}（约 {item.estimated_tokens} tokens）"
        for item in selection_items
    )
    token_budget = sum(item.estimated_tokens for item in selection_items)

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

- 知识检索来源：{cfg.main_vault_path}
- 知识写入目标：{cfg.main_vault_write_path or cfg.main_vault_path}
- dev-vault 可读写范围：{cfg.dev_vault_path}
- 本次禁止读取的范围：未授权的隐私、账号、密钥、令牌、Cookie。
- 本次禁止写入的范围：项目自有知识库以外的任何知识库（默认读写都只在项目内进行）。

## 上下文选择记录

{selection_log}

## Token 预算估算

- 已选上下文约：{token_budget} tokens。
- 项目文档选择上限：最多 {MAX_CONTEXT_DOCS} 个文档，每篇摘录最多 {DOC_EXCERPT_CHARS} 字符。
- 说明：这是本地粗略估算，用于控制上下文规模，不等同于真实 API 计费。

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

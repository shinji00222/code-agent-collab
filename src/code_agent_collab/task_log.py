from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .file_utils import ensure_dir, write_text


@dataclass(frozen=True)
class TaskLogSnapshot:
    task_id: str
    goal: str
    status: str
    detail: str
    completed: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=datetime.now)


def task_log_path(project_root: Path, task_id: str) -> Path:
    return project_root / "logs" / "tasks" / f"{task_id}.md"


def write_task_log(project_root: Path, snapshot: TaskLogSnapshot) -> Path:
    path = task_log_path(project_root, snapshot.task_id)
    ensure_dir(path.parent)
    write_text(path, _render_task_log(project_root, snapshot))
    return path


def _render_task_log(project_root: Path, snapshot: TaskLogSnapshot) -> str:
    branch = _git_value(project_root, ["branch", "--show-current"], "unknown")
    status = _git_value(project_root, ["status", "--short", "--branch"], "unknown")
    return "\n".join(
        [
            f"# 任务日志：{snapshot.goal}",
            "",
            "## 基本信息",
            "",
            f"- 任务ID：{snapshot.task_id}",
            f"- 更新时间：{snapshot.updated_at:%Y-%m-%d %H:%M:%S}",
            f"- 当前项目路径：{project_root}",
            f"- Git 分支：{branch}",
            "- Git 状态：",
            "",
            "```text",
            status,
            "```",
            "",
            "## 用户请求",
            "",
            snapshot.goal,
            "",
            "## 当前状态快照",
            "",
            f"- 状态：{snapshot.status}",
            f"- 详情：{snapshot.detail}",
            _list_section("已完成", snapshot.completed),
            _list_section("未完成", snapshot.pending),
            _list_section("当前阻塞", snapshot.blocked),
            _list_section("下一步", snapshot.next_steps),
            "",
            "## 产出文件",
            "",
            _bullet_list(snapshot.outputs),
            "",
            "## 验证结果",
            "",
            "由当前工作流或人工收尾补充；本文件只记录任务状态快照。",
            "",
            "## 遗留风险",
            "",
            "真实 Provider / API 接入表现需要单独实测。",
            "",
        ]
    )


def _list_section(title: str, items: tuple[str, ...]) -> str:
    return "\n".join(["", f"### {title}", "", _bullet_list(items)])


def _bullet_list(items: tuple[str, ...]) -> str:
    if not items:
        return "- 无"
    return "\n".join(f"- {item}" for item in items)


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

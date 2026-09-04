from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .file_utils import ensure_dir


PROGRESS_ENV = "AGENT_WORKBENCH_PROGRESS_FILE"
ROLE_LABELS = {
    "ContextPack": "ContextPack",
    "CoordinatorAgent": "Coordinator",
    "KnowledgeAgent": "Knowledge",
    "PlannerAgent": "Planner",
    "OrchestratorAgent": "Orchestrator",
    "CoderAgent": "CoderAgent",
    "ReviewerAgent": "ReviewerAgent",
    "ValidatorAgent": "Validator",
    "ReflectorAgent": "Reflector",
    "PauseGate": "Pause",
    "ForceStop": "Force Stop",
}


def progress_path(project_root: Path) -> Path:
    """返回当前任务进度文件；Web UI 可用环境变量指定独立路径。"""
    configured = os.getenv(PROGRESS_ENV)
    if configured:
        return Path(configured).resolve()
    return project_root / "logs" / "progress" / "current.json"


def node(label: str, status: str, detail: str) -> dict:
    return {"kind": "node", "label": label, "status": status, "detail": detail}


def branch(children: list[dict]) -> dict:
    return {"kind": "branch", "children": children}


def lane(label: str, status: str, detail: str, *, role: str | None = None) -> dict:
    item = node(label, status, detail)
    item["role"] = role or label
    return item


def workflow_tree(
    stages: list[list[dict]],
    *,
    done: set[str] | None = None,
    running: set[str] | None = None,
    waiting: set[str] | None = None,
    failed: set[str] | None = None,
) -> list[dict]:
    done = done or set()
    running = running or set()
    waiting = waiting or set()
    failed = failed or set()
    tree: list[dict] = []
    for stage in stages:
        children = []
        for item in stage:
            role = str(item.get("role", item["label"]))
            status = "idle"
            if role in failed:
                status = "failed"
            elif role in running:
                status = "running"
            elif role in waiting:
                status = "waiting"
            elif role in done:
                status = "done"
            children.append(
                lane(
                    str(item["label"]),
                    status,
                    str(item.get("detail", "")),
                    role=role,
                )
            )
        if len(children) == 1:
            tree.append(children[0])
        elif children:
            tree.append(branch(children))
    return tree


def role_stage(role: str, detail: str = "") -> list[dict]:
    return [{"role": role, "label": ROLE_LABELS.get(role, role), "detail": detail}]


def publish_progress(
    project_root: Path,
    *,
    task_id: str,
    goal: str,
    status: str,
    detail: str,
    nodes: list[dict],
) -> Path:
    """原子写入轻量进度快照，供 Web UI 在任务执行中轮询。"""
    path = progress_path(project_root)
    ensure_dir(path.parent)
    payload = {
        "task_id": task_id,
        "goal": goal,
        "status": status,
        "detail": detail,
        "updated_at": datetime.now().isoformat(timespec="milliseconds"),
        "nodes": nodes,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def read_progress(project_root: Path) -> dict | None:
    path = progress_path(project_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload.get("nodes"), list):
        return None
    payload["path"] = str(path)
    return payload

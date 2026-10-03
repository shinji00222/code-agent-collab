from __future__ import annotations

import json
import re
from pathlib import Path

from .blackboard import blackboard_snapshot
from .control import CHECKPOINT_SUFFIX, control_dir
from .progress import read_progress
from .web_project import PROJECT_ROOT

def _latest_path(folder: Path, pattern: str) -> Path | None:
    if not folder.exists():
        return None
    matches = sorted(folder.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _node(label: str, status: str, detail: str) -> dict:
    return {"kind": "node", "label": label, "status": status, "detail": detail}


def _role_counts(workflow_path: Path | None) -> dict[str, int]:
    if workflow_path is None or not workflow_path.exists():
        return {}
    content = workflow_path.read_text(encoding="utf-8", errors="replace")
    counts: dict[str, int] = {}
    for role in re.findall(r"^##\s+([A-Za-z]+Agent)\s*$", content, flags=re.MULTILINE):
        counts[role] = counts.get(role, 0) + 1
    return counts


def _consume_role(counts: dict[str, int], role: str) -> bool:
    value = counts.get(role, 0)
    if value <= 0:
        return False
    counts[role] = value - 1
    return True


def _plan_snapshot(plan_path: Path | None, workflow_path: Path | None) -> tuple[dict | None, list[dict]]:
    if plan_path is None:
        return None, []
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    task_id = data["task_id"]
    workflow_done = workflow_path is not None and workflow_path.name == f"{task_id}-adaptive.md"
    status = "已执行" if workflow_done else "待批准"
    plan = {
        "task_id": task_id,
        "goal": data.get("goal", ""),
        "status": status,
        "complexity": data.get("complexity", ""),
        "label": data.get("label", ""),
        "worker_count": data.get("worker_count", 0),
    }

    counts = _role_counts(workflow_path if workflow_done else None)
    nodes = [
        _node("ContextPack", "done", "生成任务上下文包"),
        _node("OrchestratorAgent", "done", f"{plan['complexity']} · {plan['label']}"),
        _node("人工审批", "done" if workflow_done else "waiting", "approve 后才执行 worker"),
    ]
    for stage_index, stage in enumerate(data.get("stages", []), start=1):
        children = []
        for item in stage:
            if isinstance(item, dict):
                role = item.get("role", "")
                label = item.get("label", "")
                owned_paths = item.get("owned_paths", [])
            else:
                role = item[0]
                label = item[1]
                owned_paths = []
            done = _consume_role(counts, role)
            node_label = role if not label else f"{role}({label})"
            detail = f"阶段 {stage_index}"
            if owned_paths:
                detail = f"{detail} · 负责 {', '.join(owned_paths)}"
            children.append(
                {
                    "kind": "node",
                    "label": node_label,
                    "status": "done" if done else "idle",
                    "detail": detail,
                }
            )
        if len(children) == 1:
            nodes.append(children[0])
        elif children:
            nodes.append({"kind": "branch", "children": children})
    return plan, nodes


def _checkpoint_snapshot(project_root: Path, plan_path: Path | None) -> dict | None:
    folder = control_dir(project_root)
    if not folder.exists():
        return None
    if plan_path is not None:
        try:
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
            task_id = str(plan_data["task_id"])
            candidates = [folder / f"{task_id}{CHECKPOINT_SUFFIX}"]
        except (OSError, KeyError, json.JSONDecodeError):
            candidates = []
    else:
        candidates = []
    candidates.extend(
        sorted(
            folder.glob(f"*{CHECKPOINT_SUFFIX}"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    )
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task_id = str(data.get("task_id", ""))
        if not task_id:
            continue
        matches_latest_plan = False
        if plan_path is not None:
            try:
                plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
                matches_latest_plan = str(plan_data.get("task_id", "")) == task_id
            except (OSError, json.JSONDecodeError):
                matches_latest_plan = False
        return {
            "task_id": task_id,
            "next_stage_index": int(data.get("next_stage_index", 0)),
            "done_roles": [str(item) for item in data.get("done_roles", [])],
            "updated_at": str(data.get("updated_at", "")),
            "path": str(path),
            "matches_latest_plan": matches_latest_plan,
        }
    return None


def _workflow_snapshot(workflow_path: Path | None) -> tuple[dict | None, list[dict]]:
    if workflow_path is None:
        return None, []
    content = workflow_path.read_text(encoding="utf-8", errors="replace")
    roles = re.findall(r"^##\s+([A-Za-z]+Agent)\s*$", content, flags=re.MULTILINE)
    task_match = re.search(r"^- 任务ID：(.+)$", content, flags=re.MULTILINE)
    task_id = task_match.group(1).strip() if task_match else workflow_path.stem
    workflow = {"task_id": task_id, "path": str(workflow_path)}
    if not roles:
        return workflow, []
    nodes = [_node("ContextPack", "done", "生成任务上下文包")]
    for role in roles:
        nodes.append(_node(role, "done", "工作流日志已记录"))
    return workflow, nodes


def build_progress_snapshot(project_root: Path = PROJECT_ROOT) -> dict:
    """构建 Web UI 使用的只读进度快照。"""
    runtime_progress = read_progress(project_root)
    plan_path = _latest_path(project_root / "logs" / "plans", "*.json")
    latest_checkpoint = _checkpoint_snapshot(project_root, plan_path)
    workflow_path = _latest_path(project_root / "logs" / "workflows", "*.md")
    matching_workflow_path = None
    if plan_path is not None:
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        candidate = project_root / "logs" / "workflows" / f"{plan_data['task_id']}-adaptive.md"
        matching_workflow_path = candidate if candidate.exists() else None
    latest_workflow, workflow_nodes = _workflow_snapshot(matching_workflow_path or workflow_path)
    latest_plan, plan_nodes = _plan_snapshot(plan_path, matching_workflow_path)
    if (
        latest_plan is not None
        and latest_checkpoint is not None
        and latest_checkpoint.get("matches_latest_plan")
    ):
        latest_plan["status"] = "已暂停"
    if latest_plan is not None:
        latest_workflow, _ = _workflow_snapshot(matching_workflow_path)
    nodes = plan_nodes or workflow_nodes
    blackboard = _blackboard_for_snapshot(project_root, runtime_progress, latest_plan, latest_workflow)
    if runtime_progress is not None:
        latest_plan = latest_plan or {
            "task_id": runtime_progress.get("task_id", ""),
            "goal": runtime_progress.get("goal", ""),
            "status": runtime_progress.get("status", ""),
        }
        blackboard = _blackboard_for_snapshot(project_root, runtime_progress, latest_plan, latest_workflow)
        return {
            "latest_plan": latest_plan,
            "latest_workflow": latest_workflow,
            "latest_checkpoint": latest_checkpoint,
            "blackboard": blackboard,
            "runtime": runtime_progress,
            "nodes": runtime_progress.get("nodes", []),
        }
    return {
        "latest_plan": latest_plan,
        "latest_workflow": latest_workflow,
        "latest_checkpoint": latest_checkpoint,
        "blackboard": blackboard,
        "runtime": None,
        "nodes": nodes,
    }


def _blackboard_for_snapshot(
    project_root: Path,
    runtime_progress: dict | None,
    latest_plan: dict | None,
    latest_workflow: dict | None,
) -> dict | None:
    task_id = ""
    if runtime_progress is not None:
        task_id = str(runtime_progress.get("task_id", ""))
    if not task_id and latest_plan is not None:
        task_id = str(latest_plan.get("task_id", ""))
    if not task_id and latest_workflow is not None:
        task_id = str(latest_workflow.get("task_id", ""))
    if not task_id:
        return None
    return blackboard_snapshot(project_root, task_id)

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock, get_ident
from typing import Literal

from .agents import AgentResult
from .agents.orchestrator import WorkerSpec
from .file_utils import ensure_dir
from .worker_runs import worker_id

BlackboardStatus = Literal["planned", "running", "success", "failed", "skipped", "blocked"]
_BLACKBOARD_LOCK = RLock()


@dataclass(frozen=True)
class BlackboardEntry:
    task_id: str
    agent_id: str
    role: str
    label: str
    stage_index: int
    owned_paths: list[str]
    status: BlackboardStatus
    outputs: list[str]
    output_paths: list[str]
    blockers: list[str]
    notes: list[str]
    error: str
    updated_at: str


def blackboard_path(project_root: Path, task_id: str) -> Path:
    return project_root / "logs" / "blackboards" / f"{task_id}.json"


def load_blackboard(project_root: Path, task_id: str) -> dict[str, BlackboardEntry]:
    path = blackboard_path(project_root, task_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = {}
    for item in payload.get("agents", []):
        entry = _entry_from_json(item)
        if entry is not None:
            entries[entry.agent_id] = entry
    return entries


def blackboard_snapshot(project_root: Path, task_id: str) -> dict | None:
    path = blackboard_path(project_root, task_id)
    if not path.exists():
        return None
    entries = load_blackboard(project_root, task_id)
    return {
        "task_id": task_id,
        "path": str(path),
        "agents": [_entry_to_json(item) for item in sorted(entries.values(), key=lambda item: item.agent_id)],
    }


def mark_agent_planned(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    notes: list[str] | None = None,
) -> BlackboardEntry:
    return _upsert_entry(
        project_root,
        task_id=task_id,
        stage_index=stage_index,
        spec=spec,
        status="planned",
        notes=notes or ["已进入主控计划。"],
    )


def mark_agent_running(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
) -> BlackboardEntry:
    return _upsert_entry(
        project_root,
        task_id=task_id,
        stage_index=stage_index,
        spec=spec,
        status="running",
        notes=["开始执行。"],
    )


def mark_agent_success(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    result: AgentResult,
) -> BlackboardEntry:
    return _upsert_entry(
        project_root,
        task_id=task_id,
        stage_index=stage_index,
        spec=spec,
        status="success",
        outputs=list(result.outputs),
        output_paths=_output_paths(result),
        notes=[result.summary, *result.next_steps],
    )


def mark_agent_failed(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    error: str,
) -> BlackboardEntry:
    return _upsert_entry(
        project_root,
        task_id=task_id,
        stage_index=stage_index,
        spec=spec,
        status="failed",
        blockers=[error],
        error=error,
    )


def mark_agent_skipped(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    result: AgentResult,
) -> BlackboardEntry:
    return _upsert_entry(
        project_root,
        task_id=task_id,
        stage_index=stage_index,
        spec=spec,
        status="skipped",
        outputs=list(result.outputs),
        output_paths=_output_paths(result),
        notes=["输入未变化，复用上一轮成功结果。", result.summary],
    )


def _upsert_entry(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    status: BlackboardStatus,
    outputs: list[str] | None = None,
    output_paths: list[str] | None = None,
    blockers: list[str] | None = None,
    notes: list[str] | None = None,
    error: str = "",
) -> BlackboardEntry:
    with _BLACKBOARD_LOCK:
        entries = load_blackboard(project_root, task_id)
        agent_id = worker_id(stage_index, spec)
        current = entries.get(agent_id)
        entry = BlackboardEntry(
            task_id=task_id,
            agent_id=agent_id,
            role=spec.role,
            label=spec.label,
            stage_index=stage_index,
            owned_paths=list(spec.owned_paths),
            status=status,
            outputs=_merge_items(current.outputs if current else [], outputs or []),
            output_paths=_merge_items(current.output_paths if current else [], output_paths or []),
            blockers=_merge_items(current.blockers if current else [], blockers or []),
            notes=_merge_items(current.notes if current else [], notes or []),
            error=error,
            updated_at=_now(),
        )
        entries[agent_id] = entry
        _write_blackboard(project_root, task_id, entries)
        return entry


def _write_blackboard(project_root: Path, task_id: str, entries: dict[str, BlackboardEntry]) -> None:
    path = blackboard_path(project_root, task_id)
    ensure_dir(path.parent)
    payload = {
        "task_id": task_id,
        "updated_at": _now(),
        "agents": [_entry_to_json(item) for item in sorted(entries.values(), key=lambda item: item.agent_id)],
    }
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{get_ident()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _replace_with_retries(temporary, path)


def _entry_to_json(entry: BlackboardEntry) -> dict:
    return {
        "task_id": entry.task_id,
        "agent_id": entry.agent_id,
        "role": entry.role,
        "label": entry.label,
        "stage_index": entry.stage_index,
        "owned_paths": entry.owned_paths,
        "status": entry.status,
        "outputs": entry.outputs,
        "output_paths": entry.output_paths,
        "blockers": entry.blockers,
        "notes": entry.notes,
        "error": entry.error,
        "updated_at": entry.updated_at,
    }


def _entry_from_json(data: dict) -> BlackboardEntry | None:
    try:
        return BlackboardEntry(
            task_id=str(data["task_id"]),
            agent_id=str(data["agent_id"]),
            role=str(data["role"]),
            label=str(data.get("label", "")),
            stage_index=int(data.get("stage_index", 0)),
            owned_paths=[str(item) for item in data.get("owned_paths", [])],
            status=str(data.get("status", "planned")),  # type: ignore[arg-type]
            outputs=[str(item) for item in data.get("outputs", [])],
            output_paths=[str(item) for item in data.get("output_paths", [])],
            blockers=[str(item) for item in data.get("blockers", [])],
            notes=[str(item) for item in data.get("notes", [])],
            error=str(data.get("error", "")),
            updated_at=str(data.get("updated_at", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _merge_items(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    seen = set(merged)
    for item in right:
        if item and item not in seen:
            merged.append(item)
            seen.add(item)
    return merged


def _output_paths(result: AgentResult) -> list[str]:
    paths = []
    for item in result.evidence:
        if "路径：" in item:
            paths.append(item.split("路径：", 1)[1])
    return paths


def _replace_with_retries(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")

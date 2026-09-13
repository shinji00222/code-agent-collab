from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock, get_ident
from typing import Literal

from .agents import AgentResult, PermissionLevel
from .agents.orchestrator import WorkerSpec
from .file_utils import ensure_dir

WorkerStatus = Literal["pending", "running", "success", "failed", "skipped"]
_RUNS_LOCK = RLock()


@dataclass(frozen=True)
class WorkerRunRecord:
    task_id: str
    stage_index: int
    worker_id: str
    role: str
    label: str
    status: WorkerStatus
    attempt: int
    input_hash: str
    output_paths: list[str]
    error: str
    result: AgentResult | None
    started_at: str
    finished_at: str


def worker_runs_path(project_root: Path, task_id: str) -> Path:
    return project_root / "logs" / "runs" / task_id / "workers.json"


def worker_id(stage_index: int, spec: WorkerSpec) -> str:
    label = spec.label or "default"
    return f"stage{stage_index}-{spec.role}-{label}"


def input_hash_for(context_path: Path, task_goal: str, spec: WorkerSpec) -> str:
    digest = hashlib.sha256()
    digest.update(task_goal.encode("utf-8"))
    digest.update(b"\n")
    digest.update(str(context_path).encode("utf-8"))
    digest.update(b"\n")
    digest.update(spec.role.encode("utf-8"))
    digest.update(b"\n")
    digest.update(spec.label.encode("utf-8"))
    try:
        digest.update(context_path.read_bytes())
    except OSError:
        pass
    return digest.hexdigest()


def load_worker_runs(project_root: Path, task_id: str) -> dict[str, WorkerRunRecord]:
    path = worker_runs_path(project_root, task_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    records = {}
    for item in payload.get("workers", []):
        record = _record_from_json(item)
        if record is not None:
            records[record.worker_id] = record
    return records


def should_skip_worker(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    input_hash: str,
) -> AgentResult | None:
    record = load_worker_runs(project_root, task_id).get(worker_id(stage_index, spec))
    if record is None or record.status not in {"success", "skipped"}:
        return None
    if record.input_hash != input_hash:
        return None
    return record.result


def start_worker_run(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    input_hash: str,
) -> WorkerRunRecord:
    records = load_worker_runs(project_root, task_id)
    current = records.get(worker_id(stage_index, spec))
    attempt = (current.attempt + 1) if current else 1
    now = _now()
    record = WorkerRunRecord(
        task_id=task_id,
        stage_index=stage_index,
        worker_id=worker_id(stage_index, spec),
        role=spec.role,
        label=spec.label,
        status="running",
        attempt=attempt,
        input_hash=input_hash,
        output_paths=[],
        error="",
        result=None,
        started_at=now,
        finished_at="",
    )
    _save_record(project_root, task_id, record)
    return record


def finish_worker_success(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    input_hash: str,
    result: AgentResult,
) -> WorkerRunRecord:
    current = load_worker_runs(project_root, task_id).get(worker_id(stage_index, spec))
    record = WorkerRunRecord(
        task_id=task_id,
        stage_index=stage_index,
        worker_id=worker_id(stage_index, spec),
        role=spec.role,
        label=spec.label,
        status="success",
        attempt=current.attempt if current else 1,
        input_hash=input_hash,
        output_paths=_output_paths(result),
        error="",
        result=result,
        started_at=current.started_at if current else _now(),
        finished_at=_now(),
    )
    _save_record(project_root, task_id, record)
    return record


def finish_worker_failed(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    input_hash: str,
    error: str,
) -> WorkerRunRecord:
    current = load_worker_runs(project_root, task_id).get(worker_id(stage_index, spec))
    record = WorkerRunRecord(
        task_id=task_id,
        stage_index=stage_index,
        worker_id=worker_id(stage_index, spec),
        role=spec.role,
        label=spec.label,
        status="failed",
        attempt=current.attempt if current else 1,
        input_hash=input_hash,
        output_paths=[],
        error=error,
        result=None,
        started_at=current.started_at if current else _now(),
        finished_at=_now(),
    )
    _save_record(project_root, task_id, record)
    return record


def mark_worker_skipped(
    project_root: Path,
    *,
    task_id: str,
    stage_index: int,
    spec: WorkerSpec,
    input_hash: str,
    result: AgentResult,
) -> WorkerRunRecord:
    current = load_worker_runs(project_root, task_id).get(worker_id(stage_index, spec))
    record = WorkerRunRecord(
        task_id=task_id,
        stage_index=stage_index,
        worker_id=worker_id(stage_index, spec),
        role=spec.role,
        label=spec.label,
        status="skipped",
        attempt=current.attempt if current else 1,
        input_hash=input_hash,
        output_paths=_output_paths(result),
        error="",
        result=result,
        started_at=current.started_at if current else _now(),
        finished_at=_now(),
    )
    _save_record(project_root, task_id, record)
    return record


def _save_record(project_root: Path, task_id: str, record: WorkerRunRecord) -> None:
    with _RUNS_LOCK:
        path = worker_runs_path(project_root, task_id)
        ensure_dir(path.parent)
        records = load_worker_runs(project_root, task_id)
        records[record.worker_id] = record
        payload = {
            "task_id": task_id,
            "updated_at": _now(),
            "workers": [_record_to_json(item) for item in sorted(records.values(), key=lambda item: item.worker_id)],
        }
        temporary = path.with_name(f"{path.name}.{os.getpid()}.{get_ident()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _replace_with_retries(temporary, path)


def _record_to_json(record: WorkerRunRecord) -> dict:
    return {
        "task_id": record.task_id,
        "stage_index": record.stage_index,
        "worker_id": record.worker_id,
        "role": record.role,
        "label": record.label,
        "status": record.status,
        "attempt": record.attempt,
        "input_hash": record.input_hash,
        "output_paths": record.output_paths,
        "error": record.error,
        "result": _result_to_json(record.result) if record.result else None,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
    }


def _record_from_json(data: dict) -> WorkerRunRecord | None:
    try:
        result_data = data.get("result")
        return WorkerRunRecord(
            task_id=str(data["task_id"]),
            stage_index=int(data["stage_index"]),
            worker_id=str(data["worker_id"]),
            role=str(data["role"]),
            label=str(data.get("label", "")),
            status=str(data["status"]),  # type: ignore[arg-type]
            attempt=int(data.get("attempt", 0)),
            input_hash=str(data.get("input_hash", "")),
            output_paths=[str(item) for item in data.get("output_paths", [])],
            error=str(data.get("error", "")),
            result=_result_from_json(result_data) if isinstance(result_data, dict) else None,
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _result_to_json(result: AgentResult) -> dict:
    return {
        "role": result.role,
        "permission": result.permission.value,
        "summary": result.summary,
        "evidence": result.evidence,
        "outputs": result.outputs,
        "risks": result.risks,
        "next_steps": result.next_steps,
    }


def _result_from_json(data: dict) -> AgentResult:
    return AgentResult(
        role=str(data["role"]),
        permission=PermissionLevel(str(data["permission"])),
        summary=str(data["summary"]),
        evidence=[str(item) for item in data.get("evidence", [])],
        outputs=[str(item) for item in data.get("outputs", [])],
        risks=[str(item) for item in data.get("risks", [])],
        next_steps=[str(item) for item in data.get("next_steps", [])],
    )


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

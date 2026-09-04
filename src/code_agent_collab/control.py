from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .agents import AgentResult, PermissionLevel
from .file_utils import ensure_dir

CONTROL_ENV = "AGENT_WORKBENCH_CONTROL_DIR"
PAUSE_FILE_NAME = "pause.json"
CHECKPOINT_SUFFIX = ".checkpoint.json"


class WorkflowPaused(RuntimeError):
    """Raised when the user requested a cooperative workflow pause."""


def control_dir(project_root: Path) -> Path:
    configured = os.getenv(CONTROL_ENV)
    if configured:
        return Path(configured).resolve()
    return project_root / "logs" / "control"


def pause_path(project_root: Path) -> Path:
    return control_dir(project_root) / PAUSE_FILE_NAME


def checkpoint_path(project_root: Path, task_id: str) -> Path:
    return control_dir(project_root) / f"{task_id}{CHECKPOINT_SUFFIX}"


def request_pause(project_root: Path, *, source: str = "webui") -> Path:
    path = pause_path(project_root)
    ensure_dir(path.parent)
    payload = {
        "requested": True,
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def clear_pause_request(project_root: Path) -> None:
    path = pause_path(project_root)
    if path.exists():
        path.unlink()


def is_pause_requested(project_root: Path) -> bool:
    path = pause_path(project_root)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("requested"))


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


def save_checkpoint(
    project_root: Path,
    *,
    task_id: str,
    next_stage_index: int,
    done_roles: set[str],
    agent_results: list[AgentResult],
    latest_coder_specs: list[dict],
) -> Path:
    path = checkpoint_path(project_root, task_id)
    ensure_dir(path.parent)
    payload = {
        "task_id": task_id,
        "next_stage_index": next_stage_index,
        "done_roles": sorted(done_roles),
        "agent_results": [_result_to_json(result) for result in agent_results],
        "latest_coder_specs": latest_coder_specs,
        "updated_at": datetime.now().isoformat(timespec="milliseconds"),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_checkpoint(project_root: Path, task_id: str) -> dict | None:
    path = checkpoint_path(project_root, task_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("task_id") != task_id:
        return None
    payload["agent_results"] = [
        _result_from_json(item) for item in payload.get("agent_results", [])
    ]
    payload["done_roles"] = set(str(item) for item in payload.get("done_roles", []))
    return payload


def clear_checkpoint(project_root: Path, task_id: str) -> None:
    path = checkpoint_path(project_root, task_id)
    if path.exists():
        path.unlink()

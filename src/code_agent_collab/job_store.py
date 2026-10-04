"""后台任务记录的持久化（v0.17.15）。

背景（台账「安全方案 · 问题 3」）：job 原来只存在内存字典里，服务一重启历史就没了，
也无法判断「上次是不是有任务被中断」。

这个模块职责很窄，只做四件事：

1. 把 job 记录写到 `logs/jobs/<job_id>.json`；
2. 按时间列出历史记录；
3. 清理过旧的历史文件；
4. 服务启动时把上次遗留的 `queued` / `running` 标记为 `interrupted`。

**不做调度、不执行命令、不管并发**——那些留在 `web_jobs.py`。
这样「重启恢复」可以单独测，不需要真的起任务。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

#: 保留的历史记录条数上限，超出的按时间删最旧的。
HISTORY_LIMIT = 200

#: 这些状态代表「服务上次退出时还没结束」。
UNFINISHED_STATUSES = frozenset({"queued", "running"})

_TERMINAL_STATUSES = frozenset({"done", "failed", "timeout", "interrupted"})


def jobs_dir(project_root: Path) -> Path:
    return project_root / "logs" / "jobs"


def job_path(project_root: Path, job_id: str) -> Path:
    return jobs_dir(project_root) / f"{job_id}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def save_job(project_root: Path, payload: dict) -> Path:
    """原子写入一条 job 记录（带 pid 的临时文件 + os.replace，兼容 Windows 占用重试）。"""
    job_id = str(payload.get("job_id") or "")
    if not job_id:
        raise ValueError("job 记录缺少 job_id")
    directory = jobs_dir(project_root)
    directory.mkdir(parents=True, exist_ok=True)
    target = job_path(project_root, job_id)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    handle, temporary_name = tempfile.mkstemp(
        prefix=f"{target.name}.{os.getpid()}.",
        suffix=".tmp",
        dir=str(directory),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        last_error: OSError | None = None
        for _ in range(5):
            try:
                os.replace(temporary, target)
                return target
            except OSError as exc:  # Windows 上目标可能被短暂占用
                last_error = exc
                import time

                time.sleep(0.05)
        raise last_error if last_error is not None else OSError("保存 job 记录失败")
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:  # pragma: no cover - 清理失败不影响主流程
                pass


def load_job(project_root: Path, job_id: str) -> dict | None:
    path = job_path(project_root, job_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def list_jobs(project_root: Path, limit: int | None = None) -> list[dict]:
    """按创建时间倒序列出历史记录（最新的在前）。"""
    directory = jobs_dir(project_root)
    if not directory.exists():
        return []
    records: list[dict] = []
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("job_id"):
            records.append(payload)
    records.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return records[:limit] if limit is not None else records


def prune_jobs(project_root: Path, keep: int = HISTORY_LIMIT) -> int:
    """只保留最新的 `keep` 条记录，返回删除数量。"""
    records = list_jobs(project_root)
    removed = 0
    for record in records[keep:]:
        try:
            job_path(project_root, str(record["job_id"])).unlink()
            removed += 1
        except (OSError, KeyError):
            continue
    return removed


def recover_interrupted_jobs(project_root: Path, now: str | None = None) -> list[str]:
    """把上次遗留的 `queued` / `running` 记录标记为 `interrupted`。

    **只改状态，绝不重跑**：有副作用的步骤（改源码、起进程、花 API 额度）不能自动重放。
    返回被标记的 job id 列表。目录不存在时直接返回空列表，不创建目录。
    """
    directory = jobs_dir(project_root)
    if not directory.exists():
        return []

    recovered: list[str] = []
    timestamp = now or _now()
    for record in list_jobs(project_root):
        if str(record.get("status")) not in UNFINISHED_STATUSES:
            continue
        job_id = str(record.get("job_id"))
        record["status"] = "interrupted"
        record["error"] = (
            record.get("error")
            or "服务重启前该任务尚未结束，已标记为中断；不会自动重跑，请确认状态后手动重新提交。"
        )
        record["updated_at"] = timestamp
        record["done"] = True
        save_job(project_root, record)
        recovered.append(job_id)
    return recovered


def is_finished(status: str) -> bool:
    return status in _TERMINAL_STATUSES

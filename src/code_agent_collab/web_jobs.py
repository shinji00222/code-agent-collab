from __future__ import annotations

import atexit
import os
import shlex
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import job_store
from .control import clear_pause_request
from .web_project import CLI_EXE_NAME, PROJECT_ROOT, SRC_DIR

ALLOWED_COMMANDS = {
    "init",
    "start",
    "reflect",
    "pending",
    "review",
    "confirm",
    "discard",
    "demo",
    "run",
    "run-adaptive",
    "approve",
    "plans",
    "provider",
    "help",
}

HELP_TEXT = """可用命令（在下面输入框输入后回车）：

  help                    显示本帮助
  provider                查看当前 AI Provider 配置
  init                    生成/重置本地配置
  start "任务目标"         生成任务上下文包
  run "任务目标"           跑完整多 Agent 工作流
  run-adaptive "任务目标"   生成半动态自适应方案（等待人工审批）
  plans                   列出已保存的主控方案
  approve "任务ID或关键词"  批准方案并执行 workers
  demo "任务目标"          一键演示闭环
  pending                 列出待确认候选记录
  review                  审查候选记录（通过后需 confirm 才入库）
  confirm "候选关键词"     人工确认候选入库
  discard "候选关键词"     废弃候选记录

示例：
  run-adaptive "写一个待办清单脚本"
  plans
  approve 20260821-141421
  pending
"""

#: 只读命令：不写项目、不花模型额度，可以并发跑。
READ_ONLY_COMMANDS = frozenset({"pending", "plans", "provider", "help"})

#: 同时运行的任务数上限。
MAX_ACTIVE_JOBS = 2

#: 等待队列上限；满了直接拒绝（429），不无限堆积。
MAX_QUEUED_JOBS = 8


class JobQueueFull(RuntimeError):
    """等待队列已满，拒绝新任务。"""


_ACTIVE_PROCESSES: set[subprocess.Popen] = set()


@dataclass
class CommandJob:
    id: str
    command: str
    args: list[str]
    request_id: str = ""
    status: str = "queued"
    code: int | None = None
    output: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime_now())
    updated_at: str = field(default_factory=lambda: datetime_now())

    @property
    def is_write(self) -> bool:
        return not self.args or self.args[0] not in READ_ONLY_COMMANDS

    @property
    def finished(self) -> bool:
        return job_store.is_finished(self.status)

    def to_json(self) -> dict:
        return {
            "job_id": self.id,
            "command": self.command,
            "request_id": self.request_id,
            "status": self.status,
            "code": self.code,
            "output": self.output,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "done": self.finished,
        }


def datetime_now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="milliseconds")


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            process.terminate()
            process.wait(timeout=3)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        try:
            process.wait(timeout=3)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            process.kill()
        except OSError:
            pass
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _shutdown_cleanup() -> None:
    for process in list(_ACTIVE_PROCESSES):
        _kill_process_tree(process)
    # 退出时把还没结束的任务标成中断并落盘，下次启动就能看到"上次没跑完"
    try:
        _SCHEDULER.mark_all_unfinished_interrupted()
    except Exception:  # noqa: BLE001 - 解释器退出阶段不能再抛异常
        pass


atexit.register(_shutdown_cleanup)


def force_stop_active_work() -> int:
    processes = list(_ACTIVE_PROCESSES)
    stopped = 0
    for process in processes:
        if process.poll() is None:
            _kill_process_tree(process)
            stopped += 1
    return stopped


def build_command(text: str) -> list[str]:
    args = shlex.split(text)
    if not args:
        raise ValueError("命令为空")
    if args[0] not in ALLOWED_COMMANDS:
        raise ValueError(f"不允许的命令：{args[0]}（可用：{', '.join(sorted(ALLOWED_COMMANDS))}）")
    return args


def run_cli(args: list[str], timeout: int = 180) -> tuple[int, str]:
    if args[0] == "help":
        return 0, HELP_TEXT
    if args[0] in {"run", "run-adaptive", "approve"}:
        clear_pause_request(PROJECT_ROOT)
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        # 打包模式：调用同目录的 CLI 可执行程序（PyInstaller 单文件模式无法 -m 启动）
        cli_exe = Path(sys.executable).resolve().parent / CLI_EXE_NAME
        command = [str(cli_exe), *args]
    else:
        env["PYTHONPATH"] = str(SRC_DIR)
        command = [sys.executable, "-m", "code_agent_collab.cli", *args]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    _ACTIVE_PROCESSES.add(process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        process.wait()
        raise
    finally:
        _ACTIVE_PROCESSES.discard(process)
    output = stdout
    if stderr:
        output += "\n" + stderr
    return process.returncode, output


def _project_root() -> Path:
    """运行时读取模块级 `PROJECT_ROOT`，方便测试替换。"""
    return Path(PROJECT_ROOT)


def _persist(job: CommandJob) -> None:
    try:
        job_store.save_job(_project_root(), job.to_json())
    except OSError:
        # 落盘失败不影响任务本身，只是历史里少一条记录
        pass


class _JobScheduler:
    """带并发上限、写命令串行和重复提交去重的后台任务调度器。

    并发模型是「一个调度线程 + 每个任务一个工作线程」：

    - 调度线程只在持锁状态下改状态、挑下一个能跑的任务，**不在锁里执行命令**；
    - 写命令（除 `pending`/`plans`/`provider`/`help` 之外的命令）最多同时跑 1 个，
      避免多个任务同时抢同一批文件（台账「问题 3：项目写锁」）；
    - 同一 `request_id`、或同一条仍在排队/运行的命令重复提交，直接返回已有任务。
    """

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._jobs: dict[str, CommandJob] = {}
        self._order: list[str] = []
        self._active: set[str] = set()
        self._request_ids: dict[str, str] = {}
        self._dispatcher: threading.Thread | None = None

    def submit(self, command: str, request_id: str = "") -> tuple[CommandJob, bool]:
        args = build_command(command)
        with self._cv:
            duplicate = self._find_duplicate(command, request_id)
            if duplicate is not None:
                return duplicate, True
            if len(self._order) >= MAX_QUEUED_JOBS:
                raise JobQueueFull(
                    f"等待队列已满（上限 {MAX_QUEUED_JOBS} 个）：请等当前任务结束后再提交，"
                    f"或先用“强制停止”清掉卡住的任务。"
                )
            job = CommandJob(
                id=uuid.uuid4().hex,
                command=command,
                args=args,
                request_id=request_id,
            )
            self._jobs[job.id] = job
            self._order.append(job.id)
            if request_id:
                self._request_ids[request_id] = job.id
            _persist(job)
            self._ensure_dispatcher()
            self._cv.notify_all()
            return job, False

    def get(self, job_id: str) -> dict | None:
        with self._cv:
            job = self._jobs.get(job_id)
            if job is not None:
                return job.to_json()
        return job_store.load_job(_project_root(), job_id)

    def snapshot(self) -> list[CommandJob]:
        with self._cv:
            return list(self._jobs.values())

    def mark_all_unfinished_interrupted(self) -> None:
        with self._cv:
            for job in self._jobs.values():
                if job.finished:
                    continue
                job.status = "interrupted"
                job.error = job.error or "服务退出时该任务尚未结束，已标记为中断（不会自动重跑）。"
                job.updated_at = datetime_now()
                _persist(job)

    def _find_duplicate(self, command: str, request_id: str) -> CommandJob | None:
        if request_id:
            job_id = self._request_ids.get(request_id)
            job = self._jobs.get(job_id) if job_id else None
            if job is not None and not job.finished:
                return job
        for job_id in [*self._active, *self._order]:
            job = self._jobs.get(job_id)
            if job is not None and job.command == command and not job.finished:
                return job
        return None

    def _ensure_dispatcher(self) -> None:
        if self._dispatcher is not None and self._dispatcher.is_alive():
            return
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, name="job-dispatcher", daemon=True
        )
        self._dispatcher.start()

    def _dispatch_loop(self) -> None:
        while True:
            with self._cv:
                job = self._next_runnable()
                while job is None:
                    self._cv.wait()
                    job = self._next_runnable()
                job.status = "running"
                job.updated_at = datetime_now()
                self._active.add(job.id)
                _persist(job)
            threading.Thread(
                target=self._run_job,
                args=(job.id,),
                name=f"job-{job.id[:8]}",
                daemon=True,
            ).start()

    def _next_runnable(self) -> CommandJob | None:
        if len(self._active) >= MAX_ACTIVE_JOBS:
            return None
        write_running = any(
            job.is_write
            for job in (self._jobs.get(item) for item in self._active)
            if job is not None
        )
        for job_id in list(self._order):
            job = self._jobs.get(job_id)
            if job is None:
                self._order.remove(job_id)
                continue
            if job.is_write and write_running:
                continue
            self._order.remove(job_id)
            return job
        return None

    def _run_job(self, job_id: str) -> None:
        with self._cv:
            job = self._jobs.get(job_id)
            args = list(job.args) if job is not None else []
        try:
            code, output = run_cli(args)
        except subprocess.TimeoutExpired:
            self._finish(job_id, status="timeout", error="命令执行超时")
        except Exception as exc:  # noqa: BLE001 - 后台任务要把错误留给前端轮询
            self._finish(job_id, status="failed", error=f"服务器错误：{exc}")
        else:
            self._finish(
                job_id,
                status="done" if code in {0, 3} else "failed",
                code=code,
                output=output,
            )

    def _finish(self, job_id: str, **updates: object) -> None:
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = datetime_now()
            self._active.discard(job_id)
            _persist(job)
            job_store.prune_jobs(_project_root())
            self._cv.notify_all()


_SCHEDULER = _JobScheduler()


def start_command_job(command: str, request_id: str = "") -> dict:
    """提交一个后台任务。

    重复提交（同一 `request_id`，或同一条命令仍在排队/运行）不会重复执行，
    而是直接返回已有任务，并在返回值里带 `deduplicated: True`。
    """
    job, duplicated = _SCHEDULER.submit(command, request_id=request_id)
    payload = job.to_json()
    payload["deduplicated"] = duplicated
    return payload


def get_command_job(job_id: str) -> dict | None:
    return _SCHEDULER.get(job_id)


def list_command_jobs(limit: int | None = 50) -> list[dict]:
    """列出历史任务（最新的在前）。

    内存里没有的记录从磁盘读，所以**服务重启后仍然能查到历史**。
    """
    live = {job.id: job.to_json() for job in _SCHEDULER.snapshot()}
    merged: dict[str, dict] = {}
    for record in job_store.list_jobs(_project_root()):
        merged[str(record.get("job_id"))] = record
    merged.update(live)
    ordered = sorted(
        merged.values(), key=lambda item: str(item.get("created_at", "")), reverse=True
    )
    return ordered[:limit] if limit is not None else ordered


def initialise_job_history() -> list[str]:
    """服务启动时调用：把上次遗留的未完成记录标记为中断，并清理过旧历史。

    只改状态、**绝不重跑**——有副作用的步骤不能自动重放。
    """
    recovered = job_store.recover_interrupted_jobs(_project_root())
    job_store.prune_jobs(_project_root())
    return recovered

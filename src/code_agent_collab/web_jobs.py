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

_ACTIVE_PROCESSES: set[subprocess.Popen] = set()
_JOBS_LOCK = threading.Lock()
_JOBS: dict[str, "CommandJob"] = {}


@dataclass
class CommandJob:
    id: str
    command: str
    args: list[str]
    status: str = "queued"
    code: int | None = None
    output: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime_now())
    updated_at: str = field(default_factory=lambda: datetime_now())

    def to_json(self) -> dict:
        return {
            "job_id": self.id,
            "command": self.command,
            "status": self.status,
            "code": self.code,
            "output": self.output,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "done": self.status in {"done", "failed", "timeout"},
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


def start_command_job(command: str) -> dict:
    args = build_command(command)
    job_id = uuid.uuid4().hex
    job = CommandJob(id=job_id, command=command, args=args)
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    thread = threading.Thread(target=_run_command_job, args=(job_id,), daemon=True)
    thread.start()
    return job.to_json()


def get_command_job(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return None if job is None else job.to_json()


def _update_job(job_id: str, **updates) -> None:
    with _JOBS_LOCK:
        job = _JOBS[job_id]
        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = datetime_now()


def _run_command_job(job_id: str) -> None:
    with _JOBS_LOCK:
        job = _JOBS[job_id]
        args = list(job.args)
    _update_job(job_id, status="running")
    try:
        code, output = run_cli(args)
    except subprocess.TimeoutExpired:
        _update_job(job_id, status="timeout", error="命令执行超时")
    except Exception as exc:  # noqa: BLE001 - 后台任务需要把错误留给前端轮询
        _update_job(job_id, status="failed", error=f"服务器错误：{exc}")
    else:
        _update_job(job_id, status="done" if code in {0, 3} else "failed", code=code, output=output)

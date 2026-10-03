from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import uuid
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .blackboard import blackboard_snapshot
from .control import CHECKPOINT_SUFFIX, clear_pause_request, control_dir, request_pause
from .providers import ProviderConfigurationError, create_provider
from .progress import read_progress
from .webui_page import PAGE as TERMINAL_PAGE

PROJECT_ROOT_ENV = "AGENT_WORKBENCH_PROJECT_ROOT"
LOCAL_WORKBENCH_ROOT = (
    Path.home()
    / "Desktop"
    / "AI工作台知识库"
    / "01-项目"
    / "project 多Agent代码协作助手"
)


def _is_project_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").exists()
        and (path / "src" / "code_agent_collab").exists()
    )


def resolve_project_root(
    *,
    executable_path: Path | None = None,
    module_file: Path | None = None,
    frozen: bool | None = None,
) -> Path:
    configured = os.getenv(PROJECT_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    if not frozen:
        source_file = module_file or Path(__file__)
        return source_file.resolve().parent.parent.parent

    exe_dir = (executable_path or Path(sys.executable)).resolve().parent
    for candidate in (exe_dir, *exe_dir.parents):
        if _is_project_root(candidate):
            return candidate

    if _is_project_root(LOCAL_WORKBENCH_ROOT):
        return LOCAL_WORKBENCH_ROOT.resolve()

    return exe_dir


# 打包（PyInstaller）模式下没有 __file__，项目根目录需回到正式仓库；
# 开发模式下是仓库根目录（src/code_agent_collab/webui.py 向上三级）。
if getattr(sys, "frozen", False):
    PROJECT_ROOT = resolve_project_root(frozen=True)
    SRC_DIR = PROJECT_ROOT
else:
    PROJECT_ROOT = resolve_project_root(frozen=False)
    SRC_DIR = PROJECT_ROOT / "src"

# 打包模式下 run_cli 调用的同目录 CLI 可执行程序名
CLI_EXE_NAME = "AgentWorkbench-CLI.exe"

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

_DISCUSSION_LOCK = threading.Lock()
_DISCUSSION_HISTORY: list[dict[str, str]] = []
_DISCUSSION_MAX_ITEMS = 14


def clear_discussion() -> None:
    with _DISCUSSION_LOCK:
        _DISCUSSION_HISTORY.clear()


def build_discussion_goal() -> str:
    with _DISCUSSION_LOCK:
        history = list(_DISCUSSION_HISTORY)
    user_messages = [item["content"] for item in history if item["role"] == "user"]
    if not user_messages:
        return ""
    first_goal = user_messages[0].strip()
    supplements = user_messages[1:]
    if not supplements:
        return first_goal
    return first_goal + "\n\n讨论补充：\n" + "\n".join(
        f"- {item.strip()}" for item in supplements if item.strip()
    )


def _looks_like_question(message: str) -> bool:
    question_markers = ("?", "？", "怎么", "为什么", "啥", "什么", "能不能", "可以吗", "是不是", "如何")
    return any(marker in message for marker in question_markers)


def _mock_discussion_reply(message: str, user_count: int) -> str:
    if re.search(r"(模型|provider|Provider|api|API|key|Key|密钥|联网|本地)", message):
        return (
            "当前是 mock Provider，模型名是 mock-model。"
            "这是本地模拟回复，不联网，也不会消耗 API Key。"
            "如果要接真实模型，可以先用 provider 命令查看状态，再配置 deepseek、openai 或 openai-compatible。"
        )
    if _looks_like_question(message):
        return (
            "可以。你直接问问题时，我会先按问题本身回答；如果信息不够，我再告诉你缺什么，"
            "而不是只反问需求。等你觉得聊清楚了，再点“生成主控方案”。"
        )
    if user_count <= 1:
        return (
            "我先确认几个关键点，再生成方案：\n"
            "1. 你希望最终改的是 Web 页面、CLI 流程，还是两者都要？\n"
            "2. 完成标准是什么：能看到对话、能生成方案、能一键开始协同，还是还要保存讨论记录？\n"
            "3. 有没有不能动的部分，比如树状图、Provider 配置、GitHub 上传流程？"
        )
    return (
        "我把你的补充记下了。现在可以继续补充细节；如果目标已经说清楚，"
        "点“生成主控方案”，我会把这轮讨论整理成 OrchestratorAgent 的计划输入。"
    )


def discuss_with_orchestrator(message: str) -> dict[str, str]:
    cleaned = message.strip()
    if not cleaned:
        raise ValueError("讨论内容为空")

    with _DISCUSSION_LOCK:
        _DISCUSSION_HISTORY.append({"role": "user", "content": cleaned})
        user_count = sum(1 for item in _DISCUSSION_HISTORY if item["role"] == "user")
        history = list(_DISCUSSION_HISTORY[-_DISCUSSION_MAX_ITEMS:])

    provider = create_provider()
    if provider.name == "mock":
        reply = _mock_discussion_reply(cleaned, user_count)
    else:
        transcript = "\n".join(
            f"{item['role']}: {item['content']}" for item in history
        )
        try:
            reply = provider.complete(
                (
                    "你是 OrchestratorAgent 的前置需求讨论员。"
                    "你的任务是和用户对话澄清需求，不要写代码，不要批准执行，不要调用其他 Agent。"
                    "用户问问题时必须先正面回答，不要只追问需求；知道答案就给具体答案，"
                    "不知道就明确说不确定并说明还需要什么信息。回答后如有必要，再继续澄清。"
                    "如果信息不足，最多问 3 个关键问题；如果信息足够，先总结目标、约束和验收标准，"
                    "然后提示用户可以点击“生成主控方案”。"
                ),
                f"当前对话：\n{transcript}\n\n请给出下一轮回复。",
            )
        except ProviderConfigurationError as exc:
            reply = f"真实模型还没配置好：{exc}\n可以先用菜单配置 API，或切回 mock 后继续。"
        except Exception as exc:  # noqa: BLE001 - Web UI 需要把 Provider 失败转成可读提示
            reply = f"真实模型调用失败：{exc}\n可以检查网络/API Key，或切回 mock 后继续。"

    with _DISCUSSION_LOCK:
        _DISCUSSION_HISTORY.append({"role": "assistant", "content": reply})
        del _DISCUSSION_HISTORY[:-_DISCUSSION_MAX_ITEMS]

    return {"output": reply, "goal": build_discussion_goal()}

PAGE = TERMINAL_PAGE

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


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/progress":
            self._send_json(200, build_progress_snapshot(PROJECT_ROOT))
            return
        if self.path == "/api/discussion":
            self._send_json(200, {"goal": build_discussion_goal()})
            return
        if self.path.startswith("/api/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            job = get_command_job(job_id)
            if job is None:
                self._send_json(404, {"error": "job not found"})
            else:
                self._send_json(200, job)
            return
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/discuss":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                message = str(body.get("message", "")).strip()
                self._send_json(200, discuss_with_orchestrator(message))
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except json.JSONDecodeError:
                self._send_json(400, {"error": "请求体不是合法 JSON"})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": f"服务器错误：{exc}"})
            return

        if self.path == "/api/pause":
            request_pause(PROJECT_ROOT, source="webui")
            self._send_json(
                200,
                {
                    "code": 0,
                    "output": "已请求软暂停：当前 Agent 小步完成后，会在进入下一阶段前保存断点并暂停。",
                },
            )
            return

        if self.path == "/api/force-stop":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if str(body.get("confirm", "")).strip() != "STOP":
                self._send_json(400, {"error": "强制停止需要确认词 STOP"})
                return
            stopped = force_stop_active_work()
            self._send_json(
                200,
                {
                    "code": 0,
                    "output": (
                        f"已强制停止 {stopped} 个后台进程。"
                        if stopped
                        else "当前没有正在运行的后台进程。"
                    ),
                },
            )
            return

        if self.path == "/api/jobs":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                command = str(body.get("command", "")).strip()
                self._send_json(202, start_command_job(command))
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except json.JSONDecodeError:
                self._send_json(400, {"error": "请求体不是合法 JSON"})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"error": f"服务器错误：{exc}"})
            return

        if self.path != "/api/command":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            command = str(body.get("command", "")).strip()
            args = build_command(command)
            code, output = run_cli(args)
            self._send_json(200, {"code": code, "output": output})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except json.JSONDecodeError:
            self._send_json(400, {"error": "请求体不是合法 JSON"})
        except subprocess.TimeoutExpired:
            self._send_json(408, {"error": "命令执行超时"})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": f"服务器错误：{exc}"})

    def log_message(self, format: str, *args) -> None:  # noqa: A002, N802
        del format, args


def main() -> None:
    parser = argparse.ArgumentParser(description="多Agent工作台 Web 终端")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Web UI: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        # 等服务器就绪后再打开浏览器（打包成软件后双击即用）
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import json
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from .control import request_pause
from .progress import read_progress

APP_TITLE = "多Agent工作台"
CLI_EXE_NAME = "AgentWorkbench-CLI.exe"
PROJECT_ROOT_ENV = "AGENT_WORKBENCH_PROJECT_ROOT"
LOCAL_WORKBENCH_ROOT = (
    Path.home()
    / "Desktop"
    / "AI工作台知识库"
    / "01-项目"
    / "project 多Agent代码协作助手"
)
PROJECT_ROOT_COMMANDS = {
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
    "apply-draft",
}


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
    env_root = os.getenv(PROJECT_ROOT_ENV)
    if env_root:
        return Path(env_root).expanduser().resolve()

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    if not frozen:
        source_file = module_file or Path(__file__)
        return source_file.resolve().parent.parent.parent

    executable_dir = (executable_path or Path(sys.executable)).resolve().parent
    for candidate in (executable_dir, *executable_dir.parents):
        if _is_project_root(candidate):
            return candidate

    if _is_project_root(LOCAL_WORKBENCH_ROOT):
        return LOCAL_WORKBENCH_ROOT.resolve()

    return executable_dir


def cli_command(args: list[str], *, executable_path: Path | None = None, frozen: bool | None = None) -> list[str]:
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        executable = executable_path or Path(sys.executable)
        cli_exe = executable.resolve().parent / CLI_EXE_NAME
        return [str(cli_exe), *args]
    return [sys.executable, "-m", "code_agent_collab.cli", *args]


def desktop_cli_args(args: list[str], project_root: Path) -> list[str]:
    if not args or args[0] not in PROJECT_ROOT_COMMANDS:
        return args
    if "--project-root" in args:
        return args
    return [*args, "--project-root", str(project_root)]


PROJECT_ROOT = resolve_project_root()


def cli_env(project_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    src_path = str(project_root / "src")
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_path if not current else src_path + os.pathsep + current
    return env


def extract_task_id(output: str) -> str:
    match = re.search(r"任务ID：\s*(.+)", output)
    return match.group(1).strip() if match else ""


def load_recent_plans(project_root: Path, limit: int = 8) -> list[dict[str, str]]:
    plans_dir = project_root / "logs" / "plans"
    if not plans_dir.exists():
        return []
    rows: list[dict[str, str]] = []
    for path in sorted(plans_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task_id = str(payload.get("task_id") or path.stem)
        rows.append(
            {
                "task_id": task_id,
                "status": str(payload.get("status") or "unknown"),
                "goal": str(payload.get("goal") or ""),
                "complexity": str(payload.get("complexity") or ""),
                "worker_count": str(payload.get("worker_count") or ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def flatten_progress_nodes(nodes: list[dict]) -> list[str]:
    lines: list[str] = []

    def visit(item: dict, indent: str = "") -> None:
        if item.get("kind") == "branch":
            for child in item.get("children", []):
                if isinstance(child, dict):
                    visit(child, indent + "  ")
            return
        label = str(item.get("label") or item.get("role") or "Agent")
        status = str(item.get("status") or "idle")
        detail = str(item.get("detail") or "")
        suffix = f" - {detail}" if detail else ""
        lines.append(f"{indent}{label}: {status}{suffix}")

    for node in nodes:
        if isinstance(node, dict):
            visit(node)
    return lines


def progress_text(project_root: Path) -> str:
    payload = read_progress(project_root)
    if not payload:
        return "暂无运行进度。"
    header = [
        f"任务ID：{payload.get('task_id', '未知')}",
        f"状态：{payload.get('status', '未知')}",
        f"说明：{payload.get('detail', '')}",
        f"更新时间：{payload.get('updated_at', '')}",
    ]
    nodes = flatten_progress_nodes(payload.get("nodes", []))
    if nodes:
        header.append("")
        header.extend(nodes)
    return "\n".join(header)


class DesktopApp:
    def __init__(self, root: tk.Tk, project_root: Path = PROJECT_ROOT) -> None:
        self.root = root
        self.project_root = project_root
        self.output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.current_process: subprocess.Popen[str] | None = None
        self.current_thread: threading.Thread | None = None
        self.busy = False
        self.latest_task_id = ""
        self.goal_var = tk.StringVar()
        self.status_var = tk.StringVar(value="空闲")
        self.provider_var = tk.StringVar(value="Provider：检查中...")
        self.task_var = tk.StringVar(value="任务ID：暂无")
        self.progress_var = tk.StringVar(value="暂无运行进度。")

        self.root.title(APP_TITLE)
        self.root.geometry("1180x720")
        self.root.minsize(980, 620)
        self._build_ui()
        self.refresh_workspace()
        self._poll_output()
        self.run_command(["provider"], label="检查 Provider")

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.columnconfigure(2, weight=0)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(12, 10))
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text=APP_TITLE, font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.provider_var).grid(row=0, column=1, sticky="e")

        controls = ttk.Frame(self.root, padding=(12, 4, 8, 12))
        controls.grid(row=1, column=0, sticky="ns")
        controls.columnconfigure(0, weight=1)

        ttk.Label(controls, text="任务目标").grid(row=0, column=0, sticky="w")
        goal_entry = ttk.Entry(controls, textvariable=self.goal_var, width=34)
        goal_entry.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        goal_entry.bind("<Return>", lambda _event: self.generate_plan())

        buttons = [
            ("刷新 Provider", lambda: self.run_command(["provider"], label="刷新 Provider")),
            ("查看方案列表", lambda: self.run_command(["plans"], label="查看方案列表")),
            ("生成主控方案", self.generate_plan),
            ("开始协同工作", self.approve_latest),
            ("暂停工作", self.pause_work),
            ("强制停止", self.force_stop),
        ]
        for index, (text, command) in enumerate(buttons, start=2):
            ttk.Button(controls, text=text, command=command).grid(row=index, column=0, sticky="ew", pady=4)

        ttk.Separator(controls).grid(row=8, column=0, sticky="ew", pady=10)
        ttk.Label(controls, textvariable=self.status_var).grid(row=9, column=0, sticky="w", pady=(0, 6))
        ttk.Label(controls, textvariable=self.task_var, wraplength=240).grid(row=10, column=0, sticky="w")
        ttk.Button(controls, text="刷新工作台状态", command=self.refresh_workspace).grid(row=11, column=0, sticky="ew", pady=(16, 4))

        log_frame = ttk.Frame(self.root, padding=(4, 4, 8, 12))
        log_frame.grid(row=1, column=1, sticky="nsew")
        log_frame.rowconfigure(1, weight=1)
        log_frame.columnconfigure(0, weight=1)
        ttk.Label(log_frame, text="运行日志").grid(row=0, column=0, sticky="w")
        self.log = scrolledtext.ScrolledText(log_frame, wrap="word", font=("Consolas", 10), height=24)
        self.log.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.log.configure(state="disabled")

        side = ttk.Frame(self.root, padding=(4, 4, 12, 12), width=300)
        side.grid(row=1, column=2, sticky="nsew")
        side.rowconfigure(1, weight=1)
        side.rowconfigure(4, weight=1)
        side.columnconfigure(0, weight=1)

        ttk.Label(side, text="最近主控方案").grid(row=0, column=0, sticky="w")
        self.plan_tree = ttk.Treeview(side, columns=("status", "goal"), show="headings", height=8)
        self.plan_tree.heading("status", text="状态")
        self.plan_tree.heading("goal", text="任务")
        self.plan_tree.column("status", width=78, stretch=False)
        self.plan_tree.column("goal", width=220, stretch=True)
        self.plan_tree.grid(row=1, column=0, sticky="nsew", pady=(4, 10))
        self.plan_tree.bind("<<TreeviewSelect>>", self._select_recent_plan)

        ttk.Label(side, text="运行进度").grid(row=2, column=0, sticky="w")
        self.progress = scrolledtext.ScrolledText(side, wrap="word", font=("Consolas", 9), height=12)
        self.progress.grid(row=4, column=0, sticky="nsew", pady=(4, 0))
        self.progress.configure(state="disabled")

    def generate_plan(self) -> None:
        goal = self.goal_var.get().strip()
        if not goal:
            messagebox.showinfo(APP_TITLE, "先输入任务目标。")
            return
        self.run_command(["run-adaptive", goal], label="生成主控方案")

    def approve_latest(self) -> None:
        task = self.latest_task_id or self.goal_var.get().strip()
        if not task:
            messagebox.showinfo(APP_TITLE, "先生成方案，或输入任务ID/关键词。")
            return
        self.run_command(["approve", task], label="开始协同工作")

    def pause_work(self) -> None:
        path = request_pause(self.project_root, source="desktop")
        self._append_log(f"[暂停] 已请求阶段边界暂停：{path}\n")

    def force_stop(self) -> None:
        process = self.current_process
        if process is None or process.poll() is not None:
            self._append_log("[强制停止] 当前没有正在运行的后台任务。\n")
            return
        if not messagebox.askyesno(APP_TITLE, "确定强制停止当前后台任务？"):
            return
        process.terminate()
        self._append_log("[强制停止] 已发送终止信号。\n")

    def run_command(self, args: list[str], *, label: str) -> None:
        if self.busy or (self.current_process is not None and self.current_process.poll() is None):
            messagebox.showinfo(APP_TITLE, "已有任务正在运行，请等待完成或强制停止。")
            return
        self.busy = True
        self.status_var.set(f"{label}：运行中")
        self._append_log(f"\n$ {' '.join(args)}\n")
        thread = threading.Thread(target=self._run_command_worker, args=(args, label), daemon=True)
        self.current_thread = thread
        thread.start()

    def refresh_workspace(self) -> None:
        self._refresh_recent_plans()
        self._set_progress_text(progress_text(self.project_root))

    def _refresh_recent_plans(self) -> None:
        for item in self.plan_tree.get_children():
            self.plan_tree.delete(item)
        for plan in load_recent_plans(self.project_root):
            goal = plan["goal"]
            if len(goal) > 42:
                goal = goal[:39] + "..."
            self.plan_tree.insert(
                "",
                "end",
                iid=plan["task_id"],
                values=(plan["status"], goal),
            )

    def _select_recent_plan(self, _event: tk.Event) -> None:
        selected = self.plan_tree.selection()
        if not selected:
            return
        task_id = selected[0]
        self.latest_task_id = task_id
        self.task_var.set(f"任务ID：{task_id}")

    def _set_progress_text(self, text: str) -> None:
        self.progress.configure(state="normal")
        self.progress.delete("1.0", "end")
        self.progress.insert("end", text)
        self.progress.configure(state="disabled")

    def _run_command_worker(self, args: list[str], label: str) -> None:
        command = cli_command(desktop_cli_args(args, self.project_root))
        try:
            process = subprocess.Popen(
                command,
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=cli_env(self.project_root),
            )
            self.current_process = process
            output, _ = process.communicate()
            code = process.returncode
        except Exception as exc:  # pragma: no cover - Tk error path is manual-use oriented
            self.output_queue.put(("done", f"{label} 失败：{exc}"))
            return
        finally:
            self.current_process = None

        output = output or ""
        if args and args[0] == "provider":
            self.output_queue.put(("provider", output))
        task_id = extract_task_id(output)
        if task_id:
            self.output_queue.put(("task", task_id))
        status = "完成" if code == 0 else f"失败（退出码 {code}）"
        self.output_queue.put(("log", output))
        self.output_queue.put(("done", f"{label}：{status}"))
        self.output_queue.put(("refresh", ""))

    def _poll_output(self) -> None:
        while True:
            try:
                kind, value = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(value)
            elif kind == "provider":
                self.provider_var.set(_provider_summary(value))
            elif kind == "task":
                self.latest_task_id = value
                self.task_var.set(f"任务ID：{value}")
            elif kind == "done":
                self.busy = False
                self.status_var.set(value)
                self._append_log(f"[{value}]\n")
            elif kind == "refresh":
                self.refresh_workspace()
        self.root.after(100, self._poll_output)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")


def _provider_summary(output: str) -> str:
    provider = "未知"
    model = ""
    key_status = ""
    for line in output.splitlines():
        if line.startswith("当前 Provider："):
            provider = line.split("：", 1)[1].strip()
        elif line.startswith("模型："):
            model = line.split("：", 1)[1].strip()
        elif line.startswith("密钥状态："):
            key_status = line.split("：", 1)[1].strip()
    suffix = f" / {model}" if model else ""
    key = f" / 密钥{key_status}" if key_status else ""
    return f"Provider：{provider}{suffix}{key}"


def main() -> None:
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

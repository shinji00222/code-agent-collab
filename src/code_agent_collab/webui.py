from __future__ import annotations

import argparse
import atexit
import json
import os
import shlex
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

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
    "provider",
    "help",
}

HELP_TEXT = """可用命令（在下面输入框输入后回车）：

  help                    显示本帮助
  provider                查看当前 AI Provider 配置
  init                    生成/重置本地配置
  start "任务目标"         生成任务上下文包
  run "任务目标"           跑完整多 Agent 工作流
  demo "任务目标"          一键演示闭环
  pending                 列出待确认候选记录
  review                  审查候选记录并入库或标记人工处理
  confirm "候选关键词"     人工确认候选入库
  discard "候选关键词"     废弃候选记录

示例：
  run "DeepSeek API 配置经验"
  pending
  review
"""

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>多Agent工作台 - 终端</title>
<style>
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; background: #0c0c0c; color: #e6e6e6;
               font-family: Consolas, "Courier New", monospace; }
  body { display: flex; flex-direction: column; overflow: hidden; }
  #titlebar { background: #012456; color: #fff; padding: 6px 12px;
              font-size: 13px; user-select: none; }
  #output { margin: 0; padding: 12px 14px; white-space: pre-wrap; word-break: break-all;
            font-size: 14px; line-height: 1.5; flex: 1;
            overflow-y: auto; }
  #input-line { display: flex; align-items: center; padding: 8px 14px;
                border-top: 1px solid #333; background: #111; }
  #prompt { color: #4ec9b0; white-space: nowrap; font-size: 14px; }
  #cmd { flex: 1; background: transparent; border: none; outline: none;
         color: #e6e6e6; font-family: inherit; font-size: 14px; }
  .out { color: #e6e6e6; }
  .err { color: #f48771; }
  .ok { color: #6a9955; }
</style>
</head>
<body>
<div id="titlebar">多Agent工作台 - PowerShell 风格终端（本地 127.0.0.1）</div>
<pre id="output"><span class="ok">欢迎使用多Agent代码协作助手。输入 help 查看可用命令。</span></pre>
<div id="input-line">
  <span id="prompt">PS project 多Agent代码协作助手&gt;</span>
  <input id="cmd" autofocus autocomplete="off" spellcheck="false">
</div>
<script>
  const output = document.getElementById("output");
  const cmdInput = document.getElementById("cmd");

  function append(html) {
    output.insertAdjacentHTML("beforeend", html);
    output.scrollTop = output.scrollHeight;
  }

  async function run(command) {
    append(`<span class="promptline">PS project 多Agent代码协作助手&gt; <span class="out">${escapeHtml(command)}</span></span>\\n`);
    cmdInput.value = "";
    try {
      const resp = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        append(`<span class="err">${escapeHtml(data.error || "请求失败")}</span>\\n`);
        return;
      }
      const cls = data.code === 0 ? "out" : "err";
      append(`<span class="${cls}">${escapeHtml(data.output)}</span>\\n`);
    } catch (e) {
      append(`<span class="err">网络错误：${escapeHtml(String(e))}</span>\\n`);
    }
  }

  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                       .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  cmdInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && cmdInput.value.trim()) {
      run(cmdInput.value.trim());
    }
  });
</script>
</body>
</html>
"""

_ACTIVE_PROCESSES: set[subprocess.Popen] = set()


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
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
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    process = subprocess.Popen(
        [sys.executable, "-m", "code_agent_collab.cli", *args],
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
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
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
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Web UI: http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()

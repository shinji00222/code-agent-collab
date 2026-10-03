from __future__ import annotations

import argparse
import json
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .control import request_pause
from .web_discussion import build_discussion_goal, clear_discussion, discuss_with_orchestrator
from .web_jobs import (
    _kill_process_tree,
    build_command,
    force_stop_active_work,
    get_command_job,
    run_cli,
    start_command_job,
)
from .web_progress import build_progress_snapshot
from .web_project import PROJECT_ROOT, PROJECT_ROOT_ENV, SRC_DIR, resolve_project_root
from .webui_page import PAGE as TERMINAL_PAGE

PAGE = TERMINAL_PAGE

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

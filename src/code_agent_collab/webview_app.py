from __future__ import annotations

import argparse
import socket
import threading
import time
from contextlib import closing
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import webview

from .webui import Handler

APP_TITLE = "多Agent工作台"
DEFAULT_PORT = 8765
PORT_ATTEMPTS = 50


def find_free_port(start: int = 8765, attempts: int = 50) -> int:
    for port in range(start, start + attempts):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("无法找到可用本机端口")


def _create_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def start_local_server(port: int | None = None) -> tuple[ThreadingHTTPServer, str]:
    if port:
        selected_port = port
        server = _create_server(selected_port)
    else:
        server = None
        selected_port = DEFAULT_PORT
        for candidate in range(DEFAULT_PORT, DEFAULT_PORT + PORT_ATTEMPTS):
            try:
                server = _create_server(candidate)
            except OSError:
                continue
            selected_port = candidate
            break
        if server is None:
            raise RuntimeError("无法启动本机服务：没有可用端口")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server._agent_workbench_thread = thread  # type: ignore[attr-defined]
    return server, f"http://127.0.0.1:{selected_port}"


def wait_until_ready(url: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except Exception as exc:  # pragma: no cover - exercised through retries
            last_error = exc
        time.sleep(0.1)
    if last_error is not None:
        raise RuntimeError(f"本地服务启动超时：{last_error}") from last_error
    raise RuntimeError("本地服务启动超时")


def stop_local_server(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()
    thread = getattr(server, "_agent_workbench_thread", None)
    if thread is not None:
        thread.join(timeout=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="多Agent工作台本地软件窗口")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)

    server, url = start_local_server(args.port or None)
    try:
        wait_until_ready(url)
        webview.create_window(APP_TITLE, url, width=1280, height=820, min_size=(980, 620))
        webview.start(gui="edgechromium")
    finally:
        stop_local_server(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

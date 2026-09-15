from __future__ import annotations

import argparse
import socket
import threading
from contextlib import closing
from http.server import ThreadingHTTPServer

import webview

from .webui import Handler

APP_TITLE = "多Agent工作台"


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


def start_local_server(port: int | None = None) -> tuple[ThreadingHTTPServer, str]:
    selected_port = port or find_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", selected_port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{selected_port}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="多Agent工作台本地软件窗口")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)

    server, url = start_local_server(args.port or None)
    try:
        webview.create_window(APP_TITLE, url, width=1280, height=820, min_size=(980, 620))
        webview.start(gui="edgechromium")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

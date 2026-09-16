from __future__ import annotations

import urllib.request
import unittest
from contextlib import closing
from socket import AF_INET, SOCK_STREAM, socket

from code_agent_collab.webview_app import (
    DEFAULT_PORT,
    find_free_port,
    start_local_server,
    stop_local_server,
    wait_until_ready,
)


class WebViewAppTests(unittest.TestCase):
    def test_find_free_port_returns_available_local_port(self) -> None:
        port = find_free_port(start=8765, attempts=5)
        self.assertGreaterEqual(port, 8765)

    def test_local_server_serves_original_web_ui(self) -> None:
        server, url = start_local_server()
        try:
            wait_until_ready(url)
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode("utf-8")
        finally:
            stop_local_server(server)

        self.assertIn("/api/jobs", body)
        self.assertIn("pollJob", body)
        self.assertIn("IntegratorAgent", body)

    def test_local_server_skips_occupied_default_port(self) -> None:
        with closing(socket(AF_INET, SOCK_STREAM)) as sock:
            sock.bind(("127.0.0.1", DEFAULT_PORT))
            sock.listen(1)
            server, url = start_local_server()
            try:
                self.assertNotEqual(url, f"http://127.0.0.1:{DEFAULT_PORT}")
                wait_until_ready(url)
            finally:
                stop_local_server(server)


if __name__ == "__main__":
    unittest.main()

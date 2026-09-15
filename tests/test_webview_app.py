from __future__ import annotations

import urllib.request
import unittest

from code_agent_collab.webview_app import find_free_port, start_local_server


class WebViewAppTests(unittest.TestCase):
    def test_find_free_port_returns_available_local_port(self) -> None:
        port = find_free_port(start=8765, attempts=5)
        self.assertGreaterEqual(port, 8765)

    def test_local_server_serves_original_web_ui(self) -> None:
        server, url = start_local_server()
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()

        self.assertIn("/api/jobs", body)
        self.assertIn("pollJob", body)
        self.assertIn("IntegratorAgent", body)


if __name__ == "__main__":
    unittest.main()

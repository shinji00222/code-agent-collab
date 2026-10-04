from __future__ import annotations

import io
import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from code_agent_collab.web_security import (
    MAX_BODY_BYTES,
    SECURITY_HEADERS,
    RequestRejected,
    check_content_type,
    check_host,
    check_origin,
    inspect_request,
    read_json_body,
)
from code_agent_collab.webui import Handler


class CheckHostTests(unittest.TestCase):
    def test_loopback_hosts_are_allowed(self) -> None:
        for value in ("127.0.0.1:8765", "localhost:8080", "127.0.0.1", "[::1]:8765", "localhost"):
            with self.subTest(host=value):
                self.assertIsNone(check_host(value))

    def test_other_hosts_are_rejected(self) -> None:
        """DNS rebinding 场景下浏览器发的 Host 是攻击者域名，必须拒绝。"""
        for value in ("evil.com", "evil.com:8765", "192.168.1.10:8765", "0.0.0.0:8080"):
            with self.subTest(host=value):
                rejection = check_host(value)
                self.assertIsNotNone(rejection)
                assert rejection is not None
                self.assertEqual(rejection.status, 403)

    def test_missing_host_is_rejected(self) -> None:
        rejection = check_host(None)
        self.assertIsNotNone(rejection)
        assert rejection is not None
        self.assertEqual(rejection.status, 400)


class CheckOriginTests(unittest.TestCase):
    def test_missing_origin_is_allowed(self) -> None:
        """没有 Origin/Referer 说明不是浏览器发的（脚本、curl），交给其它防线。"""
        self.assertIsNone(check_origin(None, None))
        self.assertIsNone(check_origin("", ""))

    def test_loopback_origin_is_allowed(self) -> None:
        self.assertIsNone(check_origin("http://127.0.0.1:8765", None))
        self.assertIsNone(check_origin("http://localhost:8080/", None))
        self.assertIsNone(check_origin(None, "http://127.0.0.1:8765/index.html"))

    def test_foreign_origin_is_rejected(self) -> None:
        for origin in ("http://evil.com", "https://evil.com:443", "https://attacker.test"):
            with self.subTest(origin=origin):
                rejection = check_origin(origin, None)
                self.assertIsNotNone(rejection)
                assert rejection is not None
                self.assertEqual(rejection.status, 403)


class CheckContentTypeTests(unittest.TestCase):
    def test_json_is_allowed(self) -> None:
        self.assertIsNone(check_content_type("application/json"))
        self.assertIsNone(check_content_type("application/json; charset=utf-8"))

    def test_simple_request_types_are_rejected(self) -> None:
        """跨站表单只能发这几类，正好被挡住。"""
        for value in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", None, ""):
            with self.subTest(content_type=value):
                rejection = check_content_type(value)
                self.assertIsNotNone(rejection)
                assert rejection is not None
                self.assertEqual(rejection.status, 415)


class InspectRequestTests(unittest.TestCase):
    def test_get_only_checks_host(self) -> None:
        headers = {"Host": "127.0.0.1:8765", "Content-Type": "text/plain"}
        self.assertIsNone(inspect_request(headers, json_body=False))

    def test_post_requires_json_and_same_origin(self) -> None:
        base = {"Host": "127.0.0.1:8765", "Content-Type": "application/json"}
        self.assertIsNone(inspect_request(base, json_body=True))

        cross_site = dict(base, Origin="http://evil.com")
        rejection = inspect_request(cross_site, json_body=True)
        assert rejection is not None
        self.assertEqual(rejection.status, 403)

        fetch_metadata = dict(base, **{"Sec-Fetch-Site": "cross-site"})
        rejection = inspect_request(fetch_metadata, json_body=True)
        assert rejection is not None
        self.assertEqual(rejection.status, 403)

        no_json = {"Host": "127.0.0.1:8765", "Content-Type": "text/plain"}
        rejection = inspect_request(no_json, json_body=True)
        assert rejection is not None
        self.assertEqual(rejection.status, 415)

    def test_headers_are_case_insensitive(self) -> None:
        headers = {"host": "127.0.0.1:8765", "content-type": "application/json"}
        self.assertIsNone(inspect_request(headers, json_body=True))

    def test_host_is_checked_before_anything_else(self) -> None:
        headers = {"Host": "evil.com", "Content-Type": "text/plain"}
        rejection = inspect_request(headers, json_body=True)
        assert rejection is not None
        self.assertEqual(rejection.status, 403)


class _FakeHandler:
    def __init__(self, headers: dict[str, str], body: bytes = b"") -> None:
        self.headers = headers
        self.rfile = io.BytesIO(body)


class ReadJsonBodyTests(unittest.TestCase):
    def test_empty_body_returns_empty_dict(self) -> None:
        self.assertEqual(read_json_body(_FakeHandler({"Content-Length": "0"})), {})
        self.assertEqual(read_json_body(_FakeHandler({})), {})

    def test_valid_body_is_parsed(self) -> None:
        body = json.dumps({"command": "help"}).encode("utf-8")
        handler = _FakeHandler(
            {"Content-Length": str(len(body)), "Content-Type": "application/json"},
            body,
        )
        self.assertEqual(read_json_body(handler), {"command": "help"})

    def test_oversized_body_is_rejected_without_reading_it(self) -> None:
        handler = _FakeHandler({"Content-Length": str(MAX_BODY_BYTES + 1)})
        with self.assertRaises(RequestRejected) as ctx:
            read_json_body(handler)
        self.assertEqual(ctx.exception.status, 413)

    def test_invalid_json_is_rejected(self) -> None:
        body = b"not json"
        handler = _FakeHandler({"Content-Length": str(len(body))}, body)
        with self.assertRaises(RequestRejected) as ctx:
            read_json_body(handler)
        self.assertEqual(ctx.exception.status, 400)

    def test_non_object_json_is_rejected(self) -> None:
        body = b"[1, 2, 3]"
        handler = _FakeHandler({"Content-Length": str(len(body))}, body)
        with self.assertRaises(RequestRejected) as ctx:
            read_json_body(handler)
        self.assertEqual(ctx.exception.status, 400)


class WebApiIntegrationTests(unittest.TestCase):
    """起一个真实本机服务，验证拦截真的生效、正常请求不被误伤。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        payload: dict | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_normal_get_returns_page_with_security_headers(self) -> None:
        status, headers, body = self._request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Agent Workbench", body)
        for name, value in SECURITY_HEADERS.items():
            self.assertEqual(headers.get(name), value)

    def test_foreign_host_is_rejected(self) -> None:
        status, _, body = self._request("/", headers={"Host": "evil.com"})
        self.assertEqual(status, 403)
        self.assertIn("Host".encode(), body)

    def test_cross_site_job_post_is_rejected_without_side_effect(self) -> None:
        with patch("code_agent_collab.webui.start_command_job") as start:
            status, _, _ = self._request(
                "/api/jobs",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Origin": "http://evil.com",
                },
                payload={"command": "help"},
            )
        self.assertEqual(status, 403)
        start.assert_not_called()

    def test_cross_site_fetch_metadata_is_rejected(self) -> None:
        with patch("code_agent_collab.webui.start_command_job") as start:
            status, _, _ = self._request(
                "/api/jobs",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Sec-Fetch-Site": "cross-site",
                },
                payload={"command": "help"},
            )
        self.assertEqual(status, 403)
        start.assert_not_called()

    def test_form_content_type_is_rejected(self) -> None:
        with patch("code_agent_collab.webui.start_command_job") as start:
            status, _, _ = self._request(
                "/api/jobs",
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                payload={"command": "help"},
            )
        self.assertEqual(status, 415)
        start.assert_not_called()

    def test_same_origin_post_is_allowed(self) -> None:
        with patch(
            "code_agent_collab.webui.start_command_job",
            return_value={"job_id": "stub", "status": "queued"},
        ) as start:
            status, _, body = self._request(
                "/api/jobs",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Origin": f"http://127.0.0.1:{self.port}",
                },
                payload={"command": "help"},
            )
        self.assertEqual(status, 202)
        start.assert_called_once_with("help")
        self.assertIn(b"stub", body)

    def test_force_stop_still_requires_confirmation_word(self) -> None:
        with patch("code_agent_collab.webui.force_stop_active_work") as stop:
            status, _, _ = self._request(
                "/api/force-stop",
                method="POST",
                headers={"Content-Type": "application/json"},
                payload={"confirm": "nope"},
            )
        self.assertEqual(status, 400)
        stop.assert_not_called()

    def test_pause_endpoint_accepts_json_post(self) -> None:
        with patch("code_agent_collab.webui.request_pause") as pause:
            status, _, _ = self._request(
                "/api/pause",
                method="POST",
                headers={"Content-Type": "application/json"},
                payload={},
            )
        self.assertEqual(status, 200)
        pause.assert_called_once()

    def test_oversized_body_is_rejected_with_413(self) -> None:
        """只发头部不发正文：服务端必须在读取前就按 Content-Length 拒绝。"""
        request = (
            "POST /api/jobs HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {MAX_BODY_BYTES + 1}\r\n"
            "Connection: close\r\n\r\n"
        )
        with patch("code_agent_collab.webui.start_command_job") as start:
            with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
                sock.sendall(request.encode("ascii"))
                chunks = []
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
        response = b"".join(chunks)
        self.assertTrue(response.startswith(b"HTTP/1."), response[:50])
        self.assertEqual(int(response.split(b" ")[1]), 413)
        self.assertIn("请求体过大".encode("utf-8"), response)
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()

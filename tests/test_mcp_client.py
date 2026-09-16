from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

from code_agent_collab.mcp_bridge import (
    McpProtocolError,
    McpServerError,
    McpStdioClient,
    McpTimeoutError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def make_client(mode: str = "normal", **kwargs) -> McpStdioClient:
    env = {"FAKE_MCP_MODE": mode}
    env.update(kwargs.pop("extra_env", {}))
    return McpStdioClient(
        [sys.executable, str(FIXTURE)],
        name="fake",
        env=env,
        **kwargs,
    )


class McpClientHandshakeTests(unittest.TestCase):
    def test_handshake_records_server_identity(self) -> None:
        with make_client() as client:
            self.assertEqual(client.protocol_version, "2025-06-18")
            self.assertEqual(client.server_info.get("name"), "fake-mcp-server")
            self.assertTrue(client.supports_tools())
            self.assertTrue(client.is_running())

    def test_server_without_tools_capability_is_rejected(self) -> None:
        with self.assertRaises(McpProtocolError) as ctx:
            make_client("no_tools_capability").start()
        self.assertIn("tools", str(ctx.exception))

    def test_handshake_timeout_reports_timeout_error(self) -> None:
        started = time.monotonic()
        with self.assertRaises(McpTimeoutError):
            make_client(
                "slow",
                timeout_seconds=0.6,
                extra_env={"FAKE_MCP_DELAY_MS": "5000"},
            ).start()
        # 超时必须及时抛出，而不是干等子进程
        self.assertLess(time.monotonic() - started, 4.0)

    def test_empty_command_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            McpStdioClient([], name="fake")


class McpClientToolDiscoveryTests(unittest.TestCase):
    def test_list_tools_returns_all_tools(self) -> None:
        with make_client() as client:
            names = [tool.name for tool in client.list_tools()]
        self.assertEqual(names, ["echo", "fail", "server_state", "structured"])

    def test_pagination_is_followed_until_last_page(self) -> None:
        with make_client("pagination") as client:
            names = [tool.name for tool in client.list_tools()]
        self.assertEqual(names, ["echo", "fail", "server_state", "structured"])

    def test_repeated_cursor_raises_instead_of_looping_forever(self) -> None:
        with make_client("bad_cursor") as client:
            with self.assertRaises(McpProtocolError) as ctx:
                client.list_tools()
        self.assertIn("分页游标重复", str(ctx.exception))


class McpClientToolCallTests(unittest.TestCase):
    def test_call_tool_returns_text_content(self) -> None:
        with make_client() as client:
            result = client.call_tool("echo", {"text": "你好"})
        self.assertFalse(result.is_error)
        self.assertEqual(result.text, "echo: 你好")

    def test_tool_execution_error_is_reported_not_raised(self) -> None:
        with make_client() as client:
            result = client.call_tool("fail")
        self.assertTrue(result.is_error)
        self.assertIn("限流", result.text)

    def test_unknown_tool_raises_server_error(self) -> None:
        with make_client() as client:
            with self.assertRaises(McpServerError) as ctx:
                client.call_tool("does_not_exist")
        self.assertEqual(ctx.exception.code, -32602)

    def test_structured_content_is_exposed(self) -> None:
        with make_client() as client:
            result = client.call_tool("structured")
        self.assertEqual(result.structured, {"answer": 42})


class McpClientRobustnessTests(unittest.TestCase):
    def test_large_stderr_output_does_not_deadlock(self) -> None:
        """服务端灌 200KB stderr 时客户端仍能正常通信（证明 stderr 已被排空）。"""
        started = time.monotonic()
        with make_client("stderr_flood", timeout_seconds=20.0) as client:
            result = client.call_tool("echo", {"text": "still alive"})
            stderr_lines = client.stderr_tail(limit=5)
        self.assertEqual(result.text, "echo: still alive")
        self.assertTrue(stderr_lines)
        self.assertLess(time.monotonic() - started, 15.0)

    def test_non_json_stdout_is_skipped(self) -> None:
        with make_client("junk_stdout") as client:
            result = client.call_tool("echo", {"text": "ok"})
        self.assertEqual(result.text, "echo: ok")

    def test_client_answers_server_initiated_request(self) -> None:
        """服务端反向请求必须被回应，否则服务端会一直阻塞等待。"""
        with make_client("server_request") as client:
            client.list_tools()
            result = client.call_tool("server_state")
        self.assertIn('"client_reply_received": true', result.text)

    def test_close_is_idempotent_and_stops_process(self) -> None:
        client = make_client().start()
        client.close()
        client.close()
        self.assertFalse(client.is_running())


if __name__ == "__main__":
    unittest.main()

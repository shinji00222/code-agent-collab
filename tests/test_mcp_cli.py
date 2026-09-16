from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from code_agent_collab.cli import main
from code_agent_collab.mcp_bridge import ENV_SERVERS

FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def servers_env(mode: str = "normal") -> str:
    return json.dumps(
        {
            "fake": {
                "command": [sys.executable, str(FIXTURE)],
                "env": {"FAKE_MCP_MODE": mode},
                "timeoutSeconds": 15,
            }
        }
    )


def run_cli(argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


class McpCliTests(unittest.TestCase):
    def setUp(self) -> None:
        import os

        self._os = os
        self._previous = os.environ.get(ENV_SERVERS)

    def tearDown(self) -> None:
        if self._previous is None:
            self._os.environ.pop(ENV_SERVERS, None)
        else:
            self._os.environ[ENV_SERVERS] = self._previous

    def test_list_without_configuration_explains_how_to_configure(self) -> None:
        self._os.environ.pop(ENV_SERVERS, None)
        code, output = run_cli(["mcp", "list"])
        self.assertEqual(code, 0)
        self.assertIn("尚未配置", output)
        self.assertIn(ENV_SERVERS, output)

    def test_list_shows_connected_servers_and_tools(self) -> None:
        self._os.environ[ENV_SERVERS] = servers_env()
        code, output = run_cli(["mcp", "list"])
        self.assertEqual(code, 0)
        self.assertIn("fake.echo", output)
        self.assertIn("原样返回输入的文本", output)

    def test_list_reports_broken_server_without_crashing(self) -> None:
        self._os.environ[ENV_SERVERS] = json.dumps(
            {
                "broken": {"command": [sys.executable, "-c", "import sys; sys.exit(4)"]},
                "fake": {"command": [sys.executable, str(FIXTURE)]},
            }
        )
        code, output = run_cli(["mcp", "list"])
        self.assertEqual(code, 0)
        self.assertIn("[服务端 broken 不可用]", output)
        self.assertIn("fake.echo", output)

    def test_call_executes_tool_and_prints_text(self) -> None:
        self._os.environ[ENV_SERVERS] = servers_env()
        code, output = run_cli(
            ["mcp", "call", "fake.echo", "--args-json", json.dumps({"text": "hi"})]
        )
        self.assertEqual(code, 0)
        self.assertIn("echo: hi", output)

    def test_call_returns_nonzero_when_tool_reports_error(self) -> None:
        self._os.environ[ENV_SERVERS] = servers_env()
        code, output = run_cli(["mcp", "call", "fake.fail"])
        self.assertEqual(code, 1)
        self.assertIn("isError", output)

    def test_call_rejects_invalid_json_arguments(self) -> None:
        self._os.environ[ENV_SERVERS] = servers_env()
        code, output = run_cli(["mcp", "call", "fake.echo", "--args-json", "{not json"])
        self.assertEqual(code, 2)
        self.assertIn("不是合法 JSON", output)

    def test_call_rejects_non_object_arguments(self) -> None:
        self._os.environ[ENV_SERVERS] = servers_env()
        code, output = run_cli(["mcp", "call", "fake.echo", "--args-json", "[1,2]"])
        self.assertEqual(code, 2)
        self.assertIn("必须是 JSON 对象", output)

    def test_call_with_invalid_config_returns_config_error(self) -> None:
        self._os.environ[ENV_SERVERS] = "{not json"
        code, output = run_cli(["mcp", "list"])
        self.assertEqual(code, 2)
        self.assertIn("MCP 配置有误", output)

    def test_ask_runs_tool_loop_with_mock_provider(self) -> None:
        self._os.environ[ENV_SERVERS] = servers_env()
        self._os.environ["AGENT_WORKBENCH_PROVIDER"] = "mock"
        code, output = run_cli(["mcp", "ask", "帮我看一下"])
        self.assertEqual(code, 0)
        self.assertIn("模拟 AI 已收到任务", output)

    def test_project_root_option_is_accepted_after_subcommand(self) -> None:
        """回归：--project-root 必须定义在每个 mcp 子子命令上（argparse 不继承父级参数）。"""
        import tempfile

        self._os.environ[ENV_SERVERS] = servers_env()
        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_cli(["mcp", "list", "--project-root", tmp])
            self.assertEqual(code, 0)
            self.assertIn("fake.echo", output)

            code, output = run_cli(
                ["mcp", "call", "fake.echo", "--args-json", '{"text":"hi"}', "--project-root", tmp]
            )
            self.assertEqual(code, 0)
            self.assertIn("echo: hi", output)


if __name__ == "__main__":
    unittest.main()

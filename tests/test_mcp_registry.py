from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from code_agent_collab.mcp_bridge import (
    ENV_SERVERS,
    McpConfigError,
    McpError,
    McpServerSpec,
    McpToolRegistry,
    default_python_command,
    load_server_specs,
    parse_server_specs,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def spec(name: str = "fake", mode: str = "normal") -> McpServerSpec:
    return McpServerSpec(
        name=name,
        command=tuple(default_python_command(FIXTURE)),
        env={"FAKE_MCP_MODE": mode},
        timeout_seconds=15.0,
    )


class ServerSpecParsingTests(unittest.TestCase):
    def test_parse_valid_specs(self) -> None:
        specs = parse_server_specs(
            {
                "filesystem": {
                    "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "C:/data"],
                    "env": {"DEBUG": "1"},
                    "timeoutSeconds": 45,
                }
            }
        )
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].name, "filesystem")
        self.assertEqual(specs[0].timeout_seconds, 45.0)
        self.assertEqual(specs[0].env, {"DEBUG": "1"})

    def test_command_must_be_array_not_string(self) -> None:
        with self.assertRaises(McpConfigError) as ctx:
            parse_server_specs({"bad": {"command": "npx -y something"}})
        self.assertIn("字符串数组", str(ctx.exception))

    def test_server_name_cannot_contain_separator(self) -> None:
        with self.assertRaises(McpConfigError):
            parse_server_specs({"a.b": {"command": ["echo"]}})

    def test_timeout_must_be_positive(self) -> None:
        with self.assertRaises(McpConfigError):
            parse_server_specs({"x": {"command": ["echo"], "timeoutSeconds": 0}})

    def test_load_specs_from_env_overrides_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / ".agent-workbench"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps({"mcpServers": {"from_file": {"command": ["echo", "a"]}}}),
                encoding="utf-8",
            )
            previous = os.environ.get(ENV_SERVERS)
            os.environ[ENV_SERVERS] = json.dumps({"from_env": {"command": ["echo", "b"]}})
            try:
                specs = load_server_specs(root)
            finally:
                if previous is None:
                    os.environ.pop(ENV_SERVERS, None)
                else:
                    os.environ[ENV_SERVERS] = previous
        self.assertEqual([item.name for item in specs], ["from_env"])

    def test_load_specs_from_project_config_when_no_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / ".agent-workbench"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps({"mcpServers": {"from_file": {"command": ["echo", "a"]}}}),
                encoding="utf-8",
            )
            previous = os.environ.pop(ENV_SERVERS, None)
            try:
                specs = load_server_specs(root)
            finally:
                if previous is not None:
                    os.environ[ENV_SERVERS] = previous
        self.assertEqual([item.name for item in specs], ["from_file"])

    def test_missing_config_returns_no_specs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.environ.pop(ENV_SERVERS, None)
            try:
                self.assertEqual(load_server_specs(Path(tmp)), [])
            finally:
                if previous is not None:
                    os.environ[ENV_SERVERS] = previous


class ToolRegistryTests(unittest.TestCase):
    def test_registry_discovers_tools_with_qualified_names(self) -> None:
        with McpToolRegistry([spec("alpha")]) as registry:
            names = sorted(tool.qualified_name for tool in registry.tools())
        self.assertEqual(
            names,
            ["alpha.echo", "alpha.fail", "alpha.server_state", "alpha.structured"],
        )

    def test_registry_calls_tool_by_qualified_name(self) -> None:
        with McpToolRegistry([spec("alpha")]) as registry:
            result = registry.call("alpha.echo", {"text": "hi"})
        self.assertEqual(result.text, "echo: hi")

    def test_registry_accepts_unambiguous_bare_name(self) -> None:
        with McpToolRegistry([spec("alpha")]) as registry:
            result = registry.call("echo", {"text": "bare"})
        self.assertEqual(result.text, "echo: bare")

    def test_ambiguous_bare_name_requires_qualification(self) -> None:
        registry = McpToolRegistry([spec("alpha"), spec("beta")])
        registry.start()
        try:
            with self.assertRaises(McpError) as ctx:
                registry.call("echo", {"text": "x"})
            message = str(ctx.exception)
            self.assertIn("alpha.echo", message)
            self.assertIn("beta.echo", message)
        finally:
            registry.close()

    def test_unknown_tool_message_lists_available_tools(self) -> None:
        with McpToolRegistry([spec("alpha")]) as registry:
            with self.assertRaises(McpError) as ctx:
                registry.call("nope")
        self.assertIn("alpha.echo", str(ctx.exception))

    def test_one_broken_server_does_not_take_down_the_rest(self) -> None:
        broken = McpServerSpec(
            name="broken",
            command=(sys.executable, "-c", "import sys; sys.exit(3)"),
            timeout_seconds=10.0,
        )
        registry = McpToolRegistry([broken, spec("alpha")])
        registry.start()
        try:
            self.assertIn("broken", registry.errors)
            self.assertEqual(registry.server_names(), ["alpha"])
            self.assertEqual(registry.call("alpha.echo", {"text": "ok"}).text, "echo: ok")
        finally:
            registry.close()

    def test_describe_for_prompt_lists_tools_and_schemas(self) -> None:
        with McpToolRegistry([spec("alpha")]) as registry:
            description = registry.describe_for_prompt()
        self.assertIn("alpha.echo", description)
        self.assertIn("原样返回输入的文本", description)

    def test_describe_for_prompt_handles_empty_registry(self) -> None:
        with McpToolRegistry([]) as registry:
            self.assertIn("没有可用的 MCP 工具", registry.describe_for_prompt())


if __name__ == "__main__":
    unittest.main()

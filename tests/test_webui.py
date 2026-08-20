from __future__ import annotations

import unittest

from code_agent_collab.webui import build_command, run_cli


class CommandBuildTests(unittest.TestCase):
    def test_build_allows_known_commands(self) -> None:
        self.assertEqual(build_command('run "测试任务"'), ["run", "测试任务"])
        self.assertEqual(build_command("pending"), ["pending"])

    def test_build_rejects_unknown_commands(self) -> None:
        with self.assertRaises(ValueError):
            build_command("rm -rf C:\\")

    def test_build_rejects_empty_command(self) -> None:
        with self.assertRaises(ValueError):
            build_command("   ")


class RunCliTests(unittest.TestCase):
    def test_help_returns_help_text(self) -> None:
        code, output = run_cli(["help"])
        self.assertEqual(code, 0)
        self.assertIn("run", output)
        self.assertIn("review", output)

    def test_provider_outputs_config(self) -> None:
        code, output = run_cli(["provider"])
        self.assertEqual(code, 0)
        self.assertIn("当前 Provider", output)


if __name__ == "__main__":
    unittest.main()

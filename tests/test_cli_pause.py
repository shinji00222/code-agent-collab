from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.cli import main
from code_agent_collab.control import pause_path, request_pause


class CliPauseStateTests(unittest.TestCase):
    def _assert_work_command_clears_stale_pause(self, argv: list[str], target: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_pause(root, source="test")
            self.assertTrue(pause_path(root).exists())

            def fail_after_pause_check(*args, **kwargs):
                del args, kwargs
                self.assertFalse(pause_path(root).exists())
                raise ValueError("stop after pause check")

            with patch(target, side_effect=fail_after_pause_check), patch("sys.stdout", new=io.StringIO()):
                code = main([*argv, "--project-root", str(root)])

            self.assertEqual(code, 2)
            self.assertFalse(pause_path(root).exists())

    def test_run_clears_stale_pause_before_workflow(self) -> None:
        self._assert_work_command_clears_stale_pause(
            ["run", "测试目标"],
            "code_agent_collab.cli.run_workflow",
        )

    def test_run_adaptive_clears_stale_pause_before_plan_creation(self) -> None:
        self._assert_work_command_clears_stale_pause(
            ["run-adaptive", "测试目标"],
            "code_agent_collab.cli.create_adaptive_plan",
        )

    def test_approve_clears_stale_pause_before_execution(self) -> None:
        self._assert_work_command_clears_stale_pause(
            ["approve", "task-id"],
            "code_agent_collab.cli.execute_adaptive_plan",
        )

    def test_coding_loop_clears_stale_pause_before_execution(self) -> None:
        self._assert_work_command_clears_stale_pause(
            ["coding-loop", "测试目标"],
            "code_agent_collab.cli.run_coding_loop",
        )


if __name__ == "__main__":
    unittest.main()

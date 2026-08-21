from __future__ import annotations

import subprocess
import sys
import unittest

from code_agent_collab.webui import (
    PAGE,
    PROJECT_ROOT,
    SRC_DIR,
    _kill_process_tree,
    build_command,
    run_cli,
)


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

    def test_kill_process_tree_terminates_child(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _kill_process_tree(process)
            process.wait(timeout=10)
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                _kill_process_tree(process)


class PageTests(unittest.TestCase):
    def test_page_contains_task_workbench_controls(self) -> None:
        self.assertIn("Codex", PAGE)
        self.assertIn("文件", PAGE)
        self.assertNotIn("Share", PAGE)
        self.assertNotIn("打开位置", PAGE)
        self.assertIn("环境信息", PAGE)
        self.assertIn("只生成上下文", PAGE)
        self.assertIn("新对话", PAGE)
        self.assertIn("toggleLeftPanel", PAGE)
        self.assertIn("toggleOutput", PAGE)
        self.assertIn("toggleRightPanel", PAGE)

    def test_webui_project_root_points_to_repository_root(self) -> None:
        self.assertEqual(SRC_DIR, PROJECT_ROOT / "src")
        self.assertTrue((PROJECT_ROOT / "pyproject.toml").exists())
        self.assertTrue((SRC_DIR / "code_agent_collab").exists())


if __name__ == "__main__":
    unittest.main()

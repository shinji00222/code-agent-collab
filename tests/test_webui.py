from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from code_agent_collab.webui import (
    PAGE,
    PROJECT_ROOT,
    SRC_DIR,
    _kill_process_tree,
    build_progress_snapshot,
    build_command,
    run_cli,
)


class CommandBuildTests(unittest.TestCase):
    def test_build_allows_known_commands(self) -> None:
        self.assertEqual(build_command('run "测试任务"'), ["run", "测试任务"])
        self.assertEqual(build_command("pending"), ["pending"])
        self.assertEqual(build_command("plans"), ["plans"])

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
        self.assertIn("plans", output)

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
        self.assertIn("Agent Workbench", PAGE)
        self.assertIn("terminal", PAGE)
        self.assertNotIn("Share", PAGE)
        self.assertNotIn("打开位置", PAGE)
        self.assertNotIn("文件", PAGE)
        self.assertNotIn("环境信息", PAGE)
        self.assertIn("progressSummaryInline", PAGE)
        self.assertIn("agentTreeInline", PAGE)
        self.assertIn("ReviewerAgent", PAGE)
        self.assertIn("Fix Loop", PAGE)
        self.assertIn("var(--purple)", PAGE)
        self.assertIn("branch-child", PAGE)
        self.assertIn("renderBranch", PAGE)
        self.assertIn("/api/progress", PAGE)
        self.assertIn("setInterval(refreshProgress, 2500)", PAGE)
        self.assertNotIn("branch-wire", PAGE)
        self.assertNotIn("branch-grid", PAGE)
        self.assertNotIn("toggleLeftPanel", PAGE)
        self.assertNotIn("toggleOutput", PAGE)
        self.assertNotIn("toggleRightPanel", PAGE)

    def test_webui_project_root_points_to_repository_root(self) -> None:
        self.assertEqual(SRC_DIR, PROJECT_ROOT / "src")
        self.assertTrue((PROJECT_ROOT / "pyproject.toml").exists())
        self.assertTrue((SRC_DIR / "code_agent_collab").exists())


class ProgressSnapshotTests(unittest.TestCase):
    def test_progress_snapshot_reads_saved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans_dir = root / "logs" / "plans"
            context_dir = root / "logs" / "context-packs"
            plans_dir.mkdir(parents=True)
            context_dir.mkdir(parents=True)
            task_id = "20260828-120000-可视化"
            (context_dir / f"{task_id}.md").write_text("# context", encoding="utf-8")
            (plans_dir / f"{task_id}.json").write_text(
                """{
  "task_id": "20260828-120000-可视化",
  "goal": "可视化关系树",
  "orchestrator_summary": "测试方案",
  "complexity": "complex",
  "label": "复杂任务：知识 + 双编码 + 评审",
  "worker_count": 4,
  "stages": [[["KnowledgeAgent", null]], [["CoderAgent", "A"], ["CoderAgent", "B"]], [["ReviewerAgent", null]]]
}
""",
                encoding="utf-8",
            )

            snapshot = build_progress_snapshot(root)

            self.assertEqual(snapshot["latest_plan"]["task_id"], task_id)
            self.assertEqual(snapshot["latest_plan"]["status"], "待批准")
            self.assertIsNone(snapshot["latest_workflow"])
            labels = [node.get("label", "") for node in snapshot["nodes"] if node["kind"] == "node"]
            self.assertIn("OrchestratorAgent", labels)
            self.assertIn("人工审批", labels)
            branch_nodes = [node for node in snapshot["nodes"] if node["kind"] == "branch"]
            self.assertEqual(len(branch_nodes), 1)
            self.assertEqual(len(branch_nodes[0]["children"]), 2)

    def test_progress_snapshot_prefers_runtime_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress_dir = root / "logs" / "progress"
            progress_dir.mkdir(parents=True)
            (progress_dir / "current.json").write_text(
                """{
  "task_id": "runtime-task",
  "goal": "实时树状进度",
  "status": "running",
  "detail": "ReviewerAgent 正在审查。",
  "updated_at": "2026-09-04T17:20:15.000",
  "nodes": [
    {"kind": "node", "label": "CoderAgent", "status": "done", "detail": "生成代码草稿"},
    {"kind": "node", "label": "ReviewerAgent", "status": "running", "detail": "审查 coder 草稿"},
    {"kind": "node", "label": "Done", "status": "idle", "detail": "执行结束"}
  ]
}
""",
                encoding="utf-8",
            )

            snapshot = build_progress_snapshot(root)

            self.assertEqual(snapshot["runtime"]["task_id"], "runtime-task")
            labels = [node["label"] for node in snapshot["nodes"]]
            statuses = {node["label"]: node["status"] for node in snapshot["nodes"]}
            self.assertIn("ReviewerAgent", labels)
            self.assertEqual(statuses["CoderAgent"], "done")
            self.assertEqual(statuses["ReviewerAgent"], "running")
            self.assertEqual(statuses["Done"], "idle")


if __name__ == "__main__":
    unittest.main()

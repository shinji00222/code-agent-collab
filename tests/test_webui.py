from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.agents.orchestrator import WorkerSpec
from code_agent_collab.blackboard import mark_agent_running
from code_agent_collab.progress import publish_progress
from code_agent_collab.webui import (
    PAGE,
    PROJECT_ROOT,
    SRC_DIR,
    _kill_process_tree,
    build_progress_snapshot,
    build_discussion_goal,
    build_command,
    clear_discussion,
    discuss_with_orchestrator,
    force_stop_active_work,
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

    def test_force_stop_without_active_work_is_safe(self) -> None:
        self.assertEqual(force_stop_active_work(), 0)


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
        self.assertIn("agentInspector", PAGE)
        self.assertIn("selectAgent(entry.agent_id)", PAGE)
        self.assertIn("findAgentEntry(node)", PAGE)
        self.assertIn("查看 ${entryDisplayLabel(entry)} 详情", PAGE)
        self.assertIn("点击进度树里的 Agent 查看职责、输出和阻塞", PAGE)
        self.assertIn('take("IntegratorAgent")', PAGE)
        self.assertIn("ReviewerAgent", PAGE)
        self.assertIn("Fix Loop", PAGE)
        self.assertIn("开始协同工作", PAGE)
        self.assertIn("生成主控方案", PAGE)
        self.assertIn("暂停工作", PAGE)
        self.assertIn("继续暂停任务", PAGE)
        self.assertIn("强制停止", PAGE)
        self.assertIn("/api/pause", PAGE)
        self.assertIn("/api/force-stop", PAGE)
        self.assertIn("pauseCurrentWork", PAGE)
        self.assertIn("resumePausedWork", PAGE)
        self.assertIn("forceStopCurrentWork", PAGE)
        self.assertIn('phrase !== "STOP"', PAGE)
        self.assertIn("/api/discuss", PAGE)
        self.assertIn("/api/discussion", PAGE)
        self.assertIn("createPlanFromDiscussion", PAGE)
        self.assertIn("discuss(goal)", PAGE)
        self.assertIn("beginCollaboration", PAGE)
        self.assertIn("run-adaptive ${quoteArg(goal)}", PAGE)
        self.assertIn("approve ${taskId}", PAGE)
        self.assertIn("latest_checkpoint", PAGE)
        self.assertIn("checkpoint ready", PAGE)
        self.assertIn("var(--purple)", PAGE)
        self.assertIn("branch-child", PAGE)
        self.assertIn("renderBranch", PAGE)
        self.assertIn("branch.continues::before", PAGE)
        self.assertIn("index < nodes.length - 1", PAGE)
        self.assertIn('placeholderNode("KnowledgeAgent", "KnowledgeAgent")', PAGE)
        self.assertIn("knowledge.children = coders", PAGE)
        self.assertNotIn("__agentWorkbench", PAGE)
        self.assertIn("/api/progress", PAGE)
        self.assertIn("setInterval(refreshProgress, 2500)", PAGE)
        self.assertNotIn("branch-wire", PAGE)
        self.assertNotIn("branch-grid", PAGE)
        self.assertNotIn("toggleLeftPanel", PAGE)
        self.assertNotIn("toggleOutput", PAGE)
        self.assertNotIn("toggleRightPanel", PAGE)


class DiscussionTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_discussion()

    def tearDown(self) -> None:
        clear_discussion()

    def test_discussion_asks_questions_before_plan(self) -> None:
        with patch.dict(os.environ, {"AGENT_WORKBENCH_PROVIDER": "mock"}, clear=False):
            result = discuss_with_orchestrator("做一个待办页面")

        self.assertIn("确认", result["output"])
        self.assertIn("做一个待办页面", result["goal"])
        self.assertEqual(build_discussion_goal(), "做一个待办页面")

    def test_discussion_goal_keeps_user_supplements(self) -> None:
        with patch.dict(os.environ, {"AGENT_WORKBENCH_PROVIDER": "mock"}, clear=False):
            discuss_with_orchestrator("做一个待办页面")
            discuss_with_orchestrator("保留终端页面，只改输入对话")

        goal = build_discussion_goal()

        self.assertIn("做一个待办页面", goal)
        self.assertIn("讨论补充", goal)
        self.assertIn("保留终端页面，只改输入对话", goal)

    def test_discussion_answers_user_questions(self) -> None:
        with patch.dict(os.environ, {"AGENT_WORKBENCH_PROVIDER": "mock"}, clear=False):
            result = discuss_with_orchestrator("你能回答我的问题吗？")

        self.assertIn("按问题本身回答", result["output"])
        self.assertIn("生成主控方案", result["output"])

    def test_discussion_answers_current_model_question(self) -> None:
        with patch.dict(os.environ, {"AGENT_WORKBENCH_PROVIDER": "mock"}, clear=False):
            result = discuss_with_orchestrator("你是什么模型")

        self.assertIn("mock Provider", result["output"])
        self.assertIn("mock-model", result["output"])
        self.assertIn("不联网", result["output"])

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

    def test_progress_snapshot_reads_owned_paths_plan_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans_dir = root / "logs" / "plans"
            context_dir = root / "logs" / "context-packs"
            plans_dir.mkdir(parents=True)
            context_dir.mkdir(parents=True)
            task_id = "20260913-120000-分工"
            (context_dir / f"{task_id}.md").write_text("# context", encoding="utf-8")
            (plans_dir / f"{task_id}.json").write_text(
                """{
  "task_id": "20260913-120000-分工",
  "goal": "分工隔离",
  "orchestrator_summary": "测试方案",
  "complexity": "complex",
  "label": "检索 + 实现/测试分工 + 评审（4 阶段）",
  "worker_count": 4,
  "stages": [[{"role": "KnowledgeAgent", "label": "", "owned_paths": []}], [{"role": "CoderAgent", "label": "实现", "owned_paths": ["src/"]}, {"role": "CoderAgent", "label": "测试", "owned_paths": ["tests/"]}], [{"role": "ReviewerAgent", "label": "", "owned_paths": []}]]
}
""",
                encoding="utf-8",
            )

            snapshot = build_progress_snapshot(root)

            branch_nodes = [node for node in snapshot["nodes"] if node["kind"] == "branch"]
            self.assertEqual(len(branch_nodes), 1)
            self.assertEqual(branch_nodes[0]["children"][0]["label"], "CoderAgent(实现)")
            self.assertIn("负责 src/", branch_nodes[0]["children"][0]["detail"])

    def test_progress_snapshot_exposes_blackboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_id = "20260914-120000-黑板"
            publish_progress(
                root,
                task_id=task_id,
                goal="黑板测试",
                status="running",
                detail="测试",
                nodes=[],
            )
            mark_agent_running(
                root,
                task_id=task_id,
                stage_index=1,
                spec=WorkerSpec("CoderAgent", "实现", ("src/",)),
            )

            snapshot = build_progress_snapshot(root)

            self.assertIsNotNone(snapshot["blackboard"])
            self.assertEqual(snapshot["blackboard"]["task_id"], task_id)
            self.assertEqual(snapshot["blackboard"]["agents"][0]["label"], "实现")
            self.assertEqual(snapshot["blackboard"]["agents"][0]["owned_paths"], ["src/"])

    def test_progress_snapshot_exposes_pause_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans_dir = root / "logs" / "plans"
            control_dir = root / "logs" / "control"
            plans_dir.mkdir(parents=True)
            control_dir.mkdir(parents=True)
            task_id = "20260905-101010-暂停任务"
            (plans_dir / f"{task_id}.json").write_text(
                """{
  "task_id": "20260905-101010-暂停任务",
  "goal": "暂停后继续执行",
  "orchestrator_summary": "测试方案",
  "complexity": "medium",
  "label": "检索 + 编码 + 评审",
  "worker_count": 3,
  "stages": [[["KnowledgeAgent", null]], [["CoderAgent", null]], [["ReviewerAgent", null]]]
}
""",
                encoding="utf-8",
            )
            (control_dir / f"{task_id}.checkpoint.json").write_text(
                """{
  "task_id": "20260905-101010-暂停任务",
  "next_stage_index": 1,
  "done_roles": ["ContextPack", "OrchestratorAgent", "ApprovalGate", "KnowledgeAgent"],
  "agent_results": [],
  "latest_coder_specs": [],
  "updated_at": "2026-09-05T10:10:30.000"
}
""",
                encoding="utf-8",
            )

            snapshot = build_progress_snapshot(root)

            self.assertEqual(snapshot["latest_checkpoint"]["task_id"], task_id)
            self.assertEqual(snapshot["latest_checkpoint"]["next_stage_index"], 1)
            self.assertTrue(snapshot["latest_checkpoint"]["matches_latest_plan"])
            self.assertEqual(snapshot["latest_plan"]["status"], "已暂停")

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

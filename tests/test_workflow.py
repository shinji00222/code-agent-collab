from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.providers import AIProvider
from code_agent_collab.workflow import run_workflow


class ShortThenGoodProvider(AIProvider):
    name = "test"

    def __init__(self) -> None:
        self.coder_calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        if "代码实现草稿" not in user_prompt:
            return "模拟 AI 已收到任务：" + user_prompt
        self.coder_calls += 1
        if self.coder_calls == 1:
            return "太短"
        return "重写后的有效代码草稿。" * 20


class AlwaysShortProvider(AIProvider):
    name = "test"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return "太短"


class WorkflowTests(unittest.TestCase):
    def test_run_workflow_publishes_reviewer_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "product-docs").mkdir()

            with patch("code_agent_collab.workflow.publish_progress") as publish:
                run_workflow(project_root, "测试 Reviewer 进度")

            published_nodes = [
                call.kwargs["nodes"]
                for call in publish.call_args_list
                if call.kwargs.get("status") == "running"
            ]
            reviewer_running = any(
                node.get("label") == "ReviewerAgent" and node.get("status") == "running"
                for nodes in published_nodes
                for node in nodes
                if node.get("kind") == "node"
            )
            final_nodes = publish.call_args_list[-1].kwargs["nodes"]

            self.assertTrue(reviewer_running)
            self.assertEqual(final_nodes[-1]["label"], "Done")
            self.assertEqual(final_nodes[-1]["status"], "done")

    def test_run_workflow_creates_agent_log_and_pending_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            docs_dir = project_root / "product-docs"
            docs_dir.mkdir()
            (docs_dir / "项目定义.md").write_text("# 项目定义\n\n多 Agent 测试", encoding="utf-8")

            result = run_workflow(project_root, "测试多Agent协作")

            self.assertEqual(len(result.agent_results), 7)
            self.assertEqual(result.agent_results[0].role, "CoordinatorAgent")
            self.assertIn("模拟 AI 已收到任务", result.agent_results[2].summary)
            self.assertIn("Provider：mock", result.agent_results[2].summary)
            self.assertEqual(result.agent_results[3].role, "CoderAgent")
            self.assertEqual(result.agent_results[4].role, "ReviewerAgent")
            self.assertIn("草稿评审结论", result.agent_results[4].summary)
            self.assertTrue(
                list((project_root / "dev-vault" / "projects").glob("*-coder-draft.md"))
            )
            self.assertEqual(result.agent_results[-1].role, "ReflectorAgent")
            self.assertTrue(result.context_pack.output_path.exists())
            self.assertTrue(result.workflow_log_path.exists())
            self.assertTrue(result.reflection.output_path.exists())
            log_content = result.workflow_log_path.read_text(encoding="utf-8")
            self.assertIn("多 Agent 工作流日志", log_content)
            self.assertIn("KnowledgeAgent", log_content)

    def test_reviewer_failure_triggers_one_coder_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "product-docs").mkdir()
            provider = ShortThenGoodProvider()

            with patch("code_agent_collab.workflow.create_provider", return_value=provider):
                result = run_workflow(project_root, "测试 Reviewer 打回重写")

            roles = [item.role for item in result.agent_results]
            self.assertEqual(roles.count("CoderAgent"), 2)
            self.assertEqual(roles.count("ReviewerAgent"), 2)
            self.assertIn("ValidatorAgent", roles)
            self.assertTrue(
                list((project_root / "dev-vault" / "projects").glob("*-coder-draft-revision1.md"))
            )

    def test_reviewer_stops_workflow_after_retry_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "product-docs").mkdir()

            with patch(
                "code_agent_collab.workflow.create_provider",
                return_value=AlwaysShortProvider(),
            ):
                result = run_workflow(project_root, "测试 Reviewer 失败停止")

            roles = [item.role for item in result.agent_results]
            self.assertEqual(roles.count("CoderAgent"), 2)
            self.assertEqual(roles.count("ReviewerAgent"), 2)
            self.assertNotIn("ValidatorAgent", roles)
            self.assertNotIn("ReflectorAgent", roles)


if __name__ == "__main__":
    unittest.main()

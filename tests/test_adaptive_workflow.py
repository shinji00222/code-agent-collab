from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.orchestration import (
    create_adaptive_plan,
    execute_adaptive_plan,
    run_adaptive_workflow,
)
from code_agent_collab.providers import AIProvider


class ShortThenGoodProvider(AIProvider):
    name = "test"

    def __init__(self) -> None:
        self.coder_calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        if "几个 worker" in user_prompt:
            return "COMPLEX"
        if "代码实现草稿" not in user_prompt:
            return "模拟 AI 已收到任务：" + user_prompt
        self.coder_calls += 1
        if self.coder_calls <= 2:
            return "太短"
        return "重写后的有效代码草稿。" * 20


def _make_project(tmp: str) -> Path:
    project_root = Path(tmp) / "project"
    project_root.mkdir()
    docs_dir = project_root / "product-docs"
    docs_dir.mkdir()
    (docs_dir / "项目定义.md").write_text("# 项目定义\n\n多 Agent 自适应测试", encoding="utf-8")
    return project_root


class ApprovalGateTests(unittest.TestCase):
    def test_create_plan_waits_for_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            result = create_adaptive_plan(root, "写个计算器")

            self.assertEqual(result.plan.worker_count, 1)
            self.assertTrue(result.plan_path.exists())
            # 计划阶段不执行任何 worker：不应产生代码草稿
            self.assertFalse(list((root / "dev-vault" / "projects").glob("*-coder-draft*.md")))

    def test_execute_approved_plan_runs_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            plan_result = create_adaptive_plan(root, "写个计算器")

            result = execute_adaptive_plan(root, plan_result.task_id)

            roles = [item.role for item in result.agent_results]
            self.assertEqual(roles[0], "OrchestratorAgent")
            self.assertIn("CoderAgent", roles)
            self.assertTrue(list((root / "dev-vault" / "projects").glob("*-coder-draft.md")))
            self.assertTrue(result.workflow_log_path.exists())
            self.assertTrue(result.reflection.output_path.exists())


class AdaptiveWorkflowTests(unittest.TestCase):
    def test_simple_task_uses_one_coder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            result = run_adaptive_workflow(root, "写个计算器")

            roles = [item.role for item in result.agent_results]
            self.assertEqual(roles[0], "OrchestratorAgent")
            self.assertIn("CoderAgent", roles)
            self.assertNotIn("KnowledgeAgent", roles)
            self.assertNotIn("ReviewerAgent", roles)
            self.assertEqual(result.plan.worker_count, 1)
            self.assertTrue(list((root / "dev-vault" / "projects").glob("*-coder-draft.md")))
            self.assertTrue(result.workflow_log_path.exists())
            self.assertTrue(result.reflection.output_path.exists())

    def test_medium_task_runs_knowledge_then_coder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            result = run_adaptive_workflow(
                root, "我需要一个非常详细的完整开发计划来指导整个项目的编码工作"
            )

            roles = [item.role for item in result.agent_results]
            self.assertEqual(result.plan.complexity.value, "medium")
            self.assertEqual(result.plan.worker_count, 2)
            self.assertEqual(roles[1], "KnowledgeAgent")
            self.assertEqual(roles[2], "CoderAgent")

    def test_complex_task_parallel_coders_and_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            result = run_adaptive_workflow(
                root, "用 python 和前端写一个带多个模块和接口的完整网站，拆成前后端"
            )

            roles = [item.role for item in result.agent_results]
            self.assertEqual(result.plan.complexity.value, "complex")
            self.assertEqual(result.plan.worker_count, 4)
            # Orchestrator + Knowledge + CoderA + CoderB + Reviewer
            self.assertEqual(len(result.agent_results), 5)
            self.assertEqual(roles.count("CoderAgent"), 2)
            self.assertIn("ReviewerAgent", roles)
            drafts = sorted(
                (root / "dev-vault" / "projects").glob(f"{result.task_id}-coder-draft-*.md")
            )
            self.assertEqual(len(drafts), 2)
            self.assertIn("评审", result.agent_results[-1].summary)

    def test_complex_task_rewrites_parallel_coders_once_when_review_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            provider = ShortThenGoodProvider()

            with patch("code_agent_collab.orchestration.create_provider", return_value=provider):
                result = run_adaptive_workflow(
                    root, "用 python 和前端写一个带多个模块和接口的完整网站，拆成前后端"
                )

            roles = [item.role for item in result.agent_results]
            self.assertEqual(roles.count("CoderAgent"), 4)
            self.assertEqual(roles.count("ReviewerAgent"), 2)
            self.assertEqual(result.agent_results[-1].role, "ReviewerAgent")
            self.assertIn("通过", result.agent_results[-1].summary)
            revision_drafts = sorted(
                (root / "dev-vault" / "projects").glob(f"{result.task_id}-coder-draft-*-revision1.md")
            )
            self.assertEqual(len(revision_drafts), 2)


if __name__ == "__main__":
    unittest.main()

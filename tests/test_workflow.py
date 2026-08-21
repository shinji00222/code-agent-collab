from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent_collab.workflow import run_workflow


class WorkflowTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

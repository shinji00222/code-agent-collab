from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent_collab.agents.base import AgentContext
from code_agent_collab.agents.integrator import IntegratorAgent
from code_agent_collab.file_utils import write_text
from code_agent_collab.providers import MockProvider

TASK_ID = "20260914-000000-integrator"


def _make_context(project_root: Path) -> AgentContext:
    return AgentContext(
        project_root=project_root,
        task_goal="合并测试",
        task_id=TASK_ID,
        context_pack_path=project_root / "logs" / "context-packs" / f"{TASK_ID}.md",
    )


class IntegratorAgentTests(unittest.TestCase):
    def test_integrator_writes_integrated_draft_from_latest_coder_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects_dir = root / "dev-vault" / "projects"
            write_text(projects_dir / f"{TASK_ID}-coder-draft-实现.md", "old impl")
            write_text(projects_dir / f"{TASK_ID}-coder-draft-实现-revision1.md", "new impl")
            write_text(projects_dir / f"{TASK_ID}-coder-draft-测试.md", "test draft")

            agent = IntegratorAgent(provider=MockProvider())
            result = agent.run(_make_context(root), [])

            output_path = projects_dir / f"{TASK_ID}-integrated-draft.md"
            content = output_path.read_text(encoding="utf-8")
            self.assertTrue(output_path.exists())
            self.assertIn("new impl", content)
            self.assertNotIn("old impl", content)
            self.assertIn("test draft", content)
            self.assertIn("合并草稿路径", result.evidence[1])


if __name__ == "__main__":
    unittest.main()

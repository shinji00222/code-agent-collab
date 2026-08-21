from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent_collab.agents import ReviewerAgent
from code_agent_collab.agents.base import AgentContext
from code_agent_collab.config import load_config
from code_agent_collab.file_utils import write_text

TASK_ID = "20260101-000000-test"


def _make_context(project_root: Path) -> AgentContext:
    return AgentContext(
        project_root=project_root,
        task_goal="测试任务",
        task_id=TASK_ID,
        context_pack_path=project_root / "logs" / "context-packs" / f"{TASK_ID}.md",
    )


def _write_draft(project_root: Path, content: str) -> Path:
    path = project_root / "dev-vault" / "projects" / f"{TASK_ID}-coder-draft.md"
    write_text(path, content)
    return path


def _normal_content() -> str:
    return "# 代码草稿\n\n" + "这是一段正常代码草稿内容。" * 20


class ReviewerAgentTests(unittest.TestCase):
    def test_missing_draft_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent = ReviewerAgent()
            result = agent.run(_make_context(Path(tmp)), [])
            self.assertEqual(agent.last_verdict, "需修改")
            self.assertEqual(result.summary, "草稿评审结论：需修改（评审 0 份草稿，1 个问题）")
            self.assertIn("未找到代码草稿", result.outputs[0])

    def test_short_draft_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_draft(root, "# 太短的草稿")
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("内容过短" in reason for reason in result.outputs))

    def test_normal_draft_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_draft(root, _normal_content())
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "通过")
            self.assertEqual(result.summary, "草稿评审结论：通过（评审 1 份草稿，0 个问题）")

    def test_reviewer_checks_latest_revision_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_draft(root, "# 太短的第一版")
            revision = root / "dev-vault" / "projects" / f"{TASK_ID}-coder-draft-revision1.md"
            write_text(revision, _normal_content())

            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "通过")
            self.assertIn(revision.name, result.evidence[0])

    def test_sensitive_draft_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = _normal_content() + "\nsk-abcdefghijklmnopqrstuvwxyz\n"
            _write_draft(root, content)
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("敏感信息" in reason for reason in result.outputs))

    def test_vault_path_reference_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = Path(load_config(root).main_vault_path)
            content = _normal_content() + f"\n写入目标：{vault}\n"
            _write_draft(root, content)
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("越权" in reason for reason in result.outputs))


if __name__ == "__main__":
    unittest.main()

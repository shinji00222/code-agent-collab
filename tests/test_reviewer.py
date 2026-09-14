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
    return """# 代码草稿

## AI 草稿

## 修改文件清单
- src/example.py（修改）
## 修改原因
补充一个可验证的示例实现。
## 建议代码
### src/example.py
def answer():
    return 42
## 测试方法
运行 python -m unittest discover -s tests，并检查相关页面输出。
## 风险
影响范围限制在示例文件。
"""


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

    def test_reviewer_prefers_integrated_draft_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_draft(root, "# 太短的 coder 草稿")
            integrated = root / "dev-vault" / "projects" / f"{TASK_ID}-integrated-draft.md"
            write_text(integrated, _normal_content())

            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "通过")
            self.assertIn(integrated.name, result.evidence[0])
            self.assertNotIn("coder-draft", result.evidence[0])

    def test_sensitive_draft_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = _normal_content() + "\nsk-abcdefghijklmnopqrstuvwxyz\n"
            _write_draft(root, content)
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("敏感信息" in reason for reason in result.outputs))

    def test_missing_required_sections_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_draft(root, "# 草稿\n\n## AI 草稿\n\n只有一段说明。" + "内容" * 60)

            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("结构不完整" in reason for reason in result.outputs))

    def test_out_of_scope_path_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = _normal_content().replace("### src/example.py", "### product-docs/plan.md")
            _write_draft(root, content)

            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("路径不合规" in reason for reason in result.outputs))

    def test_vague_test_method_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = _normal_content().replace(
                "运行 python -m unittest discover -s tests，并检查相关页面输出。",
                "看起来没问题。",
            )
            _write_draft(root, content)

            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("测试方法过于笼统" in reason for reason in result.outputs))

    def test_conflict_marker_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = _normal_content() + "\n<<<<<<< HEAD\n冲突\n=======\n另一版\n>>>>>>> branch\n"
            _write_draft(root, content)

            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("冲突标记" in reason for reason in result.outputs))

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

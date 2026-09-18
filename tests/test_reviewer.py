from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.agents import ReviewerAgent
from code_agent_collab.agents.base import AgentContext
from code_agent_collab.apply import FALLBACK_MARKER
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


def _write_draft(project_root: Path, content: str, name: str | None = None) -> Path:
    path = project_root / "dev-vault" / "projects" / (name or f"{TASK_ID}-coder-draft.md")
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

    def test_external_vault_path_reference_marks_needs_fix(self) -> None:
        """显式接入外部知识库时，草稿引用该外部知识库路径要判越权。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            external_vault = Path(tmp) / "external-vault"
            external_vault.mkdir()
            content = _normal_content() + f"\n写入目标：{external_vault}\n"
            _write_draft(root, content)
            with patch.dict(
                os.environ,
                {"AGENT_WORKBENCH_MAIN_VAULT": str(external_vault)},
                clear=False,
            ):
                agent = ReviewerAgent()
                result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("越权" in reason for reason in result.outputs))

    def test_project_local_vault_reference_is_not_flagged(self) -> None:
        """默认隔离下知识库就在项目内，引用它属于正常路径，不应误判越权。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            project_vault = Path(load_config(root).main_vault_path)
            self.assertIn(root, project_vault.parents)
            content = _normal_content() + f"\n写入目标：{project_vault}\n"
            _write_draft(root, content)
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "通过")
            self.assertFalse(any("越权" in reason for reason in result.outputs))


class ReviewerOwnershipTests(unittest.TestCase):
    """Coder 之间不通信，分工只能靠 owned_paths 契约；契约必须在产物侧强制。"""

    def test_draft_outside_owned_paths_marks_needs_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            # 「实现」worker 只负责 src/，却在草稿里写了 tests/ 下的文件
            _write_draft(
                root,
                _normal_content().replace("src/example.py", "tests/test_example.py"),
                name=f"{TASK_ID}-coder-draft-实现.md",
            )
            agent = ReviewerAgent(contracts={"实现": ("src/",), "测试": ("tests/",)})
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(any("越出负责路径" in reason for reason in result.outputs))

    def test_draft_within_owned_paths_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            _write_draft(
                root,
                _normal_content(),
                name=f"{TASK_ID}-coder-draft-实现.md",
            )
            agent = ReviewerAgent(contracts={"实现": ("src/",), "测试": ("tests/",)})
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "通过", result.outputs)
            self.assertFalse(any("越出负责路径" in reason for reason in result.outputs))

    def test_integrated_draft_checked_against_union(self) -> None:
        """合并草稿可以用任一 worker 的范围，但不能超出所有范围之和。"""
        merged = """# IntegratorAgent 合并草稿：测试任务

## AI 草稿

## 修改文件清单
- src/example.py（修改）
- tests/test_example.py（新增）
## 修改原因
合并两份 Coder 草稿。
## 建议代码
### src/example.py
def answer():
    return 42
### tests/test_example.py
import unittest
## 测试方法
运行 python -m unittest discover -s tests。
## 风险
无。
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            _write_draft(root, merged, name=f"{TASK_ID}-integrated-draft.md")
            agent = ReviewerAgent(contracts={"实现": ("src/",), "测试": ("tests/",)})
            result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "通过", result.outputs)

            # 只声明「实现」负责 src/ 时，合并草稿里的 tests/ 路径就超出并集
            agent2 = ReviewerAgent(contracts={"实现": ("src/",)})
            result2 = agent2.run(_make_context(root), [])
            self.assertEqual(agent2.last_verdict, "需修改")
            self.assertTrue(any("越出负责路径" in reason for reason in result2.outputs))

    def test_coder_drafts_checked_even_when_integrated_draft_exists(self) -> None:
        """合并草稿会遮蔽单份草稿，所以每份 Coder 草稿的契约要单独校验。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            # 合并草稿本身合法（只用 src/，落在两个 worker 范围之和内）
            _write_draft(root, _normal_content(), name=f"{TASK_ID}-integrated-draft.md")
            # 「实现」worker 却越界写了 tests/ 下的文件
            _write_draft(
                root,
                _normal_content().replace("src/example.py", "tests/test_example.py"),
                name=f"{TASK_ID}-coder-draft-实现.md",
            )
            agent = ReviewerAgent(contracts={"实现": ("src/",), "测试": ("tests/",)})
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(
                any(
                    "越出负责路径" in reason and "实现" in reason
                    for reason in result.outputs
                ),
                result.outputs,
            )

    def test_fallback_integrated_draft_marks_needs_fix(self) -> None:
        """Integrator 的兜底说明结构合法，但不是真正的合并结果，不能放行。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            content = _normal_content().replace(
                "补充一个可验证的示例实现。",
                "Provider 输出没有形成可解析的五小节草稿，IntegratorAgent 生成安全兜底合并说明。"
                f"（状态标记：{FALLBACK_MARKER}）",
            )
            _write_draft(root, content, name=f"{TASK_ID}-integrated-draft.md")
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(
                any("兜底合并说明" in reason for reason in result.outputs),
                result.outputs,
            )

    def test_no_contracts_skips_ownership_check(self) -> None:
        """单 Coder 档没有契约，不得因此误报越界。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            _write_draft(root, _normal_content())
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])
            self.assertEqual(agent.last_verdict, "通过", result.outputs)

    def test_duplicate_path_in_draft_marks_needs_fix(self) -> None:
        """同一路径出现两个版本必须判需修改，不能静默留最后一份。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            single = "### src/example.py\ndef answer():\n    return 42\n"
            doubled = single + "### src/example.py\ndef answer():\n    return 43\n"
            self.assertIn(single, _normal_content())
            _write_draft(root, _normal_content().replace(single, doubled))
            agent = ReviewerAgent()
            result = agent.run(_make_context(root), [])

            self.assertEqual(agent.last_verdict, "需修改")
            self.assertTrue(
                any("同一路径出现多个版本" in reason for reason in result.outputs),
                result.outputs,
            )


if __name__ == "__main__":
    unittest.main()

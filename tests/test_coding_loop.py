from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.coding_loop import run_coding_loop
from code_agent_collab.providers import AIProvider


class GoodSimpleProvider(AIProvider):
    name = "test-simple"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        if "几个 worker" in user_prompt:
            return "SIMPLE"
        if "代码实现草稿" in user_prompt:
            return _valid_test_draft()
        return "模拟 AI 已收到任务：" + user_prompt


class BadSimpleProvider(AIProvider):
    name = "test-bad"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        if "几个 worker" in user_prompt:
            return "SIMPLE"
        if "代码实现草稿" in user_prompt:
            return "太短"
        return "模拟 AI 已收到任务：" + user_prompt


def _valid_test_draft() -> str:
    return """## 修改文件清单
- tests/test_generated_loop.py（新增）
## 修改原因
补充一个 coding loop 可以验证的最小测试文件，证明草稿能够被解析、预览和应用。
## 建议代码
### tests/test_generated_loop.py
import unittest


class GeneratedLoopTests(unittest.TestCase):
    def test_generated_loop(self) -> None:
        self.assertEqual(1 + 1, 2)

## 测试方法
运行 python -m unittest discover -s tests。
## 风险
只新增一个自包含测试文件，不影响运行时代码。
"""


def _make_project(tmp: str) -> Path:
    root = Path(tmp) / "project"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / ".gitignore").write_text(
        "dev-vault/projects/*.md\n"
        "dev-vault/pending/*.md\n"
        "logs/\n"
        "__pycache__/\n",
        encoding="utf-8",
        newline="\n",
    )
    for args in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "test"],
        ["git", "config", "core.autocrlf", "false"],
    ):
        subprocess.run(args, cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True)
    return root


class CodingLoopTests(unittest.TestCase):
    def test_coding_loop_dry_run_stops_at_diff_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            with patch("code_agent_collab.orchestration.create_provider", return_value=GoodSimpleProvider()):
                result = run_coding_loop(root, "新增一个最小测试", apply=False)

            self.assertTrue(result.ok)
            self.assertIsNotNone(result.draft_path)
            self.assertIsNotNone(result.apply_result)
            self.assertEqual(result.apply_result.stage, "预览（dry-run）")
            self.assertFalse((root / "tests" / "test_generated_loop.py").exists())

    def test_coding_loop_apply_runs_tests_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            with patch("code_agent_collab.orchestration.create_provider", return_value=GoodSimpleProvider()):
                result = run_coding_loop(root, "新增一个最小测试", apply=True)

            self.assertTrue(result.ok)
            self.assertIsNotNone(result.apply_result)
            self.assertEqual(result.apply_result.stage, "应用并提交")
            self.assertTrue((root / "tests" / "test_generated_loop.py").exists())
            log = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout
            self.assertIn("apply-draft", log)

    def test_coding_loop_stops_before_apply_when_review_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            with patch("code_agent_collab.orchestration.create_provider", return_value=BadSimpleProvider()):
                result = run_coding_loop(root, "生成一个坏草稿", apply=True)

            self.assertFalse(result.ok)
            self.assertIsNone(result.draft_path)
            self.assertIsNone(result.apply_result)
            self.assertIn("ReviewerAgent", result.message)

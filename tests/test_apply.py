from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.apply import (
    DraftChange,
    apply_draft_workflow,
    find_draft_path,
    generate_diffs,
    parse_draft,
    run_tests,
    validate_changes,
)
from code_agent_collab.file_utils import write_text

PASS_TEST = """import unittest


class SampleTests(unittest.TestCase):
    def test_ok(self) -> None:
        self.assertTrue(True)
"""

FAIL_TEST = """import unittest


class SampleTests(unittest.TestCase):
    def test_bad(self) -> None:
        self.assertTrue(False)
"""


def _make_draft(files: dict[str, str]) -> str:
    lines = ["# CoderAgent 草稿：测试任务", "- 任务ID：t1", "", "## 修改文件清单"]
    for path in files:
        lines.append(f"- {path}（修改）")
    lines += ["", "## 修改原因", "测试原因。", "", "## 建议代码"]
    for path, content in files.items():
        lines += ["", f"### {path}", content]
    lines += ["", "## 测试方法", "运行单元测试。", "", "## 风险", "低风险。"]
    return "\n".join(lines)


def _make_project(tmp: str) -> Path:
    project_root = Path(tmp) / "project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "tests").mkdir(parents=True)
    return project_root


def _write_draft(project_root: Path, content: str, name: str = "20260101-000000-任务A-coder-draft.md") -> Path:
    path = project_root / "dev-vault" / "projects" / name
    write_text(path, content)
    return path


def _init_git(project_root: Path) -> None:
    # 模拟真实项目的 .gitignore：忽略运行产物，保证 git status 干净
    (project_root / ".gitignore").write_text(
        "dev-vault/pending/*.md\ndev-vault/projects/*.md\nlogs/\n__pycache__/\n",
        encoding="utf-8",
    )
    for args in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "test"],
        ["git", "config", "core.autocrlf", "false"],
    ):
        subprocess.run(args, cwd=project_root, check=True, capture_output=True)
    (project_root / "tests" / "test_sample.py").write_text(PASS_TEST, encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "-A"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=project_root, check=True, capture_output=True)


class ParseDraftTests(unittest.TestCase):
    def test_parse_normal_draft(self) -> None:
        draft = _make_draft({"tests/test_sample.py": PASS_TEST, "src/demo.py": "print('hi')\n"})
        result = parse_draft(draft)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.declared_paths, ["tests/test_sample.py", "src/demo.py"])
        self.assertEqual(len(result.changes), 2)
        self.assertEqual(result.changes[0].path, "tests/test_sample.py")
        self.assertIn("class SampleTests", result.changes[0].content)
        self.assertEqual(result.changes[1].path, "src/demo.py")
        self.assertEqual(result.reason, "测试原因。")
        self.assertEqual(result.test_method, "运行单元测试。")

    def test_parse_missing_sections_reports_errors(self) -> None:
        result = parse_draft("# 只有标题\n\n随便写点东西")
        self.assertTrue(result.errors)
        self.assertEqual(result.changes, [])

    def test_parse_rejects_file_list_and_code_path_mismatch(self) -> None:
        draft = "\n".join(
            [
                "# CoderAgent 草稿：测试任务",
                "",
                "## 修改文件清单",
                "- src/declared.py（修改）",
                "",
                "## 修改原因",
                "测试原因。",
                "",
                "## 建议代码",
                "### src/actual.py",
                "print('actual')",
                "",
                "## 测试方法",
                "运行 python -m unittest discover -s tests。",
                "",
                "## 风险",
                "低风险。",
            ]
        )

        result = parse_draft(draft)

        self.assertIn("修改文件清单列出但建议代码缺少：src/declared.py", result.errors)
        self.assertIn("建议代码包含未在修改文件清单声明的路径：src/actual.py", result.errors)


class ValidateTests(unittest.TestCase):
    def test_allowed_paths_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            errors = validate_changes(
                root,
                [DraftChange("src/demo.py", "x"), DraftChange("tests/test_a.py", "y")],
            )
            self.assertEqual(errors, [])

    def test_forbidden_paths_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            errors = validate_changes(
                root,
                [
                    DraftChange("../outside.py", "x"),
                    DraftChange(".agent-workbench/config.json", "x"),
                    DraftChange("dev-vault/pending/a.md", "x"),
                    DraftChange(str(Path(root).parent / "evil.py"), "x"),
                    DraftChange("src/data.db", "x"),
                ],
            )
            self.assertEqual(len(errors), 5)


class ApplyDraftTests(unittest.TestCase):
    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            (root / "tests" / "test_sample.py").write_text(PASS_TEST, encoding="utf-8")
            draft_path = _write_draft(root, _make_draft({"tests/test_sample.py": FAIL_TEST}))

            result = apply_draft_workflow(root, draft_path, apply=False)

            self.assertTrue(result.ok)
            self.assertIn("dry-run", result.stage)
            self.assertTrue(result.diffs)
            # 文件未被修改
            self.assertIn("test_ok", (root / "tests" / "test_sample.py").read_text(encoding="utf-8"))

    def test_apply_with_failing_isolated_tests_does_not_write_formal_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            (root / "tests" / "test_sample.py").write_text(PASS_TEST, encoding="utf-8")
            draft_path = _write_draft(root, _make_draft({"tests/test_sample.py": FAIL_TEST}))

            result = apply_draft_workflow(root, draft_path, apply=True)

            self.assertFalse(result.ok)
            self.assertEqual(result.stage, "隔离测试")
            # 隔离副本失败，正式文件从未被写入
            self.assertIn("test_ok", (root / "tests" / "test_sample.py").read_text(encoding="utf-8"))

    def test_apply_with_passing_tests_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            _init_git(root)
            draft_path = _write_draft(root, _make_draft({"tests/test_sample.py": FAIL_TEST}))

            # 先应用一次失败测试（会回滚，工作区保持干净）
            apply_draft_workflow(root, draft_path, apply=True)
            # 改成通过版再应用
            draft_path = _write_draft(
                root, _make_draft({"tests/test_sample.py": PASS_TEST}), name="20260101-000001-任务B-coder-draft.md"
            )
            result = apply_draft_workflow(root, draft_path, apply=True)

            self.assertTrue(result.ok)
            self.assertIn("提交", result.stage)
            log = subprocess.run(
                ["git", "log", "--oneline", "-1"],
                cwd=root, check=True, capture_output=True, text=True,
            ).stdout
            self.assertIn("apply-draft", log)

    def test_apply_rejects_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            _init_git(root)
            (root / "tests" / "extra.py").write_text("x = 1\n", encoding="utf-8")  # 未提交改动
            draft_path = _write_draft(root, _make_draft({"tests/test_sample.py": PASS_TEST}))

            result = apply_draft_workflow(root, draft_path, apply=True)

            self.assertFalse(result.ok)
            self.assertEqual(result.stage, "前置检查")

    def test_apply_rejects_draft_that_fails_review_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            content = PASS_TEST + "\n<<<<<<< HEAD\nsecret = 'sk-1234567890123456'\n>>>>>>> branch\n"
            draft_path = _write_draft(root, _make_draft({"tests/test_sample.py": content}))

            result = apply_draft_workflow(root, draft_path, apply=True)

            self.assertFalse(result.ok)
            self.assertEqual(result.stage, "评审闸门")
            self.assertIn("敏感信息", result.message)
            self.assertIn("冲突标记", result.message)

    def test_find_draft_path_by_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            draft_path = _write_draft(root, "# 草稿")
            found = find_draft_path(root, "任务A")
            self.assertEqual(found, draft_path)

    def test_find_draft_path_prefers_integrated_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            _write_draft(root, "# Coder 草稿", name="20260101-000000-任务C-coder-draft.md")
            integrated = _write_draft(root, "# 合并草稿", name="20260101-000000-任务C-integrated-draft.md")

            found = find_draft_path(root, "任务C")

            self.assertEqual(found, integrated)

    def test_generate_diffs_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            diffs = generate_diffs(root, [DraftChange("src/new.py", "print(1)\n")])
            self.assertEqual(len(diffs), 1)
            self.assertIn("src/new.py", diffs[0][0])

    def test_run_tests_strips_sensitive_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            write_text(
                root / "tests" / "test_env.py",
                """import os
import unittest


class EnvTests(unittest.TestCase):
    def test_secret_env_is_absent(self) -> None:
        self.assertNotIn("DEEPSEEK_API_KEY", os.environ)
        self.assertEqual(os.environ.get("AGENT_WORKBENCH_PROVIDER"), "mock")
""",
            )

            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key", "AGENT_WORKBENCH_PROVIDER": "deepseek"}):
                code, output = run_tests(root)

            self.assertEqual(code, 0, output)


if __name__ == "__main__":
    unittest.main()

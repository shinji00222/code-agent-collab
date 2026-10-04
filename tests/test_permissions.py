from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from code_agent_collab.agents import PermissionLevel
from code_agent_collab.permissions import (
    CONFIRM_REQUIRED,
    DRAFT_WRITE,
    LEVEL_ORDER,
    PROJECT_WRITE,
    READ_ONLY,
    PermissionDenied,
    WriteZone,
    allows,
    check_command,
    check_write,
    classify_path,
    ensure_inside_project,
    level_value,
    required_level_for_write,
)

ALL_LEVELS = (READ_ONLY, DRAFT_WRITE, PROJECT_WRITE, CONFIRM_REQUIRED)


class LevelTests(unittest.TestCase):
    def test_permission_level_enum_matches_permissions_module(self) -> None:
        """级别字符串只有一处定义；枚举必须和 permissions 模块保持一致。"""
        self.assertEqual(PermissionLevel.READ_ONLY.value, READ_ONLY)
        self.assertEqual(PermissionLevel.DRAFT_WRITE.value, DRAFT_WRITE)
        self.assertEqual(PermissionLevel.PROJECT_WRITE.value, PROJECT_WRITE)
        self.assertEqual(PermissionLevel.CONFIRM_REQUIRED.value, CONFIRM_REQUIRED)
        self.assertEqual(
            [level.value for level in PermissionLevel],
            list(LEVEL_ORDER),
        )

    def test_enum_and_string_are_interchangeable(self) -> None:
        self.assertEqual(level_value(PermissionLevel.DRAFT_WRITE), DRAFT_WRITE)
        self.assertEqual(level_value(DRAFT_WRITE), DRAFT_WRITE)
        self.assertTrue(allows(PermissionLevel.PROJECT_WRITE, DRAFT_WRITE))

    def test_unknown_level_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            level_value("L9_ADMIN")

    def test_allows_is_monotonic(self) -> None:
        self.assertFalse(allows(READ_ONLY, DRAFT_WRITE))
        self.assertTrue(allows(DRAFT_WRITE, DRAFT_WRITE))
        self.assertTrue(allows(CONFIRM_REQUIRED, READ_ONLY))


class ClassifyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_zones_inside_project(self) -> None:
        cases = {
            self.root / "logs" / "progress" / "current.json": WriteZone.RUNTIME,
            self.root / ".agent-workbench" / "config.json": WriteZone.RUNTIME,
            self.root / "dev-vault" / "pending" / "a.md": WriteZone.DRAFT,
            self.root / "dev-vault" / "project-vault" / "04-知识" / "a.md": WriteZone.DRAFT,
            self.root / "src" / "app.py": WriteZone.PROJECT_SOURCE,
            self.root / "tests" / "test_app.py": WriteZone.PROJECT_SOURCE,
            self.root / "README.md": WriteZone.PROJECT_SOURCE,
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(classify_path(path, self.root), expected)

    def test_paths_outside_project_are_outside(self) -> None:
        outside = [
            Path(self._tmp.name) / "sibling" / "x.md",
            Path(self._tmp.name) / "project-copy" / "src" / "app.py",
            Path(r"C:\Windows\System32\drivers\etc\hosts"),
        ]
        for path in outside:
            with self.subTest(path=path):
                self.assertEqual(classify_path(path, self.root), WriteZone.OUTSIDE)

    def test_project_root_itself_is_inside(self) -> None:
        self.assertEqual(classify_path(self.root, self.root), WriteZone.PROJECT_SOURCE)

    def test_missing_intermediate_dirs_are_still_inside(self) -> None:
        """叶子和中间目录都不存在时，仍必须判成项目内。

        回归用例：早先的实现直接对整条路径调 `resolve()`。在 Windows 上这种解析结果
        会随「中间目录此刻是否已创建」而变——并行 worker 刚建出草稿目录时，同一个
        路径会一时被判成「项目外」，造成整包测试偶发失败（已复现：报「不在项目内」，
        但同一时刻 `relative_to` 实际成功）。
        """
        target = self.root / "dev-vault" / "projects" / "还没建的目录" / "draft.md"
        self.assertFalse(target.parent.exists())
        self.assertEqual(classify_path(target, self.root), WriteZone.DRAFT)

        source = self.root / "src" / "还没建的包" / "app.py"
        self.assertFalse(source.parent.exists())
        self.assertEqual(classify_path(source, self.root), WriteZone.PROJECT_SOURCE)

    def test_parent_traversal_out_of_project_is_outside(self) -> None:
        """`..` 穿越必须被判成项目外（`abspath` 会折叠 `..`，`Path.absolute()` 不会）。"""
        self.assertEqual(
            classify_path(self.root / ".." / "outside" / "x.md", self.root),
            WriteZone.OUTSIDE,
        )

    def test_symlink_escaping_project_is_outside(self) -> None:
        """项目内的软链接指向项目外时，写入必须被拒绝。"""
        outside = Path(self._tmp.name) / "outside-dir"
        outside.mkdir()
        link = self.root / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            # Windows 上普通用户建不了符号链接，但目录联接（junction）不需要管理员权限
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
            )
            if created.returncode != 0:
                self.skipTest(
                    "当前环境既建不了软链接也建不了目录联接："
                    f"{created.stdout.strip()} {created.stderr.strip()}"
                )

        self.assertEqual(classify_path(link / "x.md", self.root), WriteZone.OUTSIDE)
        with self.assertRaises(PermissionDenied):
            check_write(PROJECT_WRITE, link / "x.md", self.root, action="经软链接写外部")


class CheckWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_read_only_can_write_runtime_ledgers(self) -> None:
        zone = check_write(
            READ_ONLY,
            self.root / "logs" / "progress" / "current.json",
            self.root,
            action="写进度账本",
        )
        self.assertEqual(zone, WriteZone.RUNTIME)

    def test_draft_level_can_write_drafts_but_not_source(self) -> None:
        check_write(
            DRAFT_WRITE,
            self.root / "dev-vault" / "projects" / "a.md",
            self.root,
            action="写草稿",
        )
        with self.assertRaises(PermissionDenied):
            check_write(
                DRAFT_WRITE,
                self.root / "src" / "app.py",
                self.root,
                action="改源码",
            )

    def test_project_write_can_write_source(self) -> None:
        zone = check_write(
            PROJECT_WRITE,
            self.root / "src" / "app.py",
            self.root,
            action="改源码",
        )
        self.assertEqual(zone, WriteZone.PROJECT_SOURCE)

    def test_outside_project_is_denied_for_every_level(self) -> None:
        """硬边界：项目之外的写入，任何权限级别都不能解锁。"""
        target = Path(self._tmp.name) / "outside-vault" / "note.md"
        for level in ALL_LEVELS:
            with self.subTest(level=level):
                with self.assertRaises(PermissionDenied) as ctx:
                    check_write(level, target, self.root, action="写外部知识库")
                self.assertIn("项目目录之外", str(ctx.exception))

    def test_outside_denial_is_a_permission_error(self) -> None:
        with self.assertRaises(PermissionError):
            check_write(
                CONFIRM_REQUIRED,
                Path(self._tmp.name) / "x.md",
                self.root,
                action="写外部",
            )

    def test_required_level_for_write(self) -> None:
        self.assertEqual(
            required_level_for_write(self.root / "logs" / "x.json", self.root),
            READ_ONLY,
        )
        self.assertEqual(
            required_level_for_write(self.root / "dev-vault" / "x.md", self.root),
            DRAFT_WRITE,
        )
        self.assertEqual(
            required_level_for_write(self.root / "src" / "x.py", self.root),
            PROJECT_WRITE,
        )
        self.assertIsNone(
            required_level_for_write(Path(self._tmp.name) / "out.md", self.root)
        )


class CheckCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_requires_project_write(self) -> None:
        with self.assertRaises(PermissionDenied):
            check_command(
                DRAFT_WRITE,
                ["git", "status"],
                action="跑 git",
                cwd=self.root,
                project_root=self.root,
            )
        check_command(
            PROJECT_WRITE,
            ["git", "status"],
            action="跑 git",
            cwd=self.root,
            project_root=self.root,
        )

    def test_cwd_must_stay_inside_project(self) -> None:
        outside = Path(self._tmp.name) / "other"
        outside.mkdir()
        with self.assertRaises(PermissionDenied) as ctx:
            check_command(
                PROJECT_WRITE,
                ["git", "status"],
                action="跑 git",
                cwd=outside,
                project_root=self.root,
            )
        self.assertIn("工作目录", str(ctx.exception))

    def test_cwd_is_optional(self) -> None:
        check_command(PROJECT_WRITE, ["git", "--version"], action="查询版本")


class EnsureInsideProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_inside_is_returned_resolved(self) -> None:
        resolved = ensure_inside_project(
            self.root / "src" / "app.py",
            self.root,
            action="暂存",
        )
        self.assertEqual(resolved, (self.root / "src" / "app.py").resolve())

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaises(PermissionDenied):
            ensure_inside_project(
                self.root / ".." / "outside.py",
                self.root,
                action="暂存",
            )


if __name__ == "__main__":
    unittest.main()

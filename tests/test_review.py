from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from code_agent_collab.providers import MockProvider
from code_agent_collab.review import (
    _body_without_metadata,
    confirm_pending_note,
    discard_pending_note,
    find_pending_path,
    review_pending_note,
    scan_sensitive,
)


def _make_project(tmp: str) -> tuple[Path, Path]:
    project_root = Path(tmp) / "project"
    project_root.mkdir()
    (project_root / "dev-vault" / "pending").mkdir(parents=True)
    vault = Path(tmp) / "vault"
    (vault / "04-知识" / "02-Codex知识" / "04-复盘").mkdir(parents=True)
    config_dir = project_root / ".agent-workbench"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        "{"
        f'"projectName":"demo",'
        f'"mainVaultPath":"{vault.as_posix()}",'
        f'"devVaultPath":"{(project_root / "dev-vault").as_posix()}"'
        "}",
        encoding="utf-8",
    )
    return project_root, vault


def _write_note(project_root: Path, name: str, body: str) -> Path:
    note = project_root / "dev-vault" / "pending" / name
    note.write_text(f"# 候选复利记录：{name}\n\n- 当前状态：待用户确认\n\n{body}", encoding="utf-8")
    return note


class SensitiveScanTests(unittest.TestCase):
    def test_detects_api_key(self) -> None:
        self.assertIn("API密钥", scan_sensitive("密钥是 sk-abcdefghijklmnop"))

    def test_detects_phone_and_email(self) -> None:
        found = scan_sensitive("联系 13812345678 或 a@b.com")
        self.assertIn("手机号", found)
        self.assertIn("邮箱", found)

    def test_metadata_paths_do_not_count_as_sensitive(self) -> None:
        content = (
            "- 来源上下文包：C:\\Users\\lwz12\\x.md\n"
            "- 建议写入位置：C:\\Users\\lwz12\\dev-vault\\pending"
        )
        self.assertEqual(scan_sensitive(_body_without_metadata(content)), [])


class ReviewFlowTests(unittest.TestCase):
    def test_mock_review_writes_to_main_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, vault = _make_project(tmp)
            note = _write_note(project_root, "2026-08-20-任务A-复利候选.md", "内容安全，值得记录。")

            result = review_pending_note(
                project_root,
                note,
                MockProvider(),
                now=datetime(2026, 8, 20, 15, 0, 0),
            )

            self.assertEqual(result.status, "已入库")
            self.assertIsNotNone(result.target_path)
            assert result.target_path is not None
            self.assertTrue(result.target_path.exists())
            self.assertTrue(result.target_path.is_relative_to(vault))
            self.assertIn("已入库", note.read_text(encoding="utf-8"))

    def test_sensitive_note_is_held_for_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, vault = _make_project(tmp)
            note = _write_note(
                project_root,
                "2026-08-20-任务B-复利候选.md",
                "这里写了密钥 sk-abcdefghijklmnop",
            )

            result = review_pending_note(
                project_root,
                note,
                MockProvider(),
                now=datetime(2026, 8, 20, 15, 0, 0),
            )

            self.assertEqual(result.status, "待人工处理")
            self.assertIn("敏感信息", result.reason)
            self.assertFalse(list(vault.rglob("*.md")))
            self.assertIn("待人工处理", note.read_text(encoding="utf-8"))

    def test_confirm_writes_and_discard_marks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, vault = _make_project(tmp)
            note = _write_note(project_root, "2026-08-20-任务C-复利候选.md", "内容安全。")

            confirmed = confirm_pending_note(
                project_root,
                note,
                now=datetime(2026, 8, 20, 15, 0, 0),
            )
            self.assertEqual(confirmed.status, "已确认入库")
            self.assertIsNotNone(confirmed.target_path)

            note2 = _write_note(project_root, "2026-08-20-任务D-复利候选.md", "内容安全。")
            discarded = discard_pending_note(note2, now=datetime(2026, 8, 20, 15, 0, 0))
            self.assertEqual(discarded.status, "已废弃")
            self.assertIn("已废弃", note2.read_text(encoding="utf-8"))

    def test_confirm_blocks_sensitive_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, vault = _make_project(tmp)
            note = _write_note(
                project_root,
                "2026-08-20-任务E-复利候选.md",
                "邮箱 a@b.com 在里面",
            )

            result = confirm_pending_note(
                project_root,
                note,
                now=datetime(2026, 8, 20, 15, 0, 0),
            )

            self.assertEqual(result.status, "待人工处理")
            self.assertFalse(list(vault.rglob("*.md")))

    def test_find_pending_path_by_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, _ = _make_project(tmp)
            note = _write_note(project_root, "2026-08-20-任务F-复利候选.md", "内容。")

            found = find_pending_path(project_root, "任务F")

            self.assertEqual(found, note)


if __name__ == "__main__":
    unittest.main()

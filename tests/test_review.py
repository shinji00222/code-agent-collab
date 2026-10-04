from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.providers import MockProvider
from code_agent_collab.review import (
    _body_without_metadata,
    confirm_pending_note,
    discard_pending_note,
    find_pending_path,
    review_pending_note,
    scan_sensitive,
)


def _make_project(
    tmp: str,
    *,
    write_vault: Path | None = None,
    include_write_key: bool = True,
) -> tuple[Path, Path, Path]:
    """返回 (项目根, 项目自有知识库, 项目外的真实知识库)。

    默认写入目标是**项目内**的项目自有知识库 `dev-vault/project-vault`；
    `real_vault` 刻意放在项目之外，只用来验证「项目之外的知识库零写入」。
    """
    project_root = Path(tmp) / "project"
    project_root.mkdir()
    (project_root / "dev-vault" / "pending").mkdir(parents=True)
    project_vault = project_root / "dev-vault" / "project-vault"
    (project_vault / "04-知识" / "02-Codex知识" / "04-复盘").mkdir(parents=True)
    real_vault = Path(tmp) / "vault"
    (real_vault / "04-知识" / "02-Codex知识" / "04-复盘").mkdir(parents=True)
    payload = {
        "projectName": "demo",
        "mainVaultPath": real_vault.as_posix(),
        "devVaultPath": (project_root / "dev-vault").as_posix(),
    }
    if include_write_key:
        # 默认让写入目标等于项目自有知识库（项目内）；
        # 「写到项目之外」的行为由下面的专门用例覆盖。
        payload["mainVaultWritePath"] = (write_vault or project_vault).as_posix()
    config_dir = project_root / ".agent-workbench"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    return project_root, project_vault, real_vault


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
            "- 来源上下文包：C:\\Users\\someone\\x.md\n"
            "- 建议写入位置：C:\\Users\\someone\\dev-vault\\pending"
        )
        self.assertEqual(scan_sensitive(_body_without_metadata(content)), [])


class ReviewFlowTests(unittest.TestCase):
    def test_mock_review_holds_for_human_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, project_vault, real_vault = _make_project(tmp)
            note = _write_note(project_root, "2026-08-20-任务A-复利候选.md", "内容安全，值得记录。")

            result = review_pending_note(
                project_root,
                note,
                MockProvider(),
                now=datetime(2026, 8, 20, 15, 0, 0),
            )

            self.assertEqual(result.status, "待人工确认")
            self.assertIsNone(result.target_path)
            self.assertFalse(list(real_vault.rglob("*.md")))
            self.assertFalse(list(project_vault.rglob("*.md")))
            note_content = note.read_text(encoding="utf-8")
            self.assertIn("待人工确认", note_content)
            self.assertIn("AI 审查通过", note_content)

    def test_sensitive_note_is_held_for_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, project_vault, real_vault = _make_project(tmp)
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
            self.assertFalse(list(real_vault.rglob("*.md")))
            self.assertIn("待人工处理", note.read_text(encoding="utf-8"))

    def test_confirm_writes_and_discard_marks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, project_vault, real_vault = _make_project(tmp)
            note = _write_note(project_root, "2026-08-20-任务C-复利候选.md", "内容安全。")

            confirmed = confirm_pending_note(
                project_root,
                note,
                now=datetime(2026, 8, 20, 15, 0, 0),
            )
            self.assertEqual(confirmed.status, "已确认入库")
            assert confirmed.target_path is not None
            self.assertTrue(confirmed.target_path.exists())
            # 写入必须落在项目自己的知识库里，项目外零写入
            self.assertIn(project_vault.resolve(), confirmed.target_path.resolve().parents)
            self.assertFalse(list(real_vault.rglob("*.md")))

            note2 = _write_note(project_root, "2026-08-20-任务D-复利候选.md", "内容安全。")
            discarded = discard_pending_note(note2, now=datetime(2026, 8, 20, 15, 0, 0))
            self.assertEqual(discarded.status, "已废弃")
            self.assertIn("已废弃", note2.read_text(encoding="utf-8"))

    def test_confirm_blocks_sensitive_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, project_vault, real_vault = _make_project(tmp)
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
            self.assertFalse(list(real_vault.rglob("*.md")))
            self.assertFalse(list(project_vault.rglob("*.md")))

    def test_confirm_refuses_to_overwrite_existing_vault_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, project_vault, real_vault = _make_project(tmp)
            note = _write_note(project_root, "2026-08-20-任务K-复利候选.md", "第一次内容。")
            first = confirm_pending_note(
                project_root,
                note,
                now=datetime(2026, 8, 20, 15, 0, 0),
            )
            self.assertEqual(first.status, "已确认入库")
            assert first.target_path is not None
            first_content = first.target_path.read_text(encoding="utf-8")

            duplicate = _write_note(project_root, note.name, "第二次内容，不能覆盖。")
            second = confirm_pending_note(
                project_root,
                duplicate,
                now=datetime(2026, 8, 20, 16, 0, 0),
            )

            self.assertEqual(second.status, "待人工处理")
            self.assertIn("拒绝覆盖", second.reason)
            self.assertEqual(first.target_path.read_text(encoding="utf-8"), first_content)
            self.assertNotIn("第二次内容", first.target_path.read_text(encoding="utf-8"))

    def test_find_pending_path_by_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, _, _ = _make_project(tmp)
            note = _write_note(project_root, "2026-08-20-任务F-复利候选.md", "内容。")

            found = find_pending_path(project_root, "任务F")

            self.assertEqual(found, note)

    def test_confirm_uses_ai_suggested_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, project_vault, real_vault = _make_project(tmp)
            (project_vault / "02-知识" / "01-测试").mkdir(parents=True)
            note = _write_note(project_root, "2026-08-20-任务G-复利候选.md", "内容安全。")
            content = note.read_text(encoding="utf-8")
            note.write_text(
                content.rstrip() + "\n- AI建议写入位置：02-知识/01-测试\n",
                encoding="utf-8",
            )

            result = confirm_pending_note(
                project_root,
                note,
                now=datetime(2026, 8, 20, 15, 0, 0),
            )

            self.assertEqual(result.status, "已确认入库")
            self.assertIsNotNone(result.target_path)
            assert result.target_path is not None
            self.assertEqual(result.target_path.parent, project_vault / "02-知识" / "01-测试")
            self.assertTrue(result.target_path.exists())


    def test_confirm_refuses_write_target_outside_project(self) -> None:
        """硬边界：写入目标落在项目之外时一律拒绝，不创建任何文件。

        这是 shin 明确的规则：项目要有自己独立的知识库，程序不写到项目之外。
        """
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside-vault"
            outside.mkdir()
            (outside / "04-知识" / "02-Codex知识" / "04-复盘").mkdir(parents=True)
            project_root, project_vault, real_vault = _make_project(tmp, write_vault=outside)
            note = _write_note(project_root, "2026-08-20-任务H-复利候选.md", "内容安全。")

            result = confirm_pending_note(
                project_root,
                note,
                now=datetime(2026, 8, 20, 15, 0, 0),
            )

            self.assertEqual(result.status, "待人工处理")
            self.assertIn("拒绝写入", result.reason)
            self.assertIsNone(result.target_path)
            # 项目外的库和项目外的真实库都没有被写
            self.assertFalse(list(outside.rglob("*.md")))
            self.assertFalse(list(real_vault.rglob("*.md")))
            self.assertFalse(list(project_vault.rglob("*.md")))
            self.assertIn("待人工处理", note.read_text(encoding="utf-8"))

    def test_confirm_defaults_to_project_vault_when_key_missing(self) -> None:
        """旧配置没有 mainVaultWritePath 时，默认写项目自有知识库，配置的读取库零写入。"""
        with tempfile.TemporaryDirectory() as tmp:
            project_root, project_vault, real_vault = _make_project(tmp, include_write_key=False)
            note = _write_note(project_root, "2026-08-20-任务I-复利候选.md", "内容安全。")

            result = confirm_pending_note(
                project_root,
                note,
                now=datetime(2026, 8, 20, 15, 0, 0),
            )

            self.assertEqual(result.status, "已确认入库")
            assert result.target_path is not None
            self.assertIn(project_vault.resolve(), result.target_path.resolve().parents)
            self.assertFalse(list(real_vault.rglob("*.md")))

    def test_env_redirect_outside_project_is_refused(self) -> None:
        """环境变量把写入重定向到项目之外时，同样被硬边界拒绝。"""
        with tempfile.TemporaryDirectory() as tmp:
            redirect = Path(tmp) / "redirect"
            redirect.mkdir()
            project_root, project_vault, real_vault = _make_project(tmp)
            note = _write_note(project_root, "2026-08-20-任务J-复利候选.md", "内容安全。")

            with patch.dict(
                os.environ,
                {"AGENT_WORKBENCH_MAIN_VAULT_WRITE": str(redirect)},
                clear=False,
            ):
                result = confirm_pending_note(
                    project_root,
                    note,
                    now=datetime(2026, 8, 20, 15, 0, 0),
                )

            self.assertEqual(result.status, "待人工处理")
            self.assertIn("拒绝写入", result.reason)
            self.assertIsNone(result.target_path)
            self.assertFalse(list(redirect.rglob("*.md")))
            self.assertFalse(list(project_vault.rglob("*.md")))
            self.assertFalse(list(real_vault.rglob("*.md")))


if __name__ == "__main__":
    unittest.main()

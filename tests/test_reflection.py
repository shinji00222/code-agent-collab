from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent_collab.reflection import create_reflection, find_context_pack, list_pending_notes


class ReflectionTests(unittest.TestCase):
    def test_find_context_pack_by_task_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            context_dir = project_root / "logs" / "context-packs"
            context_dir.mkdir(parents=True)
            expected = context_dir / "20260819-100000-测试任务.md"
            expected.write_text("# 任务上下文包：测试任务\n", encoding="utf-8")

            self.assertEqual(find_context_pack(project_root, "测试任务"), expected)

    def test_create_reflection_writes_pending_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            context_dir = project_root / "logs" / "context-packs"
            context_dir.mkdir(parents=True)
            source = context_dir / "20260819-100000-测试任务.md"
            source.write_text("# 任务上下文包：测试任务\n\n正文", encoding="utf-8")

            result = create_reflection(project_root, "测试任务")

            self.assertEqual(result.source_path, source)
            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.output_path.parent, project_root / "dev-vault" / "pending")
            content = result.output_path.read_text(encoding="utf-8")
            self.assertIn("候选复利记录", content)
            self.assertIn("主知识库写入状态：未写入", content)

    def test_list_pending_notes_reads_title_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            pending_dir = project_root / "dev-vault" / "pending"
            pending_dir.mkdir(parents=True)
            note_path = pending_dir / "2026-08-19-demo-复利候选.md"
            note_path.write_text(
                "# 候选复利记录：demo\n\n- 当前状态：待用户确认\n",
                encoding="utf-8",
            )

            notes = list_pending_notes(project_root)

            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0].title, "候选复利记录：demo")
            self.assertEqual(notes[0].status, "待用户确认")
            self.assertEqual(notes[0].path, note_path)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from code_agent_collab.context_pack import build_context_pack, create_context_pack


class ContextPackTests(unittest.TestCase):
    def test_build_context_pack_includes_goal_and_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            docs_dir = project_root / "product-docs"
            docs_dir.mkdir()
            (docs_dir / "项目定义.md").write_text("# 项目定义\n\n测试文档", encoding="utf-8")

            task_id, content = build_context_pack(
                project_root,
                "测试任务",
                now=datetime(2026, 8, 18, 22, 40, 0),
            )

            self.assertTrue(task_id.startswith("20260818-224000-"))
            self.assertIn("测试任务", content)
            self.assertIn("项目定义.md", content)
            self.assertIn("主知识库默认禁止自动写入", content)

    def test_create_context_pack_writes_to_logs_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "product-docs").mkdir()
            (project_root / "product-docs" / "MVP范围.md").write_text("MVP", encoding="utf-8")

            result = create_context_pack(project_root, "写一个上下文包")

            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.output_path.parent, project_root / "logs" / "context-packs")
            self.assertIn("写一个上下文包", result.output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

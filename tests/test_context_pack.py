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
            self.assertIn("上下文选择记录", content)
            self.assertIn("Token 预算估算", content)
            self.assertIn("[task] 用户原始请求", content)
            self.assertIn("[repo] Git 分支与状态", content)
            self.assertIn("相关代码文件", content)
            self.assertIn("代码文件摘录", content)
            # 上下文包要写清检索来源与写入目标，且默认都指向项目自有知识库
            self.assertIn("知识检索来源", content)
            self.assertIn("知识写入目标", content)
            self.assertIn(
                str(project_root / "dev-vault" / "project-vault"),
                content,
            )

    def test_task_id_includes_microseconds_to_avoid_same_second_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "product-docs").mkdir()

            first_id, _ = build_context_pack(
                project_root,
                "连续任务",
                now=datetime(2026, 10, 3, 12, 0, 0, 1),
            )
            second_id, _ = build_context_pack(
                project_root,
                "连续任务",
                now=datetime(2026, 10, 3, 12, 0, 0, 2),
            )

            self.assertTrue(first_id.startswith("20261003-120000-000001-"))
            self.assertTrue(second_id.startswith("20261003-120000-000002-"))
            self.assertNotEqual(first_id, second_id)

    def test_create_context_pack_writes_to_logs_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "product-docs").mkdir()
            (project_root / "product-docs" / "MVP范围.md").write_text("MVP", encoding="utf-8")

            result = create_context_pack(project_root, "写一个上下文包")

            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.output_path.parent, project_root / "logs" / "context-packs")
            self.assertIn("写一个上下文包", result.output_path.read_text(encoding="utf-8"))

    def test_context_pack_selects_relevant_project_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            docs_dir = project_root / "product-docs"
            docs_dir.mkdir()
            (docs_dir / "任务上下文包格式.md").write_text(
                "# 任务上下文包格式\n\n记录上下文选择、token 预算和知识库边界。",
                encoding="utf-8",
            )
            (docs_dir / "无关文档.md").write_text(
                "# 无关文档\n\n这里只描述桌面颜色和按钮位置。",
                encoding="utf-8",
            )

            _, content = build_context_pack(
                project_root,
                "实现 v0.17 上下文选择记录和 token 预算",
                now=datetime(2026, 9, 27, 10, 0, 0),
            )

            self.assertIn("product-docs/任务上下文包格式.md", content)
            self.assertIn("命中任务关键词", content)
            self.assertIn("### 任务上下文包格式.md", content)
            self.assertNotIn("### 无关文档.md", content)

    def test_context_pack_selects_relevant_code_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "product-docs").mkdir()
            src_dir = project_root / "src" / "code_agent_collab"
            tests_dir = project_root / "tests"
            src_dir.mkdir(parents=True)
            tests_dir.mkdir()
            (src_dir / "context_pack.py").write_text(
                "def build_context_pack(project_root, goal):\n"
                "    return 'context selection budget'\n",
                encoding="utf-8",
            )
            (tests_dir / "test_context_pack.py").write_text(
                "def test_context_pack_selects_code_files():\n"
                "    assert True\n",
                encoding="utf-8",
            )
            (src_dir / "unrelated.py").write_text(
                "def paint_button_color():\n"
                "    return 'purple'\n",
                encoding="utf-8",
            )

            _, content = build_context_pack(
                project_root,
                "修改 context_pack 并补测试",
                now=datetime(2026, 9, 27, 11, 0, 0),
            )

            self.assertIn("[code] src/code_agent_collab/context_pack.py", content)
            self.assertIn("[code] tests/test_context_pack.py", content)
            self.assertIn("### src/code_agent_collab/context_pack.py", content)
            self.assertIn("### tests/test_context_pack.py", content)
            self.assertIn("def build_context_pack", content)
            self.assertIn("代码文件选择上限", content)
            self.assertNotIn("### src/code_agent_collab/unrelated.py", content)


if __name__ == "__main__":
    unittest.main()

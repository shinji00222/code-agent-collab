from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent_collab.demo import run_demo


class DemoTests(unittest.TestCase):
    def test_run_demo_creates_context_pack_and_pending_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            docs_dir = project_root / "product-docs"
            docs_dir.mkdir()
            (docs_dir / "项目定义.md").write_text("# 项目定义\n\ndemo", encoding="utf-8")

            result = run_demo(project_root, "跑通闭环")

            self.assertTrue(result.context_pack.output_path.exists())
            self.assertTrue(result.reflection.output_path.exists())
            self.assertEqual(result.reflection.source_path, result.context_pack.output_path)
            self.assertEqual(len(result.pending_notes), 1)


if __name__ == "__main__":
    unittest.main()

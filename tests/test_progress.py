from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.progress import (
    latest_progress_path,
    publish_progress,
    read_progress,
    task_progress_path,
)


class ProgressStoreTests(unittest.TestCase):
    def test_publish_progress_writes_current_task_file_and_latest_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            publish_progress(
                root,
                task_id="task-a",
                goal="任务 A",
                status="running",
                detail="A running",
                nodes=[{"kind": "node", "label": "A", "status": "running", "detail": ""}],
            )
            publish_progress(
                root,
                task_id="task-b",
                goal="任务 B",
                status="done",
                detail="B done",
                nodes=[{"kind": "node", "label": "B", "status": "done", "detail": ""}],
            )

            self.assertEqual(read_progress(root)["task_id"], "task-b")
            self.assertEqual(read_progress(root, task_id="task-a")["task_id"], "task-a")
            self.assertEqual(read_progress(root, task_id="task-b")["task_id"], "task-b")

            latest = json.loads(latest_progress_path(root).read_text(encoding="utf-8"))
            self.assertEqual(latest["task_id"], "task-b")
            self.assertTrue(task_progress_path(root, "task-a").exists())
            self.assertTrue(task_progress_path(root, "task-b").exists())

    def test_configured_progress_file_keeps_single_file_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configured = root / "custom-progress.json"
            with patch.dict(os.environ, {"AGENT_WORKBENCH_PROGRESS_FILE": str(configured)}):
                publish_progress(
                    root,
                    task_id="task-a",
                    goal="任务 A",
                    status="running",
                    detail="A running",
                    nodes=[{"kind": "node", "label": "A", "status": "running", "detail": ""}],
                )

            self.assertTrue(configured.exists())
            self.assertFalse(task_progress_path(root, "task-a").exists())
            self.assertFalse(latest_progress_path(root).exists())


if __name__ == "__main__":
    unittest.main()

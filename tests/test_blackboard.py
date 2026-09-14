from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from code_agent_collab.agents import AgentResult, PermissionLevel
from code_agent_collab.agents.orchestrator import WorkerSpec
from code_agent_collab.blackboard import (
    blackboard_snapshot,
    load_blackboard,
    mark_agent_failed,
    mark_agent_planned,
    mark_agent_running,
    mark_agent_success,
)


class BlackboardTests(unittest.TestCase):
    def test_blackboard_tracks_agent_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = WorkerSpec("CoderAgent", "实现", ("src/",))
            result = AgentResult(
                role="CoderAgent",
                permission=PermissionLevel.DRAFT_WRITE,
                summary="实现草稿完成",
                evidence=[f"草稿路径：{root / 'dev-vault' / 'projects' / 'draft.md'}"],
                outputs=["生成代码草稿"],
                next_steps=["交给 ReviewerAgent"],
            )

            mark_agent_planned(root, task_id="task-1", stage_index=2, spec=spec)
            mark_agent_running(root, task_id="task-1", stage_index=2, spec=spec)
            mark_agent_success(root, task_id="task-1", stage_index=2, spec=spec, result=result)

            entries = load_blackboard(root, "task-1")
            entry = entries["stage2-CoderAgent-实现"]

            self.assertEqual(entry.status, "success")
            self.assertEqual(entry.owned_paths, ["src/"])
            self.assertIn("生成代码草稿", entry.outputs)
            self.assertEqual(entry.output_paths, [str(root / "dev-vault" / "projects" / "draft.md")])
            self.assertIn("开始执行。", entry.notes)

    def test_blackboard_keeps_parallel_agent_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = (
                WorkerSpec("CoderAgent", "实现", ("src/",)),
                WorkerSpec("CoderAgent", "测试", ("tests/",)),
            )

            def write(spec: WorkerSpec) -> None:
                mark_agent_running(root, task_id="task-1", stage_index=2, spec=spec)

            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(write, specs))

            snapshot = blackboard_snapshot(root, "task-1")
            assert snapshot is not None

            self.assertEqual(len(snapshot["agents"]), 2)
            labels = {item["label"] for item in snapshot["agents"]}
            self.assertEqual(labels, {"实现", "测试"})

    def test_failed_agent_records_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = WorkerSpec("CoderAgent", "实现", ("src/",))

            mark_agent_failed(
                root,
                task_id="task-1",
                stage_index=2,
                spec=spec,
                error="RuntimeError: 测试失败",
            )

            entry = load_blackboard(root, "task-1")["stage2-CoderAgent-实现"]

            self.assertEqual(entry.status, "failed")
            self.assertEqual(entry.blockers, ["RuntimeError: 测试失败"])
            self.assertEqual(entry.error, "RuntimeError: 测试失败")


if __name__ == "__main__":
    unittest.main()

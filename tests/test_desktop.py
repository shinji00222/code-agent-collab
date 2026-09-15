from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from code_agent_collab.desktop import (
    _provider_summary,
    cli_command,
    desktop_cli_args,
    extract_task_id,
    flatten_progress_nodes,
    load_recent_plans,
    progress_text,
    resolve_project_root,
)


class DesktopHelperTests(unittest.TestCase):
    def test_resolve_project_root_points_to_repository(self) -> None:
        root = resolve_project_root()
        self.assertTrue((root / "pyproject.toml").exists())
        self.assertTrue((root / "src" / "code_agent_collab").exists())

    def test_cli_command_uses_module_in_development(self) -> None:
        command = cli_command(["provider"])
        self.assertIn("-m", command)
        self.assertIn("code_agent_collab.cli", command)
        self.assertEqual(command[-1], "provider")

    def test_desktop_cli_args_adds_project_root_for_workflow_commands(self) -> None:
        root = resolve_project_root()
        args = desktop_cli_args(["run-adaptive", "整理项目"], root)
        self.assertEqual(args[:2], ["run-adaptive", "整理项目"])
        self.assertEqual(args[-2:], ["--project-root", str(root)])

    def test_desktop_cli_args_leaves_provider_unchanged(self) -> None:
        root = resolve_project_root()
        self.assertEqual(desktop_cli_args(["provider"], root), ["provider"])

    def test_extract_task_id_from_cli_output(self) -> None:
        output = "已完成主控方案\n任务ID：20260915-abc-测试\n计划文件：x"
        self.assertEqual(extract_task_id(output), "20260915-abc-测试")

    def test_provider_summary_hides_key_value(self) -> None:
        output = "\n".join(
            [
                "当前 Provider：deepseek",
                "模型：deepseek-chat",
                "密钥状态：已配置",
            ]
        )
        summary = _provider_summary(output)
        self.assertEqual(summary, "Provider：deepseek / deepseek-chat / 密钥已配置")
        self.assertNotIn("DEEPSEEK_API_KEY", summary)

    def test_load_recent_plans_reads_saved_plan_summaries(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans = root / "logs" / "plans"
            plans.mkdir(parents=True)
            (plans / "task-a.json").write_text(
                '{"task_id":"task-a","status":"pending","goal":"整理桌面入口","complexity":"simple","worker_count":2}',
                encoding="utf-8",
            )
            rows = load_recent_plans(root)
        self.assertEqual(rows[0]["task_id"], "task-a")
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["goal"], "整理桌面入口")

    def test_flatten_progress_nodes_includes_branch_children(self) -> None:
        nodes = [
            {"kind": "node", "label": "ContextPack", "status": "done", "detail": "ok"},
            {
                "kind": "branch",
                "children": [
                    {"kind": "node", "label": "CoderAgent", "status": "running", "detail": "src"},
                    {"kind": "node", "label": "ReviewerAgent", "status": "idle", "detail": ""},
                ],
            },
        ]
        lines = flatten_progress_nodes(nodes)
        self.assertIn("ContextPack: done - ok", lines)
        self.assertIn("  CoderAgent: running - src", lines)

    def test_progress_text_handles_missing_snapshot(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(progress_text(Path(tmp)), "暂无运行进度。")


if __name__ == "__main__":
    unittest.main()

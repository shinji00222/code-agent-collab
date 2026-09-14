from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.agents import AgentContext, AgentResult, PermissionLevel
from code_agent_collab.blackboard import load_blackboard
from code_agent_collab.control import (
    WorkflowPaused,
    clear_pause_request,
    load_checkpoint,
    request_pause,
)
from code_agent_collab.agents.orchestrator import WorkerSpec
from code_agent_collab.orchestration import (
    WorkerContractConflict,
    WorkerStageFailed,
    _plan_from_json,
    _plan_to_json,
    _run_workers,
    create_adaptive_plan,
    execute_adaptive_plan,
    list_adaptive_plans,
    run_adaptive_workflow,
)
from code_agent_collab.providers import AIProvider
from code_agent_collab.worker_runs import load_worker_runs


class ShortThenGoodProvider(AIProvider):
    name = "test"

    def __init__(self) -> None:
        self.coder_calls = 0
        self.integrator_calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        if "几个 worker" in user_prompt:
            return "COMPLEX"
        if "合并成一份统一草稿" in user_prompt:
            self.integrator_calls += 1
            if self.integrator_calls == 1:
                return "太短"
            return _valid_draft_text("src/integrated.py")
        if "代码实现草稿" not in user_prompt:
            return "模拟 AI 已收到任务：" + user_prompt
        self.coder_calls += 1
        if self.coder_calls <= 2:
            return "太短"
        return _valid_draft_text("src/example.py")


class StaticAgent:
    permission = PermissionLevel.DRAFT_WRITE

    def __init__(self, role: str, name: str) -> None:
        self.role = role
        self.name = name
        self.calls = 0

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        del previous_results
        self.calls += 1
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=f"{self.name} 完成",
            evidence=[f"草稿路径：{context.project_root / 'dev-vault' / 'projects' / (self.name + '.md')}"],
            outputs=[self.name],
        )


class FailingAgent(StaticAgent):
    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        del context, previous_results
        self.calls += 1
        raise RuntimeError(f"{self.name} 失败")


def _valid_draft_text(path: str) -> str:
    return f"""## 修改文件清单
- {path}（修改）
## 修改原因
补充一个可验证的示例实现。
## 建议代码
### {path}
def answer():
    return 42
## 测试方法
运行 python -m unittest discover -s tests。
## 风险
影响范围限制在示例文件。
"""


def _make_project(tmp: str) -> Path:
    project_root = Path(tmp) / "project"
    project_root.mkdir()
    docs_dir = project_root / "product-docs"
    docs_dir.mkdir()
    (docs_dir / "项目定义.md").write_text("# 项目定义\n\n多 Agent 自适应测试", encoding="utf-8")
    return project_root


class ApprovalGateTests(unittest.TestCase):
    def test_create_plan_publishes_orchestrator_then_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)

            with patch("code_agent_collab.orchestration.publish_progress") as publish:
                create_adaptive_plan(root, "写个计算器")

            first_nodes = publish.call_args_list[0].kwargs["nodes"]
            last_nodes = publish.call_args_list[-1].kwargs["nodes"]

            self.assertTrue(
                any(
                    node.get("label") == "Orchestrator"
                    and node.get("status") == "running"
                    for node in first_nodes
                )
            )
            self.assertTrue(
                any(
                    node.get("label") == "ApprovalGate"
                    and node.get("status") == "waiting"
                    for node in last_nodes
                )
            )

    def test_create_plan_waits_for_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            result = create_adaptive_plan(root, "写个计算器")

            self.assertEqual(result.plan.worker_count, 2)
            self.assertTrue(result.plan_path.exists())
            # 计划阶段不执行任何 worker：不应产生代码草稿
            self.assertFalse(list((root / "dev-vault" / "projects").glob("*-coder-draft*.md")))

    def test_execute_approved_plan_runs_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            plan_result = create_adaptive_plan(root, "写个计算器")

            result = execute_adaptive_plan(root, plan_result.task_id)

            roles = [item.role for item in result.agent_results]
            self.assertEqual(roles[0], "OrchestratorAgent")
            self.assertIn("CoderAgent", roles)
            self.assertIn("ReviewerAgent", roles)
            self.assertTrue(list((root / "dev-vault" / "projects").glob("*-coder-draft.md")))
            entries = load_blackboard(root, plan_result.task_id)
            self.assertEqual(entries["stage1-CoderAgent-default"].status, "success")
            self.assertIn("生成代码草稿", entries["stage1-CoderAgent-default"].outputs)
            self.assertEqual(entries["stage2-ReviewerAgent-default"].status, "success")
            self.assertTrue(result.workflow_log_path.exists())
            self.assertTrue(result.reflection.output_path.exists())

    def test_paused_adaptive_plan_resumes_from_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            plan_result = create_adaptive_plan(
                root,
                "我需要一个非常详细的完整开发计划来指导整个项目的编码工作",
            )
            original_run_workers = __import__(
                "code_agent_collab.orchestration",
                fromlist=["_run_workers"],
            )._run_workers
            call_count = 0

            def pause_after_first_stage(workers, context, results, specs, *, stage_index):
                nonlocal call_count
                stage_results = original_run_workers(
                    workers,
                    context,
                    results,
                    specs,
                    stage_index=stage_index,
                )
                call_count += 1
                if call_count == 1:
                    request_pause(root)
                return stage_results

            with patch("code_agent_collab.orchestration._run_workers", side_effect=pause_after_first_stage):
                with self.assertRaises(WorkflowPaused):
                    execute_adaptive_plan(root, plan_result.task_id)

            checkpoint = load_checkpoint(root, plan_result.task_id)
            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint["next_stage_index"], 1)
            self.assertIn("KnowledgeAgent", checkpoint["done_roles"])

            clear_pause_request(root)
            result = execute_adaptive_plan(root, plan_result.task_id)
            roles = [item.role for item in result.agent_results]

            self.assertEqual(roles.count("KnowledgeAgent"), 1)
            self.assertIn("CoderAgent", roles)
            self.assertIn("ReviewerAgent", roles)
            self.assertIsNone(load_checkpoint(root, plan_result.task_id))

    def test_list_adaptive_plans_shows_approval_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            plan_result = create_adaptive_plan(root, "写个计算器")

            plans = list_adaptive_plans(root)

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0].task_id, plan_result.task_id)
            self.assertEqual(plans[0].goal, "写个计算器")
            self.assertEqual(plans[0].status, "待批准")

            execute_adaptive_plan(root, plan_result.task_id)
            plans = list_adaptive_plans(root)

            self.assertEqual(plans[0].status, "已执行")


class AdaptiveWorkflowTests(unittest.TestCase):
    def test_simple_task_uses_one_coder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            result = run_adaptive_workflow(root, "写个计算器")

            roles = [item.role for item in result.agent_results]
            self.assertEqual(roles[0], "OrchestratorAgent")
            self.assertIn("CoderAgent", roles)
            self.assertNotIn("KnowledgeAgent", roles)
            self.assertIn("ReviewerAgent", roles)
            self.assertGreater(roles.index("ReviewerAgent"), roles.index("CoderAgent"))
            self.assertEqual(result.plan.worker_count, 2)
            self.assertTrue(list((root / "dev-vault" / "projects").glob("*-coder-draft.md")))
            self.assertTrue(result.workflow_log_path.exists())
            self.assertTrue(result.reflection.output_path.exists())

    def test_medium_task_runs_knowledge_then_coder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            result = run_adaptive_workflow(
                root, "我需要一个非常详细的完整开发计划来指导整个项目的编码工作"
            )

            roles = [item.role for item in result.agent_results]
            self.assertEqual(result.plan.complexity.value, "medium")
            self.assertEqual(result.plan.worker_count, 3)
            self.assertEqual(roles[1], "KnowledgeAgent")
            self.assertEqual(roles[2], "CoderAgent")
            self.assertEqual(roles[3], "ReviewerAgent")

    def test_complex_task_parallel_coders_integrator_and_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            result = run_adaptive_workflow(
                root, "用 python 和前端写一个带多个模块和接口的完整网站，拆成前后端"
            )

            roles = [item.role for item in result.agent_results]
            self.assertEqual(result.plan.complexity.value, "complex")
            self.assertEqual(result.plan.worker_count, 5)
            # Orchestrator + Knowledge + CoderA + CoderB + Integrator + Reviewer
            self.assertEqual(len(result.agent_results), 6)
            self.assertEqual(roles.count("CoderAgent"), 2)
            self.assertIn("IntegratorAgent", roles)
            self.assertIn("ReviewerAgent", roles)
            self.assertGreater(roles.index("ReviewerAgent"), roles.index("IntegratorAgent"))
            drafts = sorted(
                (root / "dev-vault" / "projects").glob(f"{result.task_id}-coder-draft-*.md")
            )
            self.assertEqual(len(drafts), 2)
            self.assertTrue((root / "dev-vault" / "projects" / f"{result.task_id}-integrated-draft.md").exists())
            self.assertIn("评审", result.agent_results[-1].summary)

    def test_complex_task_rewrites_parallel_coders_once_when_review_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            provider = ShortThenGoodProvider()

            with patch("code_agent_collab.orchestration.create_provider", return_value=provider):
                result = run_adaptive_workflow(
                    root, "用 python 和前端写一个带多个模块和接口的完整网站，拆成前后端"
                )

            roles = [item.role for item in result.agent_results]
            self.assertEqual(roles.count("CoderAgent"), 4)
            self.assertEqual(roles.count("IntegratorAgent"), 2)
            self.assertEqual(roles.count("ReviewerAgent"), 2)
            self.assertEqual(result.agent_results[-1].role, "ReviewerAgent")
            self.assertIn("通过", result.agent_results[-1].summary)
            revision_drafts = sorted(
                (root / "dev-vault" / "projects").glob(f"{result.task_id}-coder-draft-*-revision1.md")
            )
            self.assertEqual(len(revision_drafts), 2)


class WorkerRunLedgerTests(unittest.TestCase):
    def test_worker_run_ledger_skips_success_and_retries_failed_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            context_pack = root / "logs" / "context-packs" / "task-1.md"
            context_pack.parent.mkdir(parents=True)
            context_pack.write_text("context", encoding="utf-8")
            context = AgentContext(
                project_root=root,
                task_goal="并行测试",
                task_id="task-1",
                context_pack_path=context_pack,
            )
            specs = (WorkerSpec("CoderAgent", "模块A"), WorkerSpec("CoderAgent", "模块B"))
            worker_a = StaticAgent("CoderAgent", "模块A")
            worker_b = FailingAgent("CoderAgent", "模块B")

            with self.assertRaises(WorkerStageFailed) as raised:
                _run_workers([worker_a, worker_b], context, [], specs, stage_index=2)

            self.assertEqual(worker_a.calls, 1)
            self.assertEqual(worker_b.calls, 1)
            self.assertEqual(len(raised.exception.partial_results), 1)
            records = load_worker_runs(root, "task-1")
            self.assertEqual(records["stage2-CoderAgent-模块A"].status, "success")
            self.assertEqual(records["stage2-CoderAgent-模块B"].status, "failed")
            entries = load_blackboard(root, "task-1")
            self.assertEqual(entries["stage2-CoderAgent-模块A"].status, "success")
            self.assertEqual(entries["stage2-CoderAgent-模块B"].status, "failed")

            worker_a_retry = FailingAgent("CoderAgent", "模块A")
            worker_b_retry = StaticAgent("CoderAgent", "模块B")
            results = _run_workers(
                [worker_a_retry, worker_b_retry],
                context,
                raised.exception.partial_results,
                specs,
                stage_index=2,
            )

            self.assertEqual(worker_a_retry.calls, 0)
            self.assertEqual(worker_b_retry.calls, 1)
            self.assertEqual([result.summary for result in results], ["模块A 完成", "模块B 完成"])
            records = load_worker_runs(root, "task-1")
            self.assertEqual(records["stage2-CoderAgent-模块A"].status, "skipped")
            self.assertEqual(records["stage2-CoderAgent-模块B"].status, "success")
            entries = load_blackboard(root, "task-1")
            self.assertEqual(entries["stage2-CoderAgent-模块A"].status, "skipped")
            self.assertEqual(entries["stage2-CoderAgent-模块B"].status, "success")

    def test_parallel_workers_with_overlapping_owned_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_project(tmp)
            context_pack = root / "logs" / "context-packs" / "task-1.md"
            context_pack.parent.mkdir(parents=True)
            context_pack.write_text("context", encoding="utf-8")
            context = AgentContext(
                project_root=root,
                task_goal="冲突测试",
                task_id="task-1",
                context_pack_path=context_pack,
            )
            specs = (
                WorkerSpec("CoderAgent", "实现A", ("src/",)),
                WorkerSpec("CoderAgent", "实现B", ("src/code_agent_collab/",)),
            )

            with self.assertRaises(WorkerContractConflict):
                _run_workers(
                    [StaticAgent("CoderAgent", "实现A"), StaticAgent("CoderAgent", "实现B")],
                    context,
                    [],
                    specs,
                    stage_index=2,
                )

    def test_plan_json_preserves_owned_paths_and_reads_legacy_arrays(self) -> None:
        from code_agent_collab.agents import ComplexityLevel, OrchestrationPlan

        plan = OrchestrationPlan(
            complexity=ComplexityLevel.COMPLEX,
            label="测试",
            stages=((WorkerSpec("CoderAgent", "实现", ("src/",)),),),
        )

        payload = _plan_to_json(plan, "task-1", "目标", "summary")
        restored = _plan_from_json(payload)
        legacy = _plan_from_json(
            {
                "complexity": "complex",
                "label": "legacy",
                "stages": [[["CoderAgent", "A"]]],
            }
        )

        self.assertEqual(restored.stages[0][0].owned_paths, ("src/",))
        self.assertEqual(legacy.stages[0][0].label, "A")
        self.assertEqual(legacy.stages[0][0].owned_paths, ())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .agents import AgentContext, AgentResult, OrchestratorAgent, PermissionLevel
from .agents.coder import CoderAgent
from .agents.knowledge import KnowledgeAgent
from .agents.orchestrator import ComplexityLevel, OrchestrationPlan, WorkerSpec
from .agents.reviewer import ReviewerAgent
from .context_pack import ContextPackResult, create_context_pack
from .file_utils import ensure_dir, write_text
from .providers import AIProvider, create_provider
from .reflection import ReflectionResult, create_reflection

MAX_REVIEW_RETRIES = 1


@dataclass(frozen=True)
class AdaptivePlanResult:
    """主控产出的执行方案（等待人工审批）。"""

    task_id: str
    context_pack: ContextPackResult
    plan: OrchestrationPlan
    plan_path: Path
    orchestrator_result: AgentResult


@dataclass(frozen=True)
class AdaptiveWorkflowResult:
    task_id: str
    context_pack: ContextPackResult
    plan: OrchestrationPlan
    agent_results: list[AgentResult]
    reflection: ReflectionResult
    workflow_log_path: Path


def build_worker(spec: WorkerSpec, provider: AIProvider):
    """按 WorkerSpec 构建 worker 实例。"""
    if spec.role == "KnowledgeAgent":
        return KnowledgeAgent()
    if spec.role == "CoderAgent":
        return CoderAgent(provider=provider, worker_label=spec.label)
    if spec.role == "ReviewerAgent":
        return ReviewerAgent(provider=provider)
    raise ValueError(f"未知 worker 角色：{spec.role}")


def _reviewer_needs_revision(worker) -> bool:
    return getattr(worker, "last_verdict", "") == "需修改"


def _reviewer_feedback(worker, result: AgentResult) -> list[str]:
    reasons = getattr(worker, "last_reasons", [])
    return list(reasons) if reasons else list(result.outputs)


def _run_workers(workers: list, context: AgentContext, results: list[AgentResult]) -> list[AgentResult]:
    if len(workers) > 1:
        with ThreadPoolExecutor(max_workers=len(workers)) as pool:
            return list(pool.map(lambda worker: worker.run(context, results), workers))
    return [workers[0].run(context, results)]


def _rerun_coders(
    coder_specs: tuple[WorkerSpec, ...],
    provider: AIProvider,
    context: AgentContext,
    results: list[AgentResult],
    feedback: list[str],
    revision: int,
) -> list[AgentResult]:
    coders = [build_worker(spec, provider) for spec in coder_specs]
    if len(coders) > 1:
        with ThreadPoolExecutor(max_workers=len(coders)) as pool:
            return list(
                pool.map(
                    lambda worker: worker.run_with_feedback(
                        context,
                        results,
                        reviewer_feedback=feedback,
                        revision=revision,
                    ),
                    coders,
                )
            )
    return [
        coders[0].run_with_feedback(
            context,
            results,
            reviewer_feedback=feedback,
            revision=revision,
        )
    ]


def _plan_to_json(plan: OrchestrationPlan, task_id: str, goal: str, summary: str) -> dict:
    return {
        "task_id": task_id,
        "goal": goal,
        "orchestrator_summary": summary,
        "complexity": plan.complexity.value,
        "label": plan.label,
        "worker_count": plan.worker_count,
        "stages": [[[spec.role, spec.label] for spec in stage] for stage in plan.stages],
    }


def _plan_from_json(data: dict) -> OrchestrationPlan:
    stages = tuple(
        tuple(WorkerSpec(role=item[0], label=item[1]) for item in stage)
        for stage in data["stages"]
    )
    return OrchestrationPlan(
        complexity=ComplexityLevel(data["complexity"]),
        label=data["label"],
        stages=stages,
    )


def _plan_dir(project_root: Path) -> Path:
    return project_root / "logs" / "plans"


def find_plan_path(project_root: Path, task: str) -> Path:
    """按任务 ID 或关键词定位计划文件（logs/plans/<任务ID>.json）。"""
    plans_dir = _plan_dir(project_root)
    if not plans_dir.exists():
        raise FileNotFoundError(f"未找到计划目录：{plans_dir}")
    direct = plans_dir / f"{task}.json"
    if direct.exists():
        return direct
    matches = sorted(
        plans_dir.glob(f"*{task}*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(f"未找到匹配任务的计划文件：{task}")
    return matches[0]


def _render_plan(plan: OrchestrationPlan) -> str:
    lines = [
        f"- 复杂度：{plan.complexity.value}",
        f"- 模板：{plan.label}",
        f"- worker 数量：{plan.worker_count}",
    ]
    for index, stage in enumerate(plan.stages, start=1):
        names = "+".join(
            spec.role if not spec.label else f"{spec.role}({spec.label})" for spec in stage
        )
        lines.append(f"- 阶段{index}：{names}")
    return "\n".join(lines)


def _write_adaptive_log(
    project_root: Path,
    task_id: str,
    goal: str,
    plan: OrchestrationPlan,
    results: list[AgentResult],
) -> Path:
    output_path = project_root / "logs" / "workflows" / f"{task_id}-adaptive.md"
    ensure_dir(output_path.parent)
    sections = []
    for result in results:
        sections.append(
            f"## {result.role}\n\n"
            f"- 权限级别：{result.permission.value}\n"
            f"- 总结：{result.summary}"
        )
    content = "\n\n".join(
        [
            f"# 自适应多 Agent 工作流日志：{goal}",
            f"- 任务ID：{task_id}",
            f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
            "## 主控方案",
            _render_plan(plan),
            "## 执行结果",
            *sections,
        ]
    )
    write_text(output_path, content)
    return output_path


def create_adaptive_plan(project_root: Path, goal: str) -> AdaptivePlanResult:
    """第一阶段：生成上下文包 + 主控产出执行方案，写入 logs/plans，等待人工审批。"""
    context_pack = create_context_pack(project_root, goal)
    context = AgentContext(
        project_root=project_root,
        task_goal=goal,
        task_id=context_pack.task_id,
        context_pack_path=context_pack.output_path,
    )
    provider = create_provider()
    orchestrator = OrchestratorAgent(provider=provider)
    orchestrator_result = orchestrator.run(context, [])
    plan = orchestrator.last_plan
    if plan is None:
        raise RuntimeError("OrchestratorAgent 未产出执行方案")

    plan_path = _plan_dir(project_root) / f"{context_pack.task_id}.json"
    ensure_dir(plan_path.parent)
    write_text(
        plan_path,
        json.dumps(
            _plan_to_json(plan, context_pack.task_id, goal, orchestrator_result.summary),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    return AdaptivePlanResult(
        task_id=context_pack.task_id,
        context_pack=context_pack,
        plan=plan,
        plan_path=plan_path,
        orchestrator_result=orchestrator_result,
    )


def execute_adaptive_plan(project_root: Path, task: str) -> AdaptiveWorkflowResult:
    """第二阶段：人工审批通过后，按已保存的计划执行 workers（阶段内并行）。"""
    plan_path = find_plan_path(project_root, task)
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    plan = _plan_from_json(data)
    task_id = data["task_id"]
    goal = data["goal"]
    context_pack_path = project_root / "logs" / "context-packs" / f"{task_id}.md"
    if not context_pack_path.exists():
        raise FileNotFoundError(f"上下文包不存在：{context_pack_path}")

    context = AgentContext(
        project_root=project_root,
        task_goal=goal,
        task_id=task_id,
        context_pack_path=context_pack_path,
    )
    provider = create_provider()
    orchestrator_result = AgentResult(
        role="OrchestratorAgent",
        permission=PermissionLevel.READ_ONLY,
        summary=data.get("orchestrator_summary", "主控方案（已审批）"),
        evidence=["计划文件：" + str(plan_path)],
        outputs=[f"复杂度：{plan.complexity.value}", f"模板：{plan.label}"],
        risks=["计划已由人工审批通过；执行阶段内并行。"],
        next_steps=["执行已完成，等待复盘确认。"],
    )

    results: list[AgentResult] = [orchestrator_result]
    latest_coder_specs: tuple[WorkerSpec, ...] = ()
    for stage in plan.stages:
        workers = [build_worker(spec, provider) for spec in stage]
        stage_results = _run_workers(workers, context, results)
        results.extend(stage_results)
        coder_specs = tuple(spec for spec in stage if spec.role == "CoderAgent")
        if coder_specs:
            latest_coder_specs = coder_specs

        reviewer_pairs = [
            (worker, result)
            for worker, result in zip(workers, stage_results, strict=True)
            if getattr(worker, "role", "") == "ReviewerAgent"
        ]
        if not reviewer_pairs:
            continue

        reviewer, reviewer_result = reviewer_pairs[0]
        retry_count = 0
        while (
            latest_coder_specs
            and _reviewer_needs_revision(reviewer)
            and retry_count < MAX_REVIEW_RETRIES
        ):
            retry_count += 1
            rewrite_results = _rerun_coders(
                latest_coder_specs,
                provider,
                context,
                results,
                _reviewer_feedback(reviewer, reviewer_result),
                retry_count,
            )
            results.extend(rewrite_results)
            reviewer = build_worker(WorkerSpec("ReviewerAgent"), provider)
            reviewer_result = reviewer.run(context, results)
            results.append(reviewer_result)

        if _reviewer_needs_revision(reviewer):
            break

    workflow_log_path = _write_adaptive_log(project_root, task_id, goal, plan, results)
    reflection = create_reflection(project_root, task_id)
    return AdaptiveWorkflowResult(
        task_id=task_id,
        context_pack=ContextPackResult(task_id=task_id, output_path=context_pack_path),
        plan=plan,
        agent_results=results,
        reflection=reflection,
        workflow_log_path=workflow_log_path,
    )


def run_adaptive_workflow(project_root: Path, goal: str) -> AdaptiveWorkflowResult:
    """程序化便捷入口：出计划 + 立即执行（不经过人工审批）。

    注意：CLI 的 run-adaptive 使用两阶段流程（create_adaptive_plan → 人工 approve），
    本函数仅供测试与脚本使用，避免在真实使用路径上绕过人工审批闸门。
    """
    plan_result = create_adaptive_plan(project_root, goal)
    return execute_adaptive_plan(project_root, plan_result.task_id)

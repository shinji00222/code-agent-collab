from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .agents import AgentContext, AgentResult, OrchestratorAgent, PermissionLevel
from .agents.coder import CoderAgent
from .agents.integrator import IntegratorAgent
from .agents.knowledge import KnowledgeAgent
from .agents.orchestrator import ComplexityLevel, OrchestrationPlan, WorkerSpec
from .agents.reviewer import ReviewerAgent
from .blackboard import (
    mark_agent_failed,
    mark_agent_planned,
    mark_agent_running,
    mark_agent_skipped,
    mark_agent_success,
)
from .control import (
    WorkflowPaused,
    clear_checkpoint,
    is_pause_requested,
    load_checkpoint,
    save_checkpoint,
)
from .context_pack import ContextPackResult, create_context_pack
from .file_utils import ensure_dir, write_text
from .progress import publish_progress, role_stage, workflow_tree
from .providers import AIProvider, create_provider
from .reflection import ReflectionResult, create_reflection
from .worker_runs import (
    finish_worker_failed,
    finish_worker_success,
    input_hash_for,
    mark_worker_skipped,
    should_skip_worker,
    start_worker_run,
)

MAX_REVIEW_RETRIES = 1


class WorkerStageFailed(RuntimeError):
    def __init__(
        self,
        message: str,
        partial_results: list[AgentResult],
        failed_roles: set[str],
        succeeded_roles: set[str],
    ) -> None:
        super().__init__(message)
        self.partial_results = partial_results
        self.failed_roles = failed_roles
        self.succeeded_roles = succeeded_roles


class WorkerContractConflict(RuntimeError):
    """同一阶段 worker 的职责边界有重叠，不能安全并行。"""


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


@dataclass(frozen=True)
class AdaptivePlanSummary:
    """已保存的自适应方案摘要，用于人工审批前查看。"""

    task_id: str
    goal: str
    complexity: str
    label: str
    worker_count: int
    status: str
    plan_path: Path
    updated_at: datetime


def build_worker(
    spec: WorkerSpec,
    provider: AIProvider,
    *,
    coder_contracts: dict[str, tuple[str, ...]] | None = None,
):
    """按 WorkerSpec 构建 worker 实例。

    coder_contracts：并行 Coder 的「worker 标签 -> 负责路径」映射，交给
    ReviewerAgent 做产物级越界校验。只有需要校验草稿的 worker 会用到它。
    """
    if spec.role == "KnowledgeAgent":
        return KnowledgeAgent()
    if spec.role == "CoderAgent":
        return CoderAgent(provider=provider, worker_label=spec.label, owned_paths=spec.owned_paths)
    if spec.role == "IntegratorAgent":
        return IntegratorAgent(provider=provider)
    if spec.role == "ReviewerAgent":
        return ReviewerAgent(provider=provider, contracts=coder_contracts)
    raise ValueError(f"未知 worker 角色：{spec.role}")


def _reviewer_needs_revision(worker) -> bool:
    return getattr(worker, "last_verdict", "") == "需修改"


def _reviewer_feedback(worker, result: AgentResult) -> list[str]:
    reasons = getattr(worker, "last_reasons", [])
    return list(reasons) if reasons else list(result.outputs)


def _result_key(result: AgentResult) -> tuple[str, str, tuple[str, ...]]:
    return result.role, result.summary, tuple(result.evidence)


def _extend_unique_results(results: list[AgentResult], new_results: list[AgentResult]) -> None:
    seen = {_result_key(result) for result in results}
    for result in new_results:
        key = _result_key(result)
        if key in seen:
            continue
        results.append(result)
        seen.add(key)


def _run_single_worker(
    worker,
    spec: WorkerSpec,
    context: AgentContext,
    results: list[AgentResult],
    *,
    stage_index: int,
    revision: int = 0,
    feedback: list[str] | None = None,
) -> AgentResult:
    input_hash = input_hash_for(context.context_pack_path, context.task_goal, spec)
    if revision or feedback:
        digest = hashlib.sha256()
        digest.update(input_hash.encode("utf-8"))
        digest.update(f"\nrevision={revision}\n".encode("utf-8"))
        digest.update("\n".join(feedback or []).encode("utf-8"))
        input_hash = digest.hexdigest()
    cached = should_skip_worker(
        context.project_root,
        task_id=context.task_id,
        stage_index=stage_index,
        spec=spec,
        input_hash=input_hash,
    )
    if cached is not None:
        mark_worker_skipped(
            context.project_root,
            task_id=context.task_id,
            stage_index=stage_index,
            spec=spec,
            input_hash=input_hash,
            result=cached,
        )
        mark_agent_skipped(
            context.project_root,
            task_id=context.task_id,
            stage_index=stage_index,
            spec=spec,
            result=cached,
        )
        return cached

    mark_agent_running(
        context.project_root,
        task_id=context.task_id,
        stage_index=stage_index,
        spec=spec,
    )
    start_worker_run(
        context.project_root,
        task_id=context.task_id,
        stage_index=stage_index,
        spec=spec,
        input_hash=input_hash,
    )
    try:
        if feedback is not None and hasattr(worker, "run_with_feedback"):
            result = worker.run_with_feedback(
                context,
                results,
                reviewer_feedback=feedback,
                revision=revision,
            )
        else:
            result = worker.run(context, results)
    except Exception as exc:  # noqa: BLE001 - worker 失败要先落账，再交给主控处理
        error = f"{type(exc).__name__}: {exc}"
        finish_worker_failed(
            context.project_root,
            task_id=context.task_id,
            stage_index=stage_index,
            spec=spec,
            input_hash=input_hash,
            error=error,
        )
        mark_agent_failed(
            context.project_root,
            task_id=context.task_id,
            stage_index=stage_index,
            spec=spec,
            error=error,
        )
        raise
    finish_worker_success(
        context.project_root,
        task_id=context.task_id,
        stage_index=stage_index,
        spec=spec,
        input_hash=input_hash,
        result=result,
    )
    mark_agent_success(
        context.project_root,
        task_id=context.task_id,
        stage_index=stage_index,
        spec=spec,
        result=result,
    )
    return result


def _run_workers(
    workers: list,
    context: AgentContext,
    results: list[AgentResult],
    specs: tuple[WorkerSpec, ...],
    *,
    stage_index: int,
) -> list[AgentResult]:
    _ensure_stage_contracts_do_not_overlap(specs)
    ordered: list[AgentResult | None] = [None] * len(workers)
    failures: list[str] = []
    failed_roles: set[str] = set()
    succeeded_roles: set[str] = set()
    if len(workers) > 1:
        with ThreadPoolExecutor(max_workers=len(workers)) as pool:
            future_map = {
                pool.submit(
                    _run_single_worker,
                    worker,
                    spec,
                    context,
                    results,
                    stage_index=stage_index,
                ): (index, spec)
                for index, (worker, spec) in enumerate(zip(workers, specs, strict=True))
            }
            for future in as_completed(future_map):
                index, spec = future_map[future]
                try:
                    ordered[index] = future.result()
                    succeeded_roles.add(_stage_item(spec, stage_index)["role"])
                except Exception as exc:  # noqa: BLE001 - 汇总同阶段失败，保留已成功结果
                    failures.append(f"{spec.role}({spec.label or 'default'}): {exc}")
                    failed_roles.add(_stage_item(spec, stage_index)["role"])
    else:
        try:
            ordered[0] = _run_single_worker(
                workers[0],
                specs[0],
                context,
                results,
                stage_index=stage_index,
            )
            succeeded_roles.add(_stage_item(specs[0], stage_index)["role"])
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{specs[0].role}({specs[0].label or 'default'}): {exc}")
            failed_roles.add(_stage_item(specs[0], stage_index)["role"])

    partial_results = [item for item in ordered if item is not None]
    if failures:
        raise WorkerStageFailed("；".join(failures), partial_results, failed_roles, succeeded_roles)
    return partial_results


def _rerun_coders(
    coder_specs: tuple[WorkerSpec, ...],
    provider: AIProvider,
    context: AgentContext,
    results: list[AgentResult],
    feedback: list[str],
    revision: int,
    stage_index: int,
) -> list[AgentResult]:
    _ensure_stage_contracts_do_not_overlap(coder_specs)
    coders = [build_worker(spec, provider) for spec in coder_specs]
    ordered: list[AgentResult | None] = [None] * len(coders)
    failures: list[str] = []
    failed_roles: set[str] = set()
    succeeded_roles: set[str] = set()
    if len(coders) > 1:
        with ThreadPoolExecutor(max_workers=len(coders)) as pool:
            future_map = {
                pool.submit(
                    _run_single_worker,
                    worker,
                    spec,
                    context,
                    results,
                    stage_index=stage_index,
                    revision=revision,
                    feedback=feedback,
                ): (index, spec)
                for index, (worker, spec) in enumerate(zip(coders, coder_specs, strict=True))
            }
            for future in as_completed(future_map):
                index, spec = future_map[future]
                try:
                    ordered[index] = future.result()
                    succeeded_roles.add(_stage_item(spec, stage_index)["role"])
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{spec.role}({spec.label or 'default'}): {exc}")
                    failed_roles.add(_stage_item(spec, stage_index)["role"])
    else:
        try:
            ordered[0] = _run_single_worker(
                coders[0],
                coder_specs[0],
                context,
                results,
                stage_index=stage_index,
                revision=revision,
                feedback=feedback,
            )
            succeeded_roles.add(_stage_item(coder_specs[0], stage_index)["role"])
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{coder_specs[0].role}({coder_specs[0].label or 'default'}): {exc}")
            failed_roles.add(_stage_item(coder_specs[0], stage_index)["role"])
    partial_results = [item for item in ordered if item is not None]
    if failures:
        raise WorkerStageFailed("；".join(failures), partial_results, failed_roles, succeeded_roles)
    return partial_results


def _stage_item(spec: WorkerSpec, stage_index: int) -> dict:
    label = spec.role if not spec.label else f"{spec.role}({spec.label})"
    detail = f"阶段 {stage_index}"
    if spec.owned_paths:
        detail = f"{detail} · 负责 {', '.join(spec.owned_paths)}"
    return {"role": label, "label": label, "detail": detail}


def _ensure_stage_contracts_do_not_overlap(specs: tuple[WorkerSpec, ...]) -> None:
    owned_specs = [spec for spec in specs if spec.owned_paths]
    for index, left in enumerate(owned_specs):
        for right in owned_specs[index + 1 :]:
            overlap = _overlapping_paths(left.owned_paths, right.owned_paths)
            if overlap:
                raise WorkerContractConflict(
                    f"{_contract_name(left)} 与 {_contract_name(right)} 职责边界重叠：{', '.join(overlap)}"
                )


def _overlapping_paths(left_paths: tuple[str, ...], right_paths: tuple[str, ...]) -> list[str]:
    overlaps = []
    for left in left_paths:
        left_norm = _normalize_contract_path(left)
        for right in right_paths:
            right_norm = _normalize_contract_path(right)
            if left_norm == right_norm or left_norm.startswith(right_norm + "/") or right_norm.startswith(left_norm + "/"):
                overlaps.append(left if left_norm == right_norm or right_norm.startswith(left_norm + "/") else right)
    return sorted(set(overlaps))


def _normalize_contract_path(value: str) -> str:
    return value.replace("\\", "/").strip().strip("/").lower()


def _contract_name(spec: WorkerSpec) -> str:
    return spec.role if not spec.label else f"{spec.role}({spec.label})"


def _adaptive_stages(plan: OrchestrationPlan | None = None) -> list[list[dict]]:
    stages = [
        role_stage("ContextPack", "生成任务上下文包"),
        role_stage("OrchestratorAgent", "分配执行计划"),
        role_stage("ApprovalGate", "等待 approve"),
    ]
    if plan is None:
        stages.extend(
            [
                role_stage("CoderAgent", "生成代码草稿"),
                role_stage("ReviewerAgent", "审查 coder 草稿"),
                role_stage("FixLoop", "review 不通过时回到 coder 修改"),
                role_stage("PauseGate", "用户请求暂停"),
                role_stage("Done", "执行结束"),
            ]
        )
        return stages

    for stage_index, stage in enumerate(plan.stages, start=1):
        stages.append([_stage_item(spec, stage_index) for spec in stage])
    stages.extend(
        [
            role_stage("FixLoop", "review 不通过时回到 coder 修改"),
            role_stage("PauseGate", "用户请求暂停"),
            role_stage("ReflectorAgent", "沉淀候选复利记录"),
            role_stage("Done", "执行结束"),
        ]
    )
    return stages


def _pause_if_requested(
    project_root: Path,
    *,
    task_id: str,
    goal: str,
    plan: OrchestrationPlan,
    done: set[str],
    next_role: str,
) -> None:
    if not is_pause_requested(project_root):
        return
    _publish_adaptive(
        project_root,
        task_id=task_id,
        goal=goal,
        status="paused",
        detail=f"用户已请求暂停，停在 {next_role} 之前。",
        plan=plan,
        done=done,
        waiting={"PauseGate", next_role},
    )
    raise WorkflowPaused(f"用户已请求暂停，停在 {next_role} 之前。")


def _publish_adaptive(
    project_root: Path,
    *,
    task_id: str,
    goal: str,
    status: str,
    detail: str,
    plan: OrchestrationPlan | None,
    done: set[str],
    running: set[str] | None = None,
    waiting: set[str] | None = None,
    failed: set[str] | None = None,
) -> None:
    publish_progress(
        project_root,
        task_id=task_id,
        goal=goal,
        status=status,
        detail=detail,
        nodes=workflow_tree(
            _adaptive_stages(plan),
            done=done,
            running=running,
            waiting=waiting,
            failed=failed,
        ),
    )


def _plan_to_json(plan: OrchestrationPlan, task_id: str, goal: str, summary: str) -> dict:
    return {
        "task_id": task_id,
        "goal": goal,
        "orchestrator_summary": summary,
        "complexity": plan.complexity.value,
        "label": plan.label,
        "worker_count": plan.worker_count,
        "stages": [[_spec_to_json(spec) for spec in stage] for stage in plan.stages],
    }


def _plan_from_json(data: dict) -> OrchestrationPlan:
    stages = tuple(
        tuple(_spec_from_plan_item(item) for item in stage)
        for stage in data["stages"]
    )
    return OrchestrationPlan(
        complexity=ComplexityLevel(data["complexity"]),
        label=data["label"],
        stages=stages,
    )


def _specs_to_json(specs: tuple[WorkerSpec, ...]) -> list[dict]:
    return [_spec_to_json(spec) for spec in specs]


def _specs_from_json(items: list[dict]) -> tuple[WorkerSpec, ...]:
    return tuple(
        _spec_from_plan_item(item)
        for item in items
        if (isinstance(item, dict) and item.get("role")) or (isinstance(item, list) and item)
    )


def _spec_to_json(spec: WorkerSpec) -> dict:
    return {
        "role": spec.role,
        "label": spec.label,
        "owned_paths": list(spec.owned_paths),
    }


def _spec_from_plan_item(item) -> WorkerSpec:
    if isinstance(item, dict):
        return WorkerSpec(
            role=str(item.get("role", "")),
            label=str(item.get("label") or ""),
            owned_paths=tuple(str(path) for path in item.get("owned_paths", []) if path),
        )
    return WorkerSpec(
        role=str(item[0]),
        label=str(item[1] or "") if len(item) > 1 else "",
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


def list_adaptive_plans(project_root: Path) -> list[AdaptivePlanSummary]:
    """列出已保存的主控方案，最近修改的排在前面。"""
    plans_dir = _plan_dir(project_root)
    if not plans_dir.exists():
        return []

    summaries: list[AdaptivePlanSummary] = []
    for path in sorted(plans_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        task_id = data["task_id"]
        workflow_log = project_root / "logs" / "workflows" / f"{task_id}-adaptive.md"
        summaries.append(
            AdaptivePlanSummary(
                task_id=task_id,
                goal=data.get("goal", ""),
                complexity=data.get("complexity", ""),
                label=data.get("label", ""),
                worker_count=int(data.get("worker_count", 0)),
                status="已执行" if workflow_log.exists() else "待批准",
                plan_path=path,
                updated_at=datetime.fromtimestamp(path.stat().st_mtime),
            )
        )
    return summaries


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
        for spec in stage:
            if spec.owned_paths:
                lines.append(f"  - {spec.role}({spec.label}) 负责：{', '.join(spec.owned_paths)}")
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
    _publish_adaptive(
        project_root,
        task_id=context_pack.task_id,
        goal=goal,
        status="running",
        detail="ContextPack 已完成，Orchestrator 正在分配计划。",
        plan=None,
        done={"ContextPack"},
        running={"OrchestratorAgent"},
    )
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
    for stage_index, stage in enumerate(plan.stages, start=1):
        for spec in stage:
            mark_agent_planned(
                project_root,
                task_id=context_pack.task_id,
                stage_index=stage_index,
                spec=spec,
            )

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
    _publish_adaptive(
        project_root,
        task_id=context_pack.task_id,
        goal=goal,
        status="waiting",
        detail="主控方案已保存，等待 approve 后执行 workers。",
        plan=plan,
        done={"ContextPack", "OrchestratorAgent"},
        waiting={"ApprovalGate"},
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

    checkpoint = load_checkpoint(project_root, task_id)
    if checkpoint is not None:
        results = list(checkpoint.get("agent_results", []))
        if not results:
            results = [orchestrator_result]
        latest_coder_specs = _specs_from_json(checkpoint.get("latest_coder_specs", []))
        latest_integrator_specs = _specs_from_json(checkpoint.get("latest_integrator_specs", []))
        done_roles = set(checkpoint.get("done_roles", set()))
        start_stage_index = int(checkpoint.get("next_stage_index", 0))
        resume_detail = f"从暂停断点继续执行，下一阶段序号：{start_stage_index + 1}。"
    else:
        results = [orchestrator_result]
        latest_coder_specs = ()
        latest_integrator_specs = ()
        done_roles = {"ContextPack", "OrchestratorAgent", "ApprovalGate"}
        start_stage_index = 0
        resume_detail = "方案已批准，开始执行 workers。"

    _publish_adaptive(
        project_root,
        task_id=task_id,
        goal=goal,
        status="running",
        detail=resume_detail,
        plan=plan,
        done=done_roles,
    )
    for stage_index, stage in enumerate(plan.stages[start_stage_index:], start=start_stage_index):
        # 把已有 Coder 的负责路径交给 Reviewer，让它能校验草稿有没有越界。
        coder_contracts = {spec.label: spec.owned_paths for spec in latest_coder_specs}
        workers = [
            build_worker(spec, provider, coder_contracts=coder_contracts) for spec in stage
        ]
        running_roles = {_stage_item(spec, 0)["role"] for spec in stage}
        _pause_if_requested(
            project_root,
            task_id=task_id,
            goal=goal,
            plan=plan,
            done=done_roles,
            next_role=" + ".join(running_roles),
        )
        _publish_adaptive(
            project_root,
            task_id=task_id,
            goal=goal,
            status="running",
            detail="正在执行：" + " + ".join(running_roles),
            plan=plan,
            done=done_roles,
            running=running_roles,
        )
        coder_specs = tuple(spec for spec in stage if spec.role == "CoderAgent")
        if coder_specs:
            latest_coder_specs = coder_specs
        integrator_specs = tuple(spec for spec in stage if spec.role == "IntegratorAgent")
        if integrator_specs:
            latest_integrator_specs = integrator_specs
        try:
            stage_results = _run_workers(
                workers,
                context,
                results,
                stage,
                stage_index=stage_index + 1,
            )
        except WorkerStageFailed as exc:
            _extend_unique_results(results, exc.partial_results)
            done_roles.update(exc.succeeded_roles)
            save_checkpoint(
                project_root,
                task_id=task_id,
                next_stage_index=stage_index,
                done_roles=done_roles,
                agent_results=results,
                latest_coder_specs=_specs_to_json(latest_coder_specs),
                latest_integrator_specs=_specs_to_json(latest_integrator_specs),
            )
            _publish_adaptive(
                project_root,
                task_id=task_id,
                goal=goal,
                status="failed",
                detail=f"阶段 {stage_index + 1} 有 worker 失败，已保存断点：{exc}",
                plan=plan,
                done=done_roles,
                failed=exc.failed_roles,
            )
            raise RuntimeError(f"阶段 {stage_index + 1} 有 worker 失败：{exc}") from exc
        _extend_unique_results(results, stage_results)
        done_roles.update(running_roles)

        reviewer_pairs = [
            (worker, result)
            for worker, result in zip(workers, stage_results, strict=True)
            if getattr(worker, "role", "") == "ReviewerAgent"
        ]
        if not reviewer_pairs:
            save_checkpoint(
                project_root,
                task_id=task_id,
                next_stage_index=stage_index + 1,
                done_roles=done_roles,
                agent_results=results,
                latest_coder_specs=_specs_to_json(latest_coder_specs),
                latest_integrator_specs=_specs_to_json(latest_integrator_specs),
            )
            continue

        reviewer, reviewer_result = reviewer_pairs[0]
        retry_count = 0
        while (
            latest_coder_specs
            and _reviewer_needs_revision(reviewer)
            and retry_count < MAX_REVIEW_RETRIES
        ):
            retry_count += 1
            _pause_if_requested(
                project_root,
                task_id=task_id,
                goal=goal,
                plan=plan,
                done=done_roles,
                next_role="FixLoop",
            )
            _publish_adaptive(
                project_root,
                task_id=task_id,
                goal=goal,
                status="running",
                detail="ReviewerAgent 未通过，进入 Fix Loop。",
                plan=plan,
                done=done_roles,
                running={"FixLoop"},
            )
            try:
                rewrite_results = _rerun_coders(
                    latest_coder_specs,
                    provider,
                    context,
                    results,
                    _reviewer_feedback(reviewer, reviewer_result),
                    retry_count,
                    stage_index=stage_index + 1,
                )
            except WorkerStageFailed as exc:
                _extend_unique_results(results, exc.partial_results)
                done_roles.update(exc.succeeded_roles)
                save_checkpoint(
                    project_root,
                    task_id=task_id,
                    next_stage_index=stage_index,
                    done_roles=done_roles,
                    agent_results=results,
                    latest_coder_specs=_specs_to_json(latest_coder_specs),
                    latest_integrator_specs=_specs_to_json(latest_integrator_specs),
                )
                _publish_adaptive(
                    project_root,
                    task_id=task_id,
                    goal=goal,
                    status="failed",
                    detail=f"Fix Loop 有 worker 失败，已保存断点：{exc}",
                    plan=plan,
                    done=done_roles,
                    failed=exc.failed_roles,
                )
                raise RuntimeError(f"Fix Loop 有 worker 失败：{exc}") from exc
            _extend_unique_results(results, rewrite_results)
            done_roles.add("FixLoop")
            done_roles.update(_stage_item(spec, 0)["role"] for spec in latest_coder_specs)
            if latest_integrator_specs:
                _publish_adaptive(
                    project_root,
                    task_id=task_id,
                    goal=goal,
                    status="running",
                    detail="CoderAgent 已重写，IntegratorAgent 正在重新合并草稿。",
                    plan=plan,
                    done=done_roles,
                    running={"IntegratorAgent"},
                )
                integrator_results = [
                    _run_single_worker(
                        build_worker(spec, provider),
                        spec,
                        context,
                        results,
                        stage_index=stage_index + 1,
                        revision=retry_count,
                        feedback=_reviewer_feedback(reviewer, reviewer_result),
                    )
                    for spec in latest_integrator_specs
                ]
                _extend_unique_results(results, integrator_results)
                done_roles.update(_stage_item(spec, 0)["role"] for spec in latest_integrator_specs)
            reviewer = build_worker(
                WorkerSpec("ReviewerAgent"),
                provider,
                coder_contracts={spec.label: spec.owned_paths for spec in latest_coder_specs},
            )
            _pause_if_requested(
                project_root,
                task_id=task_id,
                goal=goal,
                plan=plan,
                done=done_roles,
                next_role="ReviewerAgent",
            )
            _publish_adaptive(
                project_root,
                task_id=task_id,
                goal=goal,
                status="running",
                detail="CoderAgent 已重写，ReviewerAgent 正在复审。",
                plan=plan,
                done=done_roles,
                running={"ReviewerAgent"},
            )
            reviewer_result = reviewer.run(context, results)
            results.append(reviewer_result)
            done_roles.add("ReviewerAgent")

        if _reviewer_needs_revision(reviewer):
            _publish_adaptive(
                project_root,
                task_id=task_id,
                goal=goal,
                status="failed",
                detail="ReviewerAgent 复审仍未通过，执行停止。",
                plan=plan,
                done=done_roles,
                failed={"ReviewerAgent"},
            )
            break

        save_checkpoint(
            project_root,
            task_id=task_id,
            next_stage_index=stage_index + 1,
            done_roles=done_roles,
            agent_results=results,
            latest_coder_specs=_specs_to_json(latest_coder_specs),
        )

    workflow_log_path = _write_adaptive_log(project_root, task_id, goal, plan, results)
    reflection = create_reflection(project_root, task_id)
    if not any(
        result.role == "ReviewerAgent" and "需修改" in result.summary
        for result in results[-1:]
    ):
        done_roles.update({"ReflectorAgent", "Done"})
        _publish_adaptive(
            project_root,
            task_id=task_id,
            goal=goal,
            status="done",
            detail="自适应工作流已完成。",
            plan=plan,
            done=done_roles,
        )
        clear_checkpoint(project_root, task_id)
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

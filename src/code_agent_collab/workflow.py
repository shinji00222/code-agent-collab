from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .agents import AgentContext, AgentResult, create_agent
from .context_pack import ContextPackResult, create_context_pack
from .file_utils import ensure_dir, write_text
from .progress import publish_progress, role_stage, workflow_tree
from .reflection import ReflectionResult, create_reflection
from .providers import AIProvider, create_provider

MAX_REVIEW_RETRIES = 1


def build_workflow_agents(provider: AIProvider) -> list:
    """构建默认流水线 Agent 列表（供 run_workflow 使用）。

    升级空间：接入 OrchestratorAgent 后，由主控按预设模板动态构建 workers，
    本函数保留作为"默认全流程"方案，不删除。
    """
    roles = [
        "CoordinatorAgent",
        "KnowledgeAgent",
        "PlannerAgent",
        "CoderAgent",
        "ReviewerAgent",
        "ValidatorAgent",
        "ReflectorAgent",
    ]
    return [create_agent(role, provider=provider) for role in roles]


def _reviewer_needs_revision(agent) -> bool:
    return getattr(agent, "last_verdict", "") == "需修改"


def _reviewer_feedback(agent, result: AgentResult) -> list[str]:
    reasons = getattr(agent, "last_reasons", [])
    return list(reasons) if reasons else list(result.outputs)


def _latest_coder(agents: list, reviewer_index: int):
    for agent in reversed(agents[:reviewer_index]):
        if hasattr(agent, "run_with_feedback"):
            return agent
    return None


def _default_progress_stages() -> list[list[dict]]:
    return [
        role_stage("ContextPack", "生成任务上下文包"),
        role_stage("CoordinatorAgent", "确定任务边界"),
        role_stage("KnowledgeAgent", "只读检索项目知识"),
        role_stage("PlannerAgent", "生成执行计划"),
        role_stage("CoderAgent", "生成代码草稿"),
        role_stage("ReviewerAgent", "审查 coder 草稿"),
        role_stage("FixLoop", "review 不通过时回到 coder 修改"),
        role_stage("ValidatorAgent", "验证结果"),
        role_stage("ReflectorAgent", "沉淀候选复利记录"),
        role_stage("Done", "工作流结束"),
    ]


def _publish(
    project_root: Path,
    *,
    task_id: str,
    goal: str,
    status: str,
    detail: str,
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
            _default_progress_stages(),
            done=done,
            running=running,
            waiting=waiting,
            failed=failed,
        ),
    )


@dataclass(frozen=True)
class WorkflowResult:
    task_id: str
    context_pack: ContextPackResult
    agent_results: list[AgentResult]
    reflection: ReflectionResult
    workflow_log_path: Path


def _render_agent_result(result: AgentResult) -> str:
    def lines(title: str, values: list[str]) -> str:
        body = "\n".join(f"- {value}" for value in values) if values else "- 无"
        return f"### {title}\n\n{body}"

    return "\n\n".join(
        [
            f"## {result.role}",
            f"- 权限级别：{result.permission.value}",
            f"- 总结：{result.summary}",
            lines("依据", result.evidence),
            lines("产出", result.outputs),
            lines("风险", result.risks),
            lines("下一步", result.next_steps),
        ]
    )


def _write_workflow_log(project_root: Path, task_id: str, goal: str, results: list[AgentResult]) -> Path:
    output_path = project_root / "logs" / "workflows" / f"{task_id}.md"
    ensure_dir(output_path.parent)
    content = "\n\n".join(
        [
            f"# 多 Agent 工作流日志：{goal}",
            f"- 任务ID：{task_id}",
            f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
            "## 执行顺序",
            "\n".join(f"{index}. {result.role}" for index, result in enumerate(results, start=1)),
            *[_render_agent_result(result) for result in results],
        ]
    )
    write_text(output_path, content)
    return output_path


def run_workflow(project_root: Path, goal: str) -> WorkflowResult:
    context_pack = create_context_pack(project_root, goal)
    done_roles = {"ContextPack"}
    context = AgentContext(
        project_root=project_root,
        task_goal=goal,
        task_id=context_pack.task_id,
        context_pack_path=context_pack.output_path,
    )
    _publish(
        project_root,
        task_id=context_pack.task_id,
        goal=goal,
        status="running",
        detail="ContextPack 已完成，准备进入 Coordinator。",
        done=done_roles,
        running={"CoordinatorAgent"},
    )
    provider = create_provider()
    agents = build_workflow_agents(provider)

    results: list[AgentResult] = []
    stopped_by_review = False
    for index, agent in enumerate(agents):
        role = getattr(agent, "role", "")
        _publish(
            project_root,
            task_id=context_pack.task_id,
            goal=goal,
            status="running",
            detail=f"{role} 正在工作。",
            done=done_roles,
            running={role},
        )
        result = agent.run(context, results)
        results.append(result)
        done_roles.add(role)
        if getattr(agent, "role", "") != "ReviewerAgent" or not _reviewer_needs_revision(agent):
            continue

        coder = _latest_coder(agents, index)
        retry_count = 0
        while coder is not None and _reviewer_needs_revision(agent) and retry_count < MAX_REVIEW_RETRIES:
            retry_count += 1
            _publish(
                project_root,
                task_id=context_pack.task_id,
                goal=goal,
                status="running",
                detail="ReviewerAgent 未通过，进入 Fix Loop。",
                done=done_roles,
                running={"FixLoop"},
            )
            rewrite = coder.run_with_feedback(
                context,
                results,
                reviewer_feedback=_reviewer_feedback(agent, result),
                revision=retry_count,
            )
            results.append(rewrite)
            _publish(
                project_root,
                task_id=context_pack.task_id,
                goal=goal,
                status="running",
                detail="CoderAgent 已按 reviewer 反馈重写，进入复审。",
                done=done_roles | {"CoderAgent", "FixLoop"},
                running={"ReviewerAgent"},
            )
            result = agent.run(context, results)
            results.append(result)
            done_roles.update({"CoderAgent", "ReviewerAgent", "FixLoop"})

        if _reviewer_needs_revision(agent):
            stopped_by_review = True
            _publish(
                project_root,
                task_id=context_pack.task_id,
                goal=goal,
                status="failed",
                detail="ReviewerAgent 复审仍未通过，工作流停止。",
                done=done_roles,
                failed={"ReviewerAgent"},
            )
            break

    workflow_log_path = _write_workflow_log(project_root, context_pack.task_id, goal, results)
    reflection = create_reflection(project_root, context_pack.task_id)
    if not stopped_by_review:
        done_roles.update(item.role for item in results)
        done_roles.update({"ReflectorAgent", "Done"})
        _publish(
            project_root,
            task_id=context_pack.task_id,
            goal=goal,
            status="done",
            detail="工作流已完成。",
            done=done_roles,
        )
    return WorkflowResult(
        task_id=context_pack.task_id,
        context_pack=context_pack,
        agent_results=results,
        reflection=reflection,
        workflow_log_path=workflow_log_path,
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .agents import AgentContext, AgentResult, create_agent
from .context_pack import ContextPackResult, create_context_pack
from .file_utils import ensure_dir, write_text
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
    context = AgentContext(
        project_root=project_root,
        task_goal=goal,
        task_id=context_pack.task_id,
        context_pack_path=context_pack.output_path,
    )
    provider = create_provider()
    agents = build_workflow_agents(provider)

    results: list[AgentResult] = []
    for index, agent in enumerate(agents):
        result = agent.run(context, results)
        results.append(result)
        if getattr(agent, "role", "") != "ReviewerAgent" or not _reviewer_needs_revision(agent):
            continue

        coder = _latest_coder(agents, index)
        retry_count = 0
        while coder is not None and _reviewer_needs_revision(agent) and retry_count < MAX_REVIEW_RETRIES:
            retry_count += 1
            rewrite = coder.run_with_feedback(
                context,
                results,
                reviewer_feedback=_reviewer_feedback(agent, result),
                revision=retry_count,
            )
            results.append(rewrite)
            result = agent.run(context, results)
            results.append(result)

        if _reviewer_needs_revision(agent):
            break

    workflow_log_path = _write_workflow_log(project_root, context_pack.task_id, goal, results)
    reflection = create_reflection(project_root, context_pack.task_id)
    return WorkflowResult(
        task_id=context_pack.task_id,
        context_pack=context_pack,
        agent_results=results,
        reflection=reflection,
        workflow_log_path=workflow_log_path,
    )

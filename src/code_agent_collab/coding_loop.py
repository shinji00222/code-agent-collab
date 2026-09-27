from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .apply import ApplyResult, apply_draft_workflow, find_draft_path
from .orchestration import AdaptiveWorkflowResult, run_adaptive_workflow

MAX_APPLY_RETRIES = 1
RETRYABLE_APPLY_STAGES = {"隔离测试", "正式测试"}


@dataclass(frozen=True)
class CodingLoopAttempt:
    workflow: AdaptiveWorkflowResult
    draft_path: Path | None
    apply_result: ApplyResult | None
    message: str


@dataclass(frozen=True)
class CodingLoopResult:
    workflow: AdaptiveWorkflowResult
    draft_path: Path | None
    apply_result: ApplyResult | None
    ok: bool
    message: str
    attempts: list[CodingLoopAttempt]


def run_coding_loop(project_root: Path, goal: str, apply: bool = False) -> CodingLoopResult:
    """Run the minimal coding loop: plan -> workers -> review -> diff/apply.

    The default is still safe: it stops at a diff preview. Passing apply=True reuses the
    existing apply-draft safeguards: clean git check, isolated tests, formal tests, and
    local commit.
    """
    attempts: list[CodingLoopAttempt] = []
    next_goal = goal
    for attempt_index in range(MAX_APPLY_RETRIES + 1):
        workflow = run_adaptive_workflow(project_root, next_goal)
        if not _latest_reviewer_passed(workflow):
            message = "ReviewerAgent 未通过或没有产生通过结论，已停止在应用前。"
            attempts.append(CodingLoopAttempt(workflow, None, None, message))
            return CodingLoopResult(
                workflow=workflow,
                draft_path=None,
                apply_result=None,
                ok=False,
                message=message,
                attempts=attempts,
            )

        draft_path = find_draft_path(project_root, workflow.task_id)
        apply_result = apply_draft_workflow(
            project_root,
            draft_path,
            apply=apply,
            require_approval=False,
        )
        attempts.append(CodingLoopAttempt(workflow, draft_path, apply_result, apply_result.message))
        if (
            apply
            and not apply_result.ok
            and attempt_index < MAX_APPLY_RETRIES
            and apply_result.stage in RETRYABLE_APPLY_STAGES
        ):
            next_goal = _goal_with_test_feedback(goal, apply_result)
            continue
        return CodingLoopResult(
            workflow=workflow,
            draft_path=draft_path,
            apply_result=apply_result,
            ok=apply_result.ok,
            message=apply_result.message,
            attempts=attempts,
        )
    # The loop always returns from inside; this fallback keeps type checkers honest.
    return CodingLoopResult(
        workflow=workflow,
        draft_path=draft_path,
        apply_result=apply_result,
        ok=apply_result.ok,
        message=apply_result.message,
        attempts=attempts,
    )


def _latest_reviewer_passed(workflow: AdaptiveWorkflowResult) -> bool:
    for result in reversed(workflow.agent_results):
        if result.role == "ReviewerAgent":
            return "通过" in result.summary and "需修改" not in result.summary
    return False


def _goal_with_test_feedback(goal: str, apply_result: ApplyResult) -> str:
    feedback = apply_result.message[-2000:]
    return "\n".join(
        [
            goal,
            "",
            "上一轮 apply-draft 失败，请根据测试反馈重写草稿。",
            f"失败阶段：{apply_result.stage}",
            "测试反馈：",
            feedback,
            "",
            "要求：保留原任务目标，修复导致测试失败的问题，输出新的完整代码草稿。",
        ]
    )

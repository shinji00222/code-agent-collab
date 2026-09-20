from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .apply import ApplyResult, apply_draft_workflow, find_draft_path
from .orchestration import AdaptiveWorkflowResult, run_adaptive_workflow


@dataclass(frozen=True)
class CodingLoopResult:
    workflow: AdaptiveWorkflowResult
    draft_path: Path | None
    apply_result: ApplyResult | None
    ok: bool
    message: str


def run_coding_loop(project_root: Path, goal: str, apply: bool = False) -> CodingLoopResult:
    """Run the minimal coding loop: plan -> workers -> review -> diff/apply.

    The default is still safe: it stops at a diff preview. Passing apply=True reuses the
    existing apply-draft safeguards: clean git check, isolated tests, formal tests, and
    local commit.
    """
    workflow = run_adaptive_workflow(project_root, goal)
    if not _latest_reviewer_passed(workflow):
        return CodingLoopResult(
            workflow=workflow,
            draft_path=None,
            apply_result=None,
            ok=False,
            message="ReviewerAgent 未通过或没有产生通过结论，已停止在应用前。",
        )

    draft_path = find_draft_path(project_root, workflow.task_id)
    apply_result = apply_draft_workflow(project_root, draft_path, apply=apply)
    return CodingLoopResult(
        workflow=workflow,
        draft_path=draft_path,
        apply_result=apply_result,
        ok=apply_result.ok,
        message=apply_result.message,
    )


def _latest_reviewer_passed(workflow: AdaptiveWorkflowResult) -> bool:
    for result in reversed(workflow.agent_results):
        if result.role == "ReviewerAgent":
            return "通过" in result.summary and "需修改" not in result.summary
    return False

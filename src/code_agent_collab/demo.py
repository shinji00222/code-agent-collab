from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .context_pack import ContextPackResult, create_context_pack
from .reflection import PendingNote, ReflectionResult, create_reflection, list_pending_notes


@dataclass(frozen=True)
class DemoResult:
    context_pack: ContextPackResult
    reflection: ReflectionResult
    pending_notes: list[PendingNote]


def run_demo(project_root: Path, goal: str) -> DemoResult:
    context_pack = create_context_pack(project_root, goal)
    reflection = create_reflection(project_root, context_pack.task_id)
    pending_notes = list_pending_notes(project_root)
    return DemoResult(
        context_pack=context_pack,
        reflection=reflection,
        pending_notes=pending_notes,
    )

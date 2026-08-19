from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PermissionLevel(str, Enum):
    READ_ONLY = "L0_READ_ONLY"
    DRAFT_WRITE = "L1_DRAFT_WRITE"
    PROJECT_WRITE = "L2_PROJECT_WRITE"
    CONFIRM_REQUIRED = "L3_CONFIRM_REQUIRED"


@dataclass(frozen=True)
class AgentContext:
    project_root: Path
    task_goal: str
    task_id: str
    context_pack_path: Path


@dataclass(frozen=True)
class AgentResult:
    role: str
    permission: PermissionLevel
    summary: str
    evidence: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


class BaseAgent:
    role = "BaseAgent"
    permission = PermissionLevel.READ_ONLY

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        raise NotImplementedError

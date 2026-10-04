from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .. import permissions


class PermissionLevel(str, Enum):
    """权限级别。

    取值统一来自 `permissions` 模块，保证「级别定义」只有一处（台账 N5）；
    运行时强制点见 `permissions.check_write()` / `permissions.check_command()`。
    """

    READ_ONLY = permissions.READ_ONLY
    DRAFT_WRITE = permissions.DRAFT_WRITE
    PROJECT_WRITE = permissions.PROJECT_WRITE
    CONFIRM_REQUIRED = permissions.CONFIRM_REQUIRED


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

from __future__ import annotations

from .base import BaseAgent
from .coder import CoderAgent
from .coordinator import CoordinatorAgent
from .knowledge import KnowledgeAgent
from .orchestrator import OrchestratorAgent
from .planner import PlannerAgent
from .reflector import ReflectorAgent
from .reviewer import ReviewerAgent
from .validator import ValidatorAgent


def create_agent(role: str, provider=None) -> BaseAgent:
    """按角色名创建 Agent 实例。

    升级空间：OrchestratorAgent 按预设模板动态构建 workers 时复用此工厂，
    避免在主控代码里写死实例化逻辑；新增 Agent 角色时只需在此登记。
    """
    factories = {
        "CoordinatorAgent": lambda: CoordinatorAgent(),
        "KnowledgeAgent": lambda: KnowledgeAgent(),
        "PlannerAgent": lambda: PlannerAgent(provider=provider),
        "CoderAgent": lambda: CoderAgent(provider=provider),
        "ReviewerAgent": lambda: ReviewerAgent(provider=provider),
        "OrchestratorAgent": lambda: OrchestratorAgent(provider=provider),
        "ValidatorAgent": lambda: ValidatorAgent(),
        "ReflectorAgent": lambda: ReflectorAgent(),
    }
    if role not in factories:
        raise ValueError(f"未知 Agent 角色：{role}")
    return factories[role]()

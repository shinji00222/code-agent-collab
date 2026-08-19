from __future__ import annotations

from ..providers import AIProvider, create_provider
from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class PlannerAgent(BaseAgent):
    role = "PlannerAgent"
    permission = PermissionLevel.DRAFT_WRITE

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or create_provider()

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        ai_plan = self.provider.complete(
            "你是一个谨慎的代码项目计划 Agent，只能提出计划，不能执行高风险操作。",
            (
                f"请为这个任务提出一句保守计划：{context.task_goal}\n"
                f"任务上下文包：{context.context_pack_path}\n"
                "要求：先检查上下文，写入候选区前保留人工确认。"
            ),
        )
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=f"{ai_plan}（Provider：{self.provider.name}）",
            evidence=[
                f"已接收上游 Agent 数量：{len(previous_results)}",
                f"使用 Provider：{self.provider.name}",
            ],
            outputs=[
                "生成任务上下文包",
                "生成候选复利记录",
                "保留用户确认闸门",
            ],
            risks=["AI 只提供计划，不能代替用户确认高风险操作。"],
            next_steps=["交给 ValidatorAgent 验证上下文包和边界。"],
        )

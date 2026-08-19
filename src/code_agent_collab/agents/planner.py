from __future__ import annotations

from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class PlannerAgent(BaseAgent):
    role = "PlannerAgent"
    permission = PermissionLevel.DRAFT_WRITE

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary="已生成保守执行计划：先记录上下文与候选经验，不直接修改主知识库。",
            evidence=[f"已接收上游 Agent 数量：{len(previous_results)}"],
            outputs=[
                "生成任务上下文包",
                "生成候选复利记录",
                "保留用户确认闸门",
            ],
            risks=["如果未来接真实 AI，需要把写权限限制在明确目录内。"],
            next_steps=["交给 ValidatorAgent 验证上下文包和边界。"],
        )

from __future__ import annotations

from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class CoordinatorAgent(BaseAgent):
    role = "CoordinatorAgent"
    permission = PermissionLevel.READ_ONLY

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary="已把任务拆成知识检索、执行计划、验证和复盘四个阶段。",
            evidence=[f"任务目标：{context.task_goal}", f"任务ID：{context.task_id}"],
            outputs=["多 Agent 执行顺序：KnowledgeAgent -> PlannerAgent -> ValidatorAgent -> ReflectorAgent"],
            risks=["当前版本是规则 Agent，不调用真实 AI 模型。"],
            next_steps=["交给 KnowledgeAgent 读取项目内可用上下文。"],
        )

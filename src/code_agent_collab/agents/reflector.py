from __future__ import annotations

from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class ReflectorAgent(BaseAgent):
    role = "ReflectorAgent"
    permission = PermissionLevel.DRAFT_WRITE

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary="已确认复盘只能进入候选区，等待用户审核。",
            evidence=[f"候选区：{context.project_root / 'dev-vault' / 'pending'}"],
            outputs=["候选复利记录由 workflow 统一生成到 dev-vault/pending。"],
            risks=["候选内容仍需用户判断是否有长期价值。"],
            next_steps=["用户审核候选记录，决定保留、废弃或同步。"],
        )

from __future__ import annotations

from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class ValidatorAgent(BaseAgent):
    role = "ValidatorAgent"
    permission = PermissionLevel.READ_ONLY

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        context_exists = context.context_pack_path.exists()
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary="已检查上下文包文件是否存在，并确认本轮验证不写主知识库。",
            evidence=[
                f"上下文包存在：{context_exists}",
                f"上下文包路径：{context.context_pack_path}",
            ],
            outputs=["验证结果：通过" if context_exists else "验证结果：失败"],
            risks=[] if context_exists else ["上下文包不存在，后续复盘依据不足。"],
            next_steps=["交给 ReflectorAgent 生成候选复利记录。"],
        )

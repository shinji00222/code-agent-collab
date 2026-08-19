from __future__ import annotations

from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class KnowledgeAgent(BaseAgent):
    role = "KnowledgeAgent"
    permission = PermissionLevel.READ_ONLY

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        docs_dir = context.project_root / "product-docs"
        docs = sorted(path.name for path in docs_dir.glob("*.md")) if docs_dir.exists() else []
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary="已读取项目文档列表，并确认主知识库仍保持只读边界。",
            evidence=[f"项目文档数量：{len(docs)}", f"上下文包：{context.context_pack_path}"],
            outputs=docs[:12],
            risks=["尚未实现主知识库指定目录检索；当前只读取项目内文档。"],
            next_steps=["交给 PlannerAgent 生成本轮执行计划。"],
        )

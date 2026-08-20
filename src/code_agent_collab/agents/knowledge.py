from __future__ import annotations

from pathlib import Path

from ..config import load_config
from ..file_utils import write_text
from ..knowledge import extract_keywords, render_knowledge_note, search_knowledge
from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class KnowledgeAgent(BaseAgent):
    role = "KnowledgeAgent"
    permission = PermissionLevel.READ_ONLY

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        docs_dir = context.project_root / "product-docs"
        docs = sorted(path.name for path in docs_dir.glob("*.md")) if docs_dir.exists() else []

        main_vault = self.base_path
        if main_vault is None:
            main_vault = Path(load_config(context.project_root).main_vault_path)

        keywords = extract_keywords(context.task_goal)
        hits = search_knowledge(main_vault, keywords)
        knowledge_path = (
            context.project_root / "logs" / "context-packs" / f"{context.task_id}-knowledge.md"
        )
        if hits:
            write_text(
                knowledge_path,
                render_knowledge_note(context.task_id, context.task_goal, hits),
            )

        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=(
                f"已从主知识库检索到 {len(hits)} 个相关文档。"
                if hits
                else "主知识库未检索到与任务直接相关的内容，仍保持只读。"
            ),
            evidence=[
                f"项目文档数量：{len(docs)}",
                f"主知识库范围：{main_vault}",
                f"任务关键词：{', '.join(keywords) or '无'}",
                f"知识补充文件：{knowledge_path if hits else '未生成'}",
            ],
            outputs=[hit.path for hit in hits[:10]] or docs[:12],
            risks=[
                "检索基于关键词匹配，不使用向量语义，命中率有限。",
                "主知识库只读，未写入任何内容。",
                "默认排除隐藏目录、99-附件、work、01-项目等目录。",
            ],
            next_steps=["交给 PlannerAgent 结合检索结果生成本轮执行计划。"],
        )

from __future__ import annotations

from ..file_utils import write_text
from ..providers import AIProvider, create_provider
from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class CoderAgent(BaseAgent):
    role = "CoderAgent"
    permission = PermissionLevel.DRAFT_WRITE

    def __init__(self, provider: AIProvider | None = None, worker_label: str = "") -> None:
        self.provider = provider or create_provider()
        # worker_label 用于区分多个并行的编码 worker（如"模块A"/"模块B"）；
        # 为空时保持原有单一草稿文件名，不影响现有调用方。
        self.worker_label = worker_label

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        duty = f"你负责的部分：{self.worker_label}。" if self.worker_label else ""
        draft = self.provider.complete(
            "你是代码草稿 Agent。只能生成草稿，不能直接修改正式项目文件。",
            (
                f"请根据这个任务生成代码实现草稿：{context.task_goal}\n"
                f"{duty}"
                f"参考上下文包：{context.context_pack_path}\n"
                "请写出建议修改的文件、代码思路和测试方法；不要执行删除、覆盖、部署或推送。"
            ),
        )
        suffix = f"-{self.worker_label}" if self.worker_label else ""
        output_path = (
            context.project_root / "dev-vault" / "projects" / f"{context.task_id}-coder-draft{suffix}.md"
        )
        title = f"# CoderAgent 草稿：{context.task_goal}" + (
            f"（{self.worker_label}）" if self.worker_label else ""
        )
        content = "\n".join(
            [
                title,
                f"- 任务ID：{context.task_id}",
                f"- Provider：{self.provider.name}",
                *([f"- 负责部分：{self.worker_label}"] if self.worker_label else []),
                "- 状态：待人工确认，不得直接合并到正式源码。",
                "",
                "## AI 草稿",
                "",
                draft,
                "",
                "## 安全边界",
                "",
                "- 当前内容只写入 `dev-vault/projects`。",
                "- 写入正式项目文件前必须经过检查和用户确认。",
            ]
        )
        write_text(output_path, content + "\n")
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=f"已生成代码草稿，等待人工确认（Provider：{self.provider.name}）。",
            evidence=[
                f"已接收上游 Agent 数量：{len(previous_results)}",
                f"草稿路径：{output_path}",
                f"负责部分：{self.worker_label or '整体'}",
            ],
            outputs=["生成代码草稿", "生成测试建议", "保留正式文件确认闸门"],
            risks=["草稿未经验证，不能直接写入正式源码。"],
            next_steps=["交给 ReviewerAgent 评审草稿；评审不通过则由主控决定打回重做。"],
        )

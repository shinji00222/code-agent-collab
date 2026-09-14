from __future__ import annotations

from pathlib import Path

from ..apply import parse_draft
from ..file_utils import ensure_dir, write_text
from ..providers import AIProvider, create_provider
from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel


class IntegratorAgent(BaseAgent):
    """合并 Agent：把多份 Coder 草稿整理成统一草稿，不直接改正式源码。"""

    role = "IntegratorAgent"
    permission = PermissionLevel.DRAFT_WRITE

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or create_provider()

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        draft_paths = _find_latest_coder_drafts(context)
        if not draft_paths:
            output_path = _integrated_draft_path(context)
            content = _render_missing_draft(context)
        else:
            output_path = _integrated_draft_path(context)
            content = self._integrate(context, draft_paths)

        ensure_dir(output_path.parent)
        write_text(output_path, content + "\n")
        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=(
                f"已合并 {len(draft_paths)} 份 Coder 草稿，产出统一合并草稿"
                f"（Provider：{self.provider.name}）。"
            ),
            evidence=[
                f"输入草稿：{'、'.join(str(path) for path in draft_paths) or '未找到'}",
                f"合并草稿路径：{output_path}",
                f"已接收上游 Agent 数量：{len(previous_results)}",
            ],
            outputs=["生成合并草稿", "保留正式文件确认闸门"],
            risks=["合并草稿仍未应用到正式源码，必须继续经过 ReviewerAgent 和人工确认。"],
            next_steps=["交给 ReviewerAgent 评审合并草稿；通过后再考虑 apply-draft 或人工落盘。"],
        )

    def _integrate(self, context: AgentContext, draft_paths: list[Path]) -> str:
        drafts = []
        for path in draft_paths:
            drafts.append(f"### 来源：{path.name}\n\n{path.read_text(encoding='utf-8')}")
        source_text = "\n\n---\n\n".join(drafts)
        integrated = self.provider.complete(
            "你是多 Agent 草稿合并员。只能合并草稿，不能直接修改正式项目文件。",
            (
                f"任务：{context.task_goal}\n"
                f"上下文包：{context.context_pack_path}\n"
                "请把下面多份 Coder 草稿合并成一份统一草稿，去掉重复内容，标出冲突和风险。\n"
                "必须严格保留以下 Markdown 小节标题：\n"
                "## 修改文件清单\n"
                "## 修改原因\n"
                "## 建议代码\n"
                "## 测试方法\n"
                "## 风险\n"
                "不要执行删除、覆盖、部署或推送。\n\n"
                f"{source_text}"
            ),
        )
        integrated = _ensure_integrated_format(integrated, source_text)
        return "\n".join(
            [
                f"# IntegratorAgent 合并草稿：{context.task_goal}",
                f"- 任务ID：{context.task_id}",
                f"- Provider：{self.provider.name}",
                "- 状态：待 ReviewerAgent 评审，不得直接合并到正式源码。",
                f"- 输入草稿数量：{len(draft_paths)}",
                "",
                "## AI 草稿",
                "",
                integrated,
                "",
                "## 输入草稿",
                "",
                *[f"- {path}" for path in draft_paths],
                "",
                "## 安全边界",
                "",
                "- 当前内容只写入 `dev-vault/projects`。",
                "- 写入正式项目文件前必须经过检查和用户确认。",
            ]
        )


def _find_latest_coder_drafts(context: AgentContext) -> list[Path]:
    projects_dir = context.project_root / "dev-vault" / "projects"
    if not projects_dir.exists():
        return []
    prefix = f"{context.task_id}-coder-draft"
    latest_by_worker: dict[str, tuple[int, Path]] = {}
    for path in sorted(projects_dir.glob(f"{prefix}*.md")):
        worker_key, revision = _draft_worker_key(path, prefix)
        current = latest_by_worker.get(worker_key)
        if current is None or revision > current[0]:
            latest_by_worker[worker_key] = (revision, path)
    return [item[1] for item in sorted(latest_by_worker.values(), key=lambda item: item[1].name)]


def _draft_worker_key(path: Path, prefix: str) -> tuple[str, int]:
    tail = path.stem.removeprefix(prefix)
    marker = "-revision"
    if marker not in tail:
        return tail, 0
    key, raw_revision = tail.rsplit(marker, 1)
    try:
        return key, int(raw_revision)
    except ValueError:
        return tail, 0


def _integrated_draft_path(context: AgentContext) -> Path:
    return context.project_root / "dev-vault" / "projects" / f"{context.task_id}-integrated-draft.md"


def _render_missing_draft(context: AgentContext) -> str:
    return "\n".join(
        [
            f"# IntegratorAgent 合并草稿：{context.task_goal}",
            f"- 任务ID：{context.task_id}",
            "- 状态：未找到 Coder 草稿，等待人工处理。",
            "",
            "## AI 草稿",
            "",
            "未找到可合并的 Coder 草稿。",
            "",
            "## 安全边界",
            "",
            "- 当前内容只写入 `dev-vault/projects`。",
            "- 写入正式项目文件前必须经过检查和用户确认。",
        ]
    )


def _ensure_integrated_format(integrated: str, source_text: str) -> str:
    if len(integrated.strip()) < 100:
        return integrated
    parsed = parse_draft(integrated)
    if not parsed.errors:
        return integrated
    escaped_source = "\n".join(
        f"    {line}" for line in source_text.replace("```", "'''").splitlines()
    )
    return "\n".join(
        [
            "## 修改文件清单",
            "- src/integrated_plan.md（新增）",
            "## 修改原因",
            "Provider 输出没有形成可解析的五小节草稿，IntegratorAgent 生成安全兜底合并说明。",
            "## 建议代码",
            "### src/integrated_plan.md",
            "# 合并草稿说明",
            "",
            "以下是待人工继续整理的 Coder 草稿内容：",
            "",
            escaped_source,
            "## 测试方法",
            "运行 python -m unittest discover -s tests，并人工检查合并草稿中的冲突和重复内容。",
            "## 风险",
            "这是兜底合并说明，不应直接作为最终实现应用到正式源码。",
        ]
    )

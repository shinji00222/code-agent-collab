from __future__ import annotations

from pathlib import Path

from ..config import load_config
from ..providers import AIProvider, create_provider
from ..review import scan_sensitive
from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel

# 草稿内容低于该字符数视为"太空"（疑似空草稿）
MIN_DRAFT_CHARS = 100


class ReviewerAgent(BaseAgent):
    """草稿评审 Agent（规则版）。

    职责：CoderAgent 写完代码草稿后检查四件事：
    1. 草稿是否存在；
    2. 是否太空（内容过短，疑似空草稿）；
    3. 是否包含敏感信息（API 密钥、密码/令牌关键词、手机号、邮箱）；
    4. 是否越权（草稿内容引用主知识库路径）。

    升级空间（为后续步骤预留）：
    - 构造器已预留 provider 参数，后续可升级为 AI 评审；
    - 评审结论存到 self.last_verdict / self.last_reasons，
      供未来的 OrchestratorAgent 读取并决定是否打回 CoderAgent 重做。
    """

    role = "ReviewerAgent"
    permission = PermissionLevel.READ_ONLY

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or create_provider()
        self.last_verdict: str = "未评审"
        self.last_reasons: list[str] = []

    def run(self, context: AgentContext, previous_results: list[AgentResult]) -> AgentResult:
        draft_paths = self._find_drafts(context)
        reasons: list[str] = []

        if not draft_paths:
            reasons.append("未找到代码草稿（dev-vault/projects 下无 <任务ID>-coder-draft*.md）")
        for draft_path in draft_paths:
            name = draft_path.name
            content = draft_path.read_text(encoding="utf-8")
            stripped_len = len(content.strip())
            if stripped_len < MIN_DRAFT_CHARS:
                reasons.append(
                    f"草稿 {name} 内容过短（{stripped_len} 字符 < {MIN_DRAFT_CHARS}），疑似空草稿"
                )
            sensitive = scan_sensitive(content)
            if sensitive:
                reasons.append(f"草稿 {name} 检测到敏感信息：" + "、".join(sensitive))
            vault = Path(load_config(context.project_root).main_vault_path)
            if str(vault) in content or vault.as_posix() in content:
                reasons.append(f"草稿 {name} 内容引用了主知识库路径，疑似越权")

        verdict = "通过" if not reasons else "需修改"
        self.last_verdict = verdict
        self.last_reasons = reasons

        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=f"草稿评审结论：{verdict}（评审 {len(draft_paths)} 份草稿，{len(reasons)} 个问题）",
            evidence=[
                f"草稿路径：{'、'.join(str(p) for p in draft_paths) or '未找到'}",
                "检查项：存在性 / 内容长度 / 敏感信息 / 越权",
            ],
            outputs=reasons or ["评审通过，无问题"],
            risks=[] if verdict == "通过" else ["草稿存在问题，打回修改前不应进入正式流程。"],
            next_steps=[
                "评审通过则交给 ValidatorAgent；不通过则由主控决定打回 CoderAgent 重做。"
            ],
        )

    def _find_drafts(self, context: AgentContext) -> list[Path]:
        projects_dir = context.project_root / "dev-vault" / "projects"
        if not projects_dir.exists():
            return []
        matches = sorted(projects_dir.glob(f"{context.task_id}-coder-draft*.md"))
        return matches

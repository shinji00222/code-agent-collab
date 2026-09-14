from __future__ import annotations

from pathlib import Path

from ..apply import parse_draft, validate_changes
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
            draft_body = _extract_ai_draft_body(content)
            stripped_len = len(draft_body.strip())
            if stripped_len < MIN_DRAFT_CHARS:
                reasons.append(
                    f"草稿 {name} 内容过短（{stripped_len} 字符 < {MIN_DRAFT_CHARS}），疑似空草稿"
                )
            sensitive = scan_sensitive(content)
            if sensitive:
                reasons.append(f"草稿 {name} 检测到敏感信息：" + "、".join(sensitive))
            vault = Path(load_config(context.project_root).main_vault_path)
            if _mentions_main_vault_outside_project(content, vault, context.project_root):
                reasons.append(f"草稿 {name} 内容引用了主知识库路径，疑似越权")
            reasons.extend(_review_draft_structure(context.project_root, name, draft_body))

        verdict = "通过" if not reasons else "需修改"
        self.last_verdict = verdict
        self.last_reasons = reasons

        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=f"草稿评审结论：{verdict}（评审 {len(draft_paths)} 份草稿，{len(reasons)} 个问题）",
            evidence=[
                f"草稿路径：{'、'.join(str(p) for p in draft_paths) or '未找到'}",
                "检查项：存在性 / 内容长度 / 敏感信息 / 越权 / 草稿结构 / 路径范围 / 测试方法 / 冲突标记",
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
        integrated = projects_dir / f"{context.task_id}-integrated-draft.md"
        if integrated.exists():
            return [integrated]
        matches = sorted(projects_dir.glob(f"{context.task_id}-coder-draft*.md"))
        latest_by_worker: dict[str, tuple[int, Path]] = {}
        prefix = f"{context.task_id}-coder-draft"
        for path in matches:
            worker_key, revision = _draft_worker_key(path, prefix)
            current = latest_by_worker.get(worker_key)
            if current is None or revision > current[0]:
                latest_by_worker[worker_key] = (revision, path)
        return [item[1] for item in sorted(latest_by_worker.values(), key=lambda item: item[1].name)]


def _draft_worker_key(path: Path, prefix: str) -> tuple[str, int]:
    stem = path.stem
    tail = stem.removeprefix(prefix)
    marker = "-revision"
    if marker not in tail:
        return tail, 0
    key, raw_revision = tail.rsplit(marker, 1)
    try:
        return key, int(raw_revision)
    except ValueError:
        return tail, 0


def _mentions_main_vault_outside_project(content: str, vault: Path, project_root: Path) -> bool:
    vault_forms = _path_forms(vault)
    project_forms = _path_forms(project_root)
    for line in content.splitlines():
        normalized = line.lower()
        if any(vault_form in normalized for vault_form in vault_forms) and not any(
            project_form in normalized for project_form in project_forms
        ):
            return True
    return False


def _path_forms(path: Path) -> tuple[str, str]:
    raw = str(path).lower()
    return raw, path.as_posix().lower()


def _extract_ai_draft_body(content: str) -> str:
    marker = "## AI 草稿"
    if marker not in content:
        return content
    body = content.split(marker, 1)[1]
    for boundary in ("\n## 安全边界", "\n## 输入草稿", "\n## Reviewer 反馈"):
        if boundary in body:
            body = body.split(boundary, 1)[0]
    return body


def _review_draft_structure(project_root: Path, name: str, draft_body: str) -> list[str]:
    reasons: list[str] = []
    parsed = parse_draft(draft_body)
    for error in parsed.errors:
        if _is_template_placeholder_error(error):
            continue
        reasons.append(f"草稿 {name} 结构不完整：{error}")

    path_errors = validate_changes(project_root, parsed.changes)
    for error in path_errors:
        if _is_template_placeholder_error(error):
            continue
        reasons.append(f"草稿 {name} 路径不合规：{error}")

    if parsed.test_method and not _has_concrete_test_method(parsed.test_method):
        reasons.append(f"草稿 {name} 测试方法过于笼统，需写明具体命令或检查点")
    if _has_unresolved_conflict_marker(draft_body):
        reasons.append(f"草稿 {name} 包含未解决冲突标记")
    return reasons


def _is_template_placeholder_error(error: str) -> bool:
    return "<路径>" in error or "<文件相对路径>" in error


def _has_concrete_test_method(test_method: str) -> bool:
    text = test_method.lower()
    concrete_tokens = (
        "python",
        "pytest",
        "unittest",
        "npm",
        "pnpm",
        "node",
        "pwsh",
        "powershell",
        "curl",
        "http",
        "点击",
        "打开",
        "检查",
        "验证",
        "运行",
        "命令",
    )
    return any(token in text for token in concrete_tokens)


def _has_unresolved_conflict_marker(content: str) -> bool:
    return any(marker in content for marker in ("<<<<<<<", "=======", ">>>>>>>"))

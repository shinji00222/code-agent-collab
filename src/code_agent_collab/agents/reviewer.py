from __future__ import annotations

import re
from pathlib import Path

from ..apply import FALLBACK_MARKER, parse_draft, validate_changes
from ..config import load_config
from ..providers import AIProvider, create_provider
from ..review import scan_sensitive
from .base import AgentContext, AgentResult, BaseAgent, PermissionLevel

# 草稿内容低于该字符数视为"太空"（疑似空草稿）
MIN_DRAFT_CHARS = 100


class ReviewerAgent(BaseAgent):
    """草稿评审 Agent（规则版）。

    职责：CoderAgent 写完代码草稿后检查：
    1. 草稿是否存在；
    2. 是否太空（内容过短，疑似空草稿）；
    3. 是否包含敏感信息（API 密钥、密码/令牌关键词、手机号、邮箱）；
    4. 是否越权（草稿内容引用主知识库路径）；
    5. 结构、路径范围、测试方法、冲突标记；
    6. **是否越出产出它的 worker 的负责路径**（contracts 非空时生效）。

    为什么需要第 6 项：本项目里 Coder 之间不通信，分工完全依赖
    WorkerSpec.owned_paths 这一份契约。契约只写在提示词里就不算强制，
    必须在这里对草稿的实际路径做校验，否则"分工"只是口头约定。

    升级空间（为后续步骤预留）：
    - 构造器已预留 provider 参数，后续可升级为 AI 评审；
    - 评审结论存到 self.last_verdict / self.last_reasons，
      供未来的 OrchestratorAgent 读取并决定是否打回 CoderAgent 重做。
    """

    role = "ReviewerAgent"
    permission = PermissionLevel.READ_ONLY

    def __init__(
        self,
        provider: AIProvider | None = None,
        contracts: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.provider = provider or create_provider()
        # worker 标签 -> 负责路径。空字典表示"没有分工契约"，此时不做越界检查。
        self.contracts: dict[str, tuple[str, ...]] = dict(contracts or {})
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
            parsed = parse_draft(draft_body)
            reasons.extend(
                _review_draft_structure(context.project_root, name, draft_body, parsed)
            )
            reasons.extend(_review_ownership(name, parsed, self.contracts))

        # COMPLEX 档下合并草稿会遮蔽单份 Coder 草稿（_find_drafts 只返回合并草稿），
        # 所以这里额外按 worker 契约单独校验每一份 Coder 草稿，否则"分工"在
        # 真实复杂流程里等于没查。
        integrated_reviewed = any(
            path.name.endswith("-integrated-draft.md") for path in draft_paths
        )
        if integrated_reviewed and self.contracts:
            reasons.extend(self._review_coder_drafts_contracts(context))

        verdict = "通过" if not reasons else "需修改"
        self.last_verdict = verdict
        self.last_reasons = reasons

        return AgentResult(
            role=self.role,
            permission=self.permission,
            summary=f"草稿评审结论：{verdict}（评审 {len(draft_paths)} 份草稿，{len(reasons)} 个问题）",
            evidence=[
                f"草稿路径：{'、'.join(str(p) for p in draft_paths) or '未找到'}",
                "检查项：存在性 / 内容长度 / 敏感信息 / 越权 / 草稿结构 / 路径范围 / 测试方法 / 冲突标记 / worker 负责路径",
            ],
            outputs=reasons or ["评审通过，无问题"],
            risks=[] if verdict == "通过" else ["草稿存在问题，打回修改前不应进入正式流程。"],
            next_steps=[
                "评审通过则交给 ValidatorAgent；不通过则由主控决定打回 CoderAgent 重做。"
            ],
        )

    def _review_coder_drafts_contracts(self, context: AgentContext) -> list[str]:
        """按 worker 契约校验每一份 Coder 草稿（每个 worker 只取最新一版）。

        只在合并草稿存在时调用：那种情况下 _find_drafts 只返回合并草稿，
        单份 Coder 草稿不会被上面那轮循环看到。
        """
        projects_dir = context.project_root / "dev-vault" / "projects"
        if not projects_dir.exists():
            return []
        prefix = f"{context.task_id}-coder-draft"
        latest: dict[str, tuple[int, Path]] = {}
        for path in sorted(projects_dir.glob(f"{prefix}*.md")):
            worker_key, revision = _draft_worker_key(path, prefix)
            current = latest.get(worker_key)
            if current is None or revision > current[0]:
                latest[worker_key] = (revision, path)
        reasons: list[str] = []
        for _, path in sorted(latest.values(), key=lambda item: item[1].name):
            parsed = parse_draft(_extract_ai_draft_body(path.read_text(encoding="utf-8")))
            reasons.extend(_review_ownership(path.name, parsed, self.contracts))
        return reasons

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


def _review_draft_structure(
    project_root: Path,
    name: str,
    draft_body: str,
    parsed,
) -> list[str]:
    reasons: list[str] = []
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
    # 兜底合并说明结构上合法，但内容只是把原始草稿堆在一起，不是真正的合并结果；
    # 放行它等于让"合并失败"悄悄变成"评审通过"。
    if FALLBACK_MARKER in draft_body:
        reasons.append(
            f"草稿 {name} 是兜底合并说明（未经真正合并），必须重新合并或人工处理"
        )
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


def _draft_worker_label(name: str) -> str:
    """从草稿文件名里取 worker 标签。

    形如 `<任务ID>-coder-draft-<标签>-revision1.md` 时返回 `<标签>`；
    没有标签（单一 Coder）返回空串；不是 coder 草稿也返回空串。
    """
    stem = Path(name).stem
    marker = "-coder-draft"
    if marker not in stem:
        return ""
    tail = stem.split(marker, 1)[1].lstrip("-")
    return re.sub(r"-revision\d+$", "", tail)


def _normalize_owned_path(value: str) -> str:
    return value.replace("\\", "/").strip().strip("/").lower()


def _within_owned(target_path: str, owned_paths: tuple[str, ...]) -> bool:
    target = _normalize_owned_path(target_path)
    for item in owned_paths:
        own = _normalize_owned_path(item)
        if not own:
            continue
        if target == own or target.startswith(own + "/"):
            return True
    return False


def _review_ownership(name: str, parsed, contracts: dict[str, tuple[str, ...]]) -> list[str]:
    """校验草稿里的每个路径是否落在产出它的 worker 负责范围内。

    - 没有契约（单 Coder 档）→ 不检查；
    - 文件名认不出 worker 标签 → 不猜，跳过，避免误报；
    - 合并草稿 → 用所有 worker 负责路径的并集校验。
    """
    if not contracts:
        return []
    if name.endswith("-integrated-draft.md"):
        owned = tuple(path for paths in contracts.values() for path in paths)
        scope = "合并草稿（所有 worker 范围之和）"
    else:
        label = _draft_worker_label(name)
        if label not in contracts:
            return []
        owned = contracts[label]
        scope = f"{label or '默认'} worker"
    if not owned:
        return []
    reasons: list[str] = []
    for change in parsed.changes:
        # 模板占位符（如 <文件相对路径>）说明草稿没按格式填，
        # 那是"结构不完整"的问题，不该在这里被判成越界。
        if _is_template_placeholder_error(change.path):
            continue
        if not _within_owned(change.path, owned):
            reasons.append(
                f"草稿 {name} 越出负责路径：{change.path}"
                f"（{scope} 只负责 {'、'.join(owned)}）"
            )
    return reasons

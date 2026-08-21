from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import load_config
from .file_utils import ensure_dir, read_text, write_text
from .providers import AIProvider

SENSITIVE_PATTERNS: dict[str, re.Pattern] = {
    "API密钥": re.compile(r"sk-[A-Za-z0-9]{12,}"),
    "密码/令牌关键词": re.compile(r"(password|passwd|secret|token|cookie)", re.IGNORECASE),
    "手机号": re.compile(r"1[3-9]\d{9}"),
    "邮箱": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
}

METADATA_PREFIXES = ("来源上下文包：", "建议写入位置：", "- AI建议写入位置：")

DEFAULT_VAULT_SUBDIR = "04-知识/02-Codex知识/04-复盘"

STATUS_LINE_PREFIXES = ("- 当前状态：", "- 状态：")


@dataclass(frozen=True)
class ReviewResult:
    path: Path
    status: str
    reason: str
    target_path: Path | None = None


def _pending_dir(project_root: Path) -> Path:
    return project_root / "dev-vault" / "pending"


def scan_sensitive(content: str) -> list[str]:
    found: list[str] = []
    for name, pattern in SENSITIVE_PATTERNS.items():
        if pattern.search(content):
            found.append(name)
    return found


AI_TARGET_PREFIX = "- AI建议写入位置："


def _read_ai_target(content: str) -> str:
    """读取候选记录中 AI 建议的写入位置（相对主知识库路径）。"""
    for line in content.splitlines():
        if line.startswith(AI_TARGET_PREFIX):
            return line.removeprefix(AI_TARGET_PREFIX).strip().strip("/\\")
    return ""


def _body_without_metadata(content: str) -> str:
    return "\n".join(
        line for line in content.splitlines() if not line.startswith(METADATA_PREFIXES)
    )


def _strip_machine_paths(content: str) -> str:
    return re.sub(r"[A-Za-z]:\\[^\s`\"<>|*?]+", "（本机路径已省略）", content)


def _replace_status(content: str, new_status: str) -> str:
    for prefix in STATUS_LINE_PREFIXES:
        if any(line.startswith(prefix) for line in content.splitlines()):
            lines = [
                line if not line.startswith(prefix) else f"{prefix}{new_status}"
                for line in content.splitlines()
            ]
            return "\n".join(lines)
    return content


def _append_review_record(content: str, reason: str, now: datetime) -> str:
    return content.rstrip() + f"\n\n## 审查记录\n\n- 审查时间：{now:%Y-%m-%d %H:%M:%S}\n- 审查结果：{reason}\n"


def _mark_status(path: Path, status: str, reason: str, now: datetime | None = None) -> ReviewResult:
    now = now or datetime.now()
    content = read_text(path)
    content = _replace_status(content, status)
    content = _append_review_record(content, reason, now)
    write_text(path, content)
    return ReviewResult(path=path, status=status, reason=reason)


def _main_vault(project_root: Path) -> Path:
    return Path(load_config(project_root).main_vault_path)


def _resolve_target(project_root: Path, ai_target: str) -> Path:
    vault = _main_vault(project_root)
    if ai_target:
        candidate = (vault / ai_target).resolve()
        if vault.resolve() in candidate.parents and candidate.is_dir():
            return candidate
    default_dir = (vault / DEFAULT_VAULT_SUBDIR).resolve()
    if default_dir.is_dir():
        return default_dir
    return vault


def _write_to_main_vault(project_root: Path, content: str, target_dir: Path, source_name: str) -> Path:
    ensure_dir(target_dir)
    cleaned = _strip_machine_paths(content)
    target = target_dir / source_name
    write_text(target, cleaned)
    return target


def review_pending_note(
    project_root: Path,
    path: Path,
    provider: AIProvider,
    now: datetime | None = None,
) -> ReviewResult:
    now = now or datetime.now()
    content = read_text(path)
    sensitive = scan_sensitive(_body_without_metadata(content))
    if sensitive:
        return _mark_status(
            path,
            "待人工处理",
            "检测到敏感信息：" + "、".join(sensitive),
            now,
        )

    vault = _main_vault(project_root)
    prompt = (
        "你是知识入库审查员。请审查下面的候选复利记录，判断它是否有长期价值、"
        "是否与主知识库明显重复、是否包含不适合入库的内容。\n"
        f"主知识库位置：{vault}\n\n"
        f"{content}\n\n"
        "请按以下格式输出三行：\n"
        "REVIEW_VERDICT: approve 或 risky\n"
        "REVIEW_REASON: 一句话理由\n"
        "REVIEW_TARGET: 建议写入的主知识库相对路径（必须是现有目录，或留空）"
    )
    try:
        ai_text = provider.complete("知识入库审查", prompt)
    except Exception as exc:  # noqa: BLE001 - 审查失败要转为人工处理
        return _mark_status(path, "待人工处理", f"AI 审查失败：{exc}", now)

    verdict = ""
    reason = ""
    ai_target = ""
    verdict_ok = False
    for line in ai_text.splitlines():
        if line.startswith("REVIEW_VERDICT:"):
            raw = line.split(":", 1)[1].strip().lower()
            if raw in {"approve", "risky"}:
                verdict = raw
                verdict_ok = True
        elif line.startswith("REVIEW_REASON:"):
            reason = line.split(":", 1)[1].strip()
        elif line.startswith("REVIEW_TARGET:"):
            ai_target = line.split(":", 1)[1].strip().strip("/\\")

    if not verdict_ok:
        if provider.name == "mock":
            verdict = "approve"
            reason = "mock 审查（仅本地脱敏扫描通过）"
        else:
            return _mark_status(path, "待人工处理", "AI 审查输出无法解析", now)

    if verdict != "approve":
        return _mark_status(path, "待人工处理", reason or "AI 判定不建议入库", now)

    # AI 审查通过：只记录 AI 建议的写入位置，绝不自动入库，必须人工确认
    if ai_target:
        write_text(path, content.rstrip() + f"\n{AI_TARGET_PREFIX}{ai_target}\n")
    return _mark_status(path, "待人工确认", "AI 审查通过，建议入库，等待人工确认", now)


def confirm_pending_note(project_root: Path, path: Path, now: datetime | None = None) -> ReviewResult:
    now = now or datetime.now()
    content = read_text(path)
    sensitive = scan_sensitive(_body_without_metadata(content))
    if sensitive:
        return _mark_status(
            path,
            "待人工处理",
            "人工确认仍发现敏感信息：" + "、".join(sensitive),
            now,
        )
    vault = _main_vault(project_root)
    ai_target = _read_ai_target(content)
    target_dir = _resolve_target(project_root, ai_target)
    target_path = _write_to_main_vault(project_root, content, target_dir, path.name)
    relative = target_path.relative_to(vault)
    _mark_status(path, f"已确认入库：{relative}", f"人工确认，写入 {relative}", now)
    return ReviewResult(
        path=path,
        status="已确认入库",
        reason=f"人工确认，写入 {relative}",
        target_path=target_path,
    )


def discard_pending_note(path: Path, now: datetime | None = None) -> ReviewResult:
    return _mark_status(path, "已废弃", "用户选择废弃，不写入主知识库", now)


def list_pending_paths(project_root: Path, task: str | None = None) -> list[Path]:
    pending_dir = _pending_dir(project_root)
    if not pending_dir.exists():
        return []
    paths = sorted(
        pending_dir.glob("*.md"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not task:
        return paths
    return [path for path in paths if task in path.stem]


def find_pending_path(project_root: Path, name: str) -> Path:
    pending_dir = _pending_dir(project_root)
    direct = pending_dir / name
    if direct.exists():
        return direct
    matches = [path for path in pending_dir.glob("*.md") if name in path.stem]
    if not matches:
        raise FileNotFoundError(f"未找到候选记录：{name}")
    return matches[0]

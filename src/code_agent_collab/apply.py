from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import load_config
from .draft_review import (
    extract_ai_draft_body,
    has_concrete_test_method,
    has_unresolved_conflict_marker,
    mentions_main_vault_outside_project,
)
from .file_utils import ensure_dir, read_text, write_text
from .permissions import (
    PROJECT_WRITE,
    check_command,
    check_write,
    ensure_inside_project,
)
from .review import scan_sensitive

# apply-draft 允许写入的目录（相对项目根）；其他区域一律拒绝
ALLOWED_DIRS = ("src", "tests")
ALLOWED_SUFFIXES = (".py", ".md", ".toml", ".txt", ".json", ".ini", ".cfg", ".yaml", ".yml")

SECTION_FILES = "## 修改文件清单"
SECTION_REASON = "## 修改原因"
SECTION_CODE = "## 建议代码"
SECTION_TEST = "## 测试方法"
SECTION_RISK = "## 风险"

DRAFT_GLOB = "*-coder-draft*.md"
TEST_TIMEOUT_SECONDS = 120
APPROVAL_SCHEMA_VERSION = 1

# 兜底合并草稿的状态标记：Integrator 没能产出可解析的合并草稿时会生成这种
# 兜底说明。它结构上是合法的，但内容只是把原始草稿堆在一起，绝不能当成
# 可应用的实现，所以评审和应用闸门都要认得这个标记。
FALLBACK_MARKER = "FALLBACK_INTEGRATED_DRAFT"

TRIAL_COPY_EXCLUDE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "dev-vault",
}
SENSITIVE_ENV_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "cookie",
    "credential",
    "passwd",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class DraftChange:
    """草稿中一个文件的改动：相对项目根路径 + 完整新内容。"""

    path: str
    content: str


@dataclass(frozen=True)
class ParseResult:
    changes: list[DraftChange]
    declared_paths: list[str]
    reason: str
    test_method: str
    risk: str
    errors: list[str]


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    stage: str
    message: str
    changes: list[DraftChange] = field(default_factory=list)
    diffs: list[tuple[str, str]] = field(default_factory=list)


def _section(content: str, title: str) -> str:
    """取某二级标题到下一个二级标题之间的文本；标题不存在返回空串。"""
    lines = content.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == title:
            start = index + 1
            break
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out).strip()


def _code_blocks(section: str) -> list[DraftChange]:
    """解析"建议代码"小节：### <路径> 块到下一个 ### 或二级标题为止。"""
    changes: list[DraftChange] = []
    lines = section.splitlines()
    current_path: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal current_path, buf
        if current_path is not None:
            changes.append(DraftChange(current_path, _strip_code_fence("\n".join(buf))))
        current_path = None
        buf = []

    for line in lines:
        if line.startswith("### "):
            flush()
            current_path = line[4:].strip().strip("`")
        elif line.startswith("## "):
            flush()
        elif current_path is not None:
            buf.append(line)
    flush()
    return changes


def _strip_code_fence(content: str) -> str:
    """去掉单个文件内容外层的 Markdown fenced code wrapper。"""
    lines = content.strip().splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return content.strip()


def _normalize_draft_path(path: str) -> str:
    normalized = path.strip().strip("`").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _declared_file_paths(section: str) -> list[str]:
    """解析"修改文件清单"小节中的相对路径。"""
    paths: list[str] = []
    for line in section.splitlines():
        text = line.strip()
        if not text:
            continue
        text = re.sub(r"^[-*]\s*", "", text)
        text = re.sub(r"^\d+[.)、]\s*", "", text)
        if text.startswith("`") and "`" in text[1:]:
            candidate = text.split("`", 2)[1]
        else:
            candidate = re.split(r"\s|（|\(|：|:", text, maxsplit=1)[0]
        candidate = _normalize_draft_path(candidate)
        if candidate and candidate not in paths:
            paths.append(candidate)
    return paths


def parse_draft(content: str) -> ParseResult:
    """解析规范化的 Coder 草稿，提取各文件改动与说明小节。"""
    errors: list[str] = []
    files_section = _section(content, SECTION_FILES)
    if not files_section:
        errors.append(f"缺少小节 {SECTION_FILES}")
    declared_paths = _declared_file_paths(files_section) if files_section else []
    reason = _section(content, SECTION_REASON)
    if not reason:
        errors.append(f"缺少小节 {SECTION_REASON}")
    code_section = _section(content, SECTION_CODE)
    if not code_section:
        errors.append(f"缺少小节 {SECTION_CODE}")
    test_method = _section(content, SECTION_TEST)
    if not test_method:
        errors.append(f"缺少小节 {SECTION_TEST}")
    risk = _section(content, SECTION_RISK)

    changes = _code_blocks(code_section) if code_section else []
    if not changes:
        errors.append(f"{SECTION_CODE} 下没有找到任何 ### <路径> 代码块")
    actual_paths = [_normalize_draft_path(change.path) for change in changes]
    # 同一路径出现多个块时，落盘只会保留最后一份（_apply_changes 顺序写），
    # 前面几份会静默消失。这里必须直接判不合法，不能让它在没人察觉的情况下通过。
    duplicates = sorted({path for path in actual_paths if actual_paths.count(path) > 1})
    if duplicates:
        detail = "、".join(
            f"{path}（出现 {actual_paths.count(path)} 次）" for path in duplicates
        )
        errors.append(
            f"{SECTION_CODE} 中同一路径出现多个版本，必须先合并成一份完整内容：{detail}"
        )
    if declared_paths and actual_paths:
        missing_code = sorted(set(declared_paths) - set(actual_paths))
        undeclared_code = sorted(set(actual_paths) - set(declared_paths))
        if missing_code:
            errors.append("修改文件清单列出但建议代码缺少：" + "、".join(missing_code))
        if undeclared_code:
            errors.append("建议代码包含未在修改文件清单声明的路径：" + "、".join(undeclared_code))
    return ParseResult(
        changes=changes,
        declared_paths=declared_paths,
        reason=reason,
        test_method=test_method,
        risk=risk,
        errors=errors,
    )


def validate_changes(project_root: Path, changes: list[DraftChange]) -> list[str]:
    """白名单与路径安全校验：只允许改项目内 src/、tests/ 下的文本文件。"""
    errors: list[str] = []
    root = project_root.resolve()
    for change in changes:
        rel = Path(change.path)
        parts = rel.parts
        if not parts or parts[0] not in ALLOWED_DIRS:
            errors.append(f"路径越界（只允许 {'、'.join(ALLOWED_DIRS)} 内）：{change.path}")
            continue
        if rel.is_absolute():
            errors.append(f"不允许绝对路径：{change.path}")
            continue
        if rel.suffix.lower() not in ALLOWED_SUFFIXES:
            errors.append(f"不允许的文件类型：{change.path}")
            continue
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            errors.append(f"路径越界：{change.path}")
            continue
    return errors


def review_apply_gate(project_root: Path, draft_path: Path, content: str, parsed: ParseResult) -> list[str]:
    """应用草稿前的硬闸门：复用 Reviewer 的关键规则，避免不合格草稿落盘。"""
    errors: list[str] = []
    draft_body = extract_ai_draft_body(content)
    stripped_len = len(draft_body.strip())
    if stripped_len < 100:
        errors.append(f"草稿内容过短（{stripped_len} 字符 < 100），疑似空草稿")

    sensitive = scan_sensitive(content)
    if sensitive:
        errors.append("检测到敏感信息：" + "、".join(sensitive))

    vault = Path(load_config(project_root).main_vault_path)
    if mentions_main_vault_outside_project(content, vault, project_root):
        errors.append("草稿内容引用了项目外的主知识库路径，疑似越权")

    if parsed.test_method and not has_concrete_test_method(parsed.test_method):
        errors.append("测试方法过于笼统，需写明具体命令或检查点")

    if has_unresolved_conflict_marker(draft_body):
        errors.append("草稿包含未解决冲突标记")

    if FALLBACK_MARKER in content:
        errors.append(
            "草稿是兜底合并说明（未经真正合并），不能直接应用到正式源码，"
            "请重新合并或人工处理"
        )

    if draft_path.name.endswith("-integrated-draft.md"):
        return errors
    if "-coder-draft" not in draft_path.name:
        errors.append("草稿文件名不是 Coder/Integrator 标准草稿，拒绝应用")
    return errors


def generate_diffs(project_root: Path, changes: list[DraftChange]) -> list[tuple[str, str]]:
    """生成每个文件的 unified diff 预览，不写任何文件。"""
    result: list[tuple[str, str]] = []
    for change in changes:
        target = project_root / change.path
        old = read_text(target) if target.exists() else ""
        diff = difflib.unified_diff(
            old.splitlines(),
            change.content.splitlines(),
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
            lineterm="",
        )
        result.append((change.path, "\n".join(diff)))
    return result


def git_status_porcelain(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return ""
    return result.stdout.strip()


def git_is_clean(project_root: Path) -> bool:
    return not git_status_porcelain(project_root)


def _git_head(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return _sha256_bytes(path.read_bytes())


def _approval_path(project_root: Path, draft_path: Path) -> Path:
    return project_root / "logs" / "approvals" / f"{draft_path.stem}.json"


def _approval_payload(
    project_root: Path,
    draft_path: Path,
    changes: list[DraftChange],
    diffs: list[tuple[str, str]],
) -> dict:
    return {
        "schemaVersion": APPROVAL_SCHEMA_VERSION,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "gitHead": _git_head(project_root),
        "draftPath": draft_path.relative_to(project_root).as_posix()
        if draft_path.is_relative_to(project_root)
        else str(draft_path),
        "draftSha256": _file_sha256(draft_path),
        "targets": [
            {
                "path": change.path,
                "sha256": _file_sha256(project_root / change.path),
            }
            for change in changes
        ],
        "diffSha256": _sha256_text("\n".join(diff for _, diff in diffs)),
    }


def _write_approval(
    project_root: Path,
    draft_path: Path,
    changes: list[DraftChange],
    diffs: list[tuple[str, str]],
) -> Path:
    path = _approval_path(project_root, draft_path)
    ensure_dir(path.parent)
    payload = _approval_payload(project_root, draft_path, changes, diffs)
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def _validate_approval(
    project_root: Path,
    draft_path: Path,
    changes: list[DraftChange],
    diffs: list[tuple[str, str]],
) -> list[str]:
    path = _approval_path(project_root, draft_path)
    if not path.exists():
        return [
            "未找到 dry-run 批准基线，请先执行 "
            f"apply-draft {draft_path.stem} 预览并确认 diff。"
        ]
    try:
        payload = json.loads(read_text(path))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"批准基线文件无法读取：{exc}"]
    expected = _approval_payload(project_root, draft_path, changes, diffs)
    errors: list[str] = []
    if payload.get("schemaVersion") != APPROVAL_SCHEMA_VERSION:
        errors.append("批准基线版本不匹配，请重新 dry-run。")
    if payload.get("gitHead") != expected["gitHead"]:
        errors.append("Git HEAD 已变化，请重新 dry-run 预览。")
    if payload.get("draftSha256") != expected["draftSha256"]:
        errors.append("草稿文件已变化，请重新 dry-run 预览。")
    if payload.get("diffSha256") != expected["diffSha256"]:
        errors.append("diff 摘要已变化，请重新 dry-run 预览。")
    previous_targets = {
        str(item.get("path")): item.get("sha256")
        for item in payload.get("targets", [])
        if isinstance(item, dict)
    }
    for target in expected["targets"]:
        path_text = target["path"]
        if previous_targets.get(path_text) != target["sha256"]:
            errors.append(f"目标文件已变化：{path_text}，请重新 dry-run 预览。")
    return errors


def run_tests(
    project_root: Path,
    timeout_seconds: int = TEST_TIMEOUT_SECONDS,
    *,
    permission: object = PROJECT_WRITE,
) -> tuple[int, str]:
    env = _test_env(project_root)
    argv = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    check_command(
        permission,
        argv,
        action="运行项目测试",
        cwd=project_root,
        project_root=project_root,
    )
    try:
        result = subprocess.run(
            argv,
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return 124, f"测试超时（>{timeout_seconds} 秒），已终止测试进程。\n{output[-2000:]}"
    return result.returncode, (result.stdout + result.stderr)


def _test_env(project_root: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not _is_sensitive_env_item(key, value)
    }
    env["PYTHONPATH"] = str(project_root / "src")
    env["AGENT_WORKBENCH_PROVIDER"] = "mock"
    for key in ("AGENT_WORKBENCH_API_KEY_ENV", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        env.pop(key, None)
    return env


def _is_sensitive_env_item(key: str, value: str) -> bool:
    lowered = key.lower()
    if any(token in lowered for token in SENSITIVE_ENV_TOKENS):
        return True
    if re.search(r"sk-[A-Za-z0-9]{12,}", value):
        return True
    return False


def _run_isolated_tests(
    project_root: Path,
    changes: list[DraftChange],
    *,
    permission: object = PROJECT_WRITE,
) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="agent-workbench-apply-") as tmp:
        trial_root = Path(tmp) / project_root.name
        shutil.copytree(project_root, trial_root, ignore=_ignore_trial_copy)
        _apply_changes(trial_root, changes, permission=permission)
        return run_tests(trial_root, permission=permission)


def _ignore_trial_copy(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in TRIAL_COPY_EXCLUDE_DIRS:
            ignored.add(name)
    return ignored


def git_commit(
    project_root: Path,
    message: str,
    paths: list[str] | None = None,
    *,
    permission: object = PROJECT_WRITE,
) -> tuple[bool, str]:
    """提交改动。

    paths 非空时只暂存这些路径（apply-draft 的批准清单），避免把无关改动卷进提交；
    paths 为空时保持旧的 `git add -A` 行为，供其他调用方使用。

    暂存清单里的每个路径都必须落在项目内，否则拒绝执行（防止把项目外的内容提进来）。
    """
    if not (project_root / ".git").exists():
        return False, "不是 Git 仓库，跳过自动提交"
    for path in paths or []:
        ensure_inside_project(
            project_root / path,
            project_root,
            action=f"暂存批准清单路径 {path}",
        )
    add_args = ["git", "add", "--", *paths] if paths else ["git", "add", "-A"]
    check_command(
        permission,
        add_args,
        action="暂存改动",
        cwd=project_root,
        project_root=project_root,
    )
    add = subprocess.run(
        add_args,
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if add.returncode != 0:
        return False, add.stderr.strip()
    commit_args = ["git", "commit", "-m", message]
    check_command(
        permission,
        commit_args,
        action="创建本地提交",
        cwd=project_root,
        project_root=project_root,
    )
    commit = subprocess.run(
        commit_args,
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if commit.returncode != 0:
        return False, commit.stderr.strip()
    return True, commit.stdout.strip()


def _draft_sort_key(path: Path) -> tuple[float, int]:
    match = re.search(r"-revision(\d+)\.md$", path.name)
    revision = int(match.group(1)) if match else 0
    return (path.stat().st_mtime, revision)


def find_draft_path(project_root: Path, task: str) -> Path:
    projects_dir = project_root / "dev-vault" / "projects"
    if not projects_dir.exists():
        raise FileNotFoundError(f"草稿目录不存在：{projects_dir}")
    integrated_direct = projects_dir / f"{task}-integrated-draft.md"
    if integrated_direct.exists():
        return integrated_direct
    integrated_matches = sorted(
        projects_dir.glob(f"*{task}*integrated-draft.md"),
        key=_draft_sort_key,
        reverse=True,
    )
    if integrated_matches:
        return integrated_matches[0]
    direct = projects_dir / f"{task}-coder-draft.md"
    matches = sorted(
        projects_dir.glob(f"*{task}*coder-draft*.md"),
        key=_draft_sort_key,
        reverse=True,
    )
    if direct.exists() and direct not in matches:
        matches.append(direct)
    if not matches:
        matches = sorted(
            (path for path in projects_dir.glob(DRAFT_GLOB) if task in path.stem),
            key=_draft_sort_key,
            reverse=True,
        )
    if not matches:
        raise FileNotFoundError(f"未找到匹配任务的代码草稿：{task}")
    return matches[0]


def _apply_changes(
    project_root: Path,
    changes: list[DraftChange],
    *,
    permission: object = PROJECT_WRITE,
) -> dict[str, str | None]:
    """写文件并返回 {路径: 旧内容} 备份（旧文件不存在时为 None）。

    这是唯一会把草稿内容落成项目文件的入口，所以每个目标在写入前都要过权限强制点。
    """
    backup: dict[str, str | None] = {}
    for change in changes:
        target = project_root / change.path
        check_write(permission, target, project_root, action=f"写入项目文件 {change.path}")
        backup[change.path] = read_text(target) if target.exists() else None
        write_text(target, change.content)
    return backup


def _rollback_changes(
    project_root: Path,
    backup: dict[str, str | None],
    *,
    permission: object = PROJECT_WRITE,
) -> None:
    for path, old in backup.items():
        target = project_root / path
        check_write(permission, target, project_root, action=f"回滚项目文件 {path}")
        if old is None:
            if target.exists():
                target.unlink()
        else:
            write_text(target, old)


def apply_draft_workflow(
    project_root: Path,
    draft_path: Path,
    apply: bool,
    *,
    require_approval: bool = True,
    permission: object = PROJECT_WRITE,
) -> ApplyResult:
    """apply-draft 主流程：解析 → 校验 → 预览（或 应用→测试→提交/回滚）。

    `permission` 是调用方声明的当前权限级别，会传给写入/命令强制点。
    `apply-draft --apply` 属于人工确认过的改源码操作，用默认的 L2_PROJECT_WRITE。
    """
    content = read_text(draft_path)
    parsed = parse_draft(content)
    if parsed.errors:
        return ApplyResult(ok=False, stage="解析", message="；".join(parsed.errors))
    errors = validate_changes(project_root, parsed.changes)
    if errors:
        return ApplyResult(ok=False, stage="校验", message="；".join(errors))
    review_errors = review_apply_gate(project_root, draft_path, content, parsed)
    if review_errors:
        return ApplyResult(ok=False, stage="评审闸门", message="；".join(review_errors))

    diffs = generate_diffs(project_root, parsed.changes)
    if not apply:
        approval_path = _write_approval(project_root, draft_path, parsed.changes, diffs)
        return ApplyResult(
            ok=True,
            stage="预览（dry-run）",
            message=(
                f"共 {len(parsed.changes)} 个文件改动，未写入任何文件；"
                f"已保存批准基线：{approval_path}；"
                f"确认无误后执行：apply-draft {draft_path.stem} --apply"
            ),
            changes=parsed.changes,
            diffs=diffs,
        )

    if require_approval:
        approval_errors = _validate_approval(project_root, draft_path, parsed.changes, diffs)
        if approval_errors:
            return ApplyResult(
                ok=False,
                stage="批准基线",
                message="；".join(approval_errors),
                changes=parsed.changes,
                diffs=diffs,
            )

    if not git_is_clean(project_root):
        return ApplyResult(
            ok=False,
            stage="前置检查",
            message="Git 工作区有未提交改动，请先提交或处理后再应用，否则无法干净回滚。",
            changes=parsed.changes,
            diffs=diffs,
        )

    code, output = _run_isolated_tests(project_root, parsed.changes, permission=permission)
    if code != 0:
        return ApplyResult(
            ok=False,
            stage="隔离测试",
            message=f"隔离副本测试失败（退出码 {code}），正式源码未被写入。\n{output[-2000:]}",
            changes=parsed.changes,
            diffs=diffs,
        )

    backup = _apply_changes(project_root, parsed.changes, permission=permission)
    code, output = run_tests(project_root, permission=permission)
    if code != 0:
        _rollback_changes(project_root, backup, permission=permission)
        return ApplyResult(
            ok=False,
            stage="正式测试",
            message=f"正式工作区测试失败（退出码 {code}），已自动回滚改动。\n{output[-2000:]}",
            changes=parsed.changes,
            diffs=diffs,
        )

    # 只暂存本次批准清单里的文件，避免把工作区其它改动一起卷进提交
    committed, commit_msg = git_commit(
        project_root,
        f"apply-draft: {draft_path.stem}",
        paths=[change.path for change in parsed.changes],
        permission=permission,
    )
    if not committed:
        return ApplyResult(
            ok=True,
            stage="应用完成",
            message=f"测试通过，改动已写入。{commit_msg}",
            changes=parsed.changes,
            diffs=diffs,
        )
    return ApplyResult(
        ok=True,
        stage="应用并提交",
        message=f"测试通过，已自动提交：{commit_msg}",
        changes=parsed.changes,
        diffs=diffs,
    )

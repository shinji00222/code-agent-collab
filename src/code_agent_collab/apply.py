from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import load_config
from .file_utils import read_text, write_text
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
            changes.append(DraftChange(current_path, "\n".join(buf).strip()))
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
    draft_body = _extract_ai_draft_body(content)
    stripped_len = len(draft_body.strip())
    if stripped_len < 100:
        errors.append(f"草稿内容过短（{stripped_len} 字符 < 100），疑似空草稿")

    sensitive = scan_sensitive(content)
    if sensitive:
        errors.append("检测到敏感信息：" + "、".join(sensitive))

    vault = Path(load_config(project_root).main_vault_path)
    if _mentions_main_vault_outside_project(content, vault, project_root):
        errors.append("草稿内容引用了项目外的主知识库路径，疑似越权")

    if parsed.test_method and not _has_concrete_test_method(parsed.test_method):
        errors.append("测试方法过于笼统，需写明具体命令或检查点")

    if _has_unresolved_conflict_marker(draft_body):
        errors.append("草稿包含未解决冲突标记")

    if draft_path.name.endswith("-integrated-draft.md"):
        return errors
    if "-coder-draft" not in draft_path.name:
        errors.append("草稿文件名不是 Coder/Integrator 标准草稿，拒绝应用")
    return errors


def _extract_ai_draft_body(content: str) -> str:
    marker = "## AI 草稿"
    if marker not in content:
        return content
    body = content.split(marker, 1)[1]
    for boundary in ("\n## 安全边界", "\n## 输入草稿", "\n## Reviewer 反馈"):
        if boundary in body:
            body = body.split(boundary, 1)[0]
    return body


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


def run_tests(project_root: Path, timeout_seconds: int = TEST_TIMEOUT_SECONDS) -> tuple[int, str]:
    env = _test_env(project_root)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
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


def _run_isolated_tests(project_root: Path, changes: list[DraftChange]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory(prefix="agent-workbench-apply-") as tmp:
        trial_root = Path(tmp) / project_root.name
        shutil.copytree(project_root, trial_root, ignore=_ignore_trial_copy)
        _apply_changes(trial_root, changes)
        return run_tests(trial_root)


def _ignore_trial_copy(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in TRIAL_COPY_EXCLUDE_DIRS:
            ignored.add(name)
    return ignored


def git_commit(project_root: Path, message: str) -> tuple[bool, str]:
    if not (project_root / ".git").exists():
        return False, "不是 Git 仓库，跳过自动提交"
    add = subprocess.run(
        ["git", "add", "-A"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if add.returncode != 0:
        return False, add.stderr.strip()
    commit = subprocess.run(
        ["git", "commit", "-m", message],
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


def find_draft_path(project_root: Path, task: str) -> Path:
    projects_dir = project_root / "dev-vault" / "projects"
    if not projects_dir.exists():
        raise FileNotFoundError(f"草稿目录不存在：{projects_dir}")
    direct = projects_dir / f"{task}-coder-draft.md"
    if direct.exists():
        return direct
    integrated_direct = projects_dir / f"{task}-integrated-draft.md"
    if integrated_direct.exists():
        return integrated_direct
    integrated_matches = sorted(
        projects_dir.glob(f"*{task}*integrated-draft.md"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if integrated_matches:
        return integrated_matches[0]
    matches = sorted(
        projects_dir.glob(f"*{task}*coder-draft*.md"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        matches = sorted(
            (path for path in projects_dir.glob(DRAFT_GLOB) if task in path.stem),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    if not matches:
        raise FileNotFoundError(f"未找到匹配任务的代码草稿：{task}")
    return matches[0]


def _apply_changes(project_root: Path, changes: list[DraftChange]) -> dict[str, str | None]:
    """写文件并返回 {路径: 旧内容} 备份（旧文件不存在时为 None）。"""
    backup: dict[str, str | None] = {}
    for change in changes:
        target = project_root / change.path
        backup[change.path] = read_text(target) if target.exists() else None
        write_text(target, change.content)
    return backup


def _rollback_changes(project_root: Path, backup: dict[str, str | None]) -> None:
    for path, old in backup.items():
        target = project_root / path
        if old is None:
            if target.exists():
                target.unlink()
        else:
            write_text(target, old)


def apply_draft_workflow(project_root: Path, draft_path: Path, apply: bool) -> ApplyResult:
    """apply-draft 主流程：解析 → 校验 → 预览（或 应用→测试→提交/回滚）。"""
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
        return ApplyResult(
            ok=True,
            stage="预览（dry-run）",
            message=(
                f"共 {len(parsed.changes)} 个文件改动，未写入任何文件；"
                f"确认无误后执行：apply-draft {draft_path.stem} --apply"
            ),
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

    code, output = _run_isolated_tests(project_root, parsed.changes)
    if code != 0:
        return ApplyResult(
            ok=False,
            stage="隔离测试",
            message=f"隔离副本测试失败（退出码 {code}），正式源码未被写入。\n{output[-2000:]}",
            changes=parsed.changes,
            diffs=diffs,
        )

    backup = _apply_changes(project_root, parsed.changes)
    code, output = run_tests(project_root)
    if code != 0:
        _rollback_changes(project_root, backup)
        return ApplyResult(
            ok=False,
            stage="正式测试",
            message=f"正式工作区测试失败（退出码 {code}），已自动回滚改动。\n{output[-2000:]}",
            changes=parsed.changes,
            diffs=diffs,
        )

    committed, commit_msg = git_commit(project_root, f"apply-draft: {draft_path.stem}")
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

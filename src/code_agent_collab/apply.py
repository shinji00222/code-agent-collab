from __future__ import annotations

import difflib
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .file_utils import read_text, write_text

# apply-draft 允许写入的目录（相对项目根）；其他区域一律拒绝
ALLOWED_DIRS = ("src", "tests")
ALLOWED_SUFFIXES = (".py", ".md", ".toml", ".txt", ".json", ".ini", ".cfg", ".yaml", ".yml")

SECTION_FILES = "## 修改文件清单"
SECTION_REASON = "## 修改原因"
SECTION_CODE = "## 建议代码"
SECTION_TEST = "## 测试方法"
SECTION_RISK = "## 风险"

DRAFT_GLOB = "*-coder-draft*.md"


@dataclass(frozen=True)
class DraftChange:
    """草稿中一个文件的改动：相对项目根路径 + 完整新内容。"""

    path: str
    content: str


@dataclass(frozen=True)
class ParseResult:
    changes: list[DraftChange]
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


def parse_draft(content: str) -> ParseResult:
    """解析规范化的 Coder 草稿，提取各文件改动与说明小节。"""
    errors: list[str] = []
    files_section = _section(content, SECTION_FILES)
    if not files_section:
        errors.append(f"缺少小节 {SECTION_FILES}")
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
    return ParseResult(
        changes=changes,
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


def run_tests(project_root: Path) -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_root / "src")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return result.returncode, (result.stdout + result.stderr)


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

    backup = _apply_changes(project_root, parsed.changes)
    code, output = run_tests(project_root)
    if code != 0:
        _rollback_changes(project_root, backup)
        return ApplyResult(
            ok=False,
            stage="测试",
            message=f"测试失败（退出码 {code}），已自动回滚改动。\n{output[-2000:]}",
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

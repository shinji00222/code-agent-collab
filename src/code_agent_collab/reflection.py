from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import load_config
from .file_utils import ensure_dir, read_text, simple_task_slug, write_text


@dataclass(frozen=True)
class ReflectionResult:
    task_id: str
    source_path: Path
    output_path: Path


def _context_pack_dir(project_root: Path) -> Path:
    return project_root / "logs" / "context-packs"


def _pending_dir(project_root: Path) -> Path:
    return project_root / "dev-vault" / "pending"


def find_context_pack(project_root: Path, task: str | None = None) -> Path:
    context_dir = _context_pack_dir(project_root)
    if not context_dir.exists():
        raise FileNotFoundError(f"未找到上下文包目录：{context_dir}")

    if task:
        direct = context_dir / f"{task}.md"
        if direct.exists():
            return direct
        matches = sorted(context_dir.glob(f"*{task}*.md"), key=lambda item: item.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
        raise FileNotFoundError(f"未找到匹配任务的上下文包：{task}")

    matches = sorted(context_dir.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"上下文包目录为空：{context_dir}")
    return matches[0]


def _extract_task_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# 任务上下文包："):
            return line.removeprefix("# 任务上下文包：").strip() or fallback
    return fallback


def _render_reflection(
    task_id: str,
    source_path: Path,
    task_title: str,
    project_root: Path,
    now: datetime,
) -> str:
    cfg = load_config(project_root)
    return f"""# 候选复利记录：{task_title}

## 来源

- 任务ID：{task_id}
- 生成时间：{now:%Y-%m-%d %H:%M:%S}
- 来源上下文包：{source_path}
- 当前状态：待用户确认

## 候选内容

- 日期：{now:%Y-%m-%d}
- 场景：围绕任务“{task_title}”生成上下文包并准备后续协作。
- 问题或经验：知识库自生长不应直接写入主知识库，应先生成候选记录放入 dev-vault/pending。
- 原因：候选记录需要经过验证、去重、脱敏和用户确认，才能进入长期知识库。
- 以后采用的规则：自动生成的复盘内容默认进入项目测试知识库，主知识库保持只读。
- 验证方式：候选记录文件已写入 dev-vault/pending，未写入主知识库。
- 建议写入位置：{cfg.dev_vault_path}\\pending

## 检查项

- 是否已经验证：部分验证
- 是否包含敏感信息：否
- 是否建议写入主知识库：暂不建议，等待用户确认
- 主知识库写入状态：未写入

## 下一步

用户确认这条候选记录有长期价值后，再决定是否同步到主知识库对应位置。
"""


def create_reflection(project_root: Path, task: str | None = None) -> ReflectionResult:
    source_path = find_context_pack(project_root, task)
    task_id = source_path.stem
    content = read_text(source_path)
    task_title = _extract_task_title(content, fallback=task_id)
    now = datetime.now()
    output_name = f"{now:%Y-%m-%d}-{simple_task_slug(task_id, max_length=48)}-复利候选.md"
    output_path = _pending_dir(project_root) / output_name
    ensure_dir(output_path.parent)
    write_text(
        output_path,
        _render_reflection(
            task_id=task_id,
            source_path=source_path,
            task_title=task_title,
            project_root=project_root,
            now=now,
        ),
    )
    return ReflectionResult(task_id=task_id, source_path=source_path, output_path=output_path)

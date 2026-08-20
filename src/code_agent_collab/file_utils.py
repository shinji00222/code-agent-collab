from __future__ import annotations

import re
from pathlib import Path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8", newline="\n")


def simple_task_slug(text: str, max_length: int = 24) -> str:
    slug = re.sub(r"\s+", "-", text.strip())
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", slug)
    slug = slug.strip(".-")
    if not slug:
        return "task"
    return slug[:max_length]

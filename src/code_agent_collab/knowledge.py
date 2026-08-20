from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_FILES = 20
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_FILE_BYTES = 200_000
DEFAULT_EXCERPT_CHARS = 160

EXCLUDED_DIR_NAMES = {
    ".git",
    ".obsidian",
    ".claudian",
    ".trash",
    "99-附件",
    "work",
    "deepseek工作区",
    "01-项目",
}

STOPWORDS = {
    "一个",
    "这个",
    "那个",
    "什么",
    "怎么",
    "如何",
    "我们",
    "你们",
    "他们",
    "项目",
    "任务",
    "测试",
    "需要",
    "可以",
    "进行",
    "没有",
    "不是",
    "就是",
    "了",
    "的",
    "吗",
    "呢",
    "吧",
    "啊",
    "和",
    "与",
    "或",
    "在",
    "是",
    "有",
    "我",
    "你",
    "他",
    "她",
    "它",
    "请",
    "帮",
    "做",
    "写",
    "用",
    "把",
    "要",
    "给",
    "让",
    "这",
    "那",
}

_STOP_CHARS = set(
    "请帮我做写把要给让这那的了吗呢吧啊和与或在是有一下不没么怎如何你他她它"
)


@dataclass(frozen=True)
class KnowledgeHit:
    path: str
    keywords: tuple[str, ...]
    excerpt: str
    score: int


def _chinese_candidates(text: str) -> list[str]:
    if len(text) <= 4:
        candidates = [text]
    else:
        candidates = []
        for size in (2, 3, 4):
            candidates.extend(text[index : index + size] for index in range(len(text) - size + 1))
    result: list[str] = []
    for candidate in candidates:
        if candidate in STOPWORDS:
            continue
        if any(char in _STOP_CHARS for char in candidate):
            continue
        result.append(candidate)
    return result


def extract_keywords(goal: str, max_keywords: int = 8) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_.-]{1,40}|[\u4e00-\u9fff]+", goal):
        token = match.group(0)
        if token[0].isascii():
            cleaned = token.strip().strip("._-")
            if cleaned and cleaned.lower() not in STOPWORDS and not cleaned.isdigit():
                tokens.append(cleaned)
        else:
            tokens.extend(_chinese_candidates(token))
    keywords: list[str] = []
    for token in tokens:
        if token not in keywords:
            keywords.append(token)
    return keywords[:max_keywords]


def _iter_markdown(base_path: Path, max_depth: int):
    stack: list[tuple[Path, int]] = [(base_path, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name.startswith(".") or entry.name in EXCLUDED_DIR_NAMES:
                    continue
                stack.append((entry, depth + 1))
            elif entry.suffix.lower() == ".md":
                yield entry


def _make_excerpt(content: str, keywords: list[str], max_chars: int = DEFAULT_EXCERPT_CHARS) -> str:
    lowered = content.lower()
    positions = [lowered.find(keyword.lower()) for keyword in keywords]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return content[:max_chars]
    start = max(0, min(positions) - 40)
    end = min(len(content), start + max_chars)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return prefix + content[start:end].replace("\n", " ").strip() + suffix


def search_knowledge(
    base_path: Path,
    keywords: list[str],
    max_files: int = DEFAULT_MAX_FILES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[KnowledgeHit]:
    if not base_path.exists() or not base_path.is_dir() or not keywords:
        return []
    hits: list[KnowledgeHit] = []
    for path in _iter_markdown(base_path, max_depth):
        try:
            if path.stat().st_size > DEFAULT_MAX_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        matched = [
            keyword
            for keyword in keywords
            if keyword.lower() in (path.name + "\n" + content).lower()
        ]
        if not matched:
            continue
        hits.append(
            KnowledgeHit(
                path=str(path),
                keywords=tuple(matched),
                excerpt=_make_excerpt(content, matched),
                score=len(matched),
            )
        )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:max_files]


def render_knowledge_note(task_id: str, task_goal: str, hits: list[KnowledgeHit]) -> str:
    sections = []
    for index, hit in enumerate(hits, start=1):
        sections.append(
            "\n".join(
                [
                    f"### {index}. {Path(hit.path).name}",
                    f"- 路径：{hit.path}",
                    f"- 命中关键词：{', '.join(hit.keywords)}",
                    f"- 摘录：{hit.excerpt}",
                ]
            )
        )
    return "\n\n".join(
        [
            f"# 主知识库检索：{task_goal}",
            f"- 任务ID：{task_id}",
            "- 状态：只读检索，未写入主知识库。",
            "",
            f"共命中 {len(hits)} 个相关文档：",
            "",
            *sections,
        ]
    ) + "\n"

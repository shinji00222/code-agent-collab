from __future__ import annotations

from pathlib import Path


def extract_ai_draft_body(content: str) -> str:
    """Return the AI draft section body when a draft wrapper is present."""
    marker = "## AI 草稿"
    if marker not in content:
        return content
    body = content.split(marker, 1)[1]
    for boundary in ("\n## 安全边界", "\n## 输入草稿", "\n## Reviewer 反馈"):
        if boundary in body:
            body = body.split(boundary, 1)[0]
    return body


def mentions_main_vault_outside_project(
    content: str,
    vault: Path,
    project_root: Path,
) -> bool:
    vault_forms = path_forms(vault)
    project_forms = path_forms(project_root)
    for line in content.splitlines():
        normalized = line.lower()
        if any(vault_form in normalized for vault_form in vault_forms) and not any(
            project_form in normalized for project_form in project_forms
        ):
            return True
    return False


def path_forms(path: Path) -> tuple[str, str]:
    raw = str(path).lower()
    return raw, path.as_posix().lower()


def has_concrete_test_method(test_method: str) -> bool:
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


def has_unresolved_conflict_marker(content: str) -> bool:
    return any(marker in content for marker in ("<<<<<<<", "=======", ">>>>>>>"))

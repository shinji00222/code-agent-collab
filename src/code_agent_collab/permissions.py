"""运行时权限强制点（v0.17.13）。

背景（问题台账 N5 / N14）：`PermissionLevel` 以前只是**标注**——会写进日志和账本，
但运行时没有任何检查；`WorkbenchConfig.main_vault_default_mode` / `dev_vault_default_mode`
同样是装饰性的，只在配置读写时被用到，`src/` 其他位置零引用。

这个模块提供唯一的强制点：按**写入目标落在哪里**划分区域，每个区域有最低权限要求；
调用方必须显式声明自己当前的权限级别，级别不够就抛 `PermissionDenied`。

设计原则：

1. **叶子模块**：不 import 本项目任何其他模块，避免和 `agents` 包形成循环导入
   （`agents/base.py` 反向从这里取级别常量）。
2. **按目标区域判断，不按调用方身份判断**：同一段代码写到不同位置要求不同，
   所以判断依据始终是目标路径本身，而不是"谁在调用"。
3. **级别用字符串值比较**：`PermissionLevel` 是 `str` 枚举，传枚举或传字符串都可以。

区域与规则：

| 区域 | 落点 | 规则 |
| --- | --- | --- |
| `runtime` | 项目内 `logs/`、`.agent-workbench/`（运行时账本、进度、批准基线、本地配置） | 最低 `L0_READ_ONLY` |
| `draft` | 项目内 `dev-vault/`（草稿、候选、**本项目自己的知识库**） | 最低 `L1_DRAFT_WRITE` |
| `project-source` | 项目内其他位置（`src/`、`tests/`、`product-docs/`、根目录文档…） | 最低 `L2_PROJECT_WRITE` |
| `outside-project` | 项目目录之外的任何位置 | **一律拒绝**，与权限级别无关 |

两条边界说明（都是刻意的）：

1. **只写当前项目目录内，项目之外一律不写。** 这是硬边界：外部路径没有任何权限级别可以解锁。
   本项目自己的独立知识库就是项目内的 `dev-vault/project-vault`；程序不会去写项目之外的
   知识库或任何其他位置。
   需要让工具去改**别的代码库**时，正确做法是把「项目根」指到那个代码库
   （CLI `--project-root <目录>` 或环境变量 `AGENT_WORKBENCH_PROJECT_ROOT`）——
   那时那个代码库就是当前项目，写入都落在它自己里面，边界依然成立。
2. **`logs/` 允许在 `L0_READ_ONLY` 下写入**，因为它是系统自己的运行时账本，不属于用户内容。

注意：这里**没有**「临时目录例外」。`apply-draft --apply` 的隔离测试副本虽然建在系统临时目录，
但它的写入是以 `project_root=副本目录` 调用的，副本自身就是当时的项目根，所以不需要开口子。
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

READ_ONLY = "L0_READ_ONLY"
DRAFT_WRITE = "L1_DRAFT_WRITE"
PROJECT_WRITE = "L2_PROJECT_WRITE"
CONFIRM_REQUIRED = "L3_CONFIRM_REQUIRED"

#: 从低到高。顺序即等级，`allows()` 按索引比较。
LEVEL_ORDER = (READ_ONLY, DRAFT_WRITE, PROJECT_WRITE, CONFIRM_REQUIRED)


class PermissionDenied(PermissionError):
    """运行时权限强制点拒绝了这次写入或命令。"""


class WriteZone(str, Enum):
    RUNTIME = "runtime"
    DRAFT = "draft"
    PROJECT_SOURCE = "project-source"
    OUTSIDE = "outside-project"


ZONE_REQUIRED_LEVEL: dict[WriteZone, str] = {
    WriteZone.RUNTIME: READ_ONLY,
    WriteZone.DRAFT: DRAFT_WRITE,
    WriteZone.PROJECT_SOURCE: PROJECT_WRITE,
}

#: 硬边界：这些区域**一律拒绝**写入，任何权限级别都不能解锁。
#: 项目只写自己的目录，不写你电脑上项目之外的位置（包括项目外的知识库）。
DENIED_ZONES: frozenset[WriteZone] = frozenset({WriteZone.OUTSIDE})

#: 启动子进程（git、测试、CLI）所需的最低权限。
COMMAND_REQUIRED_LEVEL = PROJECT_WRITE

#: 项目内属于「运行时状态」而不是「用户内容」的顶层目录。
RUNTIME_TOP_DIRS = frozenset({"logs", ".agent-workbench"})

#: 项目内属于「草稿/候选/项目自有知识库」的顶层目录。
DRAFT_TOP_DIRS = frozenset({"dev-vault"})


def level_value(level: object) -> str:
    """把 `PermissionLevel` 枚举或字符串统一成级别字符串。"""
    value = getattr(level, "value", level)
    text = str(value)
    if text not in LEVEL_ORDER:
        raise ValueError(f"未知权限级别：{level!r}（可用：{', '.join(LEVEL_ORDER)}）")
    return text


def level_rank(level: object) -> int:
    return LEVEL_ORDER.index(level_value(level))


def allows(granted: object, required: object) -> bool:
    """`granted` 是否达到 `required`。"""
    return level_rank(granted) >= level_rank(required)


def _absolute(path: object) -> Path:
    """纯字符串归一化的绝对路径：不访问文件系统、不解析符号链接。

    用 `os.path.abspath` 而不是 `Path.absolute()`——前者会折叠 `..`，
    这样 `..` 穿越才会被判成「项目外」。
    """
    return Path(os.path.abspath(str(path)))


def _nearest_existing(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def _is_within(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def _escapes_via_link(target: Path, root: Path) -> bool:
    """目标的「最近存在祖先」解析后是否越出项目（防符号链接 / junction 逃逸）。

    **为什么只解析存在的祖先**：早先的实现直接对整条路径（含尚不存在的叶子）调
    `resolve()`，在 Windows 上这种解析结果会随「中间目录此刻是否已创建」而变——
    并行 worker 刚建好草稿目录时，同一个路径会一时被判成「项目外」，造成偶发误判
    （已在整包测试中复现：报「不在项目内」，但同一时刻 `relative_to` 实际成功）。
    只解析已存在的祖先既能稳定判断，又能挡住「项目内的软链接指向项目外」。
    """
    ancestor = _nearest_existing(target)
    if ancestor is None:
        return False
    try:
        resolved_ancestor = ancestor.resolve()
        resolved_root = root.resolve()
    except OSError:
        return False
    return not _is_within(resolved_ancestor, resolved_root)


def classify_path(path: object, project_root: object) -> WriteZone:
    """按落点判断写入区域。路径不存在也可以判断（不做存在性检查）。"""
    root = _absolute(project_root)
    target = _absolute(path)

    if not _is_within(target, root):
        return WriteZone.OUTSIDE
    if _escapes_via_link(target, root):
        return WriteZone.OUTSIDE

    relative = target.relative_to(root)
    top = relative.parts[0] if relative.parts else ""
    if top in RUNTIME_TOP_DIRS:
        return WriteZone.RUNTIME
    if top in DRAFT_TOP_DIRS:
        return WriteZone.DRAFT
    return WriteZone.PROJECT_SOURCE

    return WriteZone.OUTSIDE


def required_level_for_write(path: object, project_root: object) -> str | None:
    """返回该落点所需的最低权限；落到硬边界区域时返回 `None`（表示禁止写入）。"""
    zone = classify_path(path, project_root)
    return None if zone in DENIED_ZONES else ZONE_REQUIRED_LEVEL[zone]


def check_write(
    permission: object,
    path: object,
    project_root: object,
    *,
    action: str,
) -> WriteZone:
    """写入前的强制检查。通过则返回区域，不通过抛 `PermissionDenied`。

    先判硬边界，再判权限级别：项目之外的路径没有任何级别可以解锁。
    """
    zone = classify_path(path, project_root)
    if zone in DENIED_ZONES:
        raise PermissionDenied(
            f"拒绝写入项目目录之外的路径：{action} 的目标 {path} 不在项目内。"
            f"本项目只写自己的目录（自己的知识库是项目内的 dev-vault/project-vault），"
            f"任何权限级别都不能解锁项目外的写入。项目根：{project_root}"
        )
    required = ZONE_REQUIRED_LEVEL[zone]
    if not allows(permission, required):
        raise PermissionDenied(
            f"权限不足：{action} 需要至少 {required}，当前只有 {level_value(permission)}；"
            f"目标落在 {zone.value} 区域：{path}"
        )
    return zone


def ensure_inside_project(path: object, project_root: object, *, action: str) -> Path:
    """确认路径落在项目内（不接受项目外与临时目录），返回解析后的路径。

    用于「把一批路径交给外部命令处理」的场景，例如 `git add -- <paths>`：
    这类操作不写文件，但可以被指向项目之外，所以单独做一个原语。
    """
    target = _absolute(path)
    root = _absolute(project_root)
    if _is_within(target, root) and not _escapes_via_link(target, root):
        return target
    raise PermissionDenied(f"权限不足：{action} 的路径必须落在项目内，实际为 {path}")


def check_command(
    permission: object,
    argv: list[str] | tuple[str, ...],
    *,
    action: str,
    cwd: object | None = None,
    project_root: object | None = None,
) -> None:
    """启动子进程前的强制检查。

    工作目录必须落在**项目内**，避免命令被引到项目之外执行。
    """
    if not allows(permission, COMMAND_REQUIRED_LEVEL):
        raise PermissionDenied(
            f"权限不足：{action} 需要至少 {COMMAND_REQUIRED_LEVEL}，"
            f"当前只有 {level_value(permission)}；命令：{list(argv)}"
        )
    if cwd is None or project_root is None:
        return
    resolved_cwd = _absolute(cwd)
    resolved_root = _absolute(project_root)
    if _is_within(resolved_cwd, resolved_root) and not _escapes_via_link(
        resolved_cwd, resolved_root
    ):
        return
    raise PermissionDenied(
        f"权限不足：{action} 的工作目录必须落在项目内，"
        f"实际为 {cwd}（项目根：{project_root}）"
    )

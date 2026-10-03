from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT_ENV = "AGENT_WORKBENCH_PROJECT_ROOT"
LOCAL_WORKBENCH_ROOT = (
    Path.home()
    / "Desktop"
    / "AI工作台知识库"
    / "01-项目"
    / "project 多Agent代码协作助手"
)


def _is_project_root(path: Path) -> bool:
    return (
        (path / "pyproject.toml").exists()
        and (path / "src" / "code_agent_collab").exists()
    )


def resolve_project_root(
    *,
    executable_path: Path | None = None,
    module_file: Path | None = None,
    frozen: bool | None = None,
) -> Path:
    configured = os.getenv(PROJECT_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    if not frozen:
        source_file = module_file or Path(__file__)
        return source_file.resolve().parent.parent.parent

    exe_dir = (executable_path or Path(sys.executable)).resolve().parent
    for candidate in (exe_dir, *exe_dir.parents):
        if _is_project_root(candidate):
            return candidate

    if _is_project_root(LOCAL_WORKBENCH_ROOT):
        return LOCAL_WORKBENCH_ROOT.resolve()

    return exe_dir

# 打包（PyInstaller）模式下没有 __file__，项目根目录需回到正式仓库；
# 开发模式下是仓库根目录（src/code_agent_collab/webui.py 向上三级）。
if getattr(sys, "frozen", False):
    PROJECT_ROOT = resolve_project_root(frozen=True)
    SRC_DIR = PROJECT_ROOT
else:
    PROJECT_ROOT = resolve_project_root(frozen=False)
    SRC_DIR = PROJECT_ROOT / "src"

# 打包模式下 run_cli 调用的同目录 CLI 可执行程序名
CLI_EXE_NAME = "AgentWorkbench-CLI.exe"

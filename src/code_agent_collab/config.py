from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

from .file_utils import write_text


CONFIG_DIR = ".agent-workbench"
CONFIG_FILE = "config.json"

MAIN_VAULT_ENV = "AGENT_WORKBENCH_MAIN_VAULT"
MAIN_VAULT_WRITE_ENV = "AGENT_WORKBENCH_MAIN_VAULT_WRITE"

# 项目自有知识库目录名（位于 dev-vault 下）。
# 读取和写入默认都在这里，与用户电脑上的真实知识库完全隔离。
PROJECT_VAULT_DIR_NAME = "project-vault"


@dataclass(frozen=True)
class WorkbenchConfig:
    project_name: str
    main_vault_path: str
    dev_vault_path: str
    main_vault_default_mode: str = "readonly"
    dev_vault_default_mode: str = "readwrite"
    # 知识写入位置；默认与 main_vault_path 一起指向项目自有知识库
    main_vault_write_path: str = ""


def default_vault_path(project_root: Path) -> str:
    """项目自有知识库：读写都在项目内，默认不碰外部知识库。"""
    return str(project_root / "dev-vault" / PROJECT_VAULT_DIR_NAME)


def default_config(project_root: Path) -> WorkbenchConfig:
    vault = default_vault_path(project_root)
    return WorkbenchConfig(
        project_name=project_root.name.removeprefix("project "),
        main_vault_path=vault,
        dev_vault_path=str(project_root / "dev-vault"),
        main_vault_write_path=vault,
    )


def config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / CONFIG_FILE


def load_config(project_root: Path) -> WorkbenchConfig:
    path = config_path(project_root)
    vault = default_vault_path(project_root)
    if not path.exists():
        cfg = default_config(project_root)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg = WorkbenchConfig(
            project_name=data["projectName"],
            # 读和写都用「缺键即回退项目自有知识库」的安全默认，
            # 不会因为配置里没写就退化成读写用户电脑上的真实知识库。
            main_vault_path=data.get("mainVaultPath") or vault,
            dev_vault_path=data["devVaultPath"],
            main_vault_default_mode=data.get("mainVaultDefaultMode", "readonly"),
            dev_vault_default_mode=data.get("devVaultDefaultMode", "readwrite"),
            main_vault_write_path=data.get("mainVaultWritePath") or vault,
        )
    env_main_vault = os.getenv(MAIN_VAULT_ENV)
    if env_main_vault:
        cfg = replace(cfg, main_vault_path=env_main_vault)
    env_main_vault_write = os.getenv(MAIN_VAULT_WRITE_ENV)
    if env_main_vault_write:
        cfg = replace(cfg, main_vault_write_path=env_main_vault_write)
    return cfg


def save_default_config(project_root: Path) -> Path:
    cfg = default_config(project_root)
    path = config_path(project_root)
    payload = {
        "projectName": cfg.project_name,
        "mainVaultPath": cfg.main_vault_path,
        "devVaultPath": cfg.dev_vault_path,
        "mainVaultDefaultMode": cfg.main_vault_default_mode,
        "devVaultDefaultMode": cfg.dev_vault_default_mode,
        "mainVaultWritePath": cfg.main_vault_write_path,
    }
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path

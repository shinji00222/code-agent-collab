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

# 知识写入沙箱目录名（位于 dev-vault 下，属于项目自己的目录）
SANDBOX_DIR_NAME = "main-vault-sandbox"


@dataclass(frozen=True)
class WorkbenchConfig:
    project_name: str
    main_vault_path: str
    dev_vault_path: str
    main_vault_default_mode: str = "readonly"
    dev_vault_default_mode: str = "readwrite"
    # 知识真正写入的位置；默认是项目内沙箱，与真实主知识库分离
    main_vault_write_path: str = ""


def default_write_vault_path(project_root: Path) -> str:
    """默认写入沙箱：项目自己的目录，保证"确认入库"不会写进真实主知识库。"""
    return str(project_root / "dev-vault" / SANDBOX_DIR_NAME)


def default_config(project_root: Path) -> WorkbenchConfig:
    if project_root.parent.name == "01-项目":
        main_vault_path = str(project_root.parent.parent)
    else:
        main_vault_path = str(project_root.parent)

    return WorkbenchConfig(
        project_name=project_root.name.removeprefix("project "),
        main_vault_path=main_vault_path,
        dev_vault_path=str(project_root / "dev-vault"),
        main_vault_write_path=default_write_vault_path(project_root),
    )


def config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / CONFIG_FILE


def load_config(project_root: Path) -> WorkbenchConfig:
    path = config_path(project_root)
    if not path.exists():
        cfg = default_config(project_root)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg = WorkbenchConfig(
            project_name=data["projectName"],
            main_vault_path=data["mainVaultPath"],
            dev_vault_path=data["devVaultPath"],
            main_vault_default_mode=data.get("mainVaultDefaultMode", "readonly"),
            dev_vault_default_mode=data.get("devVaultDefaultMode", "readwrite"),
            # 旧配置文件没有这个键时，安全默认仍然是项目内沙箱，
            # 不会退化成"直接写真实主知识库"。
            main_vault_write_path=(
                data.get("mainVaultWritePath") or default_write_vault_path(project_root)
            ),
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

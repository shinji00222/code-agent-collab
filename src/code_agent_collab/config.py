from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .file_utils import write_text


CONFIG_DIR = ".agent-workbench"
CONFIG_FILE = "config.json"


@dataclass(frozen=True)
class WorkbenchConfig:
    project_name: str
    main_vault_path: str
    dev_vault_path: str
    main_vault_default_mode: str = "readonly"
    dev_vault_default_mode: str = "readwrite"


def default_config(project_root: Path) -> WorkbenchConfig:
    return WorkbenchConfig(
        project_name=project_root.name.removeprefix("project "),
        main_vault_path=r"C:\Users\lwz12\Desktop\AI工作台知识库",
        dev_vault_path=str(project_root / "dev-vault"),
    )


def config_path(project_root: Path) -> Path:
    return project_root / CONFIG_DIR / CONFIG_FILE


def load_config(project_root: Path) -> WorkbenchConfig:
    path = config_path(project_root)
    if not path.exists():
        return default_config(project_root)

    data = json.loads(path.read_text(encoding="utf-8"))
    return WorkbenchConfig(
        project_name=data["projectName"],
        main_vault_path=data["mainVaultPath"],
        dev_vault_path=data["devVaultPath"],
        main_vault_default_mode=data.get("mainVaultDefaultMode", "readonly"),
        dev_vault_default_mode=data.get("devVaultDefaultMode", "readwrite"),
    )


def save_default_config(project_root: Path) -> Path:
    cfg = default_config(project_root)
    path = config_path(project_root)
    payload = {
        "projectName": cfg.project_name,
        "mainVaultPath": cfg.main_vault_path,
        "devVaultPath": cfg.dev_vault_path,
        "mainVaultDefaultMode": cfg.main_vault_default_mode,
        "devVaultDefaultMode": cfg.dev_vault_default_mode,
    }
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path

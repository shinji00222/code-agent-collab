from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.config import (
    MAIN_VAULT_WRITE_ENV,
    default_write_vault_path,
    load_config,
    save_default_config,
)


class ConfigTests(unittest.TestCase):
    def test_env_var_overrides_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            config_dir = project_root / ".agent-workbench"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps(
                    {
                        "projectName": "demo",
                        "mainVaultPath": r"C:\old\vault",
                        "devVaultPath": r"C:\old\dev-vault",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"AGENT_WORKBENCH_MAIN_VAULT": r"D:\new\vault"}, clear=False):
                cfg = load_config(project_root)
            self.assertEqual(cfg.main_vault_path, r"D:\new\vault")
            self.assertEqual(cfg.dev_vault_path, r"C:\old\dev-vault")

    def test_env_var_applies_without_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            with patch.dict(os.environ, {"AGENT_WORKBENCH_MAIN_VAULT": r"D:\vault"}, clear=False):
                cfg = load_config(project_root)
            self.assertEqual(cfg.main_vault_path, r"D:\vault")

    def test_save_default_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            save_default_config(project_root)
            cfg = load_config(project_root)
            self.assertTrue(cfg.main_vault_path)
            self.assertTrue(cfg.dev_vault_path)

    def test_write_vault_defaults_to_project_sandbox(self) -> None:
        """没有配置文件时，写入目标必须是项目内沙箱，不是上层的主知识库。"""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "01-项目" / "project demo"
            project_root.mkdir(parents=True)
            cfg = load_config(project_root)
            self.assertEqual(cfg.main_vault_path, str(project_root.parent.parent))
            self.assertEqual(Path(cfg.main_vault_write_path), Path(default_write_vault_path(project_root)))
            self.assertNotEqual(Path(cfg.main_vault_write_path), Path(cfg.main_vault_path))
            self.assertEqual(Path(cfg.main_vault_write_path).parent, project_root / "dev-vault")

    def test_old_config_without_write_key_still_uses_sandbox(self) -> None:
        """旧配置文件没有 mainVaultWritePath 时，不能退化成直接写真实主知识库。"""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project demo"
            project_root.mkdir()
            config_dir = project_root / ".agent-workbench"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps(
                    {
                        "projectName": "demo",
                        "mainVaultPath": r"C:\real\vault",
                        "devVaultPath": str(project_root / "dev-vault"),
                    }
                ),
                encoding="utf-8",
            )
            cfg = load_config(project_root)
            self.assertEqual(cfg.main_vault_path, r"C:\real\vault")
            self.assertEqual(
                Path(cfg.main_vault_write_path),
                Path(default_write_vault_path(project_root)),
            )

    def test_write_vault_env_var_overrides_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project demo"
            project_root.mkdir()
            config_dir = project_root / ".agent-workbench"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps(
                    {
                        "projectName": "demo",
                        "mainVaultPath": r"C:\real\vault",
                        "devVaultPath": str(project_root / "dev-vault"),
                        "mainVaultWritePath": r"C:\real\vault",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {MAIN_VAULT_WRITE_ENV: r"D:\sandbox"}, clear=False):
                cfg = load_config(project_root)
            self.assertEqual(cfg.main_vault_path, r"C:\real\vault")
            self.assertEqual(cfg.main_vault_write_path, r"D:\sandbox")


if __name__ == "__main__":
    unittest.main()

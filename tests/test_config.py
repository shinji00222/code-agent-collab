from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.config import (
    MAIN_VAULT_WRITE_ENV,
    default_vault_path,
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

    def test_defaults_are_project_local_vault(self) -> None:
        """没有配置文件时，读和写都必须落在项目自有知识库，不能指向项目外的目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "01-项目" / "project demo"
            project_root.mkdir(parents=True)
            cfg = load_config(project_root)
            vault = Path(default_vault_path(project_root))
            self.assertEqual(Path(cfg.main_vault_path), vault)
            self.assertEqual(Path(cfg.main_vault_write_path), vault)
            self.assertEqual(vault.parent, project_root / "dev-vault")
            self.assertEqual(vault.name, "project-vault")
            # 关键断言：默认不再指向项目目录之外（旧行为是上层的知识库根目录）
            self.assertNotEqual(Path(cfg.main_vault_path), project_root.parent.parent)
            self.assertIn(project_root, vault.parents)

    def test_config_without_main_vault_key_falls_back_to_project_vault(self) -> None:
        """配置里缺 mainVaultPath 时，读取也不能退化成读项目外的知识库。"""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project demo"
            project_root.mkdir()
            config_dir = project_root / ".agent-workbench"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps(
                    {
                        "projectName": "demo",
                        "devVaultPath": str(project_root / "dev-vault"),
                    }
                ),
                encoding="utf-8",
            )
            cfg = load_config(project_root)
            vault = Path(default_vault_path(project_root))
            self.assertEqual(Path(cfg.main_vault_path), vault)
            self.assertEqual(Path(cfg.main_vault_write_path), vault)

    def test_old_config_without_write_key_still_uses_project_vault(self) -> None:
        """旧配置文件没有 mainVaultWritePath 时，不能退化成直接写配置里的真实知识库。"""
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
            # 显式配置的读取路径仍然生效（用户要接真实知识库时就是这个入口）
            self.assertEqual(cfg.main_vault_path, r"C:\real\vault")
            self.assertEqual(
                Path(cfg.main_vault_write_path),
                Path(default_vault_path(project_root)),
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

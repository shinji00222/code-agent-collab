from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.config import load_config, save_default_config


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


if __name__ == "__main__":
    unittest.main()

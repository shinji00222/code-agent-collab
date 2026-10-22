from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import runtime_hook_pythonnet_path as hook
from runtime_hook_pythonnet_path import _writable_cache_root


class WritableCacheRootTests(unittest.TestCase):
    def test_resolves_existing_base_before_appending_cache_subdirectories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            unicode_root = Path(temp_dir) / "本地目录"
            ascii_root = Path(temp_dir) / "local"
            unicode_root.mkdir()
            ascii_root.mkdir()
            temp_root = Path(temp_dir) / "temp"

            def short_path_for_existing_base(value):
                if value == str(unicode_root):
                    return ascii_root
                return Path(value)

            with patch.dict(os.environ, {"LOCALAPPDATA": str(unicode_root)}):
                with patch("runtime_hook_pythonnet_path.tempfile.gettempdir", return_value=str(temp_root)):
                    with patch("runtime_hook_pythonnet_path._ascii_existing_path", side_effect=short_path_for_existing_base):
                        cache_root = _writable_cache_root("pythonnet")
                        self.assertEqual(cache_root, ascii_root / "CodeAgentCollab" / "pythonnet")
                        self.assertTrue(cache_root.is_dir())

    def test_prefers_local_app_data_when_writable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "local"
            temp_root = Path(temp_dir) / "temp"
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                with patch("runtime_hook_pythonnet_path.tempfile.gettempdir", return_value=str(temp_root)):
                    cache_root = _writable_cache_root("pythonnet")
                    self.assertEqual(cache_root, local_app_data / "CodeAgentCollab" / "pythonnet")
                    self.assertTrue(cache_root.is_dir())

    def test_falls_back_to_temp_when_local_app_data_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "local"
            temp_root = Path(temp_dir) / "temp"
            denied = local_app_data / "CodeAgentCollab" / "webview"
            original_mkdir = Path.mkdir

            def mkdir_with_local_denial(path, *args, **kwargs):
                if path == denied:
                    raise PermissionError("access denied")
                return original_mkdir(path, *args, **kwargs)

            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                with patch("runtime_hook_pythonnet_path.tempfile.gettempdir", return_value=str(temp_root)):
                    with patch.object(Path, "mkdir", mkdir_with_local_denial):
                        cache_root = _writable_cache_root("webview")
                        self.assertEqual(cache_root, temp_root / "CodeAgentCollab" / "webview")
                        self.assertTrue(cache_root.is_dir())

    def test_falls_back_to_bundle_when_local_app_data_and_temp_are_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "local"
            temp_root = Path(temp_dir) / "temp"
            bundle_root = Path(temp_dir) / "bundle"
            denied = {
                local_app_data / "CodeAgentCollab" / "pythonnet",
                temp_root / "CodeAgentCollab" / "pythonnet",
            }
            original_mkdir = Path.mkdir

            def mkdir_with_denials(path, *args, **kwargs):
                if path in denied:
                    raise PermissionError("access denied")
                return original_mkdir(path, *args, **kwargs)

            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                with patch("runtime_hook_pythonnet_path.tempfile.gettempdir", return_value=str(temp_root)):
                    with patch.object(sys, "_MEIPASS", str(bundle_root), create=True):
                        with patch.object(Path, "mkdir", mkdir_with_denials):
                            cache_root = _writable_cache_root("pythonnet")
                            self.assertEqual(cache_root, bundle_root / "runtime-cache" / "pythonnet")
                            self.assertTrue(cache_root.is_dir())

    def test_pythonnet_staging_uses_fallback_after_local_app_data_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_app_data = root / "local"
            temp_root = root / "temp"
            source = root / "source" / "pythonnet"
            (source / "runtime").mkdir(parents=True)
            (source / "runtime" / "Python.Runtime.dll").write_bytes(b"fixture")
            (source / "__init__.py").write_text("", encoding="utf-8")
            denied = local_app_data / "CodeAgentCollab" / "pythonnet"
            original_mkdir = Path.mkdir

            def mkdir_with_local_denial(path, *args, **kwargs):
                if path == denied:
                    raise PermissionError("access denied")
                return original_mkdir(path, *args, **kwargs)

            fake_pythonnet = types.ModuleType("pythonnet")
            fake_pythonnet.__file__ = str(source / "__init__.py")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                with patch("runtime_hook_pythonnet_path.tempfile.gettempdir", return_value=str(temp_root)):
                    with patch.object(sys, "frozen", True, create=True):
                        with patch.dict(sys.modules, {"pythonnet": fake_pythonnet}):
                            with patch.object(Path, "mkdir", mkdir_with_local_denial):
                                hook._stage_pythonnet()

            staged_package = Path(fake_pythonnet.__file__).parent
            self.assertEqual(staged_package.parent, temp_root / "CodeAgentCollab" / "pythonnet")
            self.assertTrue((staged_package / "runtime" / "Python.Runtime.dll").is_file())

    def test_webview_staging_creates_digest_parent_in_selected_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_app_data = root / "local"
            source_lib = root / "source" / "webview" / "lib"
            source_lib.mkdir(parents=True)
            (source_lib / "WebBrowserInterop.x64.dll").write_bytes(b"fixture")
            fake_webview = types.ModuleType("webview")
            fake_webview.__path__ = []
            fake_util = types.ModuleType("webview.util")
            fake_util.__file__ = str(source_lib.parent / "util.py")
            fake_util.interop_dll_path = lambda name: str(source_lib / name)
            fake_webview.util = fake_util

            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}):
                with patch.object(sys, "frozen", True, create=True):
                    with patch.dict(sys.modules, {"webview": fake_webview, "webview.util": fake_util}):
                        hook._stage_webview_interop()

            staged = Path(fake_util.interop_dll_path("WebBrowserInterop.dll"))
            self.assertEqual(staged.name, "WebBrowserInterop.x64.dll")
            self.assertTrue(staged.is_file())

    def test_reports_error_when_no_cache_location_is_writable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"LOCALAPPDATA": str(Path(temp_dir) / "local")}):
                with patch("runtime_hook_pythonnet_path.tempfile.gettempdir", return_value=str(Path(temp_dir) / "temp")):
                    with patch.object(sys, "_MEIPASS", str(Path(temp_dir) / "bundle"), create=True):
                        with patch.object(Path, "mkdir", side_effect=PermissionError("access denied")):
                            with self.assertRaisesRegex(OSError, "Unable to create a writable ASCII runtime cache"):
                                _writable_cache_root("pythonnet")


if __name__ == "__main__":
    unittest.main()

"""Stage frozen .NET and pywebview interop libraries under an ASCII path."""

from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _ascii_existing_path(path: str) -> Path:
    """Return an ASCII DOS path when a Windows profile path contains Unicode."""
    candidate = Path(path)
    value = str(candidate)
    if value.isascii():
        return candidate
    if os.name != "nt":
        raise RuntimeError("Python.NET runtime staging requires an ASCII path")

    get_short_path = ctypes.windll.kernel32.GetShortPathNameW
    get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    get_short_path.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_short_path(value, buffer, len(buffer))
    short_value = buffer.value if length else ""
    if short_value and short_value.isascii():
        return Path(short_value)
    raise RuntimeError(
        "Python.NET cannot load from a Unicode path on this Windows setup. "
        "Enable short file names or use an ASCII Windows profile path."
    )


def _writable_cache_root(component: str) -> Path:
    """Choose a writable ASCII cache location, falling back to temp or the bundle."""
    candidates: list[Path] = []
    errors: list[str] = []

    def add_candidate(base: str, *parts: str) -> None:
        try:
            ascii_base = _ascii_existing_path(base)
            candidates.append(ascii_base.joinpath(*parts))
        except (OSError, RuntimeError) as exc:
            errors.append(f"{base}: {exc}")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        add_candidate(local_app_data, "CodeAgentCollab", component)

    temp_root = tempfile.gettempdir()
    if temp_root:
        add_candidate(temp_root, "CodeAgentCollab", component)

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        add_candidate(bundle_root, "runtime-cache", component)

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")

    detail = "; ".join(errors) if errors else "no cache locations are available"
    raise OSError(f"Unable to create a writable ASCII runtime cache: {detail}")


def _stage_pythonnet() -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return

    import pythonnet

    source = Path(pythonnet.__file__).parent
    source_runtime = source / "runtime"
    source_loader = source_runtime / "Python.Runtime.dll"
    if not source_loader.is_file():
        raise FileNotFoundError(f"Python.NET runtime assembly missing: {source_loader}")

    cache_root = _writable_cache_root("pythonnet")
    fingerprint = hashlib.sha256(source_loader.read_bytes()).hexdigest()[:16]
    staged_package = cache_root / fingerprint
    staged_loader = staged_package / "runtime" / "Python.Runtime.dll"

    if not staged_loader.is_file():
        staging_root = Path(tempfile.mkdtemp(prefix=".stage-", dir=cache_root))
        try:
            candidate = staging_root / "pythonnet"
            shutil.copytree(source, candidate)
            try:
                os.rename(candidate, staged_package)
            except FileExistsError:
                # Another app instance completed the same version while we copied.
                if not staged_loader.is_file():
                    raise
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    if not staged_loader.is_file():
        raise FileNotFoundError(f"Python.NET runtime staging failed: {staged_loader}")

    # pythonnet.load() resolves Python.Runtime.dll relative to __file__.
    # Keep Python imports on the bundled package path; only redirect that DLL path.
    pythonnet.__file__ = str(staged_package / "__init__.py")


def _stage_webview_interop() -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return

    import webview.util

    source_lib = Path(webview.util.__file__).parent / "lib"
    if not source_lib.is_dir():
        raise FileNotFoundError(f"pywebview interop libraries missing: {source_lib}")

    cache_root = _writable_cache_root("webview")
    digest = hashlib.sha256()
    files = sorted(path for path in source_lib.rglob("*") if path.is_file())
    for path in files:
        digest.update(path.relative_to(source_lib).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    staged_lib = cache_root / digest.hexdigest()[:16] / "lib"

    if not staged_lib.is_dir():
        staged_lib.parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(tempfile.mkdtemp(prefix=".stage-", dir=staged_lib.parent))
        try:
            candidate = staging_root / "lib"
            shutil.copytree(source_lib, candidate)
            try:
                os.rename(candidate, staged_lib)
            except FileExistsError:
                # Another app instance completed the same version while we copied.
                if not staged_lib.is_dir():
                    raise
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    if not staged_lib.is_dir():
        raise FileNotFoundError(f"pywebview interop staging failed: {staged_lib}")

    original_path = webview.util.interop_dll_path

    def interop_dll_path(dll_name: str) -> str:
        if dll_name == "WebBrowserInterop.dll":
            import struct

            dll_name = (
                "WebBrowserInterop.x64.dll"
                if struct.calcsize("P") == 8
                else "WebBrowserInterop.x86.dll"
            )
        candidate = staged_lib / dll_name
        if candidate.is_file():
            return str(candidate)
        native_candidates = sorted(staged_lib.glob(f"runtimes/*/native/{dll_name}"))
        if native_candidates:
            return str(native_candidates[0])
        return original_path(dll_name)

    webview.util.interop_dll_path = interop_dll_path


_stage_pythonnet()
_stage_webview_interop()

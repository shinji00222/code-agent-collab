"""Stage Python.NET assemblies under an ASCII path before pywebview imports clr."""

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


def _stage_pythonnet() -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return

    import pythonnet

    source = Path(pythonnet.__file__).parent
    source_runtime = source / "runtime"
    source_loader = source_runtime / "Python.Runtime.dll"
    if not source_loader.is_file():
        raise FileNotFoundError(f"Python.NET runtime assembly missing: {source_loader}")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = tempfile.gettempdir()
    cache_root = _ascii_existing_path(local_app_data) / "CodeAgentCollab" / "pythonnet"
    fingerprint = hashlib.sha256(source_loader.read_bytes()).hexdigest()[:16]
    staged_package = cache_root / fingerprint
    staged_loader = staged_package / "runtime" / "Python.Runtime.dll"

    if not staged_loader.is_file():
        cache_root.mkdir(parents=True, exist_ok=True)
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


_stage_pythonnet()

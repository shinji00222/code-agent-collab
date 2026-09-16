"""跨环境通用的测试入口。

直接 `python -m unittest discover -s tests` 在两种环境下会失败，不是因为代码有问题：

1. **DSH/受限 Windows 沙箱**：`os.mkdir(path, 0o700)` 建出的目录，当前进程再往里
   写会报 `PermissionError: [WinError 5]`；而 `tempfile.mkdtemp()` 正是用 0o700，
   于是所有用 `TemporaryDirectory()` 的用例在 setup 阶段就崩。本脚本在建目录后
   统一放宽到 0o777 规避。
2. **本机用户级环境变量** `AGENT_WORKBENCH_PROVIDER` 可能指向真实 Provider
   （如 deepseek），会让用例走到真实网络路径。本脚本默认强制为 `mock`。

用法：
    python scripts/run-tests.py                     # 全量
    python scripts/run-tests.py test_mcp_client     # 只跑匹配的用例
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _patch_tempdir_for_sandbox() -> None:
    """把 tempfile.mkdtemp 换成用 0o777 建目录的版本（沙箱下 0o700 会拒绝写入）。"""

    def mkdtemp_wide_open(suffix=None, prefix=None, dir=None):
        base = dir or tempfile.gettempdir()
        suffix = suffix or ""
        prefix = tempfile.template if prefix is None else prefix
        names = tempfile._get_candidate_names()
        for _ in range(tempfile.TMP_MAX):
            path = os.path.join(base, prefix + next(names) + suffix)
            try:
                os.mkdir(path, 0o777)
            except FileExistsError:
                continue
            return path
        raise FileExistsError(f"无法在 {base} 创建临时目录")

    tempfile.mkdtemp = mkdtemp_wide_open


def main(argv: list[str]) -> int:
    _patch_tempdir_for_sandbox()

    src = str(PROJECT_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    # 除非显式指定，一律用 mock Provider，避免测试打真实模型接口。
    os.environ["AGENT_WORKBENCH_PROVIDER"] = os.getenv("AGENT_WORKBENCH_TEST_PROVIDER", "mock")

    tests_dir = str(PROJECT_ROOT / "tests")
    loader = unittest.TestLoader()
    if argv:
        suite = unittest.TestSuite(
            loader.loadTestsFromName(name) for name in argv
        )
    else:
        suite = loader.discover(start_dir=tests_dir, top_level_dir=tests_dir)

    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

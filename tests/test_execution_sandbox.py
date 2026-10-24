from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent_collab.execution_sandbox import (
    OUTPUT_TRUNCATION_MARKER,
    TrialWorkspace,
    _TailBuffer,
    run_bounded,
    scrubbed_env,
)


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class TailBufferTests(unittest.TestCase):
    def test_keeps_only_last_bytes(self) -> None:
        buffer = _TailBuffer(10)
        for _ in range(100):
            buffer.feed(b"0123456789abcdef")
        self.assertEqual(len(buffer.data), 10)
        self.assertTrue(buffer.truncated)
        self.assertEqual(buffer.text(), "6789abcdef")

    def test_drops_partial_utf8_prefix_after_truncation(self) -> None:
        buffer = _TailBuffer(5)
        buffer.feed("汉汉".encode("utf-8"))  # 6 字节，截断后开头是半个字符
        self.assertEqual(buffer.text(), "汉")


class RunBoundedTests(unittest.TestCase):
    def test_merges_stdout_and_stderr(self) -> None:
        result = run_bounded(
            _python("import sys; print('out', flush=True); sys.stderr.write('err')"),
            cwd=Path.cwd(),
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.timed_out)
        self.assertIn("out", result.output)
        self.assertIn("err", result.output)

    def test_large_output_is_bounded_in_memory_and_result(self) -> None:
        max_bytes = 4 * 1024
        fed: list[int] = []
        original_feed = _TailBuffer.feed

        def tracking_feed(self: _TailBuffer, chunk: bytes) -> None:
            original_feed(self, chunk)
            fed.append(len(self.data))

        code = "import sys\nfor _ in range(512): sys.stdout.write('x' * 8192)\nsys.stdout.write('END')"
        with patch.object(_TailBuffer, "feed", tracking_feed):
            result = run_bounded(_python(code), cwd=Path.cwd(), timeout=60, max_bytes=max_bytes)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.truncated)
        self.assertTrue(fed)
        self.assertLessEqual(max(fed), max_bytes)
        self.assertLessEqual(len(result.output.encode("utf-8")), max_bytes)
        self.assertTrue(result.output.startswith(OUTPUT_TRUNCATION_MARKER))
        self.assertTrue(result.output.endswith("END"))

    def test_timeout_kills_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "child.pid"
            # 父进程拉起一个孙进程，两者都会一直睡；超时后整棵树都应结束
            code = (
                "import subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
                "print('ready', flush=True)\n"
                "time.sleep(60)\n"
            )
            started = time.monotonic()
            result = run_bounded(_python(code), cwd=tmp, timeout=3)
            elapsed = time.monotonic() - started

            self.assertTrue(result.timed_out)
            self.assertLess(elapsed, 30)
            self.assertIn("ready", result.output)
            child_pid = int(pid_file.read_text())
            self.assertFalse(_pid_alive(child_pid), "孙进程在超时后仍在运行")

    def test_registers_and_releases_active_process(self) -> None:
        active: set[subprocess.Popen] = set()
        seen: list[int] = []
        original_popen = subprocess.Popen

        def recording_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            process = original_popen(*args, **kwargs)
            seen.append(process.pid)
            return process

        with patch.object(subprocess, "Popen", side_effect=recording_popen):
            run_bounded(_python("print(1)"), cwd=Path.cwd(), timeout=30, active=active)
        self.assertEqual(len(seen), 1)
        self.assertEqual(active, set())

    def test_rejects_non_positive_limit(self) -> None:
        with self.assertRaises(ValueError):
            run_bounded(_python("print(1)"), cwd=Path.cwd(), timeout=5, max_bytes=0)


class ScrubbedEnvTests(unittest.TestCase):
    def test_removes_sensitive_keys_and_values(self) -> None:
        env = scrubbed_env(
            {"EXTRA": "1"},
            drop=("DROP_ME",),
            base={
                "PATH": "p",
                "MY_API_KEY": "x",
                "GITHUB_TOKEN": "x",
                "HARMLESS": "sk-abcdefghijklmnop",
                "DROP_ME": "1",
            },
        )
        self.assertEqual(env, {"PATH": "p", "EXTRA": "1"})

    def test_defaults_to_process_environment(self) -> None:
        with patch.dict(os.environ, {"SANDBOX_TEST_SECRET": "x", "SANDBOX_TEST_OK": "y"}):
            env = scrubbed_env()
        self.assertNotIn("SANDBOX_TEST_SECRET", env)
        self.assertEqual(env.get("SANDBOX_TEST_OK"), "y")


class TrialWorkspaceTests(unittest.TestCase):
    def test_copies_without_excluded_dirs_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            (project / "src").mkdir(parents=True)
            (project / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
            (project / "logs").mkdir()
            (project / "logs" / "big.log").write_text("log", encoding="utf-8")

            with TrialWorkspace(project, exclude_dirs={"logs"}) as trial:
                root = trial.root
                assert root is not None
                self.assertTrue((root / "src" / "a.py").exists())
                self.assertFalse((root / "logs").exists())
                (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")

            self.assertFalse(root.exists())
            self.assertEqual((project / "src" / "a.py").read_text(encoding="utf-8"), "x = 1\n")
            self.assertIsNone(trial.root)

    def test_cleans_up_when_body_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "proj"
            project.mkdir()
            with self.assertRaises(RuntimeError):
                with TrialWorkspace(project) as trial:
                    root = trial.root
                    raise RuntimeError("boom")
            assert root is not None
            self.assertFalse(root.parent.exists())


def _pid_alive(pid: int) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if os.name == "nt":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            alive = str(pid) in out
        else:
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        if not alive:
            return False
        time.sleep(0.2)
    return True


if __name__ == "__main__":
    unittest.main()

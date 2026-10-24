"""项目内受控执行的共享接口。

所有「替用户跑一个子进程」的入口（apply 测试、Web CLI）都走这里，统一四件事：

- 环境：`scrubbed_env()` 去掉 API Key、token、cookie 等敏感变量；
- 目录：调用方必须显式给出 cwd；
- 超时：超时后连同子进程树一起结束，不留孤儿进程；
- 输出：边读边丢弃旧内容，内存里最多保留 `max_bytes` 字节的末尾输出。

`TrialWorkspace` 把「复制项目到临时目录 → 在副本里试跑 → 清理」封装成一个对象，
避免临时副本的生命周期散落在调用方里。
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

MAX_COMMAND_OUTPUT_BYTES = 64 * 1024
OUTPUT_TRUNCATION_MARKER = "\n...[输出过长，已截断；仅保留末尾内容]...\n"
_READ_CHUNK_BYTES = 8 * 1024
_READER_JOIN_SECONDS = 5

SENSITIVE_ENV_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "cookie",
    "credential",
    "passwd",
    "password",
    "secret",
    "token",
)
_SECRET_VALUE_PATTERN = re.compile(r"sk-[A-Za-z0-9]{12,}")


def limit_command_output(output: str, max_bytes: int = MAX_COMMAND_OUTPUT_BYTES) -> str:
    """Keep command results bounded while preserving the useful final diagnostics."""
    if max_bytes <= 0:
        raise ValueError("max_bytes 必须大于 0")
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return output
    marker = OUTPUT_TRUNCATION_MARKER.encode("utf-8")
    if len(marker) >= max_bytes:
        return marker[-max_bytes:].decode("utf-8", errors="ignore")
    tail = encoded[-(max_bytes - len(marker)) :].decode("utf-8", errors="ignore")
    return OUTPUT_TRUNCATION_MARKER + tail


def is_sensitive_env_item(key: str, value: str) -> bool:
    lowered = key.lower()
    if any(token in lowered for token in SENSITIVE_ENV_TOKENS):
        return True
    return bool(_SECRET_VALUE_PATTERN.search(value))


def scrubbed_env(
    overrides: Mapping[str, str] | None = None,
    *,
    drop: Iterable[str] = (),
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """复制当前环境并去掉敏感变量；`overrides` 最后写入，`drop` 里的键一律移除。"""
    source = os.environ if base is None else base
    env = {
        key: value
        for key, value in source.items()
        if not is_sensitive_env_item(key, value)
    }
    for key in drop:
        env.pop(key, None)
    env.update(overrides or {})
    return env


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str
    timed_out: bool = False
    truncated: bool = False


class _TailBuffer:
    """只保留最近 `max_bytes` 字节的缓冲区，保证内存占用有上限。"""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.data = bytearray()
        self.truncated = False

    def feed(self, chunk: bytes) -> None:
        self.data.extend(chunk)
        overflow = len(self.data) - self.max_bytes
        if overflow > 0:
            del self.data[:overflow]
            self.truncated = True

    def text(self) -> str:
        data = bytes(self.data)
        if self.truncated:
            # 截断点可能落在多字节字符中间，丢掉开头残缺的 UTF-8 续字节
            data = data.lstrip(bytes(range(0x80, 0xC0)))
        return data.decode("utf-8", errors="replace")


def _drain(stream, buffer: _TailBuffer) -> None:  # noqa: ANN001 - 二进制管道
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            buffer.feed(chunk)
    except (OSError, ValueError):
        # 进程被强制结束后管道可能已关闭
        pass


def kill_process_tree(process: subprocess.Popen) -> None:
    """结束进程及其子进程；子进程已退出时什么都不做。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        # 先按进程树结束：只 terminate 父进程会让孙进程继续持有输出管道
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (OSError, AttributeError):
            pass
    try:
        process.wait(timeout=3)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_bounded(
    argv: list[str],
    *,
    cwd: Path | str,
    timeout: float,
    env: Mapping[str, str] | None = None,
    max_bytes: int = MAX_COMMAND_OUTPUT_BYTES,
    active: set[subprocess.Popen] | None = None,
) -> CommandResult:
    """运行命令并合并 stdout/stderr；超时会结束整棵进程树。

    `active` 用于登记正在运行的进程，方便上层「强制停止」。
    返回的 `output` 已加截断标记，字节数不超过 `max_bytes`。
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes 必须大于 0")
    popen_kwargs: dict[str, object] = {}
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **popen_kwargs,
    )
    if active is not None:
        active.add(process)
    buffer = _TailBuffer(max_bytes)
    reader = threading.Thread(
        target=_drain, args=(process.stdout, buffer), name="bounded-output", daemon=True
    )
    reader.start()
    timed_out = False
    try:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_tree(process)
        reader.join(_READER_JOIN_SECONDS)
    finally:
        if active is not None:
            active.discard(process)
        if process.stdout is not None:
            try:
                process.stdout.close()
            except OSError:
                pass
    text = buffer.text()
    if buffer.truncated:
        text = OUTPUT_TRUNCATION_MARKER + text
    output = limit_command_output(text, max_bytes)
    truncated = buffer.truncated or output != text
    returncode = process.returncode if process.returncode is not None else -1
    return CommandResult(returncode, output, timed_out=timed_out, truncated=truncated)


class TrialWorkspace:
    """项目的临时试跑副本：进入时复制，退出时整体删除。

    用法：
        with TrialWorkspace(project_root, exclude_dirs={".git"}) as trial:
            ...  # 在 trial.root 里改文件、跑测试
    """

    def __init__(
        self,
        project_root: Path,
        *,
        exclude_dirs: Iterable[str] = (),
        prefix: str = "agent-workbench-trial-",
    ) -> None:
        self.project_root = Path(project_root)
        self.exclude_dirs = frozenset(exclude_dirs)
        self.prefix = prefix
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.root: Path | None = None

    def _ignore(self, directory: str, names: list[str]) -> set[str]:
        del directory
        return {name for name in names if name in self.exclude_dirs}

    def __enter__(self) -> TrialWorkspace:
        self._tmp = tempfile.TemporaryDirectory(prefix=self.prefix)
        try:
            self.root = Path(self._tmp.name) / self.project_root.name
            shutil.copytree(self.project_root, self.root, ignore=self._ignore)
        except BaseException:
            self._tmp.cleanup()
            self._tmp = None
            raise
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
        self.root = None

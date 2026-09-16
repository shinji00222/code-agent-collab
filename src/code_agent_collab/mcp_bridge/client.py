"""MCP（Model Context Protocol）stdio 传输的最小客户端实现。

为什么要自己写：本项目的定位是「只依赖标准库 + pywebview」的本地优先工作台，
引入官方 `mcp` SDK 会连带 pydantic / anyio / httpx 等一串传递依赖。MCP 协议
在 stdio 上就是「换行分隔的 JSON-RPC 2.0」，核心子集（握手 → 工具发现 → 工具调用）
用标准库完全可以正确实现。

协议依据（MCP 2025-06-18）：
- stdio 传输：客户端拉起子进程；消息为 JSON-RPC，**以换行分隔、不得含内嵌换行**；
  服务端 stderr 只用于日志（客户端可选捕获）。
- 生命周期：客户端先发 `initialize`，收到结果后再发 `notifications/initialized`，
  之后才进入正常通信。
- 工具：`tools/list`（支持 cursor 分页）、`tools/call`（结果为 content 数组 +
  可选 isError / structuredContent）。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# 客户端声明支持的协议版本；实际版本以服务端 initialize 结果为准。
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "code-agent-collab", "version": "0.14.5"}

# 声明空能力：本项目不需要 roots / sampling / elicitation，保持最小实现。
CLIENT_CAPABILITIES: dict[str, Any] = {}

DEFAULT_TIMEOUT_SECONDS = 15.0
STDERR_BUFFER_LINES = 200


class McpError(RuntimeError):
    """MCP 相关错误基类。"""


class McpProtocolError(McpError):
    """收到的报文不符合 MCP / JSON-RPC 约定。"""


class McpServerError(McpError):
    """服务端返回了 JSON-RPC error 响应（协议层错误，如未知工具）。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"MCP 服务端错误 {code}：{message}")
        self.code = code
        self.message = message
        self.data = data


class McpTimeoutError(McpError):
    """等待服务端响应超时。"""


class McpTransportError(McpError):
    """传输层错误：子进程退出、管道关闭等。"""


@dataclass(frozen=True)
class McpTool:
    """服务端声明的一个工具。"""

    name: str
    title: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "McpTool":
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise McpProtocolError("工具定义缺少合法的 name 字段")
        schema = payload.get("inputSchema")
        return cls(
            name=name,
            title=str(payload.get("title") or ""),
            description=str(payload.get("description") or ""),
            input_schema=dict(schema) if isinstance(schema, Mapping) else {},
        )


@dataclass(frozen=True)
class McpToolResult:
    """`tools/call` 的结果。"""

    text: str
    is_error: bool = False
    content: tuple[dict[str, Any], ...] = ()
    structured: dict[str, Any] | None = None


def _extract_text(content: Sequence[Any]) -> str:
    """把 content 数组里的文本块拼成一段文本；非文本块给出占位说明。

    刻意不解析 image/audio 的 base64（体积大且当前用不到），只标注类型，
    避免把无关大块数据灌进提示词。
    """
    parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "text":
            parts.append(str(block.get("text") or ""))
        elif block_type == "resource":
            resource = block.get("resource") or {}
            if isinstance(resource, Mapping) and isinstance(resource.get("text"), str):
                parts.append(resource["text"])
            else:
                parts.append(f"[embedded resource: {resource.get('uri', 'unknown')}]")
        elif block_type == "resource_link":
            parts.append(f"[resource link: {block.get('uri', 'unknown')}]")
        elif block_type:
            parts.append(f"[{block_type} content omitted]")
    return "\n".join(part for part in parts if part)


class McpStdioClient:
    """通过 stdio 与单个 MCP 服务端通信的客户端。

    线程模型：一个读线程负责消费子进程 stdout（按 id 派发响应、把服务端的
    反向请求和通知分流），一个 stderr 线程负责持续排空 stderr。
    两者都不可省略——stdio 管道写满后子进程会阻塞，读端不排空就是死锁。
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        name: str = "mcp",
        env: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not command:
            raise ValueError("MCP 服务端命令不能为空")
        self.name = name
        self.command = [str(part) for part in command]
        self.env = dict(env) if env else None
        self.cwd = str(cwd) if cwd else None
        self.timeout_seconds = float(timeout_seconds)

        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stderr_tail: deque[str] = deque(maxlen=STDERR_BUFFER_LINES)
        self._responses: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        # 读线程也要写 stdin（回应服务端的反向请求），必须与主线程写操作互斥，
        # 否则两次 write 可能交错，破坏「一行一个 JSON 消息」的约定。
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._closed = False
        self._stderr_lock = threading.Lock()
        self.server_info: dict[str, Any] = {}
        self.protocol_version: str = ""
        self.capabilities: dict[str, Any] = {}

    # ---------- 生命周期 ----------

    def start(self) -> "McpStdioClient":
        if self._process is not None:
            return self
        env = dict(os.environ)
        if self.env:
            env.update(self.env)
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=self.cwd,
                env=env,
            )
        except OSError as exc:
            raise McpTransportError(f"无法启动 MCP 服务端 {self.name}：{exc}") from exc

        self._stderr_reader = threading.Thread(
            target=self._drain_stderr, name=f"mcp-stderr-{self.name}", daemon=True
        )
        self._stderr_reader.start()
        self._reader = threading.Thread(
            target=self._read_stdout, name=f"mcp-stdout-{self.name}", daemon=True
        )
        self._reader.start()

        try:
            self._handshake()
        except McpError:
            # 握手失败（超时、能力不满足等）必须回收子进程，避免留下孤儿进程。
            self.close()
            raise
        return self
    def _handshake(self) -> None:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": CLIENT_CAPABILITIES,
                "clientInfo": CLIENT_INFO,
            },
        )
        if not isinstance(result, Mapping):
            raise McpProtocolError("initialize 结果不是对象")
        server_version = result.get("protocolVersion")
        if not isinstance(server_version, str) or not server_version:
            raise McpProtocolError("initialize 结果缺少 protocolVersion")
        self.protocol_version = server_version
        info = result.get("serverInfo")
        self.server_info = dict(info) if isinstance(info, Mapping) else {}
        caps = result.get("capabilities")
        self.capabilities = dict(caps) if isinstance(caps, Mapping) else {}

        # 握手完成的标志：客户端发出 initialized 通知（通知没有 id，不等响应）。
        if not self.supports_tools():
            raise McpProtocolError(
                f"MCP 服务端 {self.name} 未声明 tools 能力，无法提供工具"
            )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def supports_tools(self) -> bool:
        return "tools" in self.capabilities

    def close(self, grace_seconds: float = 3.0) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process is None:
            return
        # 规范建议的关闭方式：先关 stdin，让服务端自然退出；超时再强杀。
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=grace_seconds)
                except subprocess.TimeoutExpired:
                    pass
        for thread in (self._reader, self._stderr_reader):
            if thread is not None:
                thread.join(timeout=grace_seconds)
        # Windows 上管道句柄不显式关闭会一直占着，属于句柄泄漏；读线程已 join，可安全关闭。
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except (OSError, ValueError):
                pass
        for waiter in list(self._responses.values()):
            waiter.put({"__transport_closed__": True})

    def __enter__(self) -> "McpStdioClient":
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def stderr_tail(self, limit: int = 20) -> list[str]:
        with self._stderr_lock:
            return list(self._stderr_tail)[-limit:]

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # ---------- 协议请求 ----------

    def list_tools(self) -> list[McpTool]:
        tools: list[McpTool] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self._request("tools/list", params)
            if not isinstance(result, Mapping):
                raise McpProtocolError("tools/list 结果不是对象")
            raw_tools = result.get("tools")
            if raw_tools is None:
                raw_tools = []
            if not isinstance(raw_tools, Sequence):
                raise McpProtocolError("tools/list 的 tools 字段不是数组")
            for payload in raw_tools:
                if not isinstance(payload, Mapping):
                    raise McpProtocolError("tools/list 的条目不是对象")
                tools.append(McpTool.from_payload(payload))
            next_cursor = result.get("nextCursor")
            if not next_cursor or not isinstance(next_cursor, str):
                break
            # 防御服务端游标不前进导致的死循环
            if next_cursor in seen_cursors:
                raise McpProtocolError(f"tools/list 分页游标重复：{next_cursor}")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return tools

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> McpToolResult:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
        )
        if not isinstance(result, Mapping):
            raise McpProtocolError("tools/call 结果不是对象")
        raw_content = result.get("content")
        content: tuple[dict[str, Any], ...] = ()
        if isinstance(raw_content, Sequence):
            content = tuple(dict(item) for item in raw_content if isinstance(item, Mapping))
        structured = result.get("structuredContent")
        return McpToolResult(
            text=_extract_text(content),
            is_error=bool(result.get("isError", False)),
            content=content,
            structured=dict(structured) if isinstance(structured, Mapping) else None,
        )

    # ---------- 内部：收发 ----------

    def _send(self, message: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise McpTransportError(f"MCP 服务端 {self.name} 尚未启动")
        if process.poll() is not None:
            raise McpTransportError(
                f"MCP 服务端 {self.name} 已退出（code={process.returncode}）"
            )
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if "\n" in line or "\r" in line:
            # stdio 传输要求消息不得含内嵌换行
            raise McpProtocolError("待发送的消息包含内嵌换行，违反 stdio 传输约定")
        try:
            with self._write_lock:
                process.stdin.write(line + "\n")
                process.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            raise McpTransportError(f"写入 MCP 服务端 {self.name} 失败：{exc}") from exc

    def _request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._responses[request_id] = waiter

        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = dict(params)
        try:
            self._send(message)
        except McpError:
            with self._lock:
                self._responses.pop(request_id, None)
            raise

        try:
            response = waiter.get(timeout=timeout_seconds or self.timeout_seconds)
        except queue.Empty:
            with self._lock:
                self._responses.pop(request_id, None)
            raise McpTimeoutError(
                f"MCP 服务端 {self.name} 在 {timeout_seconds or self.timeout_seconds}s 内未响应 {method}"
            ) from None
        finally:
            pass

        if response.get("__transport_closed__"):
            raise McpTransportError(f"MCP 服务端 {self.name} 连接已关闭")
        error = response.get("error")
        if error is not None:
            if isinstance(error, Mapping):
                raise McpServerError(
                    int(error.get("code", 0) or 0),
                    str(error.get("message", "unknown error")),
                    error.get("data"),
                )
            raise McpProtocolError(f"JSON-RPC error 字段格式非法：{error!r}")
        if "result" not in response:
            raise McpProtocolError(f"响应缺少 result 字段：{response!r}")
        return response["result"]

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    # 服务端把非协议内容写进了 stdout，违反规范；跳过并记录诊断。
                    self._append_stderr(f"[client] 忽略非 JSON 输出：{line[:200]}")
                    continue
                if not isinstance(message, Mapping):
                    self._append_stderr(f"[client] 忽略非对象报文：{line[:200]}")
                    continue
                self._dispatch(message)
        except (OSError, ValueError):
            # close() 关掉管道时会打断阻塞的读取，属正常收尾路径。
            pass
        self._fail_pending()

    def _dispatch(self, message: Mapping[str, Any]) -> None:
        message_id = message.get("id")
        has_method = "method" in message

        if message_id is not None and not has_method:
            with self._lock:
                waiter = self._responses.pop(int(message_id), None)
            if waiter is None:
                self._append_stderr(f"[client] 收到未知 id 的响应：{message_id}")
                return
            waiter.put(dict(message))
            return

        if message_id is not None and has_method:
            # 服务端反向请求：本客户端未声明任何能力，按规范回「方法不存在」，
            # 必须回，否则服务端会一直等待。
            try:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": message_id,
                        "error": {"code": -32601, "message": "Method not found"},
                    }
                )
            except McpError:
                pass
            return

        # 通知：当前实现不需要处理 notify，仅记录便于排障。
        self._append_stderr(f"[client] 收到通知：{message.get('method')}")

    def _fail_pending(self) -> None:
        with self._lock:
            waiters = list(self._responses.values())
            self._responses.clear()
        for waiter in waiters:
            waiter.put({"__transport_closed__": True})

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            for raw_line in process.stderr:
                self._append_stderr(raw_line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass

    def _append_stderr(self, line: str) -> None:
        with self._stderr_lock:
            self._stderr_tail.append(line)


def default_python_command(script_path: str | os.PathLike[str]) -> list[str]:
    """用当前解释器运行一个 Python 写的 MCP 服务端脚本。"""
    return [sys.executable, str(script_path)]

"""测试用的假 MCP 服务端（纯标准库，按 MCP 2025-06-18 stdio 传输约定实现）。

它只做测试需要的事：握手、tools/list（含分页与坏游标）、tools/call（成功 / isError /
JSON-RPC 错误），并可用 FAKE_MCP_MODE 制造各种异常场景来验证客户端行为。

支持的 FAKE_MCP_MODE：
- normal（默认）     正常服务端
- pagination         tools/list 分两页返回
- bad_cursor         tools/list 永远返回同一个游标（验证客户端防死循环）
- stderr_flood       启动时向 stderr 灌入大量日志（验证客户端必须排空 stderr，否则死锁）
- junk_stdout        在 stdout 混入非 JSON 行（验证客户端跳过并继续）
- no_tools_capability initialize 结果不声明 tools 能力
- slow               响应前按 FAKE_MCP_DELAY_MS 延迟（验证超时）
- server_request     握手后向客户端发一个反向请求（验证客户端会回应、不会卡住）
"""

from __future__ import annotations

import json
import os
import sys
import time

MODE = os.getenv("FAKE_MCP_MODE", "normal")
DELAY_MS = int(os.getenv("FAKE_MCP_DELAY_MS", "0"))
PROTOCOL_VERSION = os.getenv("FAKE_MCP_PROTOCOL_VERSION", "2025-06-18")

# MCP 规范要求 stdio 上的消息必须是 UTF-8。Windows 上 Python 的 stdio 默认跟随
# 本地代码页（简体中文环境是 cp936），不显式改成 UTF-8 就会出现中文乱码——
# 这一点对真实 MCP 服务端同样成立，客户端需要留意。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_STATE = {"client_reply_received": False, "initialized": False}

TOOLS_PAGE_1 = [
    {
        "name": "echo",
        "title": "Echo",
        "description": "原样返回输入的文本",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "fail",
        "description": "总是以 isError=true 报告执行失败",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOLS_PAGE_2 = [
    {
        "name": "server_state",
        "description": "返回服务端记录的客户端行为（用于验证客户端是否回应了反向请求）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "structured",
        "description": "返回 structuredContent 的工具",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _log(text: str) -> None:
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def _handle_initialize(request: dict) -> None:
    capabilities: dict = {"tools": {"listChanged": False}}
    if MODE == "no_tools_capability":
        capabilities = {}
    _write(
        {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": capabilities,
                "serverInfo": {"name": "fake-mcp-server", "version": "1.0.0"},
            },
        }
    )


def _handle_tools_list(request: dict) -> None:
    params = request.get("params") or {}
    cursor = params.get("cursor")

    if MODE == "pagination":
        if cursor == "page2":
            result = {"tools": TOOLS_PAGE_2}
        else:
            result = {"tools": TOOLS_PAGE_1, "nextCursor": "page2"}
    elif MODE == "bad_cursor":
        result = {"tools": TOOLS_PAGE_1, "nextCursor": "stuck"}
    else:
        result = {"tools": TOOLS_PAGE_1 + TOOLS_PAGE_2}

    _write({"jsonrpc": "2.0", "id": request.get("id"), "result": result})


def _handle_tools_call(request: dict) -> None:
    params = request.get("params") or {}
    name = params.get("name")
    arguments = params.get("arguments") or {}

    if name == "echo":
        _write(
            {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "content": [{"type": "text", "text": f"echo: {arguments.get('text', '')}"}],
                    "isError": False,
                },
            }
        )
        return

    if name == "fail":
        _write(
            {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "content": [{"type": "text", "text": "模拟的执行失败：上游 API 限流"}],
                    "isError": True,
                },
            }
        )
        return

    if name == "server_state":
        _write(
            {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(_STATE, ensure_ascii=False)}
                    ]
                },
            }
        )
        return

    if name == "structured":
        _write(
            {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {
                    "content": [{"type": "text", "text": '{"answer": 42}'}],
                    "structuredContent": {"answer": 42},
                },
            }
        )
        return

    _write(
        {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": -32602, "message": f"Unknown tool: {name}"},
        }
    )


def main() -> int:
    if MODE == "stderr_flood":
        # 约 200KB，远超管道缓冲区；客户端若不排空 stderr，这里就会阻塞住再也回不了消息。
        for index in range(4000):
            _log(f"flood {index} " + "x" * 40)

    if MODE == "junk_stdout":
        sys.stdout.write("this is not json\n")
        sys.stdout.flush()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = message.get("method")
        message_id = message.get("id")

        # 延迟对所有消息生效（含 initialize），否则测不出客户端握手超时。
        if DELAY_MS:
            time.sleep(DELAY_MS / 1000.0)

        # 客户端对我们反向请求的回应（没有 method）
        if method is None and message_id == 9001:
            _STATE["client_reply_received"] = True
            continue

        if method == "initialize":
            _handle_initialize(message)
            continue

        if method == "notifications/initialized":
            _STATE["initialized"] = True
            if MODE == "server_request":
                # 反向请求：客户端必须回应，否则这里会一直等下去。
                _write({"jsonrpc": "2.0", "id": 9001, "method": "roots/list"})
            continue

        if method == "tools/list":
            _handle_tools_list(message)
        elif method == "tools/call":
            _handle_tools_call(message)
        elif message_id is not None:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

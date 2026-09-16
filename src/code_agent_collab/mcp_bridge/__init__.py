"""MCP 工具接入层（零新增依赖，仅标准库）。

对外入口：
- `McpStdioClient`：单个 MCP 服务端的 stdio 客户端（JSON-RPC 2.0）。
- `McpToolRegistry` / `load_server_specs`：多服务端配置与工具聚合。
- `run_tool_loop` / `parse_tool_call`：把工具接进纯文本 Provider 的调用循环。
"""

from .client import (
    PROTOCOL_VERSION,
    McpError,
    McpProtocolError,
    McpServerError,
    McpStdioClient,
    McpTimeoutError,
    McpTool,
    McpToolResult,
    McpTransportError,
    default_python_command,
)
from .loop import (
    TOOL_CALL_FENCE,
    TOOL_PROTOCOL_INSTRUCTIONS,
    ToolCallParseError,
    ToolCallRecord,
    ToolCallRequest,
    ToolLoopResult,
    parse_tool_call,
    run_tool_loop,
)
from .registry import (
    ENV_SERVERS,
    McpConfigError,
    McpServerSpec,
    McpToolRegistry,
    RegisteredTool,
    load_server_specs,
    parse_server_specs,
)

__all__ = [
    "ENV_SERVERS",
    "PROTOCOL_VERSION",
    "TOOL_CALL_FENCE",
    "TOOL_PROTOCOL_INSTRUCTIONS",
    "McpConfigError",
    "McpError",
    "McpProtocolError",
    "McpServerError",
    "McpServerSpec",
    "McpStdioClient",
    "McpTimeoutError",
    "McpTool",
    "McpToolRegistry",
    "McpToolResult",
    "McpTransportError",
    "RegisteredTool",
    "ToolCallParseError",
    "ToolCallRecord",
    "ToolCallRequest",
    "ToolLoopResult",
    "default_python_command",
    "load_server_specs",
    "parse_server_specs",
    "parse_tool_call",
    "run_tool_loop",
]

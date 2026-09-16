"""MCP 服务端配置、工具注册表与多服务端聚合。

职责：
1. 从项目配置（`.agent-workbench/config.json` 的 `mcpServers` 字段）或环境变量
   `AGENT_WORKBENCH_MCP_SERVERS` 读取要连接的服务端；
2. 拉起服务端、发现工具，并把多个服务端的工具聚合成一个可检索的注册表；
3. 提供「按限定名调用工具」的统一入口。

设计取舍：
- **单点故障不影响整体**：某个服务端启动失败只记录错误，其余照常可用。工作台
  是本地优先工具，不能因为一个外部 MCP 服务端挂掉就整个不可用。
- **工具名限定为 `服务端名.工具名`**：不同服务端可能有同名工具，限定名避免歧义；
  若某个工具名全局唯一，也允许用裸名调用。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .client import (
    DEFAULT_TIMEOUT_SECONDS,
    McpError,
    McpStdioClient,
    McpTool,
    McpToolResult,
)

CONFIG_DIR = ".agent-workbench"
CONFIG_FILE = "config.json"
ENV_SERVERS = "AGENT_WORKBENCH_MCP_SERVERS"
QUALIFIED_SEPARATOR = "."


class McpConfigError(ValueError):
    """MCP 服务端配置格式非法。"""


@dataclass(frozen=True)
class McpServerSpec:
    """一个 MCP 服务端的启动配置。"""

    name: str
    command: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_payload(cls, name: str, payload: Mapping[str, Any]) -> "McpServerSpec":
        if not isinstance(name, str) or not name.strip():
            raise McpConfigError("MCP 服务端名称不能为空")
        if QUALIFIED_SEPARATOR in name:
            raise McpConfigError(f"MCP 服务端名称不能包含 {QUALIFIED_SEPARATOR!r}：{name}")
        raw_command = payload.get("command")
        if isinstance(raw_command, str) or not isinstance(raw_command, Sequence):
            raise McpConfigError(
                f"MCP 服务端 {name} 的 command 必须是字符串数组"
                "（例如 [\"npx\", \"-y\", \"@modelcontextprotocol/server-filesystem\"]）"
            )
        command = tuple(str(part) for part in raw_command)
        if not command:
            raise McpConfigError(f"MCP 服务端 {name} 的 command 不能为空")

        raw_env = payload.get("env") or {}
        if not isinstance(raw_env, Mapping):
            raise McpConfigError(f"MCP 服务端 {name} 的 env 必须是对象")
        env = {str(key): str(value) for key, value in raw_env.items()}

        raw_cwd = payload.get("cwd")
        cwd = str(raw_cwd) if raw_cwd else None

        try:
            timeout_seconds = float(payload.get("timeoutSeconds", DEFAULT_TIMEOUT_SECONDS))
        except (TypeError, ValueError) as exc:
            raise McpConfigError(f"MCP 服务端 {name} 的 timeoutSeconds 不是数字") from exc
        if timeout_seconds <= 0:
            raise McpConfigError(f"MCP 服务端 {name} 的 timeoutSeconds 必须为正数")

        return cls(
            name=name,
            command=command,
            env=env,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )


def parse_server_specs(payload: Mapping[str, Any]) -> list[McpServerSpec]:
    if not isinstance(payload, Mapping):
        raise McpConfigError("mcpServers 必须是对象（服务端名 -> 配置）")
    specs: list[McpServerSpec] = []
    for name, item in payload.items():
        if not isinstance(item, Mapping):
            raise McpConfigError(f"MCP 服务端 {name} 的配置必须是对象")
        specs.append(McpServerSpec.from_payload(str(name), item))
    return specs


def load_server_specs(project_root: Path | str) -> list[McpServerSpec]:
    """读取 MCP 服务端配置：环境变量优先于项目配置文件。"""
    from_env = os.getenv(ENV_SERVERS)
    if from_env:
        try:
            payload = json.loads(from_env)
        except json.JSONDecodeError as exc:
            raise McpConfigError(f"环境变量 {ENV_SERVERS} 不是合法 JSON：{exc}") from exc
        return parse_server_specs(payload)

    config_path = Path(project_root) / CONFIG_DIR / CONFIG_FILE
    if not config_path.exists():
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"{config_path} 不是合法 JSON：{exc}") from exc
    raw_servers = data.get("mcpServers") or {}
    return parse_server_specs(raw_servers)


@dataclass(frozen=True)
class RegisteredTool:
    """注册表里的一个工具（含它来自哪个服务端）。"""

    server: str
    tool: McpTool

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def qualified_name(self) -> str:
        return f"{self.server}{QUALIFIED_SEPARATOR}{self.tool.name}"

    @property
    def description(self) -> str:
        return self.tool.description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.tool.input_schema


class McpToolRegistry:
    """聚合多个 MCP 服务端的工具。

    用法：
        registry = McpToolRegistry(specs).start()
        try:
            registry.tools()
            registry.call("filesystem.read_file", {"path": "..."})
        finally:
            registry.close()
    """

    def __init__(self, specs: Sequence[McpServerSpec]) -> None:
        self._specs = list(specs)
        self._clients: dict[str, McpStdioClient] = {}
        self._tools: list[RegisteredTool] = []
        self.errors: dict[str, str] = {}
        self._started = False

    # ---------- 生命周期 ----------

    def start(self) -> "McpToolRegistry":
        if self._started:
            return self
        self._started = True
        for spec in self._specs:
            client = McpStdioClient(
                spec.command,
                name=spec.name,
                env=spec.env,
                cwd=spec.cwd,
                timeout_seconds=spec.timeout_seconds,
            )
            try:
                client.start()
                tools = client.list_tools()
            except McpError as exc:
                self.errors[spec.name] = str(exc)
                client.close()
                continue
            self._clients[spec.name] = client
            for tool in tools:
                self._tools.append(RegisteredTool(server=spec.name, tool=tool))
        return self

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()
        self._tools.clear()
        self._started = False

    def __enter__(self) -> "McpToolRegistry":
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------- 查询 ----------

    def tools(self) -> list[RegisteredTool]:
        return list(self._tools)

    def server_names(self) -> list[str]:
        return sorted(self._clients)

    def get(self, name: str) -> RegisteredTool:
        """按限定名或（全局唯一的）裸名查找工具。"""
        for item in self._tools:
            if item.qualified_name == name:
                return item
        matches = [item for item in self._tools if item.name == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            candidates = "、".join(sorted(item.qualified_name for item in matches))
            raise McpError(f"工具名 {name} 在多个服务端中存在，请使用限定名：{candidates}")
        available = "、".join(sorted(item.qualified_name for item in self._tools)) or "（无）"
        raise McpError(f"找不到工具 {name}；可用工具：{available}")

    def describe_for_prompt(self) -> str:
        """生成给模型看的工具清单（名称 + 说明 + 入参 schema）。"""
        if not self._tools:
            return "（当前没有可用的 MCP 工具）"
        blocks: list[str] = []
        for item in self._tools:
            schema = json.dumps(item.input_schema, ensure_ascii=False) if item.input_schema else "{}"
            head = f"- {item.qualified_name}"
            if item.description:
                head += f"：{item.description}"
            blocks.append(f"{head}\n  入参 schema：{schema}")
        return "\n".join(blocks)

    # ---------- 调用 ----------

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> McpToolResult:
        item = self.get(name)
        client = self._clients.get(item.server)
        if client is None:
            raise McpError(f"MCP 服务端 {item.server} 当前不可用")
        return client.call_tool(item.name, arguments)

    def stderr_tail(self, server: str, limit: int = 20) -> list[str]:
        client = self._clients.get(server)
        return client.stderr_tail(limit) if client else []

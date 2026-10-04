"""本机 Web API 的请求级安全校验（v0.17.14）。

背景（问题台账「2026-09-15 安全方案 · 问题 2」）：Web API 绑定在 `127.0.0.1`，
但没有任何 Host / Origin 校验和请求体上限。风险不在于"外网能连上"，而在于：

1. **DNS rebinding**：恶意网页把自己的域名解析到 `127.0.0.1`，浏览器就会把请求打到本机服务，
   而且浏览器认为这是"同源"，响应可读。校验 `Host` 头能挡住它——rebinding 场景下
   浏览器发的 `Host` 是攻击者域名，不是 `127.0.0.1`。
2. **CSRF / 跨站触发**：用户访问的任意网页都可以 `fetch('http://127.0.0.1:<port>/api/jobs', ...)`。
   即使响应被 CORS 挡住，**副作用已经发生**（起任务、花钱、写文件）。
   校验 `Origin` / `Sec-Fetch-Site`，并要求 `Content-Type: application/json`，
   可以把这类"简单请求"挡在门外：跨站表单只能发 `text/plain`、`urlencoded`、`multipart`，
   而带自定义 JSON Content-Type 的请求会先触发预检，而本服务不返回 CORS 头 → 预检失败。
3. **请求体过大**：原来直接 `int(Content-Length)` 后一次性读出，超大值会直接吃内存。

设计：一个纯函数 `inspect_request()` 做全部判断并返回第一个拒绝原因，便于单测；
`read_json_body()` 负责带上限地读取与解析。

**边界（明确写下，避免误以为这层能挡住一切）**：

- Origin 只校验**主机名是回环地址**，不校验端口。也就是说，本机上另一个端口的网页仍可能
  触发本服务。这不是本层要解决的问题——同机同权限的进程本来就能读写你的文件。
  这层挡的是"任意一个外部网站"和"DNS rebinding"。
- 没有做会话令牌。页面由本服务自己下发，且跨站读不到响应；加令牌的收益低于它对
  WebView / 浏览器兼容性的风险。**如果以后要把端口对外开放，必须重新评估并加令牌。**
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

#: 只接受本机回环地址作为 Host。
ALLOWED_HOST_NAMES = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})

#: 请求体上限。本机工作台的请求都是小 JSON，64 KiB 足够。
MAX_BODY_BYTES = 64 * 1024

#: 只接受 JSON 请求体，借此把跨站"简单请求"挡掉。
ALLOWED_CONTENT_TYPES = frozenset({"application/json"})

#: 所有响应统一附加的安全头。
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


@dataclass(frozen=True)
class Rejection:
    status: int
    message: str


class RequestRejected(Exception):
    """读取请求体过程中的拒绝；由调用方转成 HTTP 响应。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def header_map(headers: object) -> dict[str, str]:
    """把 headers 统一成小写键的字典；`email.message.Message` 和普通 dict 都支持。"""
    items = headers.items() if hasattr(headers, "items") else headers
    return {str(key).lower(): str(value) for key, value in items}  # type: ignore[union-attr]


def _host_name(host_header: str) -> str:
    """从 Host 头取出主机名（去掉端口），IPv6 字面量保留方括号形式。"""
    value = host_header.strip()
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1].lower() if end != -1 else value.lower()
    if ":" in value:
        return value.rsplit(":", 1)[0].strip().lower()
    return value.lower()


def check_host(host_header: str | None) -> Rejection | None:
    if not host_header or not host_header.strip():
        return Rejection(400, "缺少 Host 请求头")
    name = _host_name(host_header)
    if name not in ALLOWED_HOST_NAMES:
        return Rejection(
            403,
            f"Host 不被允许：{name}；本机工作台只接受来自 127.0.0.1 / localhost 的访问",
        )
    return None


def _origin_host(origin: str) -> str | None:
    try:
        parts = urlsplit(origin.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"}:
        return None
    return (parts.hostname or "").lower() or None


def check_origin(origin: str | None, referer: str | None) -> Rejection | None:
    """有 Origin / Referer 时必须是本机来源；两者都没有则视为非浏览器客户端（脚本、curl）。"""
    candidate = (origin or "").strip() or (referer or "").strip()
    if not candidate:
        return None
    host = _origin_host(candidate)
    if host in ALLOWED_HOST_NAMES:
        return None
    return Rejection(403, f"请求来源不被允许：{candidate}；只接受本机页面发出的请求")


def check_fetch_metadata(sec_fetch_site: str | None) -> Rejection | None:
    """现代浏览器会带 `Sec-Fetch-Site`；跨站直接拒绝（额外一层，缺失时不判）。"""
    value = (sec_fetch_site or "").strip().lower()
    if value == "cross-site":
        return Rejection(403, "跨站请求被拒绝（Sec-Fetch-Site: cross-site）")
    return None


def check_content_type(content_type: str | None) -> Rejection | None:
    value = (content_type or "").split(";", 1)[0].strip().lower()
    if value not in ALLOWED_CONTENT_TYPES:
        return Rejection(
            415,
            "只接受 Content-Type: application/json 的请求体"
            "（这也是挡住跨站简单请求的一道防线）",
        )
    return None


def inspect_request(
    headers: object,
    *,
    json_body: bool,
    check_origin_header: bool = True,
) -> Rejection | None:
    """对一次请求做全部安全校验，返回第一个拒绝原因；通过则返回 `None`。

    `json_body=True` 表示这是会改状态、带 JSON 请求体的接口（POST）。
    """
    values = header_map(headers)

    rejection = check_host(values.get("host"))
    if rejection is not None:
        return rejection

    if not json_body:
        return None

    rejection = check_fetch_metadata(values.get("sec-fetch-site"))
    if rejection is not None:
        return rejection

    if check_origin_header:
        rejection = check_origin(values.get("origin"), values.get("referer"))
        if rejection is not None:
            return rejection

    return check_content_type(values.get("content-type"))


def read_json_body(handler: object, max_bytes: int = MAX_BODY_BYTES) -> dict:
    """带上限地读取 JSON 请求体（空请求体返回 `{}`）。"""
    headers = header_map(getattr(handler, "headers", {}))
    raw_length = headers.get("content-length")
    if raw_length is None or raw_length.strip() == "":
        return {}
    try:
        length = int(raw_length)
    except ValueError:
        raise RequestRejected(400, "Content-Length 不是合法整数") from None
    if length < 0:
        raise RequestRejected(400, "Content-Length 不能为负数") from None
    if length > max_bytes:
        raise RequestRejected(
            413,
            f"请求体过大：{length} 字节，上限 {max_bytes} 字节（已关闭连接）",
        )
    if length == 0:
        return {}

    stream = getattr(handler, "rfile")
    data = stream.read(length)
    if len(data) != length:
        raise RequestRejected(400, "请求体长度与 Content-Length 不一致")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestRejected(400, f"请求体不是合法 JSON：{exc}") from None
    if not isinstance(payload, dict):
        raise RequestRejected(400, "请求体必须是 JSON 对象")
    return payload

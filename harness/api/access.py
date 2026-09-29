# 接口层的认证（应用层与接口层设计说明第 2.2、6.2 节）：访问方式、Host 与 Origin 检查、命令的媒体类型，
# 都在路由处理之前完成。访问令牌与 TLS 保留位置（第 6.3 节，TODO）。

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from ..app.contracts import AccessMode

# 两种访问方式的提出者都是 user:local（加入令牌以后为 user:<令牌名称>）
LOCAL_ACTOR = "user:local"

# 本机访问方式的 Host 只能是本机名称，防止 DNS 重新绑定（第 6.2 节）
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# 桌面客户端页面的来源（第 6.2 节）：Electron 用注册过的自定义协议加载界面，跨来源请求带这个 Origin。
# 来源字符串见 docs/architecture-issues.md 中 #76 的登记
CLIENT_ORIGINS = ("yudao://app",)

# 命令只接受 application/json（第 6.2 节）
COMMAND_MEDIA_TYPE = "application/json"


def host_name(host_header: str) -> str:
    # Host 带端口：127.0.0.1:8765、localhost:8765、[::1]:8765
    if host_header.startswith("["):
        return host_header[1:].partition("]")[0]
    return host_header.partition(":")[0]


def rejection(*, access: AccessMode, method: str, path: str, headers: Headers) -> int | None:
    # 请求被拒绝时返回 HTTP 状态；检查不通过就不进入路由
    if access == "local" and host_name(headers.get("host", "")) not in LOCAL_HOSTS:
        return 403
    origin = headers.get("origin")
    if origin is not None and origin not in CLIENT_ORIGINS:
        return 403
    if method == "POST" and path.startswith("/api/commands/"):
        media_type = headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != COMMAND_MEDIA_TYPE:
            return 415
    return None


def authenticate() -> str:
    # TODO（第 6.3 节）：离开局域网访问之前在这里校验 Authorization: Bearer <令牌>，提出者为 user:<令牌名称>，
    # 认证失败返回 401。两种访问方式当前都直接通过，提出者是 user:local
    return LOCAL_ACTOR


class AccessMiddleware:
    # 认证在路由处理之前完成（第 2.2 节）。写成 ASGI 中间件：响应体逐块经过，
    # 不用 BaseHTTPMiddleware，事件流不会被缓冲
    def __init__(self, app: ASGIApp, *, access: AccessMode = "local") -> None:
        self.app = app
        self.access = access

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        status = rejection(access=self.access, method=scope["method"], path=scope["path"], headers=headers)
        if status is not None:
            await Response(status_code=status)(scope, receive, send)
            return
        # 提出者由认证得出（第 6.2 节），写入事件的 actor 字段
        scope.setdefault("state", {})["actor"] = authenticate()
        await self.app(scope, receive, send)

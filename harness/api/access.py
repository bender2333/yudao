# 接口层的认证（应用层与接口层设计说明第 2.2、6.2、6.3 节）：访问方式、Host 与 Origin 检查、
# 访问令牌与命令的媒体类型，都在路由处理之前完成。

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from ..app.access_tokens import AccessTokenStore
from ..app.contracts import AccessMode

# 本机访问方式的提出者；局域网访问方式的提出者是 user:<令牌名称>（第 6.2、6.3 节）
LOCAL_ACTOR = "user:local"

# 本机访问方式的 Host 只能是本机名称，防止 DNS 重新绑定（第 6.2 节）
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# 页面与接口同一来源（第 6.2 节）：带 Origin 的请求只接受 http:// 加本次请求的 Host
def same_origin(headers: Headers) -> str:
    return f"http://{headers.get('host', '')}"

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
    if origin is not None and origin != same_origin(headers):
        return 403
    if method == "POST" and path.startswith("/api/commands/"):
        media_type = headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type != COMMAND_MEDIA_TYPE:
            return 415
    return None


# 页面文件不需要令牌（第 6.3 节）：页面文件在接口路径之外，其余全部路径（能力清单、OpenAPI、
# 查询、命令、事件流）都需要 Authorization: Bearer <令牌>
INTERFACE_PATHS = ("/api/", "/openapi.json")


def requires_token(path: str) -> bool:
    return path.startswith(INTERFACE_PATHS)


def token_from(headers: Headers) -> str | None:
    # 请求头里的 Bearer 令牌；没有这个头或格式不对时返回 None（认证失败返回 401，不附原因）
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


class AccessMiddleware:
    # 认证在路由处理之前完成（第 2.2 节）。写成 ASGI 中间件：响应体逐块经过，
    # 不用 BaseHTTPMiddleware，事件流不会被缓冲
    def __init__(self, app: ASGIApp, *, access: AccessMode = "local",
                 tokens: AccessTokenStore | None = None) -> None:
        self.app = app
        self.access = access
        # 数据目录里的令牌文件：局域网访问方式按它校验（第 6.3 节）
        self.tokens = tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        status = rejection(access=self.access, method=scope["method"], path=scope["path"], headers=headers)
        if status is not None:
            await Response(status_code=status)(scope, receive, send)
            return
        actor = LOCAL_ACTOR if self.access == "local" else self._authenticate(scope["path"], headers)
        if actor is None:
            await Response(status_code=401)(scope, receive, send)
            return
        # 提出者由认证得出（第 6.2 节），写入事件的 actor 字段
        scope.setdefault("state", {})["actor"] = actor
        await self.app(scope, receive, send)

    # 局域网访问方式的令牌校验（第 6.3 节）：页面文件不需要令牌，其余路径需要有效令牌
    def _authenticate(self, path: str, headers: Headers) -> str | None:
        if not requires_token(path):
            return LOCAL_ACTOR
        token = token_from(headers)
        if token is None or self.tokens is None:
            return None
        name = self.tokens.name_of(token)
        return None if name is None else f"user:{name}"

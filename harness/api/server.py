# 以 uvicorn 运行接口层：接口层、应用层与控制核心在同一个进程、同一个事件循环中运行（ADR-0011）。

from __future__ import annotations

import socket
from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from ..app.access_tokens import AccessTokenStore
from ..app.application import Application
from ..app.contracts import AccessMode
from .app import close_event_streams, create_app

# 本机访问方式只能监听回环地址（设计说明第 6.2 节）
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

GRACEFUL_TIMEOUT_SEC = 3.0


class _ReadyServer(uvicorn.Server):
    # 开始接受请求以后通知一次：uvicorn 在 startup() 末尾才置位 started，
    # 而 run() 一直阻塞到服务结束，就绪通知因此由覆写 startup() 给出
    def __init__(self, config: uvicorn.Config, api: FastAPI,
                 on_ready: Callable[[], None] | None) -> None:
        super().__init__(config)
        self._api = api
        self._on_ready = on_ready

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        if self._on_ready is not None:
            self._on_ready()
            self._on_ready = None

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        # 关闭开始时先让等待中的事件流连接干净结束（设计说明第 4.2 节）：uvicorn 随后等这些连接
        # 关闭，打开着的事件流连接因此不拖到优雅退出超时，也不阻止进程退出
        close_event_streams(self._api)
        await super().shutdown(sockets)



def listen_error(access: AccessMode, host: str) -> str | None:
    # 访问方式与监听地址不符合时给出给用户的原因：本机访问方式设置非回环地址时拒绝启动
    if access == "local" and host not in LOOPBACK_HOSTS:
        return f"the local access mode only listens on a loopback address, not {host}"
    return None

def serve(open_application: Callable[[], Application], *, access: AccessMode = "local",
          host: str, port: int, on_ready: Callable[[], None] | None = None,
          data_dir: str | Path | None = None) -> None:
    # 服务进程持有 uvicorn 的 Server：停止服务就是结束这个进程（Ctrl+C，设计说明第 4.2 节）；
    # 进程退出以后由启动处释放数据目录的进程锁。
    # on_ready 在服务开始接受请求以后调用一次（第 4.2 节：此时输出页面地址并打开浏览器）。
    # 局域网访问方式按数据目录里的令牌文件校验（第 6.3 节）
    error = listen_error(access, host)
    if error is not None:
        raise ValueError(error)
    # 页面文件与接口由同一个应用提供，服务进程持有这个应用：关闭开始时由它关闭事件流连接
    api = create_app(open_application, access=access,
                     tokens=None if data_dir is None else AccessTokenStore(data_dir))
    server = _ReadyServer(uvicorn.Config(
        api,
        host=host, port=port, timeout_graceful_shutdown=GRACEFUL_TIMEOUT_SEC,
        # 不重新配置日志：服务日志由启动处写进 <数据目录>/logs/ 并按大小轮换（设计说明第 4.2 节）
        log_config=None), api, on_ready)
    server.run()

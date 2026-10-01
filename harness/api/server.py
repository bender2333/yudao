# 以 uvicorn 运行接口层：接口层、应用层与控制核心在同一个进程、同一个事件循环中运行（ADR-0011）。

from __future__ import annotations

import logging
from collections.abc import Callable

import uvicorn

from ..app.application import Application
from ..app.contracts import AccessMode
from .app import create_app

# 本机访问方式只能监听回环地址（设计说明第 6.2 节）
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# 收到停止请求以后等待进行中的请求结束的上限；事件流是长连接，超过这个时间被强制关闭
GRACEFUL_TIMEOUT_SEC = 3.0

def listen_error(access: AccessMode, host: str) -> str | None:
    # 访问方式与监听地址不符合时给出给用户的原因：本机访问方式设置非回环地址时拒绝启动
    if access == "local" and host not in LOOPBACK_HOSTS:
        return f"the local access mode only listens on a loopback address, not {host}"
    return None

def serve(open_application: Callable[[], Application], *, access: AccessMode = "local",
          host: str, port: int) -> None:
    # 服务进程持有 uvicorn 的 Server：本机停止请求经它把 should_exit 置为真，停止接受新请求、
    # 关闭事件流连接、等待进行中的写入完成；进程退出以后由启动处释放数据目录的进程锁
    error = listen_error(access, host)
    if error is not None:
        raise ValueError(error)
    server = uvicorn.Server(uvicorn.Config(
        lambda: create_app(open_application, access=access, on_stop=lambda: _request_stop(server)),
        host=host, port=port, timeout_graceful_shutdown=GRACEFUL_TIMEOUT_SEC,
        # 不重新配置日志：服务日志由启动处写进 <数据目录>/logs/ 并按大小轮换（设计说明第 4.2 节）
        log_config=None, factory=True))
    server.run()

def _request_stop(server: uvicorn.Server) -> None:
    # 由接口层的停止请求调用：日志留一行，然后让 uvicorn 优雅退出
    logging.getLogger("harness").info("stop requested, shutting down")
    server.should_exit = True

# 以 uvicorn 运行接口层：接口层、应用层与控制核心在同一个进程、同一个事件循环中运行（ADR-0011）。

from __future__ import annotations

from collections.abc import Callable

import uvicorn

from ..app.application import Application
from ..app.contracts import AccessMode
from .app import create_app

# 本机访问方式只能监听回环地址（设计说明第 6.2 节）
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

GRACEFUL_TIMEOUT_SEC = 3.0

def listen_error(access: AccessMode, host: str) -> str | None:
    # 访问方式与监听地址不符合时给出给用户的原因：本机访问方式设置非回环地址时拒绝启动
    if access == "local" and host not in LOOPBACK_HOSTS:
        return f"the local access mode only listens on a loopback address, not {host}"
    return None

def serve(open_application: Callable[[], Application], *, access: AccessMode = "local",
          host: str, port: int) -> None:
    # 服务进程持有 uvicorn 的 Server：停止服务就是结束这个进程（Ctrl+C，设计说明第 4.2 节）；
    # 进程退出以后由启动处释放数据目录的进程锁
    error = listen_error(access, host)
    if error is not None:
        raise ValueError(error)
    server = uvicorn.Server(uvicorn.Config(
        lambda: create_app(open_application, access=access),
        host=host, port=port, timeout_graceful_shutdown=GRACEFUL_TIMEOUT_SEC,
        # 不重新配置日志：服务日志由启动处写进 <数据目录>/logs/ 并按大小轮换（设计说明第 4.2 节）
        log_config=None, factory=True))
    server.run()

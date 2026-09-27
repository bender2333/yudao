# 以 uvicorn 运行接口层：接口层、应用层与控制核心在同一个进程、同一个事件循环中运行（ADR-0011）。

from collections.abc import Callable

import uvicorn

from ..app.application import Application
from .app import create_app

# 本机访问方式只能监听回环地址（设计说明第 6.2 节）
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def serve(open_application: Callable[[], Application], *, host: str, port: int) -> None:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"the local access mode only listens on a loopback address, not {host}")
    uvicorn.run(create_app(open_application), host=host, port=port)

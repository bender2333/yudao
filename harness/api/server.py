# 以 uvicorn 运行接口层：接口层、应用层与控制核心在同一个进程、同一个事件循环中运行（ADR-0011）。

from collections.abc import Callable

import uvicorn

from ..app.application import Application
from ..app.contracts import AccessMode
from .app import create_app

# 本机访问方式只能监听回环地址（设计说明第 6.2 节）
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def listen_error(access: AccessMode, host: str) -> str | None:
    # 访问方式与监听地址不符合时给出给用户的原因：本机访问方式设置非回环地址时拒绝启动
    if access == "local" and host not in LOOPBACK_HOSTS:
        return f"the local access mode only listens on a loopback address, not {host}"
    return None


def serve(open_application: Callable[[], Application], *, access: AccessMode = "local",
          host: str, port: int) -> None:
    error = listen_error(access, host)
    if error is not None:
        raise ValueError(error)
    uvicorn.run(create_app(open_application, access=access), host=host, port=port)

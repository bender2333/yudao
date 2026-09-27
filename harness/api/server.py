# 以 uvicorn 运行接口层：接口层、应用层与控制核心在同一个进程、同一个事件循环中运行（ADR-0011）。

from collections.abc import Callable

import uvicorn

from ..app.application import Application
from .app import create_app


def serve(open_application: Callable[[], Application], *, host: str, port: int) -> None:
    uvicorn.run(create_app(open_application), host=host, port=port)

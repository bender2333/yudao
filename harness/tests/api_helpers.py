import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass

import httpx
import uvicorn

from harness.api.app import create_app
from harness.api.pages import RELEASE_ASSETS
from harness.app.access_tokens import AccessTokenStore
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.contracts import AccessMode
from harness.app.registry import Registry

# uvicorn 自带的日志配置；核对服务日志内容的检查让它自己写日志文件，与命令行启动的方式相同
LOGGING_CONFIG = uvicorn.config.LOGGING_CONFIG

# 接口测试使用真实运行的服务：uvicorn 在测试进程的一个线程中运行 FastAPI 应用，监听本机的空闲端口，
# 测试经 HTTP 请求它；控制核心在服务的生命周期中建立，模型回答由调用方交给 LoopSystem 的 FakeAdapter 给出。
# host 是监听地址，connect 是测试连接的地址（默认回环）
STARTUP_TIMEOUT_SEC = 30

@dataclass
class RunningServer:
    # 一个运行中的接口服务：客户端、服务句柄、端口与宿主线程。停止请求的测试用它核对服务是否真的退出
    client: httpx.Client
    server: uvicorn.Server
    port: int
    thread: threading.Thread

    def wait_stopped(self, timeout: float = STARTUP_TIMEOUT_SEC) -> bool:
        # 服务宿主线程结束（服务进程退出）时返回真
        self.thread.join(timeout)
        return not self.thread.is_alive()

@contextmanager
def running_server(open_application: Callable[[], Application], *,
                   registry: Registry = DEFAULT_REGISTRY, access: AccessMode = "local",
                   host: str = "127.0.0.1", connect: str | None = None,
                   keepalive_sec: float = 15.0,
                   pages: Path | None = None,
                   data_dir: Path | str | None = None,
                   disable_uvicorn_logging: bool = False) -> Iterator[RunningServer]:
    # 与 running_api 相同的启动方式，另外把服务句柄交给调用方。
    # pages 是页面文件目录；不给出时用一个不存在的目录，页面请求按「没有页面文件」回答。
    # data_dir 是令牌文件所在的数据目录，局域网访问方式按它校验访问令牌（第 6.3 节）。
    # disable_uvicorn_logging 交给真实的服务日志处理时用：日志写进数据目录里的日志文件
    server = uvicorn.Server(uvicorn.Config(
        create_app(open_application, registry=registry, access=access, keepalive_sec=keepalive_sec,
                   pages=RELEASE_ASSETS if pages is None else pages,
                   tokens=None if data_dir is None else AccessTokenStore(data_dir)),
        host=host, port=0, log_level="warning", lifespan="on", timeout_graceful_shutdown=3.0,
        log_config=None if disable_uvicorn_logging else LOGGING_CONFIG))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("the API server stopped during startup")
        if time.monotonic() > deadline:
            raise TimeoutError("the API server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    handle = RunningServer(httpx.Client(base_url=f"http://{connect or '127.0.0.1'}:{port}", timeout=30),
                           server, port, thread)
    try:
        yield handle
    finally:
        handle.client.close()
        server.should_exit = True
        thread.join(STARTUP_TIMEOUT_SEC)

@contextmanager
def running_api(open_application: Callable[[], Application], *,
                registry: Registry = DEFAULT_REGISTRY, access: AccessMode = "local",
                host: str = "127.0.0.1", connect: str | None = None,
                keepalive_sec: float = 15.0, pages: Path | None = None,
                data_dir: Path | str | None = None,
                disable_uvicorn_logging: bool = False) -> Iterator[httpx.Client]:
    with running_server(open_application, registry=registry, access=access, host=host, connect=connect,
                        keepalive_sec=keepalive_sec, pages=pages, data_dir=data_dir,
                        disable_uvicorn_logging=disable_uvicorn_logging) as handle:
        yield handle.client

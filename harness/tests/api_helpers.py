import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx
import uvicorn

from harness.api.app import create_app
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.client_update import ReleaseAssets
from harness.app.contracts import AccessMode
from harness.app.registry import Registry

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
                   release_assets: ReleaseAssets | None = None) -> Iterator[RunningServer]:
    # 与 running_api 相同的启动方式，另外把服务句柄交给调用方，并接受本机停止请求
    server = uvicorn.Server(uvicorn.Config(
        create_app(open_application, registry=registry, access=access, keepalive_sec=keepalive_sec,
                   on_stop=lambda: setattr(server, "should_exit", True), release_assets=release_assets),
        host=host, port=0, log_level="warning", lifespan="on", timeout_graceful_shutdown=3.0))
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
                keepalive_sec: float = 15.0) -> Iterator[httpx.Client]:
    with running_server(open_application, registry=registry, access=access, host=host, connect=connect,
                        keepalive_sec=keepalive_sec) as handle:
        yield handle.client

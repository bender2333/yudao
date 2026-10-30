import asyncio
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import uvicorn

from harness.api.app import create_app
from harness.api.pages import RELEASE_ASSETS
from harness.app.access_tokens import AccessTokenStore
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.contracts import AccessMode
from harness.app.registry import Registry
from harness.models import DEPARTMENTS

# uvicorn 自带的日志配置；核对服务日志内容的检查让它自己写日志文件，与命令行启动的方式相同
LOGGING_CONFIG = uvicorn.config.LOGGING_CONFIG

# 接口测试使用真实运行的服务：uvicorn 在测试进程的一个线程中运行 FastAPI 应用，监听本机的空闲端口，
# 测试经 HTTP 请求它；控制核心在服务的生命周期中建立，模型回答由调用方交给 LoopSystem 的 FakeAdapter 给出。
# host 是监听地址，connect 是测试连接的地址（默认回环）
STARTUP_TIMEOUT_SEC = 30


def bearer(token: str) -> dict[str, str]:
    # 请求头里的访问令牌（应用层与接口层设计说明第 6.3 节）：令牌只放在请求头中，不出现在地址里
    return {"Authorization": f"Bearer {token}"}


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
                   disable_uvicorn_logging: bool = False,
                   http_protocol: type[asyncio.Protocol] | None = None) -> Iterator[RunningServer]:
    # 与 running_api 相同的启动方式，另外把服务句柄交给调用方。
    # pages 是页面文件目录；不给出时用一个不存在的目录，页面请求按「没有页面文件」回答。
    # data_dir 是令牌文件所在的数据目录，局域网访问方式按它校验访问令牌（第 6.3 节）。
    # disable_uvicorn_logging 交给真实的服务日志处理时用：日志写进数据目录里的日志文件
    server = uvicorn.Server(uvicorn.Config(
        create_app(open_application, registry=registry, access=access, keepalive_sec=keepalive_sec,
                   pages=RELEASE_ASSETS if pages is None else pages,
                   tokens=None if data_dir is None else AccessTokenStore(data_dir)),
        host=host, port=0, log_level="warning", lifespan="on", timeout_graceful_shutdown=3.0,
        log_config=None if disable_uvicorn_logging else LOGGING_CONFIG,
        http=http_protocol or "auto"))
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
                disable_uvicorn_logging: bool = False,
                http_protocol: type[asyncio.Protocol] | None = None) -> Iterator[httpx.Client]:
    with running_server(open_application, registry=registry, access=access, host=host, connect=connect,
                        keepalive_sec=keepalive_sec, pages=pages, data_dir=data_dir,
                        disable_uvicorn_logging=disable_uvicorn_logging,
                        http_protocol=http_protocol) as handle:
        yield handle.client


# 目录文件中的一条 Provider 配置与一条模型：MODELS_BASE_URL 指向测试内启动的本机模型服务，
# CREDENTIAL_A/B 写进 .env（事件与日志中不出现凭据值）
CREDENTIAL_A = "KEY_A"
CREDENTIAL_B = "KEY_B"


def catalog_provider(provider_id: str, base_url: str, ref: str) -> dict:
    return {"id": provider_id, "name": provider_id, "base_url": base_url,
            "credential_ref": ref, "timeout_sec": 20, "preset_id": "", "models_url": ""}


def catalog_model(model_id: str, provider_id: str, upstream: str, *, protocol: str = "responses") -> dict:
    return {"id": model_id, "provider_id": provider_id, "model": upstream, "protocol": protocol,
            "context_window": 32000, "max_output_tokens": 2048, "capability_source": ""}


def catalog_document(client) -> dict:
    # 当前保存的目录文档，经服务的 catalog.document 查询读出
    response = client.get("/api/queries/catalog.document")
    assert response.status_code == 200, response.text
    return response.json()["data"]


class OpenedCatalog:
    # 真实目录文件、真实 .env、真实数据目录上打开的应用：base_url 指向测试内启动的本机模型服务。
    # 所有部门默认都指向 model-a，使 model-a 被部门默认引用，model-a2 与 model-b 没有任何引用方
    def __init__(self, tmp_path, *, base_url: str = "http://127.0.0.1:1/v1"):
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self._base_url = base_url
        self.applications: list[Application] = []
        self.write_document()

    def write_document(self) -> None:
        providers = [catalog_provider("provider-a", self._base_url, CREDENTIAL_A),
                     catalog_provider("provider-b", self._base_url, CREDENTIAL_B)]
        models = [catalog_model("model-a", "provider-a", "upstream-a"),
                  catalog_model("model-a2", "provider-a", "upstream-a2"),
                  catalog_model("model-b", "provider-b", "upstream-b")]
        document = {
            "providers": providers,
            "models": models,
            "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a"}
                         for department in DEPARTMENTS},
        }
        self.config.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def __call__(self) -> Application:
        self.dotenv.write_text(f"{CREDENTIAL_A}=issue90-key-a\n{CREDENTIAL_B}=issue90-key-b\n", encoding="utf-8")
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def application(self) -> Application:
        return self.applications[-1]

    @property
    def system(self):
        return self.application.system

    def admit(self, *pairs: tuple[str, str]) -> None:
        for provider_id, model_id in pairs:
            self.system.facade.record_admission(provider_id, model_id, admitted_model=model_id)

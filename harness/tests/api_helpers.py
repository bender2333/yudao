import asyncio
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
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
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

# uvicorn 自带的日志配置；核对服务日志内容的检查让它自己写日志文件，与命令行启动的方式相同
LOGGING_CONFIG = uvicorn.config.LOGGING_CONFIG

# 接口测试使用真实运行的服务：uvicorn 在测试进程的一个线程中运行 FastAPI 应用，监听本机的空闲端口，
# 测试经 HTTP 请求它；控制核心在服务的生命周期中建立，模型回答由调用方交给 LoopSystem 的 FakeAdapter 给出。
# host 是监听地址，connect 是测试连接的地址（默认回环）。
#
# 服务就绪的等待上限取按层的表（harness/tests/wait_limits.py）：启动要做约一秒的 CPU 工作（建立路由、
# 算合同摘要），机器被别的用例占满时这段工作按分到的 CPU 拉长；写死的 30 秒在满负载时会先到上限，
# 服务其实还在启动（工单 #1566，六条用例同时在就绪之前超时；工单 #1437，test_catalog_api.py 的两条
# 用例在 30.11 秒、30.06 秒上先到，同一次运行里别的起服务用例也被拉到 14 至 24 秒）。上限是本层每条
# 用例上限的一半，到了上限以一条写明在等什么的失败结束，不等 pytest-timeout 结束整个进程。
SERVER_READY_TIMEOUT_SEC = WAIT_FOR_HOST_WORK_SEC
# 停止服务是主机上的收尾，正常在一秒内完成：短上限只用来防止一直等待
STOP_TIMEOUT_SEC = 30

# 服务起不来时的失败信息（工单 #1447）：到上限或者服务线程退出时只说「没有起来」看不出卡在哪一步，
# 因此留下服务线程最后的输出，并在失败信息里写出等待上限与用时、监听地址与测试连接的地址、
# 应用打开走到哪一步、服务线程是否还在。uvicorn 把启动失败与异常写在 uvicorn.error 上。
SERVER_OUTPUT_LINES = 20


class _ServerOutput(logging.Handler):
    # 服务线程的日志留在内存里：失败信息带上最后若干行（启动失败的异常与 uvicorn 的结论都在里面）
    def __init__(self) -> None:
        super().__init__()
        self._lines: deque[str] = deque(maxlen=SERVER_OUTPUT_LINES)
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._lines.append(self.format(record))
        except Exception:  # noqa: BLE001 - 诊断输出出错不应该让测试结果变样
            self.handleError(record)

    def tail(self) -> str:
        return "\n".join(self._lines) if self._lines else "(no output)"


@dataclass
class _Startup:
    # 服务线程里走到哪一步、为什么退出：失败信息据此说明在等什么
    opened_at: float | None = None
    open_finished_at: float | None = None
    open_error: BaseException | None = None
    exit_reason: BaseException | None = None
    output: _ServerOutput = field(default_factory=_ServerOutput)

    def opening(self, now: float) -> str:
        if self.opened_at is None:
            return "the application has not started opening"
        if self.open_finished_at is None:
            return f"the application has been opening for {now - self.opened_at:.1f} seconds"
        if self.open_error is not None:
            return (f"the application failed to open after {self.open_finished_at - self.opened_at:.1f} seconds: "
                    f"{self.open_error!r}")
        return f"the application opened in {self.open_finished_at - self.opened_at:.1f} seconds"


def _bound_port(server: uvicorn.Server) -> int | None:
    # 服务监听端口 0，由操作系统在绑定时分配：绑定以后才有这个端口，绑定以前为 None
    for bound in getattr(server, "servers", None) or []:
        sockets = getattr(bound, "sockets", None) or []
        if sockets:
            return sockets[0].getsockname()[1]
    return None


def _startup_failure(startup: _Startup, *, what: str, elapsed: float, host: str,
                     connect: str | None, server: uvicorn.Server,
                     thread: threading.Thread) -> str:
    # 一条说明在等什么的失败信息：上限与用时、监听地址与测试连接的地址、应用打开走到哪一步、
    # 服务线程是否还在与它的退出原因、服务线程最后的输出（docs/design/test-pyramid.md「测试的写法」第 7 条）
    port = _bound_port(server)
    address = f"{connect or '127.0.0.1'}:{port if port is not None else '<not assigned yet>'}"
    state = "is still starting" if thread.is_alive() else "has exited"
    if startup.exit_reason is not None:
        state += f" with {startup.exit_reason!r}"
    return "\n".join([
        f"{what} (waited {elapsed:.1f} seconds; listening on {host}:{server.config.port}; "
        f"the test connects to http://{address}; {startup.opening(time.monotonic())}; "
        f"the server thread {state})",
        f"--- server output (last {SERVER_OUTPUT_LINES} lines) ---",
        startup.output.tail(),
    ])


def bearer(token: str) -> dict[str, str]:
    # 请求头里的访问令牌（应用层与接口层 docs/design/app-and-interface.md「令牌与 TLS」）：令牌只放在请求头中，不出现在地址里
    return {"Authorization": f"Bearer {token}"}


@dataclass
class RunningServer:
    # 一个运行中的接口服务：客户端、服务句柄、端口与宿主线程。停止请求的测试用它核对服务是否真的退出
    client: httpx.Client
    server: uvicorn.Server
    port: int
    thread: threading.Thread

    def wait_stopped(self, timeout: float = STOP_TIMEOUT_SEC) -> bool:
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
    # data_dir 是令牌文件所在的数据目录，局域网访问方式按它校验访问令牌。
    # disable_uvicorn_logging 交给真实的服务日志处理时用：日志写进数据目录里的日志文件
    # http_protocol 让并发测试通过真实协议处理器发出关闭信号。
    startup = _Startup()

    def open_tracked() -> Application:
        # 应用在服务线程的 lifespan 里打开（建控制核心、算合同摘要）：记下走到哪一步，
        # 起不来时的失败信息才能说是哪一步慢或者哪一步出错
        startup.opened_at = time.monotonic()
        try:
            return open_application()
        except BaseException as exc:
            startup.open_error = exc
            raise
        finally:
            startup.open_finished_at = time.monotonic()

    server = uvicorn.Server(uvicorn.Config(
        create_app(open_tracked, registry=registry, access=access, keepalive_sec=keepalive_sec,
                   pages=RELEASE_ASSETS if pages is None else pages,
                   tokens=None if data_dir is None else AccessTokenStore(data_dir)),
        host=host, port=0, log_level="warning", lifespan="on", timeout_graceful_shutdown=3.0,
        log_config=None if disable_uvicorn_logging else LOGGING_CONFIG,
        http=http_protocol or "auto"))
    output_logger = logging.getLogger("uvicorn.error")
    output_logger.addHandler(startup.output)

    def serve() -> None:
        # 服务线程退出的原因带进失败信息：启动失败时 uvicorn 以 SystemExit(3) 结束线程
        try:
            server.run()
        except BaseException as exc:
            startup.exit_reason = exc
            raise

    thread = threading.Thread(target=serve, daemon=True)
    started_at = time.monotonic()
    try:
        thread.start()
        deadline = started_at + SERVER_READY_TIMEOUT_SEC
        while not server.started:
            if not thread.is_alive():
                raise RuntimeError(_startup_failure(
                    startup, what="the API server stopped during startup",
                    elapsed=time.monotonic() - started_at, host=host, connect=connect,
                    server=server, thread=thread))
            if time.monotonic() > deadline:
                # 等不到就绪：先按此刻的样子写好失败信息（说明在等什么），再让服务线程与它打开的应用退出，
                # 不在进程里留下一个还在启动的服务
                message = _startup_failure(
                    startup,
                    what=f"the API server did not start within {SERVER_READY_TIMEOUT_SEC:g} seconds",
                    elapsed=time.monotonic() - started_at, host=host, connect=connect,
                    server=server, thread=thread)
                server.should_exit = True
                thread.join(STOP_TIMEOUT_SEC)
                raise TimeoutError(message)
            time.sleep(0.01)
    finally:
        output_logger.removeHandler(startup.output)
    port = server.servers[0].sockets[0].getsockname()[1]
    # 测试在两次请求之间执行领域检查，耗时由调度决定；每次响应结束后释放空闲连接，
    # 避免下一次请求选中连接之后，与服务的空闲关闭计时竞争。正在读取的事件流仍保持连接。
    client = httpx.Client(base_url=f"http://{connect or '127.0.0.1'}:{port}", timeout=30,
                          limits=httpx.Limits(max_keepalive_connections=0))
    handle = RunningServer(client, server, port, thread)
    try:
        yield handle
    finally:
        handle.client.close()
        server.should_exit = True
        thread.join(STOP_TIMEOUT_SEC)

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

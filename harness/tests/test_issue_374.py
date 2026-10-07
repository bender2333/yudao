# 手动启动、停止与升级 Yudao 服务（工单 #374，网页界面的提供与发布设计说明第 4.2、5.1 节）。
#
# 启动、停止、浏览器与进程锁用真实的服务进程：启动方式与用户在命令行里做的一样（yudao api），
# BROWSER 环境变量指向一个记录地址的脚本，核对打开的是哪个地址。停止用 Windows 的
# CTRL_BREAK_EVENT（与 Ctrl+C 同一条路径：uvicorn 的 HANDLED_SIGNALS 含 SIGBREAK），POSIX 上发 SIGINT。
# 进行中的 run 在服务进程里自动继续，用真实的 uvicorn 事件循环核对（那里没有 asyncio.run 的位置）。

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.models import TERMINAL_PHASES
from harness.projection import project_run
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_server
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

REPO_ROOT = Path(__file__).resolve().parents[2]
# 服务进程启动时导入模型 SDK 并构建流事件的模型，机器负载高时要一分钟以上
STARTUP_TIMEOUT_SEC = 300
# 关闭以后等待进程退出的时间：服务停止接受新请求、关闭事件流连接、等待进行中的写入以后进程退出
SHUTDOWN_TIMEOUT_SEC = 30


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _recording_browser(directory: Path, recorded: Path) -> Path:
    # 标准库 webbrowser 读 BROWSER 环境变量（设计说明第 12 节），用一条命令把打开的地址记进文件
    script = directory / "record-browser.cmd"
    script.write_text(f'@echo off\r\necho %1 > "{recorded}"\r\n', encoding="utf-8")
    return script


@pytest.fixture
def service(tmp_path: Path) -> Iterator[Callable[..., subprocess.Popen]]:
    # 启动真实的服务进程并在测试结束时按进程号结束它们：测试用的进程组与用户一样是新的，
    # 因此按 Ctrl+C 与 Ctrl+Break 只送达这一组
    started: list[subprocess.Popen] = []

    def start(data_dir: Path, port: int, log: Path, *, extra: list[str] | None = None,
              browser: Path | None = None) -> subprocess.Popen:
        environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
        if browser is None:
            environment.pop("BROWSER", None)
        else:
            environment["BROWSER"] = str(browser)
        options = ["--data-dir", str(data_dir), "--port", str(port), "--provider-config", ""]
        options += extra or []
        with log.open("wb") as output:
            process = subprocess.Popen(
                [sys.executable, "-m", "harness", "api", *options], cwd=REPO_ROOT, env=environment,
                stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        started.append(process)
        return process

    yield start
    for process in reversed(started):
        if process.poll() is not None:
            continue
        # 结束整个进程树：Windows 上虚拟环境的 python.exe 会再启动真正的解释器
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(SHUTDOWN_TIMEOUT_SEC)


def _serving(port: int, log: Path, deadline: float) -> None:
    limit = time.monotonic() + deadline
    while time.monotonic() < limit:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/capabilities", timeout=2).status_code == 200:
                return
        except httpx.TransportError:
            time.sleep(0.2)
    raise TimeoutError(log.read_text(encoding="utf-8", errors="replace"))


def _ready(process: subprocess.Popen, port: int, log: Path) -> str:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while True:
        assert process.poll() is None, log.read_text(encoding="utf-8", errors="replace")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/capabilities", timeout=2).status_code == 200:
                return log.read_text(encoding="utf-8", errors="replace")
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(log.read_text(encoding="utf-8", errors="replace"))
        time.sleep(0.2)


def _opened_address(recorded: Path) -> str | None:
    return recorded.read_text(encoding="utf-8").strip() if recorded.exists() else None


def _wait_opened(recorded: Path, deadline: float) -> str | None:
    limit = time.monotonic() + deadline
    while time.monotonic() < limit:
        address = _opened_address(recorded)
        if address is not None:
            return address
        time.sleep(0.1)
    return None


def _stop(process: subprocess.Popen) -> int:
    # 用户在命令行窗口里按 Ctrl+C：Windows 上 Ctrl+Break 走同一条路径（uvicorn 捕获 SIGBREAK），
    # 且可以送达指定的服务进程组；CTRL_C_EVENT 只能送达调用者自己的进程组，因此这里不用它
    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
    return process.wait(SHUTDOWN_TIMEOUT_SEC)


def test_the_page_opens_in_the_browser_once_the_service_is_ready(service, tmp_path):
    # 不带 --no-browser：服务就绪以后在命令行输出页面地址，并用标准库的 webbrowser 打开同一个地址
    port = _free_port()
    log = tmp_path / "open.log"
    recorded = tmp_path / "opened.txt"
    process = service(tmp_path / "data", port, log, browser=_recording_browser(tmp_path, recorded))
    assert f"web: http://127.0.0.1:{port}/" in _ready(process, port, log)
    assert _wait_opened(recorded, time.monotonic() + 30) == f"http://127.0.0.1:{port}/"


def test_no_browser_leaves_the_page_closed(service, tmp_path):
    # 带 --no-browser：不打开浏览器，也不输出页面地址（供测试、走查与没有桌面的控制主机）
    port = _free_port()
    log = tmp_path / "quiet.log"
    recorded = tmp_path / "opened.txt"
    process = service(tmp_path / "data", port, log, extra=["--no-browser"],
                      browser=_recording_browser(tmp_path, recorded))
    text = _ready(process, port, log)
    assert "web: http" not in text
    assert _wait_opened(recorded, 3) is None


def test_the_lan_access_mode_opens_the_address_of_this_machine(service, tmp_path):
    # 局域网访问方式下打开的同样是本机地址：浏览器在本机地址上保留系统通知与安装应用的设置
    port = _free_port()
    log = tmp_path / "lan.log"
    recorded = tmp_path / "opened.txt"
    process = service(tmp_path / "data", port, log, extra=["--access", "lan", "--host", "0.0.0.0"],
                      browser=_recording_browser(tmp_path, recorded))
    _ready(process, port, log)
    assert _wait_opened(recorded, time.monotonic() + 30) == f"http://127.0.0.1:{port}/"
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=STARTUP_TIMEOUT_SEC) as client:
        assert client.get("/api/capabilities").json()["deployment"]["access"] == "lan"


def test_ctrl_c_stops_the_service_and_releases_the_data_directory(service, tmp_path):
    # Ctrl+C 停止服务：进程正常退出，数据目录的进程锁释放，第二个服务进程可以取得同一个数据目录
    data_dir = tmp_path / "data"
    port = _free_port()
    log = tmp_path / "stop.log"
    process = service(data_dir, port, log, extra=["--no-browser"])
    _ready(process, port, log)
    assert _stop(process) == 0

    restarted_port = _free_port()
    restarted = service(data_dir, restarted_port, tmp_path / "restart.log", extra=["--no-browser"])
    _serving(restarted_port, tmp_path / "restart.log", time.monotonic() + STARTUP_TIMEOUT_SEC)


def test_an_open_event_stream_does_not_hold_the_process(service, tmp_path):
    # 打开着的事件流连接不阻止退出：关闭开始时先让等待中的连接干净结束，进程随后退出，
    # 不拖到接口层关闭时的超时
    port = _free_port()
    log = tmp_path / "stream.log"
    process = service(tmp_path / "data", port, log, extra=["--no-browser"])
    _ready(process, port, log)
    with httpx.Client(timeout=None) as client:
        with client.stream("GET", f"http://127.0.0.1:{port}/api/events?after=0") as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            began = time.monotonic()
            assert _stop(process) == 0



def _completion_script():
    # 中断在产品提交规格以后，恢复时剩下三个回答：计划、交付与放行评审
    return [plan_turn(), delivery_turn(), review_turn("release", "checks passed on the current snapshot")]


def _interrupted_data_dir(data_dir: Path) -> tuple[str, str]:
    # 一份有未结束 run 的数据目录：产品已经提交规格，run 停在工程部门请求模型以前；
    # 这是恢复契约里的进行中 run，下次启动时由启动序列取得执行权并继续
    system = LoopSystem.for_testing(data_dir, FakeAdapter([product_spec()]))
    project_id = system.projects.register("停止与继续", "核对进行中的 run 在下次启动时自动继续")
    work_item_id, run_id = system.projects.start_work_item(project_id, "停下时进行中的事项")
    system.activate_once(run_id)
    assert project_run(system.store, run_id).phase not in TERMINAL_PHASES
    system.close()
    return project_id, run_id


def test_a_run_in_progress_continues_at_the_next_start(tmp_path):
    # 停止服务不等待 run 结束；进行中的 run 在服务进程的事件循环中由启动序列自动继续到结束
    # （工单 #374 发现：服务进程里 asyncio.run 不能在事件循环中调用）
    data_dir = tmp_path / "data"
    _project_id, run_id = _interrupted_data_dir(data_dir)
    applications: list[Application] = []

    def open_application() -> Application:
        application = Application(LoopSystem.for_testing(
            data_dir, FakeAdapter(_completion_script())))
        applications.append(application)
        return application

    with running_server(open_application):
        system = applications[-1].system
        assert run_id in system.resumed_runs, "启动时没有取得执行权"
        deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
        while time.monotonic() < deadline:
            if project_run(system.store, run_id).phase in TERMINAL_PHASES:
                break
            time.sleep(0.05)
        projection = project_run(system.store, run_id)
        assert (projection.phase, projection.stop_reason) == ("DONE", "released")
# 手动启动、停止与升级 Yudao 服务（工单 #374，网页界面的提供与发布设计说明第 4.2、5.1 节）。
#
# 启动、停止、浏览器与进程锁用真实的服务进程：启动方式与用户在命令行里做的一样（yudao api），
# BROWSER 环境变量指向一个记录地址的脚本，核对打开的是哪个地址。停止用 Windows 的
# CTRL_BREAK_EVENT（与 Ctrl+C 同一条路径：uvicorn 的 HANDLED_SIGNALS 含 SIGBREAK），POSIX 上发 SIGINT。
# 进行中的 run 在服务进程里自动继续，用真实的 uvicorn 事件循环核对（那里没有 asyncio.run 的位置）。
# 服务监听的端口由操作系统分配（--port 0），服务就绪以后在输出里报告实际端口：先占一个空闲端口
# 再交给服务进程绑定的写法在多进程运行中会冲突（测试分层设计说明第 5 节第 6 项）。

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

import httpx
import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.models import TERMINAL_STATUSES
from harness.data_directory import LOG_DIR, LOG_FILE
from harness.projection import project_run
from harness.proposals import delivery_turn, product_spec
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_server
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
from harness.tests.helpers import quality_turns

REPO_ROOT = Path(__file__).resolve().parents[2]
# 服务进程启动时导入模型 SDK 并构建流事件的模型，机器负载高时要一分钟以上
STARTUP_TIMEOUT_SEC = 300
# 关闭以后等待进程退出的时间：服务停止接受新请求、关闭事件流连接、等待进行中的写入以后进程退出
SHUTDOWN_TIMEOUT_SEC = 30

PORT_LINE = "port: "

class Started(NamedTuple):
    # 一个已启动的服务进程：port 是服务绑定端口 0 以后操作系统分配的实际端口
    process: subprocess.Popen
    port: int
    output: Path
    data_dir: Path

def _text(path: Path) -> str:
    # 服务进程的输出：标准错误与标准输出合并写进同一个文件（stderr=subprocess.STDOUT）
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

def _diagnostics(process: subprocess.Popen, log: Path, data_dir: Path) -> str:
    # 启动失败时的诊断输出：退出码、进程自身的输出，以及数据目录里的日志。服务进程绑定端口失败
    # 时以退出码 3 退出（uvicorn 的 STARTUP_FAILURE），进程的输出里只有一行 logs:，原因写在
    # 数据目录的日志里：两者都带上，失败信息才说明原因
    data_log = data_dir / LOG_DIR / LOG_FILE
    return (f"退出码 {process.poll()}\n"
            f"--- process output ---\n{_text(log)}\n"
            f"--- {data_log} ---\n{_text(data_log)}")

def _reported_port(log: Path) -> int | None:
    for line in _text(log).splitlines():
        if line.startswith(PORT_LINE):
            return int(line[len(PORT_LINE):])
    return None

def _wait_port(process: subprocess.Popen, log: Path, data_dir: Path) -> int:
    # 服务自己绑定端口 0，就绪以后在输出里报告实际端口：--port 0 时启动方只能从这里得知它
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while True:
        port = _reported_port(log)
        if port is not None:
            return port
        assert process.poll() is None, _diagnostics(process, log, data_dir)
        if time.monotonic() > deadline:
            raise TimeoutError(_diagnostics(process, log, data_dir))
        time.sleep(0.1)

def _recording_browser(directory: Path, recorded: Path) -> Path:
    # 标准库 webbrowser 读 BROWSER 环境变量（设计说明第 12 节），用一条命令把打开的地址记进文件
    script = directory / "record-browser.cmd"
    script.write_text(f'@echo off\r\necho %1 > "{recorded}"\r\n', encoding="utf-8")
    return script

@pytest.fixture
def service(tmp_path: Path) -> Iterator[Callable[..., Started]]:
    # 启动真实的服务进程并在测试结束时按进程号结束它们：测试用的进程组与用户一样是新的，
    # 因此按 Ctrl+C 与 Ctrl+Break 只送达这一组
    started: list[subprocess.Popen] = []

    def start(data_dir: Path, log: Path, *, extra: list[str] | None = None,
              browser: Path | None = None) -> Started:
        # 服务进程绑定端口 0，由操作系统分配实际端口：启动方先占一个空闲端口再交给服务进程的
        # 写法在多进程运行中会冲突——占用与绑定之间隔着一秒多的启动过程，这段间隔里端口可能
        # 已被别的进程取走，服务进程随后以退出码 3 退出（uvicorn 的 STARTUP_FAILURE）
        environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
        if browser is None:
            environment.pop("BROWSER", None)
        else:
            environment["BROWSER"] = str(browser)
        options = ["--data-dir", str(data_dir), "--port", "0", "--provider-config", ""]
        options += extra or []
        with log.open("wb") as output:
            process = subprocess.Popen(
                [sys.executable, "-m", "harness", "api", *options], cwd=REPO_ROOT, env=environment,
                stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        started.append(process)
        return Started(process, _wait_port(process, log, data_dir), log, data_dir)

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

def _serving(started: Started, deadline: float) -> None:
    limit = time.monotonic() + deadline
    while time.monotonic() < limit:
        try:
            if httpx.get(f"http://127.0.0.1:{started.port}/api/capabilities", timeout=2).status_code == 200:
                return
        except httpx.TransportError:
            time.sleep(0.2)
    raise TimeoutError(_failed(started, "服务没有开始应答"))

def _failed(started: Started, reason: str) -> str:
    return f"{reason}\n{_diagnostics(started.process, started.output, started.data_dir)}"

def _ready(started: Started, *, headers: dict[str, str] | None = None) -> str:
    # 端口由服务进程报告，这里只等它开始应答：端口探测不再承担判断服务是否启动成功的职责
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while True:
        assert started.process.poll() is None, _failed(started, "服务进程在就绪以前退出")
        try:
            url = f"http://127.0.0.1:{started.port}/api/capabilities"
            response = httpx.get(url, timeout=2, headers=headers)
            if response.status_code == 200:
                return _text(started.output)
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(_failed(started, "服务没有开始应答"))
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
    recorded = tmp_path / "opened.txt"
    started = service(tmp_path / "data", tmp_path / "open.log",
                      browser=_recording_browser(tmp_path, recorded))
    address = f"http://127.0.0.1:{started.port}/"
    assert f"web: {address}" in _ready(started)
    assert _wait_opened(recorded, time.monotonic() + 30) == address

def test_no_browser_leaves_the_page_closed(service, tmp_path):
    # 带 --no-browser：不打开浏览器，也不输出页面地址（供测试、走查与没有桌面的控制主机）
    recorded = tmp_path / "opened.txt"
    started = service(tmp_path / "data", tmp_path / "quiet.log", extra=["--no-browser"],
                      browser=_recording_browser(tmp_path, recorded))
    assert "web: http" not in _ready(started)
    assert _wait_opened(recorded, 3) is None


def test_ctrl_c_stops_the_service_and_releases_the_data_directory(service, tmp_path):
    # Ctrl+C 停止服务：进程正常退出，数据目录的进程锁释放，第二个服务进程可以取得同一个数据目录
    data_dir = tmp_path / "data"
    started = service(data_dir, tmp_path / "stop.log", extra=["--no-browser"])
    _ready(started)
    assert _stop(started.process) == 0

    restarted = service(data_dir, tmp_path / "restart.log", extra=["--no-browser"])
    _serving(restarted, time.monotonic() + STARTUP_TIMEOUT_SEC)

def test_an_open_event_stream_does_not_hold_the_process(service, tmp_path):
    # 打开着的事件流连接不阻止退出：关闭开始时先让等待中的连接干净结束，进程随后退出，
    # 不拖到接口层关闭时的超时
    started = service(tmp_path / "data", tmp_path / "stream.log", extra=["--no-browser"])
    _ready(started)
    with httpx.Client(timeout=None) as client:
        url = f"http://127.0.0.1:{started.port}/api/events?after=0"
        with client.stream("GET", url) as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            began = time.monotonic()
            assert _stop(started.process) == 0

def _completion_script():
    # 中断在产品提交规格以后，恢复时剩下交付与放行评审
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def _interrupted_data_dir(data_dir: Path) -> tuple[str, str]:
    # 一份有未结束 run 的数据目录：产品已经提交规格，run 停在工程部门请求模型以前；
    # 这是恢复契约里的进行中 run，下次启动时由启动序列取得执行权并继续
    system = LoopSystem.for_testing(data_dir, FakeAdapter([product_spec()]))
    project_id = system.projects.register("停止与继续", "核对进行中的 run 在下次启动时自动继续")
    work_item_id, run_id = system.projects.start_work_item(project_id, "停下时进行中的事项")
    system.activate_once(run_id)
    assert project_run(system.store, run_id).status not in TERMINAL_STATUSES
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
            if project_run(system.store, run_id).status in TERMINAL_STATUSES:
                break
            time.sleep(0.05)
        projection = project_run(system.store, run_id)
        assert (projection.status, projection.stop_reason) == ("done", "released")
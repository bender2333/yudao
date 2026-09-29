import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from harness.__main__ import main

# 同一个数据目录只允许一个服务进程（应用层与接口层设计说明第 7.2 节）：新接口（python -m harness api）与旧控制台
# （serve）取得同一个数据目录的进程锁。测试启动真实的服务进程，经 HTTP 确认服务在运行。

REPO_ROOT = Path(__file__).resolve().parents[2]
# 服务进程启动时导入模型 SDK 并构建流事件的模型，机器负载高时要一分钟以上
STARTUP_TIMEOUT_SEC = 300
IN_USE = "data directory is in use by another service process"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _start(workdir: Path, command: str, data_dir: Path, port: int, log: Path, *,
           options_first: bool = False, extra: tuple[str, ...] = ()) -> subprocess.Popen:
    # 工作目录放在测试目录中，默认的模型目录与凭据文件路径都落在这里；PYTHONPATH 指向本仓库的 harness。
    # options_first 时选项写在子命令之前。extra 是这些公共选项之外的选项。
    # 虚拟环境在 Windows 上的 python.exe 会再启动真正的解释器，所以服务在新的进程组（会话）中启动，按进程树结束
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    options = ["--data-dir", str(data_dir), "--port", str(port), "--provider-config", "", *extra]
    arguments = [*options, command] if options_first else [command, *options]
    with log.open("wb") as output:
        return subprocess.Popen(
            [sys.executable, "-m", "harness", *arguments],
            cwd=workdir, env=environment, stdout=output, stderr=subprocess.STDOUT, **spawn,
        )


def _wait_until_serving(process: subprocess.Popen, url: str, log: Path) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        assert process.poll() is None, log.read_text(encoding="utf-8", errors="replace")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"service did not start: {log.read_text(encoding='utf-8', errors='replace')}")


def _refused(process: subprocess.Popen, log: Path) -> str:
    try:
        assert process.wait(STARTUP_TIMEOUT_SEC) == 1, log.read_text(encoding="utf-8", errors="replace")
    finally:
        if process.poll() is None:
            _stop(process)
    return log.read_text(encoding="utf-8", errors="replace")


def _stop(process: subprocess.Popen) -> None:
    # 结束整个进程树：Windows 用 taskkill，POSIX 结束服务所在会话的进程组
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(STARTUP_TIMEOUT_SEC)


def test_two_service_processes_cannot_use_the_same_data_directory(tmp_path):
    data_dir = tmp_path / "data"
    api_port = _free_port()
    api = _start(tmp_path, "api", data_dir, api_port, tmp_path / "api.log")
    try:
        _wait_until_serving(api, f"http://127.0.0.1:{api_port}/api/queries/system.status", tmp_path / "api.log")
        # 新接口运行期间，第二个新接口与旧控制台都不能使用同一个数据目录
        second = _start(tmp_path, "api", data_dir, _free_port(), tmp_path / "second.log")
        assert IN_USE in _refused(second, tmp_path / "second.log")
        console = _start(tmp_path, "serve", data_dir, _free_port(), tmp_path / "console.log")
        assert IN_USE in _refused(console, tmp_path / "console.log")
        # 另一个数据目录不受影响；选项写在子命令之前同样有效
        other_port = _free_port()
        other = _start(tmp_path, "api", tmp_path / "other", other_port, tmp_path / "other.log", options_first=True)
        try:
            _wait_until_serving(other, f"http://127.0.0.1:{other_port}/api/capabilities", tmp_path / "other.log")
            assert (tmp_path / "other" / "events.sqlite").is_file() and (tmp_path / "other" / "service.lock").exists()
        finally:
            _stop(other)
    finally:
        _stop(api)

    # 服务进程退出以后锁被释放：旧控制台可以启动；它运行期间新接口不能使用这个数据目录
    console_port = _free_port()
    console = _start(tmp_path, "serve", data_dir, console_port, tmp_path / "console-after.log")
    try:
        _wait_until_serving(console, f"http://127.0.0.1:{console_port}/api/health", tmp_path / "console-after.log")
        refused = _start(tmp_path, "api", data_dir, _free_port(), tmp_path / "refused.log")
        assert IN_USE in _refused(refused, tmp_path / "refused.log")
    finally:
        _stop(console)


def test_the_api_only_listens_on_a_loopback_address(tmp_path, capsys):
    # 本机访问方式（设计说明第 6.2 节）：设置非回环地址时拒绝启动，不取得锁，也不建立数据目录
    assert main(["api", "--host", "0.0.0.0", "--data-dir", str(tmp_path / "data")]) == 1
    assert "only listens on a loopback address, not 0.0.0.0" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_the_api_serves_the_local_network_with_the_lan_access_mode(tmp_path):
    # 局域网访问方式（设计说明第 6.2 节）：监听任意地址，能力清单列出访问方式；
    # Host 不受本机名称限制，Origin 只接受桌面客户端页面的来源
    data_dir = tmp_path / "lan"
    port = _free_port()
    log = tmp_path / "lan.log"
    api = _start(tmp_path, "api", data_dir, port, log, options_first=True,
                 extra=("--access", "lan", "--host", "0.0.0.0"))
    try:
        _wait_until_serving(api, f"http://127.0.0.1:{port}/api/capabilities", log)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=STARTUP_TIMEOUT_SEC) as client:
            capabilities = client.get("/api/capabilities")
            other_host = client.get("/api/capabilities", headers={"Host": "control-host"})
            rejected = client.get("/api/capabilities", headers={"Origin": "https://evil.example"})
        assert capabilities.status_code == 200
        assert capabilities.json()["deployment"]["access"] == "lan"
        assert other_host.status_code == 200
        assert rejected.status_code == 403
    finally:
        _stop(api)

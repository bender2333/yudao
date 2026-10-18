import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

from harness.__main__ import main
from harness.models import utc_now

# 同一个数据目录只允许一个服务进程（应用层与接口层设计说明第 7.2 节）：新接口（python -m harness api）
# 取得数据目录的进程锁。测试启动真实的服务进程，经 HTTP 确认服务在运行。

REPO_ROOT = Path(__file__).resolve().parents[2]
# 服务进程启动时导入模型 SDK 并构建流事件的模型，机器负载高时要一分钟以上
STARTUP_TIMEOUT_SEC = 300
IN_USE = "data directory is in use by another service process"


PORT_LINE = "port: "


def _started(workdir: Path, command: str, data_dir: Path, log: Path, *,
             options_first: bool = False, extra: tuple[str, ...] = ()) -> tuple[subprocess.Popen, int]:
    # 启动服务并取它实际监听的端口：子进程自己绑定端口 0，就绪以后在日志输出一行报告实际端口；
    # 由调用方先占用再释放端口的写法在多进程运行中会冲突
    process = _start(workdir, command, data_dir, 0, log, options_first=options_first, extra=extra)
    return process, _bound_port(process, log)


def _bound_port(process: subprocess.Popen, log: Path) -> int:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        assert process.poll() is None, log.read_text(encoding="utf-8", errors="replace")
        port = next((line[len(PORT_LINE):].strip() for line in _lines(log) if line.startswith(PORT_LINE)), None)
        if port is not None:
            return int(port)
        time.sleep(0.1)
    raise TimeoutError(f"service did not report its port: {log.read_text(encoding='utf-8', errors='replace')}")


def _lines(log: Path) -> list:
    # 日志文件由服务进程一直打开着写入：按读到的字节数读取，读不到内容时为空
    try:
        return log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


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


def _wait_until_serving(process: subprocess.Popen, url: str, log: Path, *, token: str | None = None) -> None:
    # 就绪的判断是第一次成功收到 200：局域网访问方式的接口路径需要访问令牌（第 6.3 节），
    # 没有令牌时一直是 401，因此请求带上这次建好的令牌
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        assert process.poll() is None, log.read_text(encoding="utf-8", errors="replace")
        try:
            if httpx.get(url, timeout=2, headers=headers).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"service did not start: {log.read_text(encoding='utf-8', errors='replace')}")


def _lan_token(data_dir: Path) -> str:
    # 局域网访问方式下的一个令牌：令牌文件在服务启动前建立，服务按它校验（第 6.3 节）
    from harness.app.access_tokens import AccessTokenStore

    _entry, token = AccessTokenStore(data_dir).create("control-host", now=utc_now())
    return token


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


def _race(workdir: Path, data_dir: Path, name: str) -> tuple[subprocess.Popen, int, Path]:
    # 两个服务进程同时启动，竞争同一个数据目录：恰好一个取得锁并报告端口，另一个以退出码 1 退出并说明
    # 数据目录被占用。一个进程启动要导入模型 SDK 约 9 秒，同时启动让「被拒绝」与「正常启动」两段重叠，
    # 不必先等第一个就绪再启动第二个。锁没有排他时两个进程都会报告端口，此时立刻判失败，不等到上限
    logs = [workdir / f"{name}-{index}.log" for index in range(2)]
    processes = [_start(workdir, "api", data_dir, 0, log) for log in logs]
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
        while time.monotonic() < deadline:
            ports = [next((line[len(PORT_LINE):].strip() for line in _lines(log) if line.startswith(PORT_LINE)),
                          None) for log in logs]
            exited = [process.poll() is not None for process in processes]
            assert not all(port is not None for port in ports), f"两个服务进程都取得了同一个数据目录：{ports}"
            if any(exited):
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("neither service process exited or reported its port")
        loser = 0 if exited[0] else 1
        winner = 1 - loser
        assert processes[loser].wait(STARTUP_TIMEOUT_SEC) == 1, _lines(logs[loser])
        assert IN_USE in logs[loser].read_text(encoding="utf-8", errors="replace")
        port = _bound_port(processes[winner], logs[winner])
        return processes[winner], port, logs[winner]
    except BaseException:
        for process in processes:
            if process.poll() is None:
                _stop(process)
        raise


def test_two_service_processes_cannot_use_the_same_data_directory(tmp_path):
    data_dir = tmp_path / "data"
    # 第二个服务进程不能使用同一个数据目录；另一个数据目录不受影响，选项写在子命令之前同样有效。
    # 三个进程同时启动
    other = _start(tmp_path, "api", tmp_path / "other", 0, tmp_path / "other.log", options_first=True)
    try:
        api, api_port, api_log = _race(tmp_path, data_dir, "first")
        try:
            _wait_until_serving(api, f"http://127.0.0.1:{api_port}/api/queries/system.status",
                                api_log)
            other_port = _bound_port(other, tmp_path / "other.log")
            _wait_until_serving(other, f"http://127.0.0.1:{other_port}/api/capabilities", tmp_path / "other.log")
            assert (tmp_path / "other" / "events.sqlite").is_file() and (tmp_path / "other" / "service.lock").exists()
        finally:
            _stop(api)
    finally:
        _stop(other)

    # 服务进程退出以后锁被释放：再同时启动两个，恰好一个启动，另一个被拒绝
    restarted, restarted_port, restarted_log = _race(tmp_path, data_dir, "second")
    try:
        _wait_until_serving(restarted, f"http://127.0.0.1:{restarted_port}/api/queries/system.status",
                            restarted_log)
    finally:
        _stop(restarted)


def test_the_api_only_listens_on_a_loopback_address(tmp_path, capsys):
    # 本机访问方式（设计说明第 6.2 节）：设置非回环地址时拒绝启动，不取得锁，也不建立数据目录
    assert main(["api", "--host", "0.0.0.0", "--data-dir", str(tmp_path / "data")]) == 1
    assert "only listens on a loopback address, not 0.0.0.0" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_the_api_serves_the_local_network_with_the_lan_access_mode(tmp_path):
    # 局域网访问方式（设计说明第 6.2 节）：监听任意地址，能力清单列出访问方式；
    # Host 不受本机名称限制，Origin 只接受桌面客户端页面的来源
    data_dir = tmp_path / "lan"
    log = tmp_path / "lan.log"
    token = _lan_token(data_dir)
    api, port = _started(tmp_path, "api", data_dir, log, options_first=True,
                         extra=("--access", "lan", "--host", "0.0.0.0"))
    try:
        _wait_until_serving(api, f"http://127.0.0.1:{port}/api/capabilities", log, token=token)
        authorized = {"Authorization": f"Bearer {token}"}
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=STARTUP_TIMEOUT_SEC,
                          headers=authorized) as client:
            capabilities = client.get("/api/capabilities")
            other_host = client.get("/api/capabilities", headers={"Host": "control-host"})
            rejected = client.get("/api/capabilities", headers={"Origin": "https://evil.example"})
        assert capabilities.status_code == 200
        assert capabilities.json()["deployment"]["access"] == "lan"
        assert other_host.status_code == 200
        assert rejected.status_code == 403
    finally:
        _stop(api)

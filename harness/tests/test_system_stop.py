# 本机停止请求、更新源与 system.status 的新字段（工单 #206，设计说明第 4.4、5.1 节）。
# 服务经真实的 uvicorn 启动（running_server）或用真实的子进程启动（python -m harness api），
# 数据目录是真实的临时目录，发布资源是临时目录中的真实文件。

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from harness.adapters.fake import FakeAdapter
from harness.api.app import create_app
from harness.app.application import Application
from harness.app.client_update import NO_INSTALLER, ReleaseAssets
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_server

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SEC = 300

def _open(data_dir: Path):
    return Application(LoopSystem.for_testing(data_dir, FakeAdapter([])))

def test_stop_request_makes_a_local_service_exit(tmp_path):
    # 本机访问方式下来自回环地址的停止请求使服务退出；停止请求不产生事件
    data_dir = tmp_path / "data"
    with running_server(lambda: _open(data_dir)) as handle:
        before = loopback_status(handle.client)
        response = handle.client.post("/api/system/stop")
        assert response.status_code == 202
        assert response.json() == {"stopping": True}
        assert handle.wait_stopped()
        # 停止请求不写事件：重新打开以后位置不变
        with running_server(lambda: _open(data_dir)) as again:
            assert loopback_status(again.client)["position"] == before["position"]

def loopback_status(client: httpx.Client) -> dict:
    response = client.get("/api/queries/system.status")
    assert response.status_code == 200
    return response.json()

def test_stop_request_is_rejected_in_lan_access_mode(tmp_path):
    # 局域网访问方式下拒绝停止请求
    data_dir = tmp_path / "lan"
    with running_server(lambda: _open(data_dir), access="lan") as handle:
        response = handle.client.post("/api/system/stop")
        assert response.status_code == 403
        assert handle.thread.is_alive()

def test_system_status_carries_the_release_version_and_running_runs(tmp_path):
    data_dir = tmp_path / "status"
    with running_server(lambda: _open(data_dir)) as handle:
        data = loopback_status(handle.client)["data"]
        from importlib.metadata import version
        assert data["version"] == version("yudao-harness")
        assert data["running_runs"] == 0

def test_client_update_serves_the_manifest_and_supports_range(tmp_path):
    # 发布资源目录中有更新清单与安装程序：latest.yml 返回正确内容，安装程序的 Range 请求返回正确的片段
    directory = tmp_path / "release_assets"
    directory.mkdir()
    manifest = b"version: 0.1.0\npath: Yudao-Setup-0.1.0.exe\n"
    (directory / "latest.yml").write_bytes(manifest)
    installer = b"0123456789abcdef"
    (directory / "Yudao-Setup-0.1.0.exe").write_bytes(installer)
    data_dir = tmp_path / "data"
    with running_server(lambda: _open(data_dir), release_assets=ReleaseAssets(directory)) as handle:
        latest = handle.client.get("/client-update/latest.yml")
        assert latest.status_code == 200
        assert latest.content == manifest
        full = handle.client.get("/client-update/Yudao-Setup-0.1.0.exe")
        assert full.status_code == 200 and full.content == installer
        assert full.headers["accept-ranges"] == "bytes"
        partial = handle.client.get("/client-update/Yudao-Setup-0.1.0.exe",
                                    headers={"Range": "bytes=4-7"})
        assert partial.status_code == 206
        assert partial.content == installer[4:8]
        assert partial.headers["content-range"] == f"bytes 4-7/{len(installer)}"

def test_client_update_reports_no_installer_without_release_assets(tmp_path):
    # 没有发布资源目录时返回 404，响应写明「没有客户端安装包」
    data_dir = tmp_path / "data"
    missing = ReleaseAssets(tmp_path / "absent")
    with running_server(lambda: _open(data_dir), release_assets=missing) as handle:
        for path in ("/client-update/latest.yml", "/client-update/Yudao-Setup-0.1.0.exe"):
            response = handle.client.get(path)
            assert response.status_code == 404
            assert response.json() == {"error": NO_INSTALLER}

def test_no_stop_callback_reports_the_service_does_not_accept_it(tmp_path):
    # 没有登记停止回调时（例如直接建立应用）回答 503，不假装停止
    data_dir = tmp_path / "data"
    server = uvicorn.Server(uvicorn.Config(
        create_app(lambda: _open(data_dir)), host="127.0.0.1", port=0, log_level="warning",
        lifespan="on", timeout_graceful_shutdown=3.0))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("the API server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        response = httpx.post(f"http://127.0.0.1:{port}/api/system/stop", timeout=10)
        assert response.status_code == 503
    finally:
        server.should_exit = True
        thread.join(STARTUP_TIMEOUT_SEC)

# ---------------------------------------------------------------------------
# 真实的子进程服务：停止请求使进程退出并释放数据目录的进程锁

def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]

def _start(data_dir: Path, port: int, log: Path) -> subprocess.Popen:
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    with log.open("wb") as output:
        return subprocess.Popen(
            [sys.executable, "-m", "harness", "api", "--data-dir", str(data_dir),
             "--port", str(port), "--provider-config", ""],
            cwd=REPO_ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT, **spawn)

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

def _stop(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(STARTUP_TIMEOUT_SEC)

def test_stop_request_ends_the_service_process_and_releases_the_lock(tmp_path):
    data_dir = tmp_path / "data"
    port = _free_port()
    log = tmp_path / "api.log"
    api = _start(data_dir, port, log)
    try:
        _wait_until_serving(api, f"http://127.0.0.1:{port}/api/queries/system.status", log)
        response = httpx.post(f"http://127.0.0.1:{port}/api/system/stop", timeout=10)
        assert response.status_code == 202
        assert api.wait(STARTUP_TIMEOUT_SEC) == 0, log.read_text(encoding="utf-8", errors="replace")
        # 服务退出以后日志写在数据目录内，进程锁被释放：同一个数据目录可以再次启动
        assert (data_dir / "logs" / "yudao.log").is_file()
    finally:
        if api.poll() is None:
            _stop(api)

    second_port = _free_port()
    second_log = tmp_path / "second.log"
    second = _start(data_dir, second_port, second_log)
    try:
        _wait_until_serving(second, f"http://127.0.0.1:{second_port}/api/queries/system.status", second_log)
    finally:
        _stop(second)

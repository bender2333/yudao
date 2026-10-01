# 发布 wheel 的验收（工单 #206，设计说明第 5.1 节）：在临时目录中构建 wheel，包内放测试用的发布资源
# （不使用仓库中的 harness/release_assets/），安装进临时虚拟环境以后，yudao --version 输出发布版本号，
# yudao api 用临时数据目录与端口启动，更新源提供正确的清单与 Range 片段。全部使用真实的 wheel 与子进程。

import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SEC = 300
MANIFEST = b"version: 0.1.0\npath: Yudao-Setup-0.1.0.exe\nsha512: test\n"
INSTALLER = bytes(range(256)) * 8

def _ignore(directory: str, names: list[str]) -> set[str]:
    # 复制仓库时跳过的目录：构建产物、虚拟环境、临时目录、已有的发布资源（要用测试用的那一份）
    skip = {".git", ".venv", ".tmp", "__pycache__", "node_modules", "release_assets", "generated",
            ".pytest_cache", "test-results"}
    return {name for name in names if name in skip or name.endswith(".egg-info")}

def _build_test_wheel(workdir: Path) -> Path:
    # 把仓库复制到临时目录，放上测试用的发布资源，在临时目录中构建 wheel
    source = workdir / "src"
    shutil.copytree(REPO_ROOT, source, ignore=_ignore)
    assets = source / "harness" / "release_assets"
    assets.mkdir()
    (assets / "latest.yml").write_bytes(MANIFEST)
    (assets / "Yudao-Setup-0.1.0.exe").write_bytes(INSTALLER)
    wheel_dir = workdir / "wheel"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)], cwd=source,
                   check=True, capture_output=True)
    wheels = list(wheel_dir.glob("yudao_harness-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]

def _install(workdir: Path, wheel: Path) -> Path:
    # 建立临时虚拟环境并安装 wheel，返回 yudao 命令的路径
    venv = workdir / "venv"
    subprocess.run(["uv", "venv", str(venv), "--python", "3.12"], check=True, capture_output=True)
    python = venv / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)],
                   check=True, capture_output=True)
    command = venv / ("Scripts" if os.name == "nt" else "bin") / ("yudao.exe" if os.name == "nt" else "yudao")
    assert command.is_file(), command
    return command

def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]

def _start(command: Path, data_dir: Path, port: int, log: Path) -> subprocess.Popen:
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    with log.open("wb") as output:
        return subprocess.Popen([str(command), "api", "--data-dir", str(data_dir), "--port", str(port),
                                 "--provider-config", ""], stdout=output, stderr=subprocess.STDOUT, **spawn)

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

def test_installed_wheel_serves_the_client_update_source(tmp_path):
    wheel = _build_test_wheel(tmp_path / "build")
    command = _install(tmp_path / "env", wheel)
    version = subprocess.run([str(command), "--version"], check=True, capture_output=True, text=True)
    assert version.stdout.strip() == "0.1.0", version.stdout

    data_dir = tmp_path / "data"
    port = _free_port()
    log = tmp_path / "api.log"
    api = _start(command, data_dir, port, log)
    try:
        _wait_until_serving(api, f"http://127.0.0.1:{port}/api/queries/system.status", log)
        latest = httpx.get(f"http://127.0.0.1:{port}/client-update/latest.yml", timeout=10)
        assert latest.status_code == 200 and latest.content == MANIFEST
        full = httpx.get(f"http://127.0.0.1:{port}/client-update/Yudao-Setup-0.1.0.exe", timeout=10)
        assert full.status_code == 200 and full.content == INSTALLER
        partial = httpx.get(f"http://127.0.0.1:{port}/client-update/Yudao-Setup-0.1.0.exe",
                            headers={"Range": "bytes=4-7"}, timeout=10)
        assert partial.status_code == 206 and partial.content == INSTALLER[4:8]
    finally:
        _stop(api)

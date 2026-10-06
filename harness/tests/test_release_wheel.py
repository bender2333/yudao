# 发布 wheel 的验收（工单 #206、#313，设计说明第 5.1 节）：在临时目录中构建 wheel，包内放测试用的发布资源
# （不使用仓库中的 harness/release_assets/），安装进临时虚拟环境以后，yudao --version 输出发布版本号，
# yudao api 用临时数据目录与端口启动，更新源提供正确的清单与 Range 片段（#206），
# 并且两个版本的安装程序都在 wheel 里时，client install 与更新源取与服务版本同名的那一个（#313）。
# 全部使用真实的 wheel 与子进程。

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SEC = 300
def _repo_version() -> str:
    # 仓库 pyproject.toml 的版本：测试构建的 wheel 就是这一版，发布资源与清单按它取名
    import tomllib
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

VERSION = _repo_version()
MANIFEST = (f"version: {VERSION}\npath: Yudao-Setup-{VERSION}.exe\nsha512: test\n").encode("utf-8")
INSTALLER = bytes(range(256)) * 8

def _system_program() -> bytes:
    # 一个真实可运行的系统程序的内容：安装程序必须是一个可执行文件，安装以后客户端更新时真的运行它
    return Path(shutil.which("hostname" if os.name == "nt" else "true")).read_bytes()

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
    (assets / f"Yudao-Setup-{VERSION}.exe").write_bytes(INSTALLER)
    wheel_dir = workdir / "wheel"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)], cwd=source,
                   check=True, capture_output=True)
    wheels = list(wheel_dir.glob("yudao_harness-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]

def test_wheel_with_two_installers_serves_the_one_of_the_service_version(tmp_path):
    # 工单 #313：wheel 里同时有两个版本的安装程序时，更新源与 client install 都取与服务版本同名的那一个，
    # 不按文件名排序取第一个。两个安装程序放进同一份发布资源：与服务版本同名的那个是真实可运行的程序，
    # 另一个版本的安装程序不是可执行文件，取错时运行与请求都拿不到它的内容
    source = tmp_path / "src"
    shutil.copytree(REPO_ROOT, source, ignore=_ignore)
    version = subprocess.run(
        [sys.executable, "-c", "import tomllib,pathlib;"
         "print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))"
         "['project']['version'])"], cwd=source, check=True, capture_output=True,
        text=True).stdout.strip()
    assets = source / "harness" / "release_assets"
    assets.mkdir()
    current = _system_program()
    previous = b"installer-from-another-version"
    (assets / f"Yudao-Setup-{version}.exe").write_bytes(current)
    (assets / "Yudao-Setup-0.0.9.exe").write_bytes(previous)
    (assets / "latest.yml").write_bytes(
        f"version: {version}\npath: Yudao-Setup-{version}.exe\n".encode("utf-8"))
    wheel_dir = tmp_path / "wheel"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)], cwd=source,
                   check=True, capture_output=True)
    wheels = list(wheel_dir.glob("yudao_harness-*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as archive:
        assert "harness/release_assets/Yudao-Setup-0.0.9.exe" in archive.namelist()

    command = _install(tmp_path / "env", wheels[0])
    # client install 运行的是与服务版本同名的那个：它退出码 0，
    # 另一个版本的安装程序不是可执行文件，取错时这一步会失败
    installed = subprocess.run([str(command), "client", "install"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
    assert installed.returncode == 0, installed.stderr

    data_dir = tmp_path / "data"
    port = _free_port()
    log = tmp_path / "api.log"
    api = _start(command, data_dir, port, log)
    try:
        _wait_until_serving(api, f"http://127.0.0.1:{port}/api/queries/system.status", log)
        manifest = httpx.get(f"http://127.0.0.1:{port}/client-update/latest.yml", timeout=10)
        assert manifest.status_code == 200
        named = manifest.text.split("path: ")[1].splitlines()[0]
        assert named == f"Yudao-Setup-{version}.exe", named
        served = httpx.get(f"http://127.0.0.1:{port}/client-update/{named}", timeout=10)
        assert served.status_code == 200 and served.content == current
        other = httpx.get(f"http://127.0.0.1:{port}/client-update/Yudao-Setup-0.0.9.exe", timeout=10)
        assert other.status_code == 200 and other.content == previous
    finally:
        _stop(api)

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
    assert version.stdout.strip() == VERSION, version.stdout

    data_dir = tmp_path / "data"
    port = _free_port()
    log = tmp_path / "api.log"
    api = _start(command, data_dir, port, log)
    try:
        _wait_until_serving(api, f"http://127.0.0.1:{port}/api/queries/system.status", log)
        latest = httpx.get(f"http://127.0.0.1:{port}/client-update/latest.yml", timeout=10)
        assert latest.status_code == 200 and latest.content == MANIFEST
        full = httpx.get(f"http://127.0.0.1:{port}/client-update/Yudao-Setup-{VERSION}.exe", timeout=10)
        assert full.status_code == 200 and full.content == INSTALLER
        partial = httpx.get(f"http://127.0.0.1:{port}/client-update/Yudao-Setup-{VERSION}.exe",
                            headers={"Range": "bytes=4-7"}, timeout=10)
        assert partial.status_code == 206 and partial.content == INSTALLER[4:8]
    finally:
        _stop(api)

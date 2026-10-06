# 发布脚本的验收（工单 #209、#313，设计说明第 6.3、9 节）：把仓库复制到临时目录，建立 main 分支
# 与一个本地 bare 远端，运行 scripts/release.py（不带 --publish），核对 wheel 的路径、SHA-256、
# wheel 内含的客户端安装程序、blockmap 与 latest.yml，latest.yml 中的 SHA-512 与安装程序一致，
# 以及 wheel 的发布资源目录里只有本次版本的文件（#313）。
# 同时核对工作区不干净、版本号不一致、当前提交不在 main 上时脚本拒绝。
#
# 构建走真实流程：npm ci、electron-builder 生成安装程序与 latest.yml、uv build 生成 wheel。
# 不使用任何 mock；构建一次约三分钟，用 module 作用域的夹具只做一次。
#
# --publish 的步骤写在脚本里，自动测试不推送真实标签、也不创建真实的 Release：本文件用一个
# 放在 PATH 前面的假 gh（只记录被调用的命令）核对 publish 发出的命令；打标签与推送到一个
# 本地 bare 远端，是真实的 git 命令。

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.py"
# 构建与复制跳过的东西：虚拟环境、临时目录、依赖、已有的构建产物与发布资源
_SKIP_NAMES = {".venv", ".tmp", "__pycache__", "node_modules", "release_assets", ".pytest_cache",
               "dist", "test-results", "playwright-report", ".git"}

def _ignore(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _SKIP_NAMES or name.endswith(".egg-info")}

def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.stdout.strip()

def _prepare_checkout(workdir: Path) -> tuple[Path, Path]:
    # 复制仓库到临时目录并建立一个 main 分支、已推送到本地 bare 远端的工作副本
    source = workdir / "src"
    shutil.copytree(REPO_ROOT, source, ignore=_ignore)
    remote = workdir / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    _git(["init", "-b", "main"], source)
    _git(["config", "user.email", "release-test@yudao.local"], source)
    _git(["config", "user.name", "release-test"], source)
    _git(["add", "-A"], source)
    _git(["commit", "-q", "-m", "release candidate"], source)
    _git(["remote", "add", "origin", str(remote)], source)
    _git(["push", "-q", "origin", "main"], source)
    _git(["fetch", "-q", "origin"], source)
    return source, remote

def _python() -> Path:
    # 项目环境中的 Python：与测试进程同一个解释器，含 PyYAML（发布脚本读 latest.yml 需要）
    return Path(sys.executable)

def _run_release(source: Path, output_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_python()), str(source / "scripts" / "release.py"), "--repo-root", str(source),
         "--output-dir", str(output_dir), *extra],
        cwd=source, capture_output=True, text=True, encoding="utf-8", errors="replace")

@pytest.fixture(scope="module")
def release_build(tmp_path_factory):
    # 一次完整构建：复制仓库、建立 git 环境、记录本机安装状态、运行发布脚本（不发布）、返回现场
    workdir = tmp_path_factory.mktemp("release-build")
    source, remote = _prepare_checkout(workdir)
    output_dir = workdir / "dist"
    before = _installed_tooling_state()
    result = _run_release(source, output_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    after = _installed_tooling_state()
    return {"source": source, "remote": remote, "output_dir": output_dir, "result": result,
            "installed_before": before, "installed_after": after}

def _load_release_module():
    # 直接加载 scripts/release.py 以便单独核对 publish 发出的命令
    spec = importlib.util.spec_from_file_location("yudao_release_script", RELEASE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def _version(path: Path) -> str:
    import tomllib
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]

def _wheel_path(output_dir: Path, version: str) -> Path:
    return output_dir / f"yudao_harness-{version}-py3-none-any.whl"

def test_build_produces_a_wheel_with_the_client_assets(release_build):
    # 验收第 1 项：不带 --publish 时得到 wheel，wheel 内含安装程序、blockmap 与 latest.yml
    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    assert wheel.is_file(), release_build["result"].stdout + release_build["result"].stderr
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
    installer_name = f"Yudao-Setup-{version}.exe"
    for member in (f"harness/release_assets/{installer_name}",
                   f"harness/release_assets/{installer_name}.blockmap",
                   "harness/release_assets/latest.yml"):
        assert member in members, member

def _checkout_copy(workdir: Path) -> Path:
    # 仓库的一份副本，只用来构建 wheel：核对 build/ 的清理与 wheel 内容的核对，不需要 git 环境
    source = workdir / "src"
    shutil.copytree(REPO_ROOT, source, ignore=_ignore)
    return source

def test_the_wheel_carries_no_installer_from_an_earlier_build_and_rejects_other_versions(tmp_path):
    # 工单 #313：setuptools 不清理 build/lib，上一次构建的安装程序会跟着这次构建进 wheel；
    # 发布脚本先删除 build/ 再构建，wheel 的发布资源目录里不留下一次构建的文件。
    # 发布资源目录里另放一个其他版本的安装程序时，脚本的核对以非零状态退出并写明文件名。
    source = _checkout_copy(tmp_path)
    version = _version(source / "pyproject.toml")
    assets = source / "harness" / "release_assets"
    assets.mkdir()
    installer = f"Yudao-Setup-{version}.exe"
    (assets / installer).write_bytes(b"current-installer")
    (assets / f"{installer}.blockmap").write_bytes(b"current-blockmap")
    (assets / "latest.yml").write_bytes(f"version: {version}\n".encode("utf-8"))
    previous_in_build = "Yudao-Setup-0.0.9.exe"
    previous_in_assets = "Yudao-Setup-0.0.8.exe"
    # 上一次构建留在 build/lib 里的安装程序，与本次组装到发布资源目录里的其他版本安装程序
    stale = source / "build" / "lib" / "harness" / "release_assets"
    stale.mkdir(parents=True)
    (stale / previous_in_build).write_bytes(b"installer-from-the-previous-build")
    (assets / previous_in_assets).write_bytes(b"installer-from-another-version")

    module = _load_release_module()
    wheel = module.build_wheel(source, version, tmp_path / "dist")
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
    assert f"harness/release_assets/{installer}" in members, installer
    assert f"harness/release_assets/{previous_in_build}" not in members, previous_in_build
    assert not (source / "build" / "lib" / "harness" / "release_assets"
                / previous_in_build).exists()
    # 其他版本的安装程序确实进了 wheel，核对步骤据此写明文件名退出
    assert f"harness/release_assets/{previous_in_assets}" in members, previous_in_assets
    try:
        module.verify_wheel_contents(
            wheel, {"installer": assets / installer, "blockmap": assets / f"{installer}.blockmap",
                    "manifest": assets / "latest.yml"}, version)
    except module.ReleaseError as error:
        assert previous_in_assets in str(error)
    else:
        raise AssertionError("verify_wheel_contents accepted an installer from another version")

def test_script_prints_the_wheel_path_and_a_matching_sha256(release_build):
    # 验收第 1 项：脚本输出 wheel 的路径与 SHA-256，SHA-256 与文件的实际值一致
    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    output = release_build["result"].stdout
    printed_path = next(line for line in output.splitlines() if line.startswith("wheel: "))
    printed_sha = next(line for line in output.splitlines() if line.startswith("sha256: "))
    assert Path(printed_path.removeprefix("wheel: ")) == wheel
    assert printed_sha.removeprefix("sha256: ") == hashlib.sha256(wheel.read_bytes()).hexdigest()

def test_manifest_sha512_matches_the_installer(release_build):
    # 验收第 1 项：latest.yml 中的 SHA-512 与安装程序一致。
    # 从 wheel 中取出两者，按 electron-builder 的取值口径（SHA-512 的 base64）比较
    import yaml

    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    with zipfile.ZipFile(wheel) as archive:
        manifest = yaml.safe_load(archive.read("harness/release_assets/latest.yml").decode("utf-8"))
        installer = archive.read(f"harness/release_assets/Yudao-Setup-{version}.exe")
    expected = base64.b64encode(hashlib.sha512(installer).digest()).decode("ascii")
    entry = next(item for item in manifest["files"] if item["url"] == f"Yudao-Setup-{version}.exe")
    assert entry["sha512"] == expected

def test_worktree_stays_clean_after_the_build(release_build):
    # 验收第 2 项：构建完成以后工作区仍然干净（发布资源与客户端构建输出被 git 忽略）
    assert _git(["status", "--porcelain"], release_build["source"]) == ""

def test_script_rejects_a_dirty_worktree(release_build, tmp_path):
    # 验收第 3 项：工作区不干净时脚本拒绝并写明原因
    source = release_build["source"]
    stray = source / "stray.txt"
    stray.write_text("dirty", encoding="utf-8")
    try:
        result = _run_release(source, tmp_path / "dist-dirty")
    finally:
        stray.unlink()
    assert result.returncode != 0
    assert "工作区不干净" in result.stderr

def test_script_rejects_a_version_mismatch(tmp_path):
    # 验收第 3 项：版本号不一致时脚本拒绝并写明原因。在一个独立的工作副本上把客户端
    # package.json 的 version 改成另一个值并提交、推送，工作区保持干净，改写的只有版本号
    source, _remote = _prepare_checkout(tmp_path)
    package = source / "client" / "package.json"
    document = json.loads(package.read_text(encoding="utf-8"))
    document["version"] = "9.9.9"
    package.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _git(["add", "-A"], source)
    _git(["commit", "-q", "-m", "mismatched version"], source)
    _git(["push", "-q", "origin", "main"], source)
    _git(["fetch", "-q", "origin"], source)
    result = _run_release(source, tmp_path / "dist-version")
    assert result.returncode != 0
    assert "版本号不一致" in result.stderr

def test_script_rejects_a_commit_outside_main(release_build, tmp_path):
    # 验收第 3 项：当前提交不在 main 上时脚本拒绝并写明原因。切到另一个分支
    source = release_build["source"]
    _git(["checkout", "-q", "-b", "feature"], source)
    try:
        result = _run_release(source, tmp_path / "dist-branch")
    finally:
        _git(["checkout", "-q", "main"], source)
    assert result.returncode != 0
    assert "发布要求当前提交在 main 上" in result.stderr

def test_script_rejects_an_unpushed_commit(tmp_path):
    # 验收第 3 项：当前提交还没有推送时脚本拒绝。在一个独立的工作副本上追加提交但不推送，
    # 不动 module 作用域的夹具
    source, _remote = _prepare_checkout(tmp_path)
    marker = source / "unpushed.txt"
    marker.write_text("x", encoding="utf-8")
    _git(["add", "-A"], source)
    _git(["commit", "-q", "-m", "unpushed"], source)
    result = _run_release(source, tmp_path / "dist-unpushed")
    assert result.returncode != 0
    assert "还没有推送" in result.stderr

def test_publish_tags_pushes_and_uploads_without_a_real_release(tmp_path):
    # 验收第 6 项：publish 的步骤（打标签、推送、上传到 Release）写在脚本中。
    # 标签与推送到一个本地 bare 远端（真实的 git 命令，不是真实发布）；
    # gh 用放在 PATH 最前面的假命令（只记录参数）代替，不创建真实的 Release
    module = _load_release_module()
    source = tmp_path / "src"
    shutil.copytree(REPO_ROOT, source, ignore=_ignore)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    _git(["init", "-b", "main"], source)
    _git(["config", "user.email", "release-test@yudao.local"], source)
    _git(["config", "user.name", "release-test"], source)
    _git(["add", "-A"], source)
    _git(["commit", "-q", "-m", "release candidate"], source)
    _git(["remote", "add", "origin", str(remote)], source)

    wheel = tmp_path / "yudao_harness-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel-bytes")
    record = tmp_path / "gh-calls.txt"
    fake_bin = _write_fake_gh(tmp_path / "fake-bin", record)

    version = _version(REPO_ROOT / "pyproject.toml")
    original_path = os.environ["PATH"]
    os.environ["PATH"] = str(fake_bin) + os.pathsep + original_path
    try:
        module.publish(source, version, wheel, remote="origin")
    finally:
        os.environ["PATH"] = original_path

    # 标签打在当前提交上，并推送到远端
    tag = f"v{version}"
    assert _git(["tag", "--list", tag], source) == tag
    assert _git(["ls-remote", "--tags", str(remote), tag], source) != ""
    # gh release create 带着本次构建的 wheel
    recorded = record.read_text(encoding="utf-8")
    assert "release create" in recorded and tag in recorded and str(wheel) in recorded

def _write_fake_gh(directory: Path, record: Path) -> Path:
    # 假 gh：把参数写进记录文件并返回成功，不创建真实的 Release
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        (directory / "gh.cmd").write_text(
            f"@echo off\r\necho %* >> \"{record}\"\r\nexit /b 0\r\n", encoding="utf-8")
    else:
        script = directory / "gh"
        script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"{record}\"\n", encoding="utf-8")
        script.chmod(0o755)
    return directory

def _installed_tooling_state() -> dict[str, object]:
    # 本机安装状态的快照：uv tool list 的输出，以及默认客户端安装目录是否存在及其中的文件清单。
    # 发布脚本只构建与上传，不运行 uv tool install，也不运行安装程序，两次快照应当相同
    tools = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    client_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Yudao"
    listing = sorted(str(path.relative_to(client_dir)) for path in client_dir.rglob("*")) \
        if client_dir.is_dir() else None
    return {"tools": tools.stdout, "client_listing": listing}

def test_installed_tooling_is_unchanged(release_build):
    # 验收第 5 项：运行脚本前后这台电脑上已经安装的 yudao 命令与桌面客户端不变。
    # 比较运行发布脚本前后两次本机安装状态的快照
    assert release_build["installed_after"] == release_build["installed_before"]

def _free_port() -> int:
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]

def _wait_until_serving(process: subprocess.Popen, url: str, log: Path) -> None:
    import time

    import httpx

    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        assert process.poll() is None, log.read_text(encoding="utf-8", errors="replace")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise TimeoutError(log.read_text(encoding="utf-8", errors="replace"))

def _stop(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(300)

def test_installed_wheel_passes_the_client_update_source_acceptance(release_build, tmp_path):
    # 验收第 4 项：脚本生成的 wheel 安装进临时虚拟环境后，#206 的各项验收通过。
    # 建立临时虚拟环境、安装 wheel、用临时数据目录与端口启动 yudao api，核对：
    # yudao --version 输出发布版本号；更新源返回的 latest.yml 与安装程序与 wheel 内的字节相同，
    # 安装程序的 Range 请求返回正确片段；同一数据目录第二次启动失败并写明原因；
    # 数据目录内有默认的 Provider 目录文件与 .env；发布资源随 wheel 提供
    import time

    import httpx
    import yaml

    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    with zipfile.ZipFile(wheel) as archive:
        packaged_manifest = archive.read("harness/release_assets/latest.yml")
        packaged_installer = archive.read(f"harness/release_assets/Yudao-Setup-{version}.exe")

    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(venv), "--python", "3.12"], check=True, capture_output=True)
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)],
                   check=True, capture_output=True)
    command = scripts / ("yudao.exe" if os.name == "nt" else "yudao")
    assert command.is_file(), command

    released = subprocess.run([str(command), "--version"], check=True, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    assert released.stdout.strip() == version

    data_dir = tmp_path / "data"
    port = _free_port()
    log = tmp_path / "api.log"
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    with log.open("wb") as output:
        api = subprocess.Popen([str(command), "api", "--data-dir", str(data_dir),
                                "--port", str(port), "--provider-config", ""],
                               stdout=output, stderr=subprocess.STDOUT, **spawn)
    try:
        _wait_until_serving(api, f"http://127.0.0.1:{port}/api/queries/system.status", log)
        latest = httpx.get(f"http://127.0.0.1:{port}/client-update/latest.yml", timeout=10)
        assert latest.status_code == 200 and latest.content == packaged_manifest
        installer = httpx.get(
            f"http://127.0.0.1:{port}/client-update/Yudao-Setup-{version}.exe", timeout=60)
        assert installer.status_code == 200 and installer.content == packaged_installer
        partial = httpx.get(f"http://127.0.0.1:{port}/client-update/Yudao-Setup-{version}.exe",
                            headers={"Range": "bytes=4-7"}, timeout=30)
        assert partial.status_code == 206 and partial.content == packaged_installer[4:8]

        # 数据目录内有服务的日志（设计说明第 3.4、4.2 节）
        assert (data_dir / "logs" / "yudao.log").is_file()

        # 同一数据目录第二次启动失败并写明原因（服务进程锁）
        second = subprocess.run(
            [str(command), "api", "--data-dir", str(data_dir), "--port", str(_free_port()),
             "--provider-config", ""],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        assert second.returncode != 0
        assert "data directory is in use by another service process" in second.stderr
        assert str(data_dir.resolve()) in second.stderr
    finally:
        _stop(api)

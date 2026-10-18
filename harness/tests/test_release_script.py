# 发布脚本的验收（工单 #373，网页界面的提供与发布设计说明第 6.3 节）：把仓库复制到临时目录，
# 建立 main 分支与一个本地 bare 远端，运行 scripts/release.py（不带 --publish），核对 wheel 的路径、
# SHA-256、wheel 内含页面文件且与页面构建输出逐个一致、不含客户端安装程序与更新清单，
# 以及 wheel 的发布资源目录里只有本次构建的文件（#313 的清理逻辑沿用）。
# 同时核对工作区不干净、发布标签已存在、当前提交不在 main 上时脚本拒绝。
#
# 构建走真实流程：npm ci、Vite 构建页面文件、uv build 生成 wheel。不使用任何 mock；
# 构建一次约几分钟，用 module 作用域的夹具只做一次。
#
# --publish 的步骤写在脚本里，自动测试不推送真实标签、也不创建真实的 Release：本文件用一个
# 放在 PATH 前面的假 gh（只记录被调用的命令）核对 publish 发出的命令；打标签与推送到一个
# 本地 bare 远端，是真实的 git 命令。

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from harness.data_directory import LOG_DIR, LOG_FILE

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.py"
# 构建与复制跳过的东西：虚拟环境、临时目录、依赖、已有的构建产物与发布资源
_SKIP_NAMES = {".venv", ".tmp", "__pycache__", "node_modules", "release_assets", ".pytest_cache",
               "dist", "test-results", "playwright-report", ".git", "out"}

def _env() -> dict[str, str]:
    # 运行 Python 子进程的环境：显式把输出编码设为 UTF-8。脚本与命令按控制台的编码写出，
    # PowerShell 里设了 PYTHONIOENCODING=utf-8:surrogateescape，Git Bash 等没有设置的环境里
    # 按 GBK 写出，读出来是乱码（#313 的合并验证遇到）。测试不依赖外部环境
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}

def _ignore(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _SKIP_NAMES or name.endswith(".egg-info")}

def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.stdout.strip()

def _prepare_template(workdir: Path) -> Path:
    # 整个模块只复制一次仓库、只建一次提交：复制到临时目录，建立 main 分支，推送到一个本地 bare 仓库。
    # 返回这个 bare 仓库的路径，各用例从它克隆自己的工作副本
    source = workdir / "template-src"
    shutil.copytree(REPO_ROOT, source, ignore=_ignore)
    template = workdir / "template.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(template)], check=True,
                   capture_output=True)
    _git(["init", "-b", "main"], source)
    _git(["config", "user.email", "release-test@yudao.local"], source)
    _git(["config", "user.name", "release-test"], source)
    _git(["add", "-A"], source)
    _git(["commit", "-q", "-m", "release candidate"], source)
    _git(["remote", "add", "origin", str(template)], source)
    _git(["push", "-q", "origin", "main"], source)
    return template

def _clone_checkout(template: Path, workdir: Path) -> tuple[Path, Path]:
    # 从模板克隆一份独立的工作副本和它自己的 bare 远端（本地 git clone，不再复制整个仓库）：
    # 远端先从模板克隆，工作副本再从这个远端克隆，origin/main 已经存在，推送和打标签互不影响
    remote = workdir / "remote.git"
    source = workdir / "src"
    subprocess.run(["git", "clone", "-q", "--bare", str(template), str(remote)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "-q", str(remote), str(source)],
                   check=True, capture_output=True)
    _git(["config", "user.email", "release-test@yudao.local"], source)
    _git(["config", "user.name", "release-test"], source)
    return source, remote

@pytest.fixture(scope="module")
def release_template(tmp_path_factory):
    return _prepare_template(tmp_path_factory.mktemp("release-template"))

def _python() -> Path:
    # 项目环境中的 Python：与测试进程同一个解释器
    return Path(sys.executable)

def _run_release(source: Path, output_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_python()), str(source / "scripts" / "release.py"), "--repo-root", str(source),
         "--output-dir", str(output_dir), *extra],
        cwd=source, capture_output=True, text=True, encoding="utf-8", errors="replace", env=_env())

@pytest.fixture(scope="module")
def release_build(tmp_path_factory, release_template):
    # 一次完整构建：从模板克隆工作副本、记录本机安装状态、运行发布脚本（不发布）、返回现场
    workdir = tmp_path_factory.mktemp("release-build")
    source, remote = _clone_checkout(release_template, workdir)
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

def _wheel_members(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())

def test_build_produces_a_wheel_with_the_page_files(release_build):
    # 验收第 1 项：不带 --publish 时得到 wheel，wheel 内含入口页面与它引用的文件
    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    assert wheel.is_file(), release_build["result"].stdout + release_build["result"].stderr
    members = _wheel_members(wheel)
    assert "harness/release_assets/index.html" in members
    hashed = [name for name in members
              if name.startswith("harness/release_assets/assets/") and not name.endswith("/")]
    assert hashed, "wheel 内的页面文件没有带内容摘要的引用文件"

def test_the_wheel_carries_no_installer_or_update_manifest(release_build):
    # 工单验收：wheel 不含客户端安装程序与更新清单
    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    members = _wheel_members(wheel)
    assert not [name for name in members if name.endswith((".exe", ".blockmap", ".yml"))], \
        [name for name in members if name.endswith((".exe", ".blockmap", ".yml"))]

def test_wheel_page_files_match_the_build_output(release_build):
    # 验收第 1 项：wheel 内的页面文件与页面构建输出目录中的文件逐个一致
    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    built = release_build["source"] / "client" / "out" / "renderer"
    expected = {path.relative_to(built).as_posix(): path.read_bytes()
                for path in sorted(built.rglob("*")) if path.is_file()}
    assert "index.html" in expected, "页面构建没有生成入口页面"
    prefix = "harness/release_assets/"
    with zipfile.ZipFile(wheel) as archive:
        packaged = {name[len(prefix):]: archive.read(name) for name in archive.namelist()
                    if name.startswith(prefix) and not name.endswith("/")}
    assert set(packaged) == set(expected), \
        set(packaged) ^ set(expected)
    changed = [name for name, content in expected.items() if packaged[name] != content]
    assert not changed, changed

def test_the_wheel_carries_no_stale_file_and_rejects_foreign_files(release_template, tmp_path):
    # 工单 #313 的清理逻辑沿用：setuptools 不清理 build/lib，上一次构建的文件会跟着这次构建进 wheel；
    # 发布脚本先删除 build/ 再构建，wheel 里不留下一次构建的文件。
    # 发布资源目录里另放一个与页面构建输出无关的文件时，脚本的核对以非零状态退出并写明文件名
    source, _remote = _clone_checkout(release_template, tmp_path)
    version = _version(source / "pyproject.toml")
    built = source / "client" / "out" / "renderer"
    built.mkdir(parents=True)
    (built / "index.html").write_bytes(b"<html></html>")
    previous_in_build = "stale-from-the-previous-build.html"
    foreign = "yudao_agent-99.99.99-py3-none-any.whl"
    # 上一次构建留在 build/lib 里的文件；本次额外放进发布资源目录的执行代理 wheel（M3 起由 #144 加入），
    # 但版本号不对，因此脚本的核对应当拒绝并写明文件名
    stale = source / "build" / "lib" / "harness" / "release_assets"
    stale.mkdir(parents=True)
    (stale / previous_in_build).write_bytes(b"stale-bytes")
    assets = source / "harness" / "release_assets"
    assets.mkdir()
    shutil.copytree(built, assets, dirs_exist_ok=True)
    (assets / foreign).write_bytes(b"foreign-bytes")

    module = _load_release_module()
    wheel = module.build_wheel(source, version, tmp_path / "dist")
    members = _wheel_members(wheel)
    assert "harness/release_assets/index.html" in members
    assert f"harness/release_assets/{previous_in_build}" not in members, previous_in_build
    assert not (source / "build" / "lib" / "harness" / "release_assets"
                / previous_in_build).exists()
    # 与页面构建输出无关的文件确实进了 wheel，核对步骤据此写明文件名退出
    assert f"harness/release_assets/{foreign}" in members, foreign
    try:
        module.verify_wheel_contents(wheel, built)
    except module.ReleaseError as error:
        assert foreign in str(error)
    else:
        raise AssertionError("verify_wheel_contents accepted a file outside the page output")

def test_script_prints_the_wheel_path_and_a_matching_sha256(release_build):
    # 验收第 1 项：脚本输出 wheel 的路径与 SHA-256，SHA-256 与文件的实际值一致
    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    output = release_build["result"].stdout
    printed_path = next(line for line in output.splitlines() if line.startswith("wheel: "))
    printed_sha = next(line for line in output.splitlines() if line.startswith("sha256: "))
    assert Path(printed_path.removeprefix("wheel: ")) == wheel
    assert printed_sha.removeprefix("sha256: ") == hashlib.sha256(wheel.read_bytes()).hexdigest()

def test_worktree_stays_clean_after_the_build(release_build):
    # 验收：构建完成以后工作区仍然干净（发布资源、页面构建输出与 wheel 输出目录被 git 忽略）
    assert _git(["status", "--porcelain"], release_build["source"]) == ""

def test_script_rejects_a_dirty_worktree(release_template, tmp_path):
    # 验收：工作区不干净时脚本拒绝并写明原因。用自己的克隆，不动 release_build 的工作副本
    source, _remote = _clone_checkout(release_template, tmp_path)
    stray = source / "stray.txt"
    stray.write_text("dirty", encoding="utf-8")
    try:
        result = _run_release(source, tmp_path / "dist-dirty")
    finally:
        stray.unlink()
    assert result.returncode != 0
    assert "工作区不干净" in result.stderr

def test_script_rejects_an_already_released_version(release_template, tmp_path):
    # 版本号只核对 pyproject.toml 与标签（设计说明第 6.2 节）：这个版本已经打过标签时脚本拒绝，
    # 避免重复发布覆盖上一次的记录
    source, _remote = _clone_checkout(release_template, tmp_path)
    version = _version(source / "pyproject.toml")
    _git(["tag", f"v{version}"], source)
    _git(["push", "-q", "origin", f"v{version}"], source)
    result = _run_release(source, tmp_path / "dist-tagged")
    assert result.returncode != 0
    assert f"v{version}" in result.stderr and "已经存在" in result.stderr

def test_script_rejects_a_commit_outside_main(release_template, tmp_path):
    # 验收：当前提交不在 main 上时脚本拒绝并写明原因。在自己的克隆里切到另一个分支
    source, _remote = _clone_checkout(release_template, tmp_path)
    _git(["checkout", "-q", "-b", "feature"], source)
    try:
        result = _run_release(source, tmp_path / "dist-branch")
    finally:
        _git(["checkout", "-q", "main"], source)
    assert result.returncode != 0
    assert "发布要求当前提交在 main 上" in result.stderr

def test_script_rejects_an_unpushed_commit(release_template, tmp_path):
    # 验收：当前提交还没有推送时脚本拒绝。在一个独立的工作副本上追加提交但不推送，
    # 不动 module 作用域的夹具
    source, _remote = _clone_checkout(release_template, tmp_path)
    marker = source / "unpushed.txt"
    marker.write_text("x", encoding="utf-8")
    _git(["add", "-A"], source)
    _git(["commit", "-q", "-m", "unpushed"], source)
    result = _run_release(source, tmp_path / "dist-unpushed")
    assert result.returncode != 0
    assert "还没有推送" in result.stderr

def test_publish_tags_pushes_and_uploads_without_a_real_release(release_template, tmp_path):
    # 验收：publish 的步骤（打标签、推送、上传到 Release）写在脚本中。
    # 标签与推送到一个本地 bare 远端（真实的 git 命令，不是真实发布）；
    # gh 用放在 PATH 最前面的假命令（只记录参数）代替，不创建真实的 Release
    module = _load_release_module()
    source, remote = _clone_checkout(release_template, tmp_path)

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

def _write_fake_yudao(directory: Path, *, exit_code: int, output: str) -> Path:
    # 假 yudao：release-check 返回给定的状态与输出。发布门只认状态与标准输出，不读真实的仓库
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        (directory / "yudao.cmd").write_text(
            f"@echo off\r\necho {output}\r\nexit /b {exit_code}\r\n", encoding="utf-8")
    else:
        script = directory / "yudao"
        script.write_text(f"#!/bin/sh\necho {output}\nexit {exit_code}\n", encoding="utf-8")
        script.chmod(0o755)
    return directory


def test_the_release_gate_refuses_upload_when_the_check_fails(release_template, tmp_path):
    # 发布检查不通过时发布脚本拒绝上传：已安装实例的 yudao release-check 返回非零状态，
    # 发布门抛出 ReleaseError 并附检查输出，不打新标签
    module = _load_release_module()
    source, _remote = _clone_checkout(release_template, tmp_path)
    fake_bin = _write_fake_yudao(tmp_path / "fake-yudao", exit_code=1, output="kernel-diff-failure")
    original_path = os.environ["PATH"]
    os.environ["PATH"] = str(fake_bin) + os.pathsep + original_path
    try:
        try:
            module._check_release(source)
        except module.ReleaseError as failed:
            assert "kernel-diff-failure" in str(failed)
        else:
            raise AssertionError("_check_release accepted a failing release check")
    finally:
        os.environ["PATH"] = original_path


def test_the_release_gate_passes_when_the_check_passes(release_template, tmp_path):
    # 发布检查通过时发布门放行：yudao release-check 返回零状态，不抛错
    module = _load_release_module()
    source, _remote = _clone_checkout(release_template, tmp_path)
    fake_bin = _write_fake_yudao(tmp_path / "fake-yudao", exit_code=0, output="all-checks-passed")
    original_path = os.environ["PATH"]
    os.environ["PATH"] = str(fake_bin) + os.pathsep + original_path
    try:
        module._check_release(source)
    finally:
        os.environ["PATH"] = original_path


def _installed_tooling_state() -> str:
    # 本机安装状态的快照：uv tool list 的输出。
    # 发布脚本只构建与上传，不运行 uv tool install，两次快照应当相同
    tools = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    return tools.stdout

def test_installed_tooling_is_unchanged(release_build):
    # 验收：运行脚本前后这台电脑上已经安装的 yudao 命令不变。
    # 比较运行发布脚本前后两次本机安装状态的快照
    assert release_build["installed_after"] == release_build["installed_before"]

PORT_LINE = "port: "


def _text(path: Path) -> str:
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
    # 服务自己绑定端口 0，就绪以后在输出里报告实际端口：由调用方先占用再释放端口的写法在
    # 多进程运行中会冲突
    import time

    deadline = time.monotonic() + 300
    while True:
        port = _reported_port(log)
        if port is not None:
            return port
        assert process.poll() is None, _diagnostics(process, log, data_dir)
        if time.monotonic() > deadline:
            raise TimeoutError(_diagnostics(process, log, data_dir))
        time.sleep(0.1)

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

def test_installed_wheel_serves_the_pages(release_build, tmp_path):
    # 工单验收第 2 项：脚本生成的 wheel 安装进临时虚拟环境后，用临时数据目录与端口启动 yudao api：
    # yudao --version 输出发布版本号；请求 / 得到入口页面；/api/capabilities 给出与 yudao --version
    # 相同的服务版本；同一数据目录第二次启动失败并写明原因
    import httpx

    version = _version(REPO_ROOT / "pyproject.toml")
    wheel = _wheel_path(release_build["output_dir"], version)
    with zipfile.ZipFile(wheel) as archive:
        packaged_index = archive.read("harness/release_assets/index.html")

    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(venv), "--python", "3.12"], check=True, capture_output=True)
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)],
                   check=True, capture_output=True)
    command = scripts / ("yudao.exe" if os.name == "nt" else "yudao")
    assert command.is_file(), command

    released = subprocess.run([str(command), "--version"], check=True, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=_env())
    assert released.stdout.strip() == version

    data_dir = tmp_path / "data"
    log = tmp_path / "api.log"
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    with log.open("wb") as output:
        api = subprocess.Popen([str(command), "api", "--data-dir", str(data_dir),
                                "--port", "0", "--provider-config", ""],
                               stdout=output, stderr=subprocess.STDOUT, **spawn)
    try:
        port = _wait_port(api, log, data_dir)
        _wait_until_serving(api, f"http://127.0.0.1:{port}/api/queries/system.status", log)
        index = httpx.get(f"http://127.0.0.1:{port}/", timeout=10)
        assert index.status_code == 200 and index.content == packaged_index
        capabilities = httpx.get(f"http://127.0.0.1:{port}/api/capabilities", timeout=10)
        assert capabilities.status_code == 200
        assert capabilities.json()["deployment"]["version"] == version

        # 同一数据目录第二次启动失败并写明原因（服务进程锁）
        second = subprocess.run(
            [str(command), "api", "--data-dir", str(data_dir), "--port", "0",
             "--provider-config", ""],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
            env=_env())
        assert second.returncode != 0
        assert "data directory is in use by another service process" in second.stderr
        assert str(data_dir.resolve()) in second.stderr
    finally:
        _stop(api)

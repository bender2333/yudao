# 工单 #298：`yudao api --data-dir X` 启动的服务把 Provider 目录文件与准入记录写在 X 内（设计说明第 3.4 节）。
# 全部是真实行为：真实的服务子进程、真实的接口命令、真实的模型上游（测试内启动的本机 HTTP 服务），不使用桩替身。

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

from harness.data_directory import LOG_DIR, LOG_FILE
from harness.tests.protocol_helpers import responses_responder, serve

REPO_ROOT = Path(__file__).resolve().parents[2]
# 服务进程启动时导入模型 SDK 并构建流事件的模型，机器负载高时要一分钟以上
STARTUP_TIMEOUT_SEC = 300
# 模型测试以后准入记录落盘的等待上限
ADMISSION_TIMEOUT_SEC = 120
SECRET = "issue-298-secret-key"
REF = "ISSUE298_KEY"
PROVIDER_ID = "p298"
MODEL_ID = "m298"

PORT_LINE = "port: "


def _user_data_environment(user_root: Path) -> dict[str, str]:
    # 把用户数据目录的根指向临时目录：Windows 读 LOCALAPPDATA，其他系统读 XDG_DATA_HOME。
    # 两个都设，测试在两种系统上都指向同一个临时目录，用户的真实目录不参与
    return {**os.environ, "PYTHONPATH": str(REPO_ROOT),
            "LOCALAPPDATA": str(user_root), "XDG_DATA_HOME": str(user_root)}


def _start_service(user_root: Path, arguments: list[str], log: Path) -> subprocess.Popen:
    # 真实的服务子进程：选项写在子命令之前或之后由 arguments 决定。
    # 端口由子进程自己绑定（--port 0），就绪以后在输出里报告实际端口：由调用方先占用再释放端口的
    # 写法在多进程运行中会冲突
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    with log.open("wb") as output:
        return subprocess.Popen(
            [sys.executable, "-m", "harness", *arguments, "--port", "0"],
            cwd=str(user_root.parent), env=_user_data_environment(user_root),
            stdout=output, stderr=subprocess.STDOUT, **spawn)


def _wait_until_serving(process: subprocess.Popen, port: int, log: Path) -> None:
    url = f"http://127.0.0.1:{port}/api/queries/system.status"
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


def _stop_service(process: subprocess.Popen) -> None:
    # 只结束本测试启动的进程树
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(STARTUP_TIMEOUT_SEC)


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


def _provider(base_url: str) -> dict:
    return {"id": PROVIDER_ID, "name": "工单 298 服务", "base_url": base_url,
            "credential_ref": REF, "timeout_sec": 20.0, "preset_id": "", "models_url": ""}


def _model() -> dict:
    return {"id": MODEL_ID, "model": "upstream-298", "protocol": "responses", "capacity_confirmed": True,
            "context_window": 32000, "max_output_tokens": 2048}


def _catalog_revision(client: httpx.Client) -> int:
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]["revision"]


def _command(client: httpx.Client, name: str, **body) -> None:
    response = client.post(f"/api/commands/{name}", json={"command_id": str(uuid.uuid4()), **body})
    assert response.status_code == 200, response.text


def _save_connection(client: httpx.Client, base_url: str) -> None:
    _command(client, "catalog.connection.save", base_version=_catalog_revision(client),
             provider=_provider(base_url), models=[_model()])


def _test_model(client: httpx.Client) -> None:
    _command(client, "catalog.model.test", base_version=_catalog_revision(client),
             provider_id=PROVIDER_ID, model_id=MODEL_ID)


def _wait_for_file(path: Path, process: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + ADMISSION_TIMEOUT_SEC
    while time.monotonic() < deadline:
        assert process.poll() is None, log.read_text(encoding="utf-8", errors="replace")
        if path.is_file():
            return
        time.sleep(0.2)
    raise TimeoutError(f"{path.name} did not appear: {log.read_text(encoding='utf-8', errors='replace')}")


def _absent_in_user_data_directory(user_root: Path) -> bool:
    # 用户数据目录里没有这两个文件：整个根下递归核对，默认目录连目录都不必建立
    if not user_root.exists():
        return True
    names = {"providers.json", "admissions.json"}
    return not [item for item in user_root.rglob("*") if item.is_file() and item.name in names]


def test_the_service_writes_the_catalog_and_admissions_into_the_data_directory(tmp_path):
    # 验收 1：环境变量把用户数据目录的根指向临时目录 A，`--data-dir B api` 启动以后保存连接并测试模型，
    # B 下出现 providers.json 与 admissions.json，A 下没有这两个文件
    user_root = tmp_path / "user-data-root"
    data_dir = tmp_path / "data-b"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / ".env").write_text(f"{REF}={SECRET}\n", encoding="utf-8")
    server, _capture, upstream = serve(responses_responder)
    log = tmp_path / "api.log"
    api = _start_service(user_root, ["--data-dir", str(data_dir), "api"], log)
    try:
        port = _wait_port(api, log, data_dir)
        _wait_until_serving(api, port, log)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=STARTUP_TIMEOUT_SEC) as client:
            _save_connection(client, f"{upstream}/v1")
            _test_model(client)
            _wait_for_file(data_dir / "admissions.json", api, log)

        config = data_dir / "providers.json"
        assert config.is_file(), config
        document = json.loads(config.read_text(encoding="utf-8"))
        assert [item["id"] for item in document["providers"]] == [PROVIDER_ID]
        admissions = data_dir / "admissions.json"
        assert admissions.is_file(), admissions
        assert [item["model_id"] for item in json.loads(admissions.read_text(encoding="utf-8"))["admissions"]] \
            == [MODEL_ID]
        assert _absent_in_user_data_directory(user_root)
    finally:
        _stop_service(api)
        server.shutdown()
        server.server_close()


def test_an_explicit_provider_config_keeps_both_files_next_to_it(tmp_path):
    # 验收 2：明确给出 --provider-config 时目录文件在该路径，admissions.json 与它同目录；
    # 数据目录内不再出现这两个文件
    user_root = tmp_path / "user-data-root"
    data_dir = tmp_path / "data-b"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    config = elsewhere / "catalog.json"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / ".env").write_text(f"{REF}={SECRET}\n", encoding="utf-8")
    server, _capture, upstream = serve(responses_responder)
    log = tmp_path / "api.log"
    api = _start_service(user_root, ["api", "--data-dir", str(data_dir), "--provider-config", str(config)],
                         log)
    try:
        port = _wait_port(api, log, data_dir)
        _wait_until_serving(api, port, log)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=STARTUP_TIMEOUT_SEC) as client:
            _save_connection(client, f"{upstream}/v1")
            _test_model(client)
            _wait_for_file(elsewhere / "admissions.json", api, log)

        assert config.is_file(), config
        assert (elsewhere / "admissions.json").is_file()
        assert not (data_dir / "providers.json").exists()
        assert not (data_dir / "admissions.json").exists()
        assert _absent_in_user_data_directory(user_root)
    finally:
        _stop_service(api)
        server.shutdown()
        server.server_close()

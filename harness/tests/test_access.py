# 访问方式（设计说明第 6.2 节）：真实启动接口，经 HTTP 检查 Host、Origin、命令的媒体类型与 CORS。

import socket
import uuid

from harness.__main__ import main
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api


class _Opened:
    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, FakeAdapter([])))
        self.applications.append(application)
        return application


def _lan_address() -> str:
    # 本机的局域网地址：从另一台机器访问控制主机时用的就是它；没有时用回环
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        address = info[4][0]
        if not address.startswith("127."):
            return address
    return "127.0.0.1"


def test_local_access_rejects_a_host_that_is_not_a_local_name(data_dir):
    # 本机访问方式：Host 不属于 127.0.0.1、localhost 或 [::1] 时拒绝，防止 DNS 重新绑定
    with running_api(_Opened(data_dir)) as client:
        rejected = client.get("/api/capabilities", headers={"Host": "evil.example"})
    assert rejected.status_code == 403
    assert rejected.content == b""


def test_access_rejects_an_origin_that_is_not_the_client_page(data_dir):
    # 带 Origin 的请求只接受桌面客户端页面的来源，其他网站的页面不能借用浏览器操作服务
    with running_api(_Opened(data_dir)) as client:
        rejected = client.get("/api/capabilities", headers={"Origin": "https://evil.example"})
    assert rejected.status_code == 403
    assert rejected.content == b""


def test_commands_only_accept_json(data_dir):
    # 命令只接受 application/json：带参数的其他类型与没有类型的请求都被拒绝，命令没有写入
    opened = _Opened(data_dir)
    body = {"command_id": str(uuid.uuid4()), "name": "文本工具", "goal": "逐行处理文本"}
    with running_api(opened) as client:
        typed = client.post("/api/commands/project.create", json=body, headers={"Content-Type": "text/plain"})
        untyped = client.post("/api/commands/project.create", content=b"{}")
        accepted = client.post("/api/commands/project.create", json=body,
                               headers={"Content-Type": "application/json; charset=utf-8"})
        assert typed.status_code == 415 and typed.content == b""
        assert untyped.status_code == 415 and untyped.content == b""
        assert accepted.status_code == 200
        project_id = accepted.json()["refs"]["project_id"]
        assert [event.type for event in opened.applications[0].system.store.list_project_events(project_id)] == [
            "project_registered"]


def test_cors_allows_only_the_client_page_origin(data_dir):
    # CORS 只允许客户端页面的来源：允许的来源回显，预检放行命令需要的 POST 与 JSON 请求头，其他来源被拒绝
    with running_api(_Opened(data_dir)) as client:
        allowed = client.get("/api/capabilities", headers={"Origin": "yudao://app"})
        preflight = client.options("/api/commands/project.create", headers={
            "Origin": "yudao://app", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        rejected = client.options("/api/commands/project.create", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
        })
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "yudao://app"
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "yudao://app"
    assert preflight.headers["access-control-allow-methods"] == "GET, POST"
    assert "content-type" in preflight.headers["access-control-allow-headers"].lower()
    assert rejected.status_code == 403


def test_capabilities_list_the_access_mode(data_dir):
    # 能力清单列出访问方式（设计说明第 6.1、6.2 节）：本机与局域网由启动设置给出
    with running_api(_Opened(data_dir)) as client:
        local = client.get("/api/capabilities").json()["deployment"]["access"]
    with running_api(_Opened(data_dir), access="lan") as client:
        lan = client.get("/api/capabilities").json()["deployment"]["access"]
    assert (local, lan) == ("local", "lan")


def test_the_local_access_mode_refuses_to_listen_on_another_address(tmp_path, capsys):
    # 本机访问方式设置非回环地址时拒绝启动（默认访问方式就是本机），不取得锁，也不建立数据目录
    assert main(["api", "--access", "local", "--host", "0.0.0.0", "--data-dir", str(tmp_path / "data")]) == 1
    assert "only listens on a loopback address, not 0.0.0.0" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_lan_access_serves_the_local_network_and_checks_only_the_origin(data_dir):
    # 局域网访问方式：监听任意地址，经局域网地址读取能力清单、查询与提交命令，事件的提出者是 user:local；
    # Host 不受本机名称限制，Origin 与客户端来源不同的请求被拒绝
    opened = _Opened(data_dir)
    with running_api(opened, access="lan", host="0.0.0.0", connect=_lan_address()) as client:
        capabilities = client.get("/api/capabilities")
        status = client.get("/api/queries/system.status")
        accepted = client.post("/api/commands/project.create",
                               json={"command_id": str(uuid.uuid4()), "name": "接入已有项目", "goal": "整理需求"},
                               headers={"Origin": "yudao://app"})
        other_host = client.get("/api/capabilities", headers={"Host": "control-host"})
        rejected = client.get("/api/queries/system.status", headers={"Origin": "https://evil.example"})
        # 事件流路由属于 #75（尚未实施）；这里核对访问检查对它的作用
        stream_denied = client.get("/api/events", headers={"Origin": "https://evil.example"})
        stream_allowed = client.get("/api/events", headers={"Origin": "yudao://app"})
        events = opened.applications[0].system.store.list_project_events(accepted.json()["refs"]["project_id"])
    assert capabilities.status_code == 200
    assert capabilities.json()["deployment"]["access"] == "lan"
    assert status.status_code == 200
    assert accepted.status_code == 200
    assert other_host.status_code == 200
    assert rejected.status_code == 403
    assert stream_denied.status_code == 403
    # #75 实施以后是 200（订阅成功），在此之前是 404（路由尚未登记）
    assert stream_allowed.status_code in (200, 404)
    assert [event.actor for event in events] == ["user:local"]

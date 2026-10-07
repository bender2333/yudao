# 访问方式（设计说明第 6.2 节）与页面文件（网页界面的提供与发布设计说明第 5.1 节）：真实启动接口，
# 经 HTTP 检查 Host、Origin、命令的媒体类型、同一来源与页面文件。

import re
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


def test_access_rejects_an_origin_that_is_not_the_service_itself(data_dir):
    # 带 Origin 的请求只接受服务自己的来源，其他网站的页面不能借用浏览器操作服务
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


def test_same_origin_requests_are_accepted_without_cors_headers(data_dir):
    # 页面与接口同一来源：Origin 为 http:// 加本次请求的 Host 时接受；同一个端口的另一个主机名、
    # 其他协议与原来的客户端来源都被拒绝；任何响应都不带 CORS 响应头
    with running_api(_Opened(data_dir)) as client:
        origin = str(client.base_url).rstrip("/")
        port = client.base_url.port
        allowed = client.get("/api/capabilities", headers={"Origin": origin})
        command = client.post("/api/commands/project.create", headers={"Origin": origin},
                              json={"command_id": str(uuid.uuid4()), "name": "文本工具", "goal": "逐行处理文本"})
        rejected = [client.get("/api/capabilities", headers={"Origin": other}) for other in (
            f"http://localhost:{port}", f"https://127.0.0.1:{port}", "yudao://app")]
        preflight = client.options("/api/commands/project.create", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
        })
    assert allowed.status_code == 200 and command.status_code == 200
    assert [response.status_code for response in rejected] == [403, 403, 403]
    for response in (allowed, command, preflight, *rejected):
        assert not any(name.startswith("access-control-") for name in response.headers)


def _pages(root):
    # 一份 Vite 构建结构的页面文件：入口页面引用 assets/ 下带内容摘要的脚本与样式
    root.mkdir()
    (root / "assets").mkdir()
    (root / "index.html").write_text(
        '<!doctype html><html><head><script type="module" src="/assets/index-a1b2c3.js"></script>'
        '<link rel="stylesheet" href="/assets/index-d4e5f6.css"></head><body><div id="root"></div></body></html>',
        encoding="utf-8")
    (root / "assets" / "index-a1b2c3.js").write_text("console.log('yudao');", encoding="utf-8")
    (root / "assets" / "index-d4e5f6.css").write_text("body{margin:0}", encoding="utf-8")
    return root


def test_the_service_serves_the_page_files(data_dir, tmp_path):
    # `/` 返回入口页面（每次确认），入口页面引用的文件都能取得（长期缓存）；接口路径照常由接口回答，
    # 没有的接口路径不返回页面，页面目录之外的文件取不到；页面文件不列入 OpenAPI
    with running_api(_Opened(data_dir), pages=_pages(tmp_path / "pages")) as client:
        index = client.get("/")
        referenced = [client.get(path) for path in re.findall(r'(?:src|href)="(/[^"]+)"', index.text)]
        capabilities = client.get("/api/capabilities")
        unknown_api = client.get("/api/queries/no.such.query")
        escape = client.get("/..%2F..%2Fpyproject.toml")
        missing = client.get("/assets/absent.js")
        paths = client.get("/openapi.json").json()["paths"]
    assert index.status_code == 200 and index.headers["content-type"].startswith("text/html")
    assert index.headers["cache-control"] == "no-cache"
    assert [response.status_code for response in referenced] == [200, 200]
    assert referenced[0].text == "console.log('yudao');"
    assert all("immutable" in response.headers["cache-control"] for response in referenced)
    assert capabilities.status_code == 200
    assert unknown_api.status_code == 404 and "root" not in unknown_api.text
    assert escape.status_code == 404 and missing.status_code == 404
    assert all(path.startswith(("/api/", "/client-update/")) for path in paths)


def test_without_page_files_the_root_explains_why(data_dir, tmp_path):
    # 从源码运行而没有构建页面：`/` 返回 404 并写明「没有页面文件」
    with running_api(_Opened(data_dir), pages=tmp_path / "absent") as client:
        response = client.get("/")
    assert response.status_code == 404
    assert response.json() == {"error": "没有页面文件"}


def test_local_access_checks_the_host_for_page_files(data_dir, tmp_path):
    # 本机访问方式的 Host 检查对页面文件同样适用
    with running_api(_Opened(data_dir), pages=_pages(tmp_path / "pages")) as client:
        allowed = client.get("/")
        rejected = client.get("/", headers={"Host": "evil.example"})
        asset = client.get("/assets/index-a1b2c3.js", headers={"Host": "evil.example"})
    assert allowed.status_code == 200
    assert rejected.status_code == 403 and asset.status_code == 403


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


def test_lan_access_serves_the_local_network_and_checks_only_the_origin(data_dir, tmp_path):
    # 局域网访问方式：监听任意地址，经局域网地址打开页面、读取能力清单、查询与提交命令，事件的提出者是
    # user:local；Host 不受本机名称限制，页面文件同样经过访问检查；Origin 与服务自己的来源不同的请求被拒绝
    opened = _Opened(data_dir)
    with running_api(opened, access="lan", host="0.0.0.0", connect=_lan_address(),
                     pages=_pages(tmp_path / "pages")) as client:
        origin = str(client.base_url).rstrip("/")
        page = client.get("/")
        page_denied = client.get("/", headers={"Origin": "https://evil.example"})
        capabilities = client.get("/api/capabilities")
        status = client.get("/api/queries/system.status")
        accepted = client.post("/api/commands/project.create",
                               json={"command_id": str(uuid.uuid4()), "name": "接入已有项目", "goal": "整理需求"},
                               headers={"Origin": origin})
        other_host = client.get("/api/capabilities", headers={"Host": "control-host"})
        rejected = client.get("/api/queries/system.status", headers={"Origin": "https://evil.example"})
        # 页面经局域网地址订阅事件流成功（用一个超过日志末尾的 after 位置，服务端据此立即发送 resync
        # 并关闭连接），来源不同的订阅在路由之前被拒绝
        stream_denied = client.get("/api/events", headers={"Origin": "https://evil.example"})
        stream_allowed = client.get("/api/events?after=999999", headers={"Origin": origin})
        events = opened.applications[0].system.store.list_project_events(accepted.json()["refs"]["project_id"])
    assert page.status_code == 200 and page_denied.status_code == 403
    assert capabilities.status_code == 200
    assert capabilities.json()["deployment"]["access"] == "lan"
    assert status.status_code == 200
    assert accepted.status_code == 200
    assert other_host.status_code == 200
    assert rejected.status_code == 403
    assert stream_denied.status_code == 403
    # 订阅成功：事件流的内容类型正确，连接以重新同步结束
    assert stream_allowed.status_code == 200
    assert stream_allowed.headers["content-type"].startswith("text/event-stream")
    assert "event: resync" in stream_allowed.text
    assert [event.actor for event in events] == ["user:local"]

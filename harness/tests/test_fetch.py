# 网络取回（工单 #68；网络与 MCP 设计说明第 3、6、8、9 节；总图第四节「动作」缝的 fetch 类别）。
#
# 用本机启动的真实 HTTP 服务核对：回执与外部来源工件完整、read_external_source 接着读第二页不再取回、
# 服务自己的地址与端口被拒绝（包括重定向到它）、回环的其它地址可以取回、超过下载上限与超时与不支持的
# 内容类型各有真实的状态与原因、请求头里没有 Cookie 与凭据、重定向的每一跳都检查地址，
# 以及 run.actions 的动作视图带上取回的回执字段与被拒绝的标记。
#
# 层：集成层（真实的本机服务与端口）。守 R2（动作回执的交换字段、外部来源工件引用与被拒绝标记）
# 与 R3（取回的地址规则、限额与结果工件）。

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from harness import fetch
from harness.actions import Action
from harness.app.application import Application, ReadOnlyCore
from harness.app.project_queries import RunActions
from harness.artifacts import ArtifactStore
from harness.environment import LocalEnvironment
from harness.event_store import EventStore, run_stream
from harness.models import EventType
from harness.projection import run_handler
from harness.write_path import NewEvent, WritePath

RUN = "run_fetch"
PAGE_LINES = 400
LINE_WIDTH = 100
DOWNLOAD_LIMIT = 5 * 1024 * 1024


def _page_html() -> bytes:
    return (
        "<html><body><h1>Echo manual</h1>"
        "<p>Read the <a href='https://example.com/spec'>specification</a> first.</p>"
        "<ul><li>first step</li><li>second step</li></ul>"
        "<table><tr><th>flag</th><th>meaning</th></tr>"
        "<tr><td>-n</td><td>no newline</td></tr></table>"
        "</body></html>"
    ).encode("utf-8")


def _long_text() -> bytes:
    return "".join(f"line {number:04d} " + "x" * LINE_WIDTH + "\n"
                   for number in range(1, PAGE_LINES + 1)).encode("utf-8")


def _routes() -> dict[str, tuple[int, dict[str, str], bytes]]:
    return {
        "/page": (200, {"Content-Type": "text/html; charset=utf-8"}, _page_html()),
        "/text": (200, {"Content-Type": "text/plain; charset=utf-8"}, _long_text()),
        "/missing": (404, {"Content-Type": "text/html; charset=utf-8"}, b"<p>no such page</p>"),
        "/binary": (200, {"Content-Type": "application/octet-stream"}, b"\x00\x01\x02\x03"),
        "/big": (200, {"Content-Type": "text/plain; charset=utf-8"}, b"y" * (6 * 1024 * 1024)),
    }


def _start(routes: dict[str, tuple[int, dict[str, str], bytes]],
           slow_path: str | None = None) -> tuple[ThreadingHTTPServer, list[dict[str, Any]]]:
    # 真实的本机 HTTP 服务：记录收到的每个请求（路径与请求头），按路径给出状态、头与正文
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的约定
            seen.append({"path": self.path,
                         "headers": {key.lower(): value for key, value in self.headers.items()}})
            if slow_path is not None and self.path == slow_path:
                time.sleep(1.0)
            status, headers, body = routes.get(
                self.path, (404, {"Content-Type": "text/plain; charset=utf-8"}, b"not found"))
            try:
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                # 取回超时或被取消时客户端会先断开：服务端的连接随之关掉，不往终端写异常
                return

        def log_message(self, *args: Any) -> None:
            return

    class Server(ThreadingHTTPServer):
        def handle_error(self, request, client_address) -> None:
            # 取回超时或被取消时客户端先断开连接：这类连接的异常不往终端写堆栈
            error = sys.exc_info()[1]
            if isinstance(error, (ConnectionError, OSError)):
                return
            super().handle_error(request, client_address)

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def _base(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def servers():
    # 两个本机服务：target 是取回的目标（先起它好知道它的端口），service 当作 Yudao 服务自己的监听地址。
    # target 上有一个重定向到 service 的路径，用于核对「第一跳合法、第二跳指向服务自己」
    service, service_seen = _start({
        "/page": (200, {"Content-Type": "text/html; charset=utf-8"}, _page_html()),
    })
    routes = _routes()
    routes["/to-service"] = (302, {"Location": f"{_base(service)}/page"}, b"")
    target, target_seen = _start(routes, slow_path="/slow")
    fetch.configure_service_address("127.0.0.1", service.server_address[1])
    try:
        yield {
            "target": target, "target_seen": target_seen,
            "service": service, "service_seen": service_seen,
        }
    finally:
        fetch.clear_service_address()
        for server in (target, service):
            server.shutdown()
            server.server_close()


def _store(tmp_path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


def _environment(tmp_path, store: ArtifactStore) -> LocalEnvironment:
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    return LocalEnvironment.open(root, artifacts=store, run_id=RUN)


def _perform(environment: LocalEnvironment, tool: str, tool_input: dict[str, Any], kind: str):
    return asyncio.run(environment.perform(Action(
        action_id=f"act:{tool}", kind=kind, tool=tool, department="engineering", input=tool_input,
        verification="none", cancellable=True)))


def _fetch(environment: LocalEnvironment, url: str):
    return _perform(environment, "fetch_url", {"url": url}, "fetch")


def test_a_real_page_is_fetched_and_the_rest_is_read_without_fetching_again(tmp_path, servers):
    store = _store(tmp_path)
    environment = _environment(tmp_path, store)
    url = f"{_base(servers['target'])}/text"

    receipt = _fetch(environment, url)

    assert receipt.status == "completed" and receipt.ok, receipt.error
    output = receipt.output
    assert output["url"] == url and output["final_url"] == url
    assert output["status_code"] == 200
    assert output["content_type"] == "text/plain"
    assert output["content_hash"].startswith("sha256:")
    assert output["ref"]["kind"] == "external_source"
    assert output["ref"]["content_hash"] == output["content_hash"]
    assert output["redirects"] == []
    assert output["duration_ms"] >= 0
    assert output["external_content"] is True and output["notice"]
    assert output["total_lines"] == PAGE_LINES
    assert output["truncated"] is True and output["next_cursor"]

    second = _perform(environment, "read_external_source",
                      {"source": output["content_hash"], "start_line": 1, "cursor": output["next_cursor"]},
                      "read")
    assert second.status == "completed", second.error
    assert second.output["lines"][0]["line"] == output["end_line"] + 1
    # 第二页读的是已经存下来的工件：服务只收到过一次请求
    assert [item["path"] for item in servers["target_seen"]] == ["/text"]


def test_html_keeps_headings_lists_links_and_tables(tmp_path, servers):
    store = _store(tmp_path)
    environment = _environment(tmp_path, store)

    receipt = _fetch(environment, f"{_base(servers['target'])}/page")

    assert receipt.status == "completed", receipt.error
    entry = store.external_source(RUN, receipt.output["content_hash"])
    assert "Echo manual" in entry.text
    assert "* first step" in entry.text and "second step" in entry.text
    assert "https://example.com/spec" in entry.text
    assert "| flag | meaning |" in entry.text and "no newline" in entry.text


def test_requests_carry_no_credentials_and_no_cookies(tmp_path, servers):
    environment = _environment(tmp_path, _store(tmp_path))

    receipt = _fetch(environment, f"{_base(servers['target'])}/page")

    assert receipt.status == "completed", receipt.error
    [seen] = servers["target_seen"]
    headers = seen["headers"]
    assert headers["user-agent"].startswith("Yudao/")
    assert "text/html" in headers["accept"]
    assert "cookie" not in headers and "authorization" not in headers

    with_credentials = f"{_base(servers['target'])}/page".replace("http://", "http://user:secret@")
    refused = _fetch(environment, with_credentials)
    assert refused.status == "failed" and not refused.ok
    assert "credentials" in (refused.error or "")


def test_the_service_address_is_refused_directly_and_through_a_redirect(tmp_path, servers):
    environment = _environment(tmp_path, _store(tmp_path))

    direct = _fetch(environment, f"{_base(servers['service'])}/page")

    assert direct.refused is True and direct.status == "failed"
    assert "own address and port" in (direct.refused_reason or "")
    assert servers["service_seen"] == [], "服务自己的地址在被拒绝之前就收到了请求"

    # 回环的其它地址可以取回
    allowed = _fetch(environment, f"{_base(servers['target'])}/page")
    assert allowed.status == "completed" and allowed.ok

    # 第一跳合法、第二跳指向服务自己的地址：每一跳都检查，重定向到那里同样被拒绝
    redirected = _fetch(environment, f"{_base(servers['target'])}/to-service")
    assert redirected.refused is True
    assert "own address and port" in (redirected.refused_reason or "")
    assert servers["service_seen"] == [], "重定向到服务自己的地址时仍然发出了请求"


def test_limits_and_unsupported_content_types_report_real_reasons(tmp_path, servers, monkeypatch):
    store = _store(tmp_path)
    environment = _environment(tmp_path, store)

    big = _fetch(environment, f"{_base(servers['target'])}/big")
    assert big.status == "completed", big.error
    assert big.output["download_truncated"] is True
    assert big.output["bytes"] == DOWNLOAD_LIMIT

    binary = _fetch(environment, f"{_base(servers['target'])}/binary")
    assert binary.status == "failed" and not binary.ok
    assert "unsupported content type" in (binary.error or "")

    monkeypatch.setattr(fetch, "TOTAL_TIMEOUT_SEC", 0.3)
    slow = _fetch(environment, f"{_base(servers['target'])}/slow")
    assert slow.status == "failed" and not slow.ok
    assert "took longer" in (slow.error or "")

    missing = _fetch(environment, f"{_base(servers['target'])}/missing")
    assert missing.status == "completed" and missing.ok
    assert missing.output["status_code"] == 404
    entry = store.external_source(RUN, missing.output["content_hash"])
    assert "no such page" in entry.text


def test_run_actions_carries_the_fetch_receipt_and_the_refusal(tmp_path):
    data_dir = tmp_path / "data"
    store = ArtifactStore(data_dir / "artifacts")
    output = {
        "url": "https://example.com/a", "final_url": "https://example.com/b", "status_code": 200,
        "content_type": "text/html", "bytes": 1234, "download_truncated": False,
        "content_hash": "sha256:" + "a" * 64, "ref": None, "redirects": ["https://example.com/a"],
        "duration_ms": 42, "external_content": True, "notice": "external",
    }
    ref = store.put(RUN, "tool_output", json.dumps(output), media_type="application/json")
    database = EventStore(data_dir / "events.sqlite")
    writes = WritePath(database, lambda _stream: run_handler())
    writes.append(run_stream(RUN), NewEvent(
        EventType.TOOL_CALLED, state_before="running", state_after="running", actor="system",
        payload={"id": "call-1", "name": "fetch_url", "step_id": 1, "activation_id": "act-1",
                 "args": {"url": "https://example.com/a"}, "ok": True, "error": None,
                 "output_ref": {"kind": ref.kind, "content_hash": ref.content_hash, "path": ref.path,
                                "media_type": ref.media_type}}))
    refusal = ("refused to fetch http://127.0.0.1:8765/page: it points at the Yudao service's own "
               "address and port (127.0.0.1:8765)")
    writes.append(run_stream(RUN), NewEvent(
        EventType.TOOL_CALLED, state_before="running", state_after="running", actor="system",
        payload={"id": "call-2", "name": "fetch_url", "step_id": 1, "activation_id": "act-1",
                 "args": {"url": "http://127.0.0.1:8765/page"}, "ok": False, "error": refusal,
                 "refused": True, "refused_reason": refusal}))
    database.close()
    application = Application(ReadOnlyCore(data_dir))
    try:
        snapshot = application.query("run.actions", RunActions(run_id=RUN))
    finally:
        application.close()
    fetched, refused = snapshot.data.actions
    assert fetched.tool == "fetch_url" and fetched.status == "completed"
    assert fetched.receipt is not None and fetched.receipt.fetch is not None
    assert fetched.receipt.fetch.status_code == 200
    assert fetched.receipt.fetch.final_url == "https://example.com/b"
    assert fetched.receipt.fetch.bytes == 1234
    assert fetched.receipt.fetch.redirects == ["https://example.com/a"]
    assert fetched.receipt.fetch.duration_ms == 42
    assert refused.status == "refused"
    assert refused.receipt is not None and refused.receipt.refused is True
    assert "own address and port" in (refused.receipt.refused_reason or "")

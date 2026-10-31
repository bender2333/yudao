# 取回进行到一半终止 Yudao（工单 #1173；网络与 MCP 设计说明第 5.1、8、12 节、恢复契约第 4 节）。
#
# 本机 HTTP 服务卡住响应，取回在飞行中时终止真实的 Yudao 进程；重新打开以后这次调用作为工具结果
# 交还发出它的会话（resolution="handed_back"），写明执行被中断、结果未知，没有自动重新取回，
# 也没有决定请求；模型重新取回时两次尝试分别记录；没有完整结果的尝试不保存外部来源工件。
#
# 层：集成层（真实进程终止、真实的本机 HTTP 服务与端口）。守 R2（恢复时结果未知动作的交换字段，
# 以及恢复页与动作表读到的处置）与 R3（取回的恢复处置与外部来源工件）。
# 中断与重启的辅助代码在 harness/tests/process_kill.py（#307 已合并）。测试里不 mock。

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from harness.app.application import Application
from harness.app.project_queries import RunActions, RunRecovery
from harness.proposals import product_spec
from harness.tests import process_kill as killed

FETCH_CALL = "call-fetch"
RETRY_CALL = "call-fetch-retry"


def _fetch_call(identity: str, url: str) -> dict[str, Any]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "fetch_url",
            "arguments": json.dumps({"url": url})}


def _base(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def _stuck_server(marker: Path) -> tuple[ThreadingHTTPServer, list[str], threading.Event]:
    # 真实的本机 HTTP 服务：第一条请求写下标记以后一直不回应，取回因此停在飞行中；
    # 之后的请求（模型重新取回的那一次）照常回应。父进程见到标记就终止 Yudao 进程：
    # 那一刻请求已经发出、还没有收到任何结果
    released = threading.Event()
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的约定
            seen.append(self.path)
            first = len(seen) == 1
            if first:
                marker.write_text("requested", encoding="utf-8")
                # 等到用例结束：Yudao 进程被终止时这条连接随之断开
                released.wait(120)
            body = b"<html><body><h1>Echo manual</h1><p>read the manual</p></body></html>"
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                # 进程被终止以后客户端先断开：这类连接的异常不往终端写堆栈
                return

        def log_message(self, *args: Any) -> None:
            return

    class Server(ThreadingHTTPServer):
        def handle_error(self, request: Any, client_address: Any) -> None:
            error = sys.exc_info()[1]
            if isinstance(error, (ConnectionError, OSError)):
                return
            super().handle_error(request, client_address)

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen, released


def _external_sources(data_dir: Path) -> list[Path]:
    # 这个数据目录里已经保存的外部来源工件：每份工件旁边有一份 .source.json（ArtifactStore）；
    # 没有完整结果的取回尝试不写这份文件，因此它的数量就是「保存了几份完整取回」的答案
    return sorted((data_dir / "artifacts").rglob("*.source.json"))


def _attempts(system: Any, run_id: str, call_id: str) -> list[dict[str, Any]]:
    # 整个 run 里这一个调用编号的每一次尝试（tool_started 的载荷，带上结果事件的种类）
    return killed.tool_attempts(system, run_id, call_id)


def _run_actions_and_recovery(system: Any, run_id: str) -> tuple[dict[str, Any], Any]:
    # 动作表与恢复页：这两个查询是界面读未完成动作处置的地方（恢复契约第 4 节）
    application = Application(system)
    try:
        actions = application.query("run.actions", RunActions(run_id=run_id)).data.actions
        recovery = application.query("run.recovery", RunRecovery(run_id=run_id)).data
    finally:
        application.close()
    return {action.action_id: action for action in actions}, recovery


def test_an_interrupted_fetch_is_handed_back_to_the_session_and_the_retry_is_a_second_attempt(tmp_path):
    # 验收一：取回进行中终止进程，重新启动以后这次调用显示「执行被中断、结果未知」，
    # 没有自动重新取回，也没有决定请求；模型重新取回时两次尝试分别记录
    data_dir = tmp_path / "data"
    marker = tmp_path / "fetch-requested"
    server, seen, released = _stuck_server(marker)
    try:
        url = _base(server) + "/manual"
        # 终止以前：产品部门调一次取回，进程在取回飞行中被终止
        script = {"product": [{"output": [_fetch_call(FETCH_CALL, url)]}],
                  "engineering": [{"proposal": {"kind": "delivery_spec"}}],
                  "quality": [{"proposal": {"kind": "quality_auto"}}]}
        # 重启以后：模型读完交还的结果，重新取回一次（新的调用编号），然后提交规格
        tail = {"product": [{"output": [_fetch_call(RETRY_CALL, url)]}, {"proposal": product_spec()}],
                "engineering": [{"proposal": {"kind": "delivery_spec"}}],
                "quality": [{"proposal": {"kind": "quality_auto"}}]}
        with killed.interrupted(data_dir, script, tail=tail, started=marker,
                                resume_after=False) as run:
            run.after.resume_startup_runs()

            events = killed.events(run.after, run.run_id)
            started = [event for event in events
                       if event.type == "tool_started"
                       and (event.payload or {}).get("id") == FETCH_CALL]
            # 没有自动重新取回：整个 run 里只有最初那一次调用，也没有它的回执
            assert len(started) == 1
            assert [event for event in events if event.type == "tool_called"
                    and (event.payload or {}).get("id") == FETCH_CALL] == []

            # 交还发出它的会话：一条 handed_back 的核实记录，写明执行被中断、结果未知
            [verified] = killed.events(run.after, run.run_id, "action_verified")
            payload = verified.payload
            assert payload["id"] == FETCH_CALL
            assert payload["name"] == "fetch_url"
            assert payload["resolution"] == "handed_back"
            assert payload["ok"] is False
            assert "执行被中断" in payload["error"] and "结果未知" in payload["error"]
            assert verified.session_id == started[0].session_id
            assert payload["input_item"]["call_id"] == FETCH_CALL
            # 交还的是工具结果本身：模型读到的是「没有成功、结果未知」
            assert json.loads(payload["input_item"]["output"])["ok"] is False

            # 没有决定请求（工单 #581 起交还取代了 unknown_action 决定请求）
            assert killed.unknown_action_requests(run.after, run.run_id) == []

            # 两次尝试分别记录：第一次没有回执，第二次取回完成
            assert [attempt["result_type"] for attempt in _attempts(run.after, run.run_id, FETCH_CALL)] == [None]
            assert [attempt["result_type"] for attempt in _attempts(run.after, run.run_id, RETRY_CALL)] == ["tool_called"]
            assert len(seen) >= 2, "第二次取回应当打到本机服务上"

            # 动作表：交还的那一次是 unknown、没有回执；重新取回的那一次完成，带上取回的明细
            actions, recovery = _run_actions_and_recovery(run.after, run.run_id)
            assert actions[FETCH_CALL].status == "unknown"
            assert actions[FETCH_CALL].receipt is None
            retried = actions[RETRY_CALL]
            assert retried.status == "completed" and retried.receipt is not None
            assert retried.receipt.fetch is not None
            assert retried.receipt.fetch.status_code == 200
            assert retried.receipt.fetch.ref is not None

            # 恢复页：未完成动作列出处置（交还发出它的会话）、会话与交还给模型的内容
            [unknown] = [item for item in recovery.unknown_actions if item.action_id == FETCH_CALL]
            assert unknown.tool == "fetch_url"
            assert unknown.handling == "returned"
            assert unknown.session_id == started[0].session_id
            assert "执行被中断" in (unknown.returned or "")

            # 没有完整结果的尝试不保存内容：这个 run 只有重新取回那一份完整取回的外部来源工件
            sources = _external_sources(data_dir)
            assert len(sources) == 1, [path.as_posix() for path in sources]
            digest = retried.receipt.fetch.content_hash.split(":", 1)[1]
            assert sources[0].name.startswith(digest)
    finally:
        released.set()
        server.shutdown()
        server.server_close()


def test_an_interrupted_fetch_saves_no_external_source_when_the_model_does_not_fetch_again(tmp_path):
    # 验收二：没有完整结果的尝试不保存内容——模型不重新取回时，这个 run 一份外部来源工件也没有，
    # 交还照样发生，动作表里这一次仍是没有回执的 unknown
    data_dir = tmp_path / "data"
    marker = tmp_path / "fetch-requested"
    server, seen, released = _stuck_server(marker)
    try:
        url = _base(server) + "/manual"
        script = {"product": [{"output": [_fetch_call(FETCH_CALL, url)]}],
                  "engineering": [{"proposal": {"kind": "delivery_spec"}}],
                  "quality": [{"proposal": {"kind": "quality_auto"}}]}
        tail = {"product": [{"proposal": product_spec()}],
                "engineering": [{"proposal": {"kind": "delivery_spec"}}],
                "quality": [{"proposal": {"kind": "quality_auto"}}]}
        with killed.interrupted(data_dir, script, tail=tail, started=marker,
                                resume_after=False) as run:
            run.after.resume_startup_runs()

            assert seen, "取回应当在进程被终止以前打到本机服务上"
            [verified] = killed.events(run.after, run.run_id, "action_verified")
            assert verified.payload["resolution"] == "handed_back"
            assert verified.payload["ok"] is False

            actions, _recovery = _run_actions_and_recovery(run.after, run.run_id)
            assert actions[FETCH_CALL].status == "unknown"
            assert actions[FETCH_CALL].receipt is None

            # 没有完整结果的尝试不保存为外部来源工件
            assert _external_sources(data_dir) == []
    finally:
        released.set()
        server.shutdown()
        server.server_close()

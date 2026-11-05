# 浏览器工具与会话：Playwright MCP + Chromium + 一个小网页（浏览器与 computer use 设计说明
# 「浏览器工具（Playwright MCP）」「保存与绑定」与「恢复契约」，工单 #1184；总图第四节「动作」缝的 browser 类别）。
#
# 这个文件查七件事：
# 1. 对会话中启动的真实网页完成导航、输入、点击与 browser_verify_* 断言：每一步的结果带页面的可访问性结构，
#    改变页面的步骤各带一张截图工件，回执里的摘要与保存下来的字节一致；
# 2. 调用目标只有文本时：进入部门历史的工具结果只有可访问性结构（没有图像），截图仍然保存为工件；
# 3. browser_file_upload 与 browser_drop 的路径在试用副本之外时被拒绝，副本之内的不被拒绝；
# 4. 导航到 Yudao 服务自己的地址与端口（127.0.0.1、localhost、本机网卡地址、本机主机名）被拒绝，
#    导航到会话中启动的软件自己的端口与一个真实外网地址可以访问；工具直接发起的导航包括
#    browser_navigate 的 url 与 browser_tabs 新建标签页时带的 url；
# 5. 来源限制不只看工具直接导航：页面上的链接点过去、页面脚本发出的请求都由浏览器按来源挡下，
#    服务那一侧一次请求都收不到（启动参数 --blocked-origins，工单 #1184 的审查第 3 条）；
# 6. 结果未知：browser_click 没有结果时重新启动 Yudao（新的系统打开同一数据目录）以后会话记为中断、
#    没有决定请求；动作进行期间结束 Playwright MCP 进程时回执为失败、会话记为中断。
#
# 层：集成层（真实的 Playwright MCP、真实的 Chromium、真实的小网页服务与子进程）。
# 守 R3：试用会话里的浏览器动作按当前页面状态执行，每一步的截图成为可核对的证据，结果未知时按恢复契约处置。
#
# MCP 客户端会话属于建立它的那个事件循环（stdio 的读写任务与子进程），所以一个场景里的全部动作跑在同一个
# 事件循环里，与服务的做法相同：这里用自己建的那个循环，不用每步一次的 asyncio.run。

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psutil
import pytest

from harness.actions import Action
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import RunActions
from harness.artifacts import ArtifactStore
from harness.browser import BrowserSessions
from harness.context import request_history
from harness.engine import tool_result_item
from harness.environment import LocalEnvironment
from harness.event_store import run_stream
from harness.fetch import clear_service_address, configure_service_address
from harness.models import EventType, hash_bytes, json_dumps
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tools import tool_cancellable, tool_verification
from harness.trial_sessions import TrialSessionTable, current_system
from harness.write_path import NewEvent

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tiny_web_app"
# 浏览器会话只在本机与控制主机两类位置上：系统不是 windows 或 linux 的机器没有启动命令的约定
pytestmark = pytest.mark.skipif(current_system() is None,
                                reason="trial launch commands are defined for windows and linux only")
# 小网页的服务：从 PORT 读端口，直接把这个目录当站点（index.html 就是页面）
_SERVER = (
    "import functools, http.server, os\n"
    f"handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=r'{FIXTURE}')\n"
    "http.server.HTTPServer(('127.0.0.1', int(os.environ['PORT'])), handler).serve_forever()\n"
)
_EXTERNAL_URL = "https://example.com/"

# Yudao 服务自己的地址与端口：一个真实的小服务，把收到的每一个请求写进日志，回报能认出来的内容。
# 浏览器挡下来时这个日志一行都不会多，所以「内容没出现」之外还有一条不依赖页面文字的判据
_SERVICE_PAGE_SERVER = textwrap.dedent("""
    import http.server, socket, sys
    from pathlib import Path
    LOG = Path(sys.argv[1])
    PAGE = (b"<html><head><title>Service page</title></head><body>"
            b"<h1>Service page</h1><p>service data</p></body></html>")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            with LOG.open("a", encoding="utf-8") as handle:
                handle.write(self.path + "\\n")
            data = self.path.startswith("/data")
            body = b"service data" if data else PAGE
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/plain; charset=utf-8" if data else "text/html; charset=utf-8")
            if data:
                # 页面脚本的普通（非 no-cors）请求在没被挡下时应当成功：服务这边允许跨来源读
                self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
    print(port, flush=True)
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
""")

# 试用会话启动的小网页：整站就是给定的那一页，端口由试用会话经 PORT 交来（与 fixture 的做法相同）
_PAGE_SERVER = textwrap.dedent("""
    import http.server, os, sys
    from pathlib import Path
    HTML = Path(sys.argv[1]).read_bytes()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(HTML)))
            self.end_headers()
            self.wfile.write(HTML)

        def log_message(self, *args):
            pass

    http.server.HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
""")

# 页面脚本发起的请求：服务那边允许跨来源读，所以请求发得出去时 Promise 成功（写下 got），
# 只有被浏览器按来源挡下来才转入 catch（写下 blocked）。两个结论都是页面自己写下的，不靠时长去猜
_SCRIPT_PAGE = """<!DOCTYPE html>
<html><head><title>script page</title></head><body>
<h1>app page</h1>
<div id="fetch-result">script pending</div>
<script>
fetch("__SERVICE__data").then(r => r.text()).then(t => {
  document.getElementById("fetch-result").textContent = "script got " + t;
}).catch(() => {
  document.getElementById("fetch-result").textContent = "script blocked";
});
</script>
</body></html>"""

_LINK_PAGE = """<!DOCTYPE html>
<html><head><title>linked page</title></head><body>
<h1>app page</h1>
<a id="to-service" href="__SERVICE__service">open the service</a>
</body></html>"""


def _launch(*, ready_timeout_sec: int = 120) -> dict[str, Any]:
    return {"name": "web", "kind": "web",
            "commands": {str(current_system()): [sys.executable, "-c", _SERVER]},
            "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": ready_timeout_sec}


def _action(tool: str, args: dict[str, Any], *, kind: str = "browser") -> Action:
    return Action(action_id=f"test:{tool}", kind=kind, tool=tool, department="engineering", input=args,
                  verification=tool_verification(tool), cancellable=tool_cancellable(tool))


@contextmanager
def _event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    # 一个场景用的事件循环：MCP 客户端会话只在建立它的循环里可用
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


class _BrowserCase:
    """一个 run 的执行环境：工件库、试用会话表与真实浏览器会话表，全部动作跑在同一个事件循环里。"""

    def __init__(self, root: Path, loop: asyncio.AbstractEventLoop, *, run_id: str = "run-1") -> None:
        self.loop = loop
        self.artifacts = ArtifactStore(root / "artifacts")
        run_root = root / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        self.environment = LocalEnvironment.open(
            run_root, run_id=run_id, artifacts=self.artifacts,
            trials=TrialSessionTable(probe=lambda: []),
            browsers=BrowserSessions(self.artifacts))

    def perform(self, tool: str, args: dict[str, Any], *, kind: str = "browser"):
        return self.loop.run_until_complete(self.environment.perform(_action(tool, args, kind=kind)))

    def start(self, launch: dict[str, Any] | None = None) -> dict[str, Any]:
        receipt = self.perform("trial_start", {"launch": launch or _launch()}, kind="trial")
        assert receipt.ok is True and receipt.status == "completed", receipt.error
        return receipt.output

    def stop(self) -> None:
        self.perform("trial_stop", {}, kind="trial")

    def close(self) -> None:
        self.loop.run_until_complete(self.environment.browsers.close_all("test cleanup"))


def _screenshot_of(artifacts: ArtifactStore, image: dict[str, Any]) -> bytes:
    # 回执里的截图引用按内容摘要取回字节：摘要与保存下来的字节一致才算「摘要与回执一致」
    raw = artifacts.get(image["content_hash"])
    assert hash_bytes(raw) == image["content_hash"], "回执里的摘要与保存的字节不一致"
    assert raw.startswith(b"\x89PNG\r\n\x1a\n"), "截图不是 PNG"
    assert image["kind"] == "screenshot" and image["media_type"] == "image/png"
    return raw


def _wait_until_ready(url: str, timeout_sec: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                response.read(64)
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    raise AssertionError(f"the tiny web app did not become ready at {url}")


class _TinyApp:
    # 一个真实的小网页服务：端口由系统分配，地址交给浏览器会话当就绪地址
    def __init__(self) -> None:
        self.process = subprocess.Popen([sys.executable, "-c", (
            "import functools, http.server, socket\n"
            f"handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=r'{FIXTURE}')\n"
            "probe = socket.socket(); probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]\n"
            "probe.close()\n"
            "print(port, flush=True)\n"
            "http.server.HTTPServer(('127.0.0.1', port), handler).serve_forever()\n")],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.port = int(self.process.stdout.readline().strip())
        self.url = f"http://127.0.0.1:{self.port}/"
        _wait_until_ready(self.url)

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - 服务自己会退出
            self.process.kill()


class _ServicePage:
    """Yudao 服务自己的地址与端口：收到什么请求就记一行，请求路径决定回报什么内容。"""

    def __init__(self, root: Path) -> None:
        self.log = root / "service-requests.log"
        self.log.write_text("", encoding="utf-8")
        script = root / "service_page_server.py"
        script.write_text(_SERVICE_PAGE_SERVER, encoding="utf-8")
        self.process = subprocess.Popen([sys.executable, str(script), str(self.log)],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.port = int(self.process.stdout.readline().strip())
        self.url = f"http://127.0.0.1:{self.port}/"
        # 等它真的在监听，再把日志清空：之后的每一行都是别人发来的请求
        _wait_until_ready(self.url)
        self.log.write_text("", encoding="utf-8")

    def requests(self) -> list[str]:
        return [line for line in self.log.read_text(encoding="utf-8").splitlines() if line]

    def body(self, path: str = "service") -> str:
        # 从浏览器外面取一次：证明这个地址与端口是通的，页面上被挡下来不是因为服务没有起来
        with urllib.request.urlopen(f"{self.url}{path}", timeout=10) as response:
            assert response.status == 200
            return response.read().decode("utf-8")

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - 服务自己会退出
            self.process.kill()


class _PageServer:
    """试用会话启动的小网页：整站是给定的那一页，端口由试用会话交来。"""

    def __init__(self, root: Path, html: str) -> None:
        page = root / "page.html"
        page.write_text(html, encoding="utf-8")
        script = root / "page_server.py"
        script.write_text(_PAGE_SERVER, encoding="utf-8")
        self.command = [sys.executable, str(script), str(page)]

    def launch(self) -> dict[str, Any]:
        return {"name": "web", "kind": "web",
                "commands": {str(current_system()): list(self.command)},
                "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": 120}


def test_a_real_page_navigates_types_clicks_and_verifies_with_screenshots(tmp_path):
    with _event_loop() as loop:
        case = _BrowserCase(tmp_path, loop)
        try:
            opened = case.start()
            session = opened["session"]
            browser = session["browser"]
            # 会话开始时已经打开就绪地址：回执带页面的可访问性结构与一张截图（docs/design/browser-and-computer-use.md「试用工具」）
            assert browser["status"] == "running" and browser["session_id"].startswith("browser_")
            assert browser["tree_digest"] == session["tree_digest"], "浏览器会话没有带试用副本的树摘要"
            assert "tiny web app" in opened["accessibility"], opened["accessibility"]
            assert "[ref=" in opened["accessibility"], "结果里没有带元素引用的可访问性结构"
            assert len(opened["images"]) == 1, opened["images"]
            _screenshot_of(case.artifacts, opened["images"][0])

            typed = case.perform("browser_type", {"target": "#name", "text": "Ada"})
            assert typed.ok is True, typed.error
            assert len(typed.output["images"]) == 1, "输入文字这一步没有截图"
            assert "Ada" in typed.output["accessibility"] and "[ref=" in typed.output["accessibility"]
            clicked = case.perform("browser_click", {"target": "#greet"})
            assert clicked.ok is True, clicked.error
            assert len(clicked.output["images"]) == 1, "点击这一步没有截图"
            assert "hello Ada" in clicked.output["accessibility"], clicked.output["accessibility"]
            verified = case.perform("browser_verify_text_visible", {"text": "hello Ada"})
            assert verified.ok is True, verified.error
            assert verified.output["images"] == [], "只读的工具不该另截图"
            assert "Done" in verified.output["accessibility"], verified.output["accessibility"]
            # 每一步的会话身份相同，截图各是一份（改变页面的每步都有）
            assert {step["session"]["session_id"]
                    for step in (typed.output, clicked.output, verified.output)} == {browser["session_id"]}
            shots = [opened["images"][0], typed.output["images"][0], clicked.output["images"][0]]
            for image in shots:
                _screenshot_of(case.artifacts, image)
            assert len({image["content_hash"] for image in shots}) == 3, "三步的截图是同一份"

            stopped = case.perform("trial_stop", {}, kind="trial")
            assert stopped.ok is True and stopped.output["browser"]["ended"] is True
            assert not Path(browser["output_dir"]).exists(), "会话结束以后 MCP 的输出目录还在"
            assert not Path(session["copy"]).exists(), "会话结束以后试用副本还在"
        finally:
            case.close()


def test_a_text_only_call_target_sees_the_structure_and_keeps_the_screenshot(tmp_path):
    with _event_loop() as loop:
        case = _BrowserCase(tmp_path, loop)
        try:
            opened = case.start()
            url = opened["session"]["ready_url"]
            receipt = case.perform("browser_navigate", {"url": url})
            assert receipt.ok is True, receipt.error
            assert len(receipt.output["images"]) == 1, receipt.output["images"]
            # 回执带可访问性结构与截图：截图存成工件，摘要与字节一致
            assert "tiny web app" in receipt.output["accessibility"]
            _screenshot_of(case.artifacts, receipt.output["images"][0])
            # 调用目标包含图像时，截图作为工件引用随结果进入历史
            with_image = tool_result_item("c1", True, receipt.output, None,
                                          input_modalities=("text", "image"))
            assert [image["content_hash"] for image in with_image["images"]] == \
                   [receipt.output["images"][0]["content_hash"]]
            # 只有文本时：进入部门历史的工具结果只有可访问性结构，没有图像
            text_only = tool_result_item("c1", True, receipt.output, None, input_modalities=("text",))
            assert not text_only.get("images"), "只有文本的调用目标收到了图像"
            sent = json.loads(text_only["output"])
            assert "tiny web app" in sent["output"]["accessibility"], sent
            assert "images" not in sent["output"], "只有文本的工具结果里还带着图像引用"
            # 装配成请求以后同样只有文字，截图仍然在工件库里
            call = {"type": "function_call", "call_id": "c1", "name": "browser_navigate",
                    "arguments": json_dumps({"url": url})}
            items = request_history([call, text_only], run_id="run-1", artifacts=case.artifacts,
                                    input_modalities=("text",))
            parts: list[dict[str, Any]] = []
            for item in items:
                output = item.get("output")
                if isinstance(output, list):
                    parts.extend(output)
                elif isinstance(output, str):
                    parts.append({"type": "input_text", "text": output})
            assert not [part for part in parts if part.get("type") == "image"], "请求里有图像"
            assert any("tiny web app" in str(part.get("text") or "") for part in parts), "请求里没有页面结构"
        finally:
            case.stop()
            case.close()


def test_local_file_paths_outside_the_trial_copy_are_refused(tmp_path):
    with _event_loop() as loop:
        case = _BrowserCase(tmp_path, loop)
        try:
            opened = case.start()
            copy_root = Path(opened["session"]["copy"])
            outside = tmp_path / "outside.txt"
            outside.write_text("not part of the trial copy\n", encoding="utf-8")

            upload = case.perform("browser_file_upload", {"paths": [str(outside)]})
            assert upload.refused is True and upload.status == "failed"
            assert "inside the trial copy only" in upload.error
            drop = case.perform("browser_drop", {"target": "#drop", "paths": ["../outside.txt"]})
            assert drop.refused is True and drop.status == "failed"
            assert "inside the trial copy only" in drop.error
            # 副本之内的相对路径不被拒绝（文件选择器没有打开时 MCP 自己报错，那不是来源拒绝）
            (copy_root / "upload.txt").write_text("inside\n", encoding="utf-8")
            inside = case.perform("browser_file_upload", {"paths": ["upload.txt"]})
            assert inside.refused is False, inside.error
        finally:
            case.stop()
            case.close()


def _local_targets() -> list[str]:
    # 指向本机的几种写法：回环地址、localhost、本机网卡地址与本机主机名（后者是本机的域名别名）
    targets = ["127.0.0.1", "localhost", socket.gethostname()]
    try:
        targets.append(socket.gethostbyname(socket.gethostname()))
    except OSError:  # pragma: no cover - 主机名解析不了的机器
        pass
    seen: list[str] = []
    for target in targets:
        if target and target not in seen:
            seen.append(target)
    return seen


def test_navigation_to_the_service_itself_is_refused_and_other_addresses_are_allowed(tmp_path):
    service_port = 8765
    with _event_loop() as loop:
        case = _BrowserCase(tmp_path, loop)
        try:
            opened = case.start()
            configure_service_address("0.0.0.0", service_port)
            for host in _local_targets():
                receipt = case.perform("browser_navigate", {"url": f"http://{host}:{service_port}/"})
                assert receipt.refused is True, f"导航到 {host}:{service_port} 没有被拒绝"
                assert "own address and port" in receipt.error, receipt.error
            # 会话中启动的软件自己的端口可以访问
            own_port = opened["session"]["port"]
            app_page = case.perform("browser_navigate", {"url": f"http://127.0.0.1:{own_port}/"})
            assert app_page.refused is False and app_page.ok is True, app_page.error
            assert "tiny web app" in app_page.output["accessibility"]
            # 真实外网地址可以访问（docs/design/browser-and-computer-use.md「安全」：其余来源不设限制）
            external = case.perform("browser_navigate", {"url": _EXTERNAL_URL})
            assert external.refused is False and external.ok is True, external.error
            assert "Example Domain" in external.output["accessibility"], external.output["accessibility"]
            # 新建标签页带的 url 也是工具直接发起的导航：同样按服务地址检查（工单 #1184 的审查第 1 条）
            for host in _local_targets():
                tab = case.perform("browser_tabs", {"action": "new", "url": f"http://{host}:{service_port}/"})
                assert tab.refused is True, f"新建标签页导航到 {host}:{service_port} 没有被拒绝"
                assert "own address and port" in tab.error, tab.error
            # 不带 url 的新建标签页是空白页，不是导航，不按来源拒绝
            blank = case.perform("browser_tabs", {"action": "new"})
            assert blank.refused is False, blank.error
        finally:
            clear_service_address()
            case.stop()
            case.close()


def test_a_link_on_the_page_cannot_reach_the_service(tmp_path):
    # 来源限制的第二条路：工具直接导航被动作层拒绝（上一条），页面上的链接由浏览器自己挡下
    service = _ServicePage(tmp_path)
    page = _PageServer(tmp_path, _LINK_PAGE.replace("__SERVICE__", service.url))
    try:
        # 控制组：这个地址与端口是通的（从浏览器外面取一次）
        assert "Service page" in service.body()
        before = service.requests()
        configure_service_address("127.0.0.1", service.port)
        with _event_loop() as loop:
            case = _BrowserCase(tmp_path, loop)
            try:
                opened = case.start(page.launch())
                assert "open the service" in opened["accessibility"], opened["accessibility"]
                clicked = case.perform("browser_click", {"target": "#to-service"})
                assert clicked.ok is True, clicked.error
                structure = clicked.output["accessibility"]
                # 页面停在 Chromium 的拦截页上：错误码不是页面文字，不受浏览器语言影响
                assert "ERR_BLOCKED_BY_CLIENT" in structure, structure
                assert "Service page" not in structure, "链接把浏览器带到了服务页面"
                # 服务那一侧一次请求都没有收到（控制组那一次之外）
                assert service.requests() == before, f"浏览器向服务发出了请求：{service.requests()}"
            finally:
                case.stop()
                case.close()
    finally:
        clear_service_address()
        service.close()


def test_a_request_from_page_script_cannot_reach_the_service(tmp_path):
    # 来源限制的第三条路：页面脚本发出的请求同样由浏览器挡下，服务那一侧收不到
    service = _ServicePage(tmp_path)
    page = _PageServer(tmp_path, _SCRIPT_PAGE.replace("__SERVICE__", service.url))
    try:
        assert "service data" in service.body("data")
        before = service.requests()
        configure_service_address("127.0.0.1", service.port)
        with _event_loop() as loop:
            case = _BrowserCase(tmp_path, loop)
            try:
                case.start(page.launch())
                # 页面自己写下结论：请求发得出去是 got，被浏览器挡下才是 blocked。等 pending 消失这个信号
                # （不用时长去赌），再取一次页面结构看它写了什么
                settled = case.perform("browser_wait_for", {"textGone": "script pending"})
                assert settled.ok is True and not settled.output.get("tool_error"), settled.error
                structure = case.perform("browser_snapshot", {}).output["accessibility"]
                assert "script blocked" in structure, structure
                assert "script got" not in structure, "页面脚本的请求发出去了"
                assert service.requests() == before, f"页面脚本的请求到了服务：{service.requests()}"
            finally:
                case.stop()
                case.close()
    finally:
        clear_service_address()
        service.close()


def _append_lost_click(system: LoopSystem, run_id: str) -> None:
    # 一次 browser_click 的 tool_started，没有对应的结果：与「进程在动作进行期间退出」留下的状态一致
    activated = [event for event in system.store.list_events(run_id)
                 if event.type == EventType.DEPARTMENT_ACTIVATED]
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.TOOL_STARTED, actor="department:engineering", department="engineering",
        state_before="running", state_after="running",
        payload={"id": "lost-click", "name": "browser_click", "args": {"target": "#greet"},
                 "step_id": 1, "activation_id": activated[-1].payload["activation_id"], "attempt": 1,
                 "purpose": "work"}))


def test_restarting_yudao_marks_the_browser_session_interrupted_without_a_question(tmp_path):
    data_dir = tmp_path / "loop"
    system = LoopSystem.for_testing(data_dir, FakeAdapter({"product": [product_spec()],
                                                           "engineering": []}))
    run_id = system.create_run("build a page")
    app = _TinyApp()
    try:
        with _event_loop() as loop:
            loop.run_until_complete(system.orchestrator.activate_once(run_id))
            copy_root = tmp_path / "copy"
            copy_root.mkdir(parents=True, exist_ok=True)
            loop.run_until_complete(system.orchestrator._workspaces.browsers.start(
                run_id=run_id, department="engineering", copy_root=copy_root,
                tree_digest="sha256:" + "0" * 64, ready_url=app.url))
            _append_lost_click(system, run_id)
            # 重新启动 Yudao：进程里的会话表不再有那个会话（持有会话的进程重新启动）
            loop.run_until_complete(system.orchestrator._workspaces.browsers.close_all("the process restarted"))
    finally:
        app.close()
        system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    try:
        restarted.orchestrator.resume_incomplete_run(run_id)
        events = restarted.store.list_events(run_id)
        assert not [event for event in events if event.type == EventType.DECISION_REQUESTED
                    and (event.payload or {}).get("kind") == "unknown_action"], "结果未知发出了决定请求"
        verified = next(event for event in events if event.type == EventType.ACTION_VERIFIED
                        and (event.payload or {}).get("id") == "lost-click")
        assert verified.payload["resolution"] == "handed_back"
        assert verified.payload["session"]["status"] == "interrupted", "会话没有记为中断"
        assert "会话已中断" in verified.payload["error"], verified.payload["error"]
        assert "会话已中断" in verified.payload["input_item"]["output"]
        actions = Application(restarted).query("run.actions", RunActions(run_id=run_id)).data.actions
        assert [action.status for action in actions if action.action_id == "lost-click"] == ["unknown"]
    finally:
        restarted.close()


def test_ending_the_mcp_process_during_an_action_fails_the_receipt_and_interrupts_the_session(tmp_path):
    receipt: dict[str, Any] = {}
    with _event_loop() as loop:
        case = _BrowserCase(tmp_path, loop)

        def act() -> None:
            # 等待时间取最长的一档（30 秒）：动作确实在进行中，这时结束 MCP 进程
            receipt["result"] = case.perform("browser_wait_for", {"time": 30})

        try:
            opened = case.start()
            pid = opened["session"]["browser"]["server_pid"]
            assert isinstance(pid, int), "会话记录里没有 Playwright MCP 的进程号"
            worker = threading.Thread(target=act, daemon=True)
            worker.start()
            time.sleep(1.5)
            psutil.Process(pid).kill()
            worker.join(120)
            assert "result" in receipt, "动作没有返回"
            failed = receipt["result"]
            assert failed.status == "failed", failed
            assert "Playwright MCP server" in (failed.error or ""), failed.error
            record = case.environment.browser_session("engineering")
            assert record is not None and record["status"] == "interrupted", record
            # 之后的动作按会话已中断交回，不再落到 MCP 上
            after = case.perform("browser_snapshot", {})
            assert after.status == "failed" and "interrupted" in (after.error or ""), after.error
        finally:
            case.close()

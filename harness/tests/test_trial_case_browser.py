# 试用用例与真实的浏览器（浏览器与 computer use 设计说明第 8.2、8.3 节；工单 #1180）。
#
# 这个文件查两件事，都用真实的 Playwright MCP、真实的 Chromium 与一个真实的小网页：
# 1. 质检在一个真实会话里打开试用用例、在浏览器里操作、以 passed 结束：用例的步骤是这几步真实动作（按动作身份），
#    每步带截图工件引用，所在会话的试用副本树摘要等于交付快照，放行的逐条结论引用它时通过核对；
# 2. 用例打开期间会话结束（trial_stop）：用例结束为 interrupted，引用它作为证据的结论被拒绝。
#
# 层：集成层（真实的 Playwright MCP、真实的 Chromium、真实的小网页服务与子进程）。
# 守 R3（试用用例的步骤来自真实动作、结论与证据绑定当前交付；中断的用例不能作为证据）。
#
# MCP 客户端会话只在建立它的事件循环里可用：一个场景里的全部动作跑在同一个循环里，与 #1184 的用例同一个做法。

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from contextlib import contextmanager

from harness.actions import Action
from harness.artifacts import ArtifactStore
from harness.browser import BrowserSessions
from harness.engine import trial_case_begin, trial_case_end
from harness.environment import LocalEnvironment
from harness.event_store import EventStore, run_stream
from harness.models import EventType
from harness.project_projection import handler_for
from harness.projection import replay_events
from harness.tightening import _trial_case_errors
from harness.tools import tool_cancellable, tool_verification
from harness.trial_sessions import TrialSessionTable, current_system
from harness.write_path import NewEvent, WritePath

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tiny_web_app"
# 试用会话只在本机与控制主机两类位置上：系统不是 windows 或 linux 的机器没有启动命令的约定
pytestmark = pytest.mark.skipif(current_system() is None,
                                reason="trial launch commands are defined for windows and linux only")
_SERVER = (
    "import functools, http.server, os\n"
    f"handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=r'{FIXTURE}')\n"
    "http.server.HTTPServer(('127.0.0.1', int(os.environ['PORT'])), handler).serve_forever()\n"
)
RUN_ID = "run-trial-cases"
DEPARTMENT = "quality"
ACTIVATION = "act_quality_1"


def _launch() -> dict[str, Any]:
    return {"name": "web", "kind": "web",
            "commands": {str(current_system()): [sys.executable, "-c", _SERVER]},
            "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": 120}


def _action(tool: str, args: dict[str, Any], *, kind: str = "browser") -> Action:
    return Action(action_id=f"test:{tool}", kind=kind, tool=tool, department=DEPARTMENT, input=args,
                  verification=tool_verification(tool), cancellable=tool_cancellable(tool))


@contextmanager
def _event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


class _Case:
    """一个 run 的事件流与执行环境：真实试用会话、真实浏览器会话，全部动作跑在同一个事件循环里。"""

    def __init__(self, root: Path, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.store = EventStore(root / "events.db")
        self.writes = WritePath(self.store, handler_for)
        self.artifacts = ArtifactStore(root / "artifacts")
        run_root = root / "runs" / RUN_ID
        run_root.mkdir(parents=True, exist_ok=True)
        self.environment = LocalEnvironment.open(
            run_root, run_id=RUN_ID, artifacts=self.artifacts,
            trials=TrialSessionTable(probe=lambda: []),
            browsers=BrowserSessions(self.artifacts))

    # ---- 事件 ----

    def append(self, *entries: NewEvent) -> None:
        self.writes.transact(run_stream(RUN_ID), lambda transaction: transaction.append(*entries))

    def event(self, type: str, payload: dict[str, Any]) -> NewEvent:
        return NewEvent(type, state_before="running", state_after="running",
                        actor=f"department:{DEPARTMENT}", department=DEPARTMENT, session_id=SESSION,
                        payload=payload)

    def projection(self):
        return replay_events(self.store.list_events(RUN_ID))

    # ---- 会话与动作 ----

    def session(self) -> dict[str, Any] | None:
        # 进行中的试用会话（引擎里 trial_case_begin 读的是同一条记录）
        trial = self.environment.trial_session(DEPARTMENT)
        if trial is None:
            return None
        return {"session_id": trial["session_id"], "tree_digest": trial["tree_digest"]}

    def perform(self, identity: str, tool: str, args: dict[str, Any], *, step_id: int) -> Any:
        # 一次真实动作：与步骤驱动一样，先写 tool_started，执行以后写 tool_called（带截图工件引用）
        self.append(self.event(EventType.TOOL_STARTED, {
            "id": identity, "name": tool, "step_id": step_id, "activation_id": ACTIVATION}))
        receipt = self.loop.run_until_complete(self.environment.perform(_action(tool, args)))
        assert receipt.ok is True, receipt.error
        self.append(self.event(EventType.TOOL_CALLED, {
            "id": identity, "name": tool, "step_id": step_id, "activation_id": ACTIVATION,
            "ok": True, "error": None, "images": list(receipt.output.get("images") or ())}))
        return receipt

    def start(self, launch: dict[str, Any]) -> dict[str, Any]:
        receipt = self.loop.run_until_complete(self.environment.perform(
            _action("trial_start", {"launch": launch}, kind="trial")))
        assert receipt.ok is True, receipt.error
        return receipt.output

    def stop(self) -> Any:
        return self.loop.run_until_complete(self.environment.perform(_action("trial_stop", {}, kind="trial")))

    def close(self) -> None:
        self.loop.run_until_complete(self.environment.browsers.close_all("test cleanup"))
        self.store.close()


SESSION = "ses_quality_1"


def _criteria(case_id: str, result: str = "passed") -> list[dict[str, Any]]:
    return [{"criterion": "AC1", "method": "trial", "result": result, "checks": [],
             "trial_cases": [case_id]}]


def test_a_real_browser_case_collects_its_steps_and_ends_as_passed(tmp_path):
    # 质检在真实会话里打开用例、在浏览器里操作、以 passed 结束：步骤是真实动作，截图是真实工件，
    # 放行引用它时通过核对（设计说明第 8.2、8.3 节）。守 R3
    with _event_loop() as loop:
        case = _Case(tmp_path, loop)
        try:
            opened = case.start(_launch())
            trial = case.session()
            assert trial is not None and opened["session"]["tree_digest"] == trial["tree_digest"]

            projection = SimpleNamespace(
                product_spec=SimpleNamespace(content_hash="sha256:spec", acceptance_criteria=["一", "二"]),
                trial_cases=[], last_activations={DEPARTMENT: ACTIVATION})
            begun = trial_case_begin({"criteria": ["AC1"], "title": "待办清单",
                                      "steps": ["输入名字", "点击问候", "断言出现 hello"],
                                      "expected": "页面上出现 hello Ada"},
                                     projection=projection, department=DEPARTMENT, session_id=SESSION,
                                     activation_id=ACTIVATION, session=trial)
            assert begun.ok is True, begun.error
            case.append(case.event(begun.event_type, begun.payload))

            case.perform("call-type", "browser_type", {"target": "#name", "text": "Ada"}, step_id=2)
            case.perform("call-click", "browser_click", {"target": "#greet"}, step_id=3)
            case.perform("call-verify", "browser_verify_text_visible", {"text": "hello Ada"}, step_id=4)

            folded = case.projection().trial_cases[0]
            assert [step.identity for step in folded.steps] == ["call-type", "call-click", "call-verify"]
            assert [step.tool for step in folded.steps] == [
                "browser_type", "browser_click", "browser_verify_text_visible"]
            assert all(step.status == "completed" for step in folded.steps)
            # 改变页面的每一步各带一张真实截图，摘要在工件库里取得到
            assert folded.steps[0].screenshots and folded.steps[1].screenshots
            for step in folded.steps[:2]:
                image = step.screenshots[0]
                assert image["media_type"] == "image/png"
                assert case.artifacts.get(image["content_hash"]).startswith(b"\x89PNG")

            ended = trial_case_end({"result": "passed", "observed": "页面上出现 hello Ada",
                                    "evidence_steps": ["call-verify"]},
                                   projection=case.projection(), department=DEPARTMENT, session_id=SESSION,
                                   session=trial)
            assert ended.ok is True, ended.error
            case.append(case.event(ended.event_type, ended.payload))

            final = case.projection()
            concluded = final.trial_cases[0]
            assert concluded.status == "concluded" and concluded.result == "passed"
            assert concluded.tree_digest == trial["tree_digest"]
            # 放行引用它：树摘要等于当前交付的 code_snapshot_hash 时通过
            assert _trial_case_errors(_criteria(concluded.case_id), final, department=DEPARTMENT,
                                      spec_hash="sha256:spec", snapshot_hash=trial["tree_digest"]) == []
            # 交付快照不同（用例在另一份试用副本里跑过）时被拒绝
            rejected = _trial_case_errors(_criteria(concluded.case_id), final, department=DEPARTMENT,
                                          spec_hash="sha256:spec", snapshot_hash="sha256:other")
            assert rejected and "does not equal the current delivery snapshot" in rejected[0].message
        finally:
            case.close()


def test_a_session_that_ends_under_an_open_case_concludes_it_as_interrupted(tmp_path):
    # 用例打开期间会话结束：用例结束为 interrupted，引用它作为证据的结论被拒绝（设计说明第 8.2 节）。守 R3
    with _event_loop() as loop:
        case = _Case(tmp_path, loop)
        try:
            case.start(_launch())
            trial = case.session()
            assert trial is not None
            projection = SimpleNamespace(
                product_spec=SimpleNamespace(content_hash="sha256:spec", acceptance_criteria=["一"]),
                trial_cases=[], last_activations={DEPARTMENT: ACTIVATION})
            begun = trial_case_begin({"criteria": ["AC1"], "title": "待办清单", "steps": ["输入名字"],
                                      "expected": "看到 hello"}, projection=projection,
                                     department=DEPARTMENT, session_id=SESSION,
                                     activation_id=ACTIVATION, session=trial)
            assert begun.ok is True, begun.error
            case.append(case.event(begun.event_type, begun.payload))
            case.perform("call-type", "browser_type", {"target": "#name", "text": "Ada"}, step_id=2)

            stopped = case.stop()
            assert stopped.ok is True, stopped.error
            # 会话结束的事件由执行环境写进 run 流（工单 #1183 的写入方在这里没有接上，按同一个形状补一条）
            case.append(case.event(EventType.TRIAL_SESSION_ENDED, {
                "session_id": trial["session_id"], "department": DEPARTMENT, "kind": "web",
                "reason": "stopped"}))

            folded = case.projection()
            concluded = folded.trial_cases[0]
            assert concluded.status == "concluded" and concluded.result == "interrupted"
            rejected = _trial_case_errors(_criteria(concluded.case_id), folded, department=DEPARTMENT,
                                          spec_hash="sha256:spec", snapshot_hash=trial["tree_digest"])
            assert rejected and "interrupted" in rejected[0].message
        finally:
            case.close()

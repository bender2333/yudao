# 试用记录与截图的查询（工单 #152；浏览器与 computer use 设计说明「查询」；应用层与接口层设计说明
# 「查询清单」；总图第四节「接口」缝）。
#
# 这个文件查八件事：
# 1. `run.trials` 按部门列出试用会话：种类、启动方式、试用副本的树摘要，质检的会话标明树摘要是否等于
#    交付快照，开始与结束、结束方式（设计「查询」）；
# 2. `run.trials` 给出质检的试用用例：引用的验收条件与原文、计划的操作与预期结果、步骤（工具、输入、
#    结果状态、截图的工件引用、可访问性结构的摘录、收到这个结果的请求是否包含图像）、结论与观察到的结果、
#    作为证据的步骤；
# 3. 调用前后事件日志末尾位置与保存的投影不变，能力清单列出两个新查询与改变它们结果的事件种类
#    （验收第 3 条）；
# 4. `evidence.screenshot` 按工件引用返回截图内容摘要与所属事件的位置；
# 5. 工件内容被改动、引用属于别的 run 或不是截图时返回找不到（验收第 2 条）；
# 6. `run.actions` 的浏览器动作回执带截图引用与浏览器会话身份；
# 7. `work_item.materials` 的交付一项带启动方式，质检一项带逐条结论、试用用例的截图引用与无法核验的条目；
# 8. `tools.registry` 的内置工具一节给出 Playwright MCP 的版本、浏览器工具与恢复契约、每个工具是否需要图像输入。
#
# 层：模块层（真实的事件库、工件库与项目投影，不出激活、不用网络、不启动子进程）。
# 守 R2（查询的交换字段与能力清单登记）与 R3（试用记录只从事实读，截图按摘要核对以后才交给界面）。

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application, ReadOnlyCore
from harness.app.evidence_queries import ScreenshotEvidence
from harness.app.project_queries import NotFound, RunActions, WorkItemMaterials
from harness.app.trial_queries import RunTrials
from harness.artifacts import ArtifactStore
from harness.browser import MCP_PACKAGE, MCP_VERSION
from harness.definitions import DEFINITIONS
from harness.event_store import EventStore, run_stream
from harness.models import EventType, json_dumps
from harness.projection import run_handler
from harness.runtime import LoopSystem
from harness.write_path import NewEvent, WritePath

RUN = "run_trials"
SPEC_HASH = "sha256:" + "5" * 64
DELIVERY_DIGEST = "sha256:" + "d" * 64
TREE_DIGEST = "sha256:" + "e" * 64
TRIAL = "trial_quality_1"
SESSION = "ses_quality_1"
ACTIVATION = "act_quality_1"


# ---------------------------------------------------------------------------
# 事件与工件：run 流的事件经写入口写进真实的事件库，工件写进工件库


def _event(kind: str, payload: dict, *, department: str = "quality",
           session_id: str | None = None) -> NewEvent:
    return NewEvent(kind, state_before="running", state_after="running",
                    actor=f"department:{department}", department=department,
                    session_id=session_id, payload=payload)


def _write(data_dir: Path, *events: NewEvent, run_id: str = RUN) -> None:
    store = EventStore(data_dir / "events.sqlite")
    try:
        writes = WritePath(store, lambda _stream: run_handler())
        writes.transact(run_stream(run_id), lambda transaction: transaction.append(*events))
    finally:
        store.close()


def _application(data_dir: Path) -> Application:
    return Application(ReadOnlyCore(data_dir))


def _ref(ref: object) -> dict:
    return {"kind": ref.kind, "content_hash": ref.content_hash, "path": ref.path,
            "media_type": ref.media_type}


def _output(data_dir: Path, accessibility: str, *, session_id: str = "brs_1",
            tree_digest: str = DELIVERY_DIGEST) -> object:
    # 浏览器动作的输出：可访问性结构与浏览器会话身份（浏览器与 computer use 设计说明「保存与绑定」）
    body = {"accessibility": accessibility, "images": [],
            "session": {"session_id": session_id, "tree_digest": tree_digest, "status": "running"}}
    return ArtifactStore(data_dir / "artifacts").put(RUN, "tool_output", json_dumps(body),
                                                     media_type="application/json")


def _screenshot(data_dir: Path, content: bytes = b"\x89PNG\r\n\x1a\nfirst") -> object:
    return ArtifactStore(data_dir / "artifacts").put(RUN, "screenshot", content,
                                                     media_type="image/png")


def _spec(acceptance: list[str], *, content_hash: str = SPEC_HASH) -> NewEvent:
    return _event(EventType.SPEC_ACCEPTED, {
        "id": "spec_1", "revision": 1, "content_hash": content_hash, "goal": "做一个待办清单",
        "requirements": [], "boundaries": [], "constraints": [], "acceptance_criteria": list(acceptance),
        "fatal_conditions": [], "non_goals": [], "decision_changes": [], "change_record": None,
        "input_version": 1, "requirement_mapping": []}, department="product")


def _delivery(tree_digest: str = DELIVERY_DIGEST, *, launch: list[dict] | None = None) -> NewEvent:
    return _event(EventType.DELIVERY_ACCEPTED, {
        "id": "del_1", "revision": 1, "content_hash": "sha256:delivery",
        "product_spec_hash": SPEC_HASH, "effective_contract_hash": "sha256:contract",
        "summary": "交付", "files": ["app.py"], "check_names": [], "checks": [], "known_risks": [],
        "code_tree_digest": tree_digest,
        "tree_ref": {"kind": "tree_snapshot", "content_hash": TREE_DIGEST, "path": "tree", "media_type": None},
        "launch": list(launch or []), "status": "active"}, department="engineering")


def _session_started(session_id: str, department: str, *, tree_digest: str,
                     launch_name: str = "web-serve",
                     source: str = "delivery_snapshot") -> NewEvent:
    return _event(EventType.TRIAL_SESSION_STARTED, {
        "session_id": session_id, "department": department, "kind": "web",
        "launch_name": launch_name, "system": "windows", "port": 41000,
        "ready_url": "http://127.0.0.1:41000/", "tree_digest": tree_digest, "source": source,
        "pid": 100, "create_time": 1.0}, department=department)


def _session_ended(session_id: str, department: str, reason: str) -> NewEvent:
    return _event(EventType.TRIAL_SESSION_ENDED, {
        "session_id": session_id, "department": department, "kind": "web", "reason": reason,
        "ended": True, "exit_code": 0}, department=department)


def _case_opened(criteria: tuple[str, ...] = ("AC1",), *, case_id: str = "case_1") -> NewEvent:
    return _event(EventType.TRIAL_CASE_OPENED, {
        "case_id": case_id, "session_id": SESSION, "trial_session_id": TRIAL,
        "department": "quality", "activation_id": ACTIVATION, "product_spec_hash": SPEC_HASH,
        "tree_digest": DELIVERY_DIGEST, "criteria": list(criteria), "title": "添加一条待办",
        "plan": ["打开页面", "点添加"], "expected": "列表里出现这条待办"}, session_id=SESSION)


def _tool_started(identity: str, tool: str, *, step_id: int) -> NewEvent:
    return _event(EventType.TOOL_STARTED, {
        "id": identity, "name": tool, "step_id": step_id, "activation_id": ACTIVATION},
        session_id=SESSION)


def _tool_called(identity: str, tool: str, *, step_id: int, args: dict | None = None,
                 images: tuple[dict, ...] = (), output_ref: dict | None = None,
                 ok: bool = True) -> NewEvent:
    payload = {"id": identity, "name": tool, "step_id": step_id, "activation_id": ACTIVATION,
               "ok": ok, "error": None if ok else "failed", "args": dict(args or {})}
    if images:
        payload["images"] = list(images)
    if output_ref is not None:
        payload["output_ref"] = output_ref
    return _event(EventType.TOOL_CALLED, payload, session_id=SESSION)


def _model_requested(step_id: int, modalities: list[str]) -> NewEvent:
    return _event(EventType.MODEL_REQUESTED, {
        "activation_id": ACTIVATION, "step_id": step_id, "attempt": 1, "root_step_id": step_id,
        "input_modalities": list(modalities)}, session_id=SESSION)


def _case_concluded(result: str, evidence: tuple[str, ...] = ()) -> NewEvent:
    return _event(EventType.TRIAL_CASE_CONCLUDED, {
        "case_id": "case_1", "session_id": SESSION, "department": "quality", "result": result,
        "observed": "列表里出现了这条待办", "evidence_steps": list(evidence), "reason": ""},
        session_id=SESSION)


def _qa_submitted(criteria: list[dict]) -> NewEvent:
    return _event(EventType.QA_SUBMITTED, {
        "id": "review_1", "revision": 1, "content_hash": "sha256:review",
        "product_spec_hash": SPEC_HASH, "effective_contract_hash": "sha256:contract",
        "delivery_spec_hash": "sha256:delivery", "code_snapshot_hash": DELIVERY_DIGEST,
        "verdict": "cannot_verify", "rationale": "一条无法核验", "checks": [], "defects": [],
        "criteria": list(criteria), "coverage": {}, "open_criteria": ["AC2"], "evidence_refs": [],
        "judgement_event": ""}, department="quality")


# ---------------------------------------------------------------------------
# 1. 试用会话按部门列出，质检的会话标明是否等于交付快照


def test_run_trials_lists_sessions_by_department_and_marks_the_delivery_snapshot(tmp_path):
    # docs/design/browser-and-computer-use.md「查询」：种类、启动方式、试用副本的树摘要，质检的会话标明是否等于交付快照，开始与结束、
    # 结束方式；没有结束记录的会话按进行中给出。守 R1（会话只由事件得出）
    data_dir = tmp_path / "data"
    _write(data_dir,
           _delivery(),
           _session_started("trial_q1", "quality", tree_digest=DELIVERY_DIGEST),
           _session_ended("trial_q1", "quality", "stopped"),
           _session_started("trial_q2", "quality", tree_digest="sha256:other"),
           _session_started("trial_e1", "engineering", tree_digest="sha256:workspace",
                            source="workspace_seal"),
           _session_ended("trial_e1", "engineering", "run_ended"))
    application = _application(data_dir)
    try:
        snapshot = application.query("run.trials", RunTrials(run_id=RUN))
    finally:
        application.close()

    # 按部门列出，部门的顺序取自定义（产品、工程、质检）
    assert [group.department for group in snapshot.data.departments] == ["engineering", "quality"]
    quality = next(group for group in snapshot.data.departments if group.department == "quality")
    assert [item.session_id for item in quality.sessions] == ["trial_q1", "trial_q2"]

    first = quality.sessions[0]
    assert (first.kind, first.launch_name) == ("web", "web-serve")
    assert first.tree_digest == DELIVERY_DIGEST
    assert first.delivery_snapshot_hash == DELIVERY_DIGEST
    assert first.matches_delivery_snapshot is True
    assert first.started_at and first.ended_at
    assert first.end_reason == "stopped" and first.status == "ended"

    second = quality.sessions[1]
    assert second.matches_delivery_snapshot is False
    assert second.status == "running" and second.ended_at is None and second.end_reason is None

    # 不是核验角色的会话只给树摘要，不写成与交付快照的比较（工程在自己的工作区副本上试用）
    engineering = next(group for group in snapshot.data.departments if group.department == "engineering")
    only = engineering.sessions[0]
    assert only.tree_digest == "sha256:workspace"
    assert only.delivery_snapshot_hash is None and only.matches_delivery_snapshot is None


# ---------------------------------------------------------------------------
# 2. 试用用例：引用的验收条件与原文、计划、步骤、结论


def test_run_trials_gives_the_case_with_criteria_text_plan_and_steps(tmp_path):
    # docs/design/browser-and-computer-use.md「查询」的用例字段；步骤里的输入取自动作参数，可访问性结构取自结果工件，收到结果的请求
    # 是否包含图像取自下一次模型请求的调用目标。守 R2（交换字段）与 R3（证据步骤与截图引用）
    data_dir = tmp_path / "data"
    screenshot = _screenshot(data_dir)
    output = _output(data_dir, "button[ref=b1] 添加待办")
    _write(data_dir,
           _spec(["列表显示一条待办", "点击添加以后列表里有这条待办"]),
           _case_opened(criteria=("AC1", "AC2")),
           _tool_started("call-1", "browser_click", step_id=2),
           _tool_called("call-1", "browser_click", step_id=2, args={"ref": "b1"},
                        images=(_ref(screenshot),), output_ref=_ref(output)),
           _model_requested(3, ["text", "image"]),
           _tool_started("call-2", "browser_verify_text_visible", step_id=3),
           _tool_called("call-2", "browser_verify_text_visible", step_id=3, args={"text": "待办"}),
           _model_requested(4, ["text"]),
           _case_concluded("passed", evidence=("call-1", "call-2")))
    application = _application(data_dir)
    try:
        snapshot = application.query("run.trials", RunTrials(run_id=RUN))
    finally:
        application.close()

    quality = next(group for group in snapshot.data.departments if group.department == "quality")
    [case] = quality.cases
    assert [(item.criterion, item.text) for item in case.criteria] == [
        ("AC1", "列表显示一条待办"), ("AC2", "点击添加以后列表里有这条待办")]
    assert case.title == "添加一条待办"
    assert case.plan == ["打开页面", "点添加"]
    assert case.expected == "列表里出现这条待办"
    assert (case.status, case.result) == ("concluded", "passed")
    assert case.observed == "列表里出现了这条待办"
    assert case.evidence_steps == ["call-1", "call-2"]

    first, second = case.steps
    assert (first.tool, first.input, first.status, first.ok) == (
        "browser_click", {"ref": "b1"}, "completed", True)
    assert first.screenshots == [_ref(screenshot)]
    assert first.accessibility == "button[ref=b1] 添加待办"
    assert first.request_had_images is True
    assert first.evidence is True

    assert second.tool == "browser_verify_text_visible"
    assert second.input == {"text": "待办"}
    assert second.screenshots == []
    assert second.accessibility is None
    assert second.request_had_images is False
    assert second.evidence is True


# ---------------------------------------------------------------------------
# 3. 只读与能力清单


def test_reading_the_trial_records_changes_nothing_and_the_capability_lists_the_events(tmp_path):
    # 验收第 3 条：调用前后事件日志末尾位置与保存的投影不变；能力清单列出两个新查询与改变它们结果的事件种类
    data_dir = tmp_path / "data"
    _write(data_dir, _spec(["一条"]), _case_opened(), _tool_started("call-1", "browser_click", step_id=2),
           _tool_called("call-1", "browser_click", step_id=2), _case_concluded("passed", evidence=("call-1",)))
    application = _application(data_dir)
    try:
        store = application.system.store
        end = store.end_position()
        saved = store.projection(run_stream(RUN))

        application.query("run.trials", RunTrials(run_id=RUN))
        capabilities = application.capabilities("", access="local")

        assert store.end_position() == end
        assert store.projection(run_stream(RUN)) == saved
    finally:
        application.close()

    by_name = {item.name: item for item in capabilities.queries}
    assert set(by_name["run.trials"].changed_by) == {
        EventType.TRIAL_SESSION_STARTED, EventType.TRIAL_SESSION_ENDED,
        EventType.TRIAL_CASE_OPENED, EventType.TRIAL_CASE_CONCLUDED,
        EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.ACTION_VERIFIED,
        EventType.MODEL_REQUESTED, EventType.SPEC_ACCEPTED, EventType.DELIVERY_ACCEPTED}
    assert by_name["evidence.screenshot"].changed_by == [EventType.TOOL_CALLED]


# ---------------------------------------------------------------------------
# 4. evidence.screenshot：按引用返回截图，位置是所属事件


def test_evidence_screenshot_returns_the_content_and_the_event_position(tmp_path):
    # 验收第 2 条：内容摘要与工件引用一致，返回的字节就是保存的那一份；位置是所属事件的位置
    data_dir = tmp_path / "data"
    content = b"\x89PNG\r\n\x1a\nshot"
    screenshot = _screenshot(data_dir, content)
    _write(data_dir, _tool_called("call-1", "browser_click", step_id=2, images=(_ref(screenshot),)))
    application = _application(data_dir)
    try:
        [event] = application.system.store.list_events(RUN)
        snapshot = application.query("evidence.screenshot", ScreenshotEvidence(
            event_id=event.event_id, kind=screenshot.kind, content_hash=screenshot.content_hash,
            path=screenshot.path, media_type=screenshot.media_type))
    finally:
        application.close()

    assert snapshot.position == event.position
    assert snapshot.data.content_hash == screenshot.content_hash
    assert snapshot.data.media_type == "image/png"
    assert base64.b64decode(snapshot.data.base64) == content


def test_evidence_screenshot_rejects_changed_content_other_runs_and_other_kinds(tmp_path):
    # 验收第 2 条：工件内容被改动时返回错误；引用属于别的 run 或不是截图时也返回找不到
    data_dir = tmp_path / "data"
    screenshot = _screenshot(data_dir)
    other = ArtifactStore(data_dir / "artifacts").put("run_other", "screenshot", b"other",
                                                      media_type="image/png")
    _write(data_dir, _tool_called("call-1", "browser_click", step_id=2, images=(_ref(screenshot),)))
    application = _application(data_dir)
    try:
        [event] = application.system.store.list_events(RUN)
        request = ScreenshotEvidence(event_id=event.event_id, kind=screenshot.kind,
                                     content_hash=screenshot.content_hash, path=screenshot.path,
                                     media_type=screenshot.media_type)
        assert base64.b64decode(application.query("evidence.screenshot", request).data.base64)

        (data_dir / "artifacts" / Path(screenshot.path)).write_bytes(b"tampered")
        with pytest.raises(NotFound, match="does not match its reference"):
            application.query("evidence.screenshot", request)

        with pytest.raises(NotFound, match="does not belong to the event"):
            application.query("evidence.screenshot", ScreenshotEvidence(
                event_id=event.event_id, kind=other.kind, content_hash=other.content_hash,
                path=other.path, media_type=other.media_type))
        with pytest.raises(NotFound, match="not a screenshot reference"):
            application.query("evidence.screenshot", ScreenshotEvidence(
                event_id=event.event_id, kind="tool_output", content_hash=screenshot.content_hash,
                path=screenshot.path, media_type=screenshot.media_type))
        with pytest.raises(NotFound, match="event not found"):
            application.query("evidence.screenshot", ScreenshotEvidence(
                event_id="evt_missing", kind=screenshot.kind, content_hash=screenshot.content_hash,
                path=screenshot.path, media_type=screenshot.media_type))
    finally:
        application.close()


# ---------------------------------------------------------------------------
# 5. run.actions：截图引用与浏览器会话身份


def test_run_actions_carries_screenshots_and_the_browser_session(tmp_path):
    # docs/design/browser-and-computer-use.md「查询」：浏览器动作的回执带截图引用与会话身份；会话身份取自结果工件里的浏览器会话
    data_dir = tmp_path / "data"
    screenshot = _screenshot(data_dir)
    output = _output(data_dir, "page", session_id="brs_1", tree_digest=TREE_DIGEST)
    _write(data_dir, _tool_called("call-1", "browser_click", step_id=2, args={"ref": "b1"},
                                  images=(_ref(screenshot),), output_ref=_ref(output)))
    application = _application(data_dir)
    try:
        result = application.query("run.actions", RunActions(run_id=RUN)).data
    finally:
        application.close()

    [action] = result.actions
    assert action.tool == "browser_click"
    assert action.receipt.args == {"ref": "b1"}
    assert action.receipt.screenshots == [_ref(screenshot)]
    assert action.receipt.session_id == "brs_1"
    assert action.receipt.session_tree_digest == TREE_DIGEST


# ---------------------------------------------------------------------------
# 6. work_item.materials：启动方式、逐条结论、试用用例截图与无法核验的条目


def test_work_item_materials_adds_launch_methods_criteria_results_and_trial_screenshots(tmp_path):
    # docs/design/browser-and-computer-use.md「查询」 `work_item.materials` 的三处增加：交付说明里的启动方式、每份 QAReview 的逐条结论与
    # 试用用例的截图引用、无法核验的条目与原因
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter([]))
    try:
        project_id = system.projects.register("资料", "做一个待办清单")
        work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
        screenshot = system.artifacts.put(run_id, "screenshot", b"\x89PNG\r\n\x1a\nshot",
                                          media_type="image/png")
        output = system.artifacts.put(run_id, "tool_output",
                                      json_dumps({"accessibility": "button[ref=b1]", "images": []}),
                                      media_type="application/json")
        system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(
            _spec(["列表显示一条待办", "列表可以点开"]),
            _delivery(launch=[{"name": "web-serve", "kind": "web",
                               "commands": {"windows": ["python", "-m", "http.server", "{port}"]},
                               "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": 30}]),
            _case_opened(criteria=("AC1",)),
            _tool_started("call-1", "browser_click", step_id=2),
            _tool_called("call-1", "browser_click", step_id=2, args={"ref": "b1"},
                         images=(_ref(screenshot),), output_ref=_ref(output)),
            _case_concluded("passed", evidence=("call-1",)),
            _qa_submitted([
                {"criterion": "AC1", "method": "trial", "result": "passed", "checks": [],
                 "trial_cases": ["case_1"], "note": ""},
                {"criterion": "AC2", "method": "open", "result": "unverified", "checks": [],
                 "trial_cases": [], "note": "没有可执行的检验"}])))

        application = Application(system)
        materials = application.query(
            "work_item.materials", WorkItemMaterials(project_id=project_id, work_item=work_item_id)).data
    finally:
        system.close()

    delivery = materials.deliveries[-1]
    assert [(item.name, item.kind) for item in delivery.launch] == [("web-serve", "web")]
    assert delivery.launch[0].ready_url == "http://127.0.0.1:{port}/"

    review = materials.reviews[-1]
    assert [(item.criterion, item.method, item.result, item.trial_cases)
            for item in review.criteria] == [
        ("AC1", "trial", "passed", ["case_1"]),
        ("AC2", "open", "unverified", [])]
    assert [item.case_id for item in review.trial_cases] == ["case_1"]
    assert review.trial_cases[0].screenshots == [_ref(screenshot)]
    assert [(item.criterion, item.note) for item in review.unverified] == [
        ("AC2", "没有可执行的检验")]


# ---------------------------------------------------------------------------
# 7. tools.registry：内置工具一节


def test_tools_registry_lists_the_builtin_browser_tools_and_whether_they_need_images(tmp_path):
    # `tools.registry`：Playwright MCP 的版本、浏览器工具与恢复契约、每个工具是否需要图像输入。
    # 版本取自浏览器模块（find_program 只接受这一版），工具与恢复契约取自定义
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter([]))
    try:
        builtin = Application(system).query("tools.registry", None).data.builtin
    finally:
        system.close()

    assert builtin.playwright_mcp.package == MCP_PACKAGE
    assert builtin.playwright_mcp.version == MCP_VERSION
    browser_tools = {name: tool for name, tool in DEFINITIONS.tools.items() if tool.action == "browser"}
    assert [item.name for item in builtin.browser_tools] == list(browser_tools)
    by_name = {item.name: item for item in builtin.browser_tools}
    for name, tool in browser_tools.items():
        assert by_name[name].verification == tool.verification, name
        assert by_name[name].cancellable is tool.cancellable, name
        assert by_name[name].requires_image_input is tool.requires_image_input, name
    assert by_name["browser_take_screenshot"].requires_image_input is True
    assert by_name["browser_navigate"].requires_image_input is False
    assert by_name["browser_navigate"].verification == "query"
    assert by_name["browser_snapshot"].verification == "none"

# 试用用例（浏览器与 computer use 设计说明第 8.1 至 8.3 节、第 7.2 节；独立性说明第 7.1 节；工单 #1180）。
#
# 这个文件查六件事：
# 1. 用例与它的步骤由事件折叠而成：用例打开到结束之间，本部门在同一会话中的浏览器与屏幕动作按动作身份
#    关联为它的步骤；别的会话、别的部门与用例结束以后的动不了它；同样的事件重放出同样的用例（R1）；
# 2. 会话在用例打开期间结束时用例结束为 interrupted，不能作为证据（R3）；
# 3. 结果未知的步骤（没有回执，或核实把结果交还会话）让用例不能以 passed 结束（R3）；
# 4. 步骤的分类：含断言工具（browser_verify_*）或检查回执（run_check）的是可执行的检验，只凭截图的是
#    模型阅读；只凭模型阅读的用例让它的条件算模型阅读、计入开环（R3）；
# 5. trial_case_begin 与 trial_case_end 的主机核对（有进行中的会话、没有另一个打开的用例、引用的验收条件
#    存在、证据步骤属于这个用例、passed 时没有结果未知的步骤）（R3）；
# 6. 放行引用的用例：属于本次激活、所在会话的试用副本树摘要等于当前交付的快照、结论与结果一致，
#    中断的与含结果未知步骤的用例被拒绝（R3）；两个工具只给质检（R2）。
#
# 层：模块层（事件库的一次事务与纯函数；没有网络、没有子进程、没有完整的三部门循环）。
# 守 R1（用例与步骤只由事件得出，重放相同）、R2（两个主机工具只在质检的工具清单里）与 R3（用例作为逐条
# 结论的证据、步骤分类与放行核对）。

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from harness.definitions import DEFINITIONS
from harness.engine import trial_case_begin, trial_case_end
from harness.event_store import EventStore, run_stream
from harness.models import EventType, RunProjection, TrialCase, TrialCaseStep
from harness.project_projection import handler_for
from harness.projection import replay_events
from harness.tightening import _criteria_evidence_errors, _release_criteria_errors, _trial_case_errors
from harness.coverage import coverage_report, criterion_is_executable, open_criteria, step_is_executable
from harness.write_path import NewEvent, WritePath

SESSION = "ses_quality_1"
OTHER_SESSION = "ses_quality_2"
TRIAL = "trial_session_1"
ACTIVATION = "act_quality_1"
SPEC_HASH = "sha256:spec"
TREE_DIGEST = "sha256:delivery"


class _Run:
    """一个真实的 run 事件流：事件经写入口写入，折叠出来的投影就是被测的那一份。"""

    def __init__(self, tmp_path: Path) -> None:
        self.store = EventStore(tmp_path / "events.db")
        self.writes = WritePath(self.store, handler_for)

    def append(self, *entries: NewEvent) -> None:
        self.writes.transact(run_stream("run-1"), lambda transaction: transaction.append(*entries))

    def event(self, type: str, payload: dict, *, department: str = "quality",
              session_id: str = SESSION) -> NewEvent:
        return NewEvent(type, state_before="running", state_after="running", actor=f"department:{department}",
                        department=department, session_id=session_id, payload=payload)

    def projection(self) -> RunProjection:
        return replay_events(self.store.list_events("run-1"))

    def close(self) -> None:
        self.store.close()


def _opened(case_id: str = "case_1", *, criteria=("AC1",), session_id: str = SESSION,
            activation_id: str = ACTIVATION, tree_digest: str = TREE_DIGEST,
            spec_hash: str = SPEC_HASH) -> NewEvent:
    return NewEvent(EventType.TRIAL_CASE_OPENED, state_before="running", state_after="running",
                    actor="department:quality", department="quality", session_id=session_id,
                    payload={"case_id": case_id, "session_id": session_id, "trial_session_id": TRIAL,
                             "department": "quality",
                             "activation_id": activation_id, "product_spec_hash": spec_hash,
                             "tree_digest": tree_digest, "criteria": list(criteria), "title": "待办清单",
                             "plan": ["打开页面", "添加一条待办"], "expected": "列表里出现这条待办"})


def _tool_started(identity: str, tool: str, *, session_id: str = SESSION, department: str = "quality",
                  step_id: int = 2) -> NewEvent:
    return NewEvent(EventType.TOOL_STARTED, state_before="running", state_after="running",
                    actor=f"department:{department}", department=department, session_id=session_id,
                    payload={"id": identity, "name": tool, "step_id": step_id,
                             "activation_id": ACTIVATION})


def _tool_called(identity: str, tool: str, *, ok: bool = True, images=(), session_id: str = SESSION,
                 department: str = "quality", step_id: int = 2) -> NewEvent:
    payload = {"id": identity, "name": tool, "step_id": step_id, "activation_id": ACTIVATION,
               "ok": ok, "error": None if ok else "failed"}
    if images:
        payload["images"] = list(images)
    return NewEvent(EventType.TOOL_CALLED, state_before="running", state_after="running",
                    actor=f"department:{department}", department=department, session_id=session_id,
                    payload=payload)


def _concluded(result: str, *, case_id: str = "case_1", evidence=(), reason: str = "",
               session_id: str = SESSION) -> NewEvent:
    return NewEvent(EventType.TRIAL_CASE_CONCLUDED, state_before="running", state_after="running",
                    actor="department:quality", department="quality", session_id=session_id,
                    payload={"case_id": case_id, "session_id": session_id, "department": "quality",
                             "result": result, "observed": "看到了", "evidence_steps": list(evidence),
                             "reason": reason})


def _session_ended(*, session_id: str = TRIAL) -> NewEvent:
    return NewEvent(EventType.TRIAL_SESSION_ENDED, state_before="running", state_after="running",
                    actor="system", department="quality", payload={"session_id": session_id,
                                                                   "department": "quality", "kind": "web",
                                                                   "reason": "interrupted"})


def _image(name: str = "shot") -> dict:
    return {"kind": "screenshot", "content_hash": f"sha256:{name}", "path": f"screenshots/{name}.png",
            "media_type": "image/png"}


# ---------------------------------------------------------------------------
# 1. 用例与它的步骤由事件折叠而成


def test_the_open_case_collects_the_actions_of_this_session_by_action_identity(tmp_path):
    # 用例打开到结束之间、本部门在同一会话中的浏览器与屏幕动作是它的步骤（按动作身份）；
    # 别的会话与结束以后的动作不算。守 R1（用例与步骤只由事件得出）与 R3（步骤是证据的计量单位）
    run = _Run(tmp_path)
    try:
        run.append(_opened())
        run.append(_tool_started("call-1", "browser_navigate"),
                   _tool_called("call-1", "browser_navigate", images=[_image("one")]))
        run.append(_tool_started("call-2", "browser_verify_text_visible", step_id=3),
                   _tool_called("call-2", "browser_verify_text_visible", step_id=3))
        run.append(_tool_started("call-other", "browser_click", session_id=OTHER_SESSION),
                   _tool_called("call-other", "browser_click", session_id=OTHER_SESSION))
        run.append(_tool_started("call-read", "read_file", step_id=4),
                   _tool_called("call-read", "read_file", step_id=4))

        case = run.projection().trial_cases[0]
        assert [step.identity for step in case.steps] == ["call-1", "call-2"]
        assert [step.tool for step in case.steps] == ["browser_navigate", "browser_verify_text_visible"]
        assert case.steps[0].screenshots == [_image("one")]
        assert all(step.status == "completed" for step in case.steps)
        assert case.status == "open" and case.criteria == ["AC1"]
        assert case.tree_digest == TREE_DIGEST and case.activation_id == ACTIVATION

        # 用例结束以后的动作不再属于它
        run.append(_concluded("passed", evidence=["call-1"]))
        run.append(_tool_started("call-after", "browser_click", step_id=5),
                   _tool_called("call-after", "browser_click", step_id=5))
        case = run.projection().trial_cases[0]
        assert [step.identity for step in case.steps] == ["call-1", "call-2"]
        assert case.status == "concluded" and case.result == "passed"
        assert case.evidence_steps == ["call-1"]
    finally:
        run.close()


def test_the_same_events_replay_to_the_same_trial_cases(tmp_path):
    # 同样的事件重放出同样的用例（R1）：写入口折叠出的投影与从头重放的结果相同
    run = _Run(tmp_path)
    try:
        run.append(_opened())
        run.append(_tool_started("call-1", "browser_snapshot"),
                   _tool_called("call-1", "browser_snapshot", images=[_image("snap")]))

        def decided(transaction):
            return transaction.projection

        lived = run.writes.transact(run_stream("run-1"), decided)
        replayed = run.projection()
        assert lived.trial_cases == replayed.trial_cases
        assert lived.trial_cases[0].steps[0].screenshots == [_image("snap")]
    finally:
        run.close()


# ---------------------------------------------------------------------------
# 2. 会话结束时打开的用例结束为中断


def test_a_session_that_ends_while_a_case_is_open_concludes_it_as_interrupted(tmp_path):
    # 会话结束或中断时打开的用例自动结束为中断，不能作为证据（设计说明第 8.2 节）。守 R3
    run = _Run(tmp_path)
    try:
        run.append(_opened())
        run.append(_tool_started("call-1", "browser_click"), _tool_called("call-1", "browser_click"))
        run.append(_session_ended())

        case = run.projection().trial_cases[0]
        assert case.status == "concluded" and case.result == "interrupted"
        assert case.reason == "session_ended"
        projection = run.projection()
        criteria = [{"criterion": "AC1", "method": "trial", "result": "passed",
                     "checks": [], "trial_cases": [case.case_id]}]
        errors = _trial_case_errors(criteria, projection, department="quality",
                                    spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST)
        assert [error.field for error in errors] == ["criteria[0].trial_cases[0]"]
        assert "interrupted" in errors[0].message
    finally:
        run.close()


# ---------------------------------------------------------------------------
# 3. 结果未知的步骤


def test_a_step_without_a_result_or_handed_back_stays_unknown(tmp_path):
    # 发出了但没有回执的步骤是结果未知；核实把结果交还会话（handed_back）同样是结果未知。
    # 含这样一步的用例不能以 passed 结束（设计说明第 8.2 节、第 9 节）。守 R3
    run = _Run(tmp_path)
    try:
        run.append(_opened())
        run.append(_tool_started("call-1", "browser_click"), _tool_called("call-1", "browser_click"))
        run.append(_tool_started("call-2", "browser_type", step_id=3))

        case = run.projection().trial_cases[0]
        assert [step.unknown for step in case.steps] == [False, True]
        assert case.has_unknown_step()

        # 核实记录把结果交还会话：仍然未知
        run.append(NewEvent(EventType.ACTION_VERIFIED, state_before="running", state_after="running",
                            actor="system", department="quality", session_id=SESSION,
                            payload={"id": "call-2", "name": "browser_type", "step_id": 3,
                                     "activation_id": ACTIVATION, "ok": False, "resolution": "handed_back"}))
        case = run.projection().trial_cases[0]
        assert case.step("call-2") is not None and case.step("call-2").unknown

        # 用例结束成 passed 被拒绝：结果未知的步骤不让它通过
        outcome = trial_case_end({"result": "passed", "observed": "看到了", "evidence_steps": ["call-1"]},
                                 projection=run.projection(), department="quality", session_id=SESSION,
                                 session={"session_id": TRIAL, "tree_digest": TREE_DIGEST})
        assert outcome.ok is False and "result is unknown" in outcome.error
        # 交成 failed 可以：未知的步骤可以作为不通过的理由
        outcome = trial_case_end({"result": "failed", "observed": "页面没有反应", "evidence_steps": ["call-1"]},
                                 projection=run.projection(), department="quality", session_id=SESSION,
                                 session={"session_id": TRIAL, "tree_digest": TREE_DIGEST})
        assert outcome.ok is True and outcome.payload["result"] == "failed"
    finally:
        run.close()


# ---------------------------------------------------------------------------
# 4. 步骤的分类与三个数


def test_assertions_and_check_receipts_are_executable_and_screenshots_are_model_reading():
    # 步骤分类（设计说明第 8.3 节）：含断言工具或检查回执的是可执行的检验，只凭截图的是模型阅读。守 R3
    assert step_is_executable("browser_verify_text_visible")
    assert step_is_executable("run_check")
    assert not step_is_executable("browser_take_screenshot")
    assert not step_is_executable("browser_click")

    cases = {
        "case-read": [TrialCaseStep("call-1", "browser_take_screenshot"),
                      TrialCaseStep("call-2", "browser_click")],
        "case-verify": [TrialCaseStep("call-3", "browser_click"),
                        TrialCaseStep("call-4", "browser_verify_text_visible")],
    }
    reading = {"criterion": "AC1", "method": "trial", "result": "passed", "trial_cases": ["case-read"]}
    verified = {"criterion": "AC2", "method": "trial", "result": "passed", "trial_cases": ["case-verify"]}
    # 只凭截图由模型判断的条目算模型阅读：不是可执行的检验，计入开环、不计入覆盖
    assert not criterion_is_executable(reading, cases)
    assert criterion_is_executable(verified, cases)
    report = coverage_report([reading, verified], cases=cases)
    assert report["executable"] == 1 and report["covered"] == 1
    assert report["model_reading"] == 1 and report["open"] == 1
    assert report["coverage_ratio"] == 0.5
    assert open_criteria([reading, verified], cases) == ["AC1"]


# ---------------------------------------------------------------------------
# 5. 两个主机工具的核对


def _projection(*, spec_criteria=("一", "二"), cases=(), activation: str = ACTIVATION) -> RunProjection:
    projection = RunProjection(run_id="run-1")
    projection.product_spec = SimpleNamespace(content_hash=SPEC_HASH,
                                              acceptance_criteria=list(spec_criteria))
    projection.last_activations = {"quality": activation}
    projection.trial_cases = list(cases)
    return projection


def _with_cases(projection: RunProjection) -> RunProjection:
    return projection




def _open_case(*, case_id: str = "case_1", criteria=("AC1",), session_id: str = SESSION,
               activation_id: str = ACTIVATION, tree_digest: str = TREE_DIGEST, result=None,
               steps=()) -> TrialCase:
    return TrialCase(case_id=case_id, session_id=session_id, trial_session_id=TRIAL, department="quality",
                     activation_id=activation_id, product_spec_hash=SPEC_HASH, tree_digest=tree_digest,
                     criteria=list(criteria), title="待办清单", plan=["打开页面"], expected="看到待办",
                     status="open" if result is None else "concluded", result=result,
                     steps=list(steps))


def test_begin_requires_a_running_session_no_other_case_and_existing_criteria():
    # trial_case_begin 的主机核对（设计说明第 8.2 节）。守 R3
    session = {"session_id": SESSION, "tree_digest": TREE_DIGEST}
    args = {"criteria": ["AC1"], "title": "待办清单", "steps": ["打开页面"], "expected": "看到待办"}

    missing = trial_case_begin(args, projection=_projection(), department="quality",
                               session_id=SESSION, activation_id=ACTIVATION, session=None)
    assert missing.ok is False and "trial session" in missing.error

    busy = trial_case_begin(args, projection=_projection(cases=[_open_case()]), department="quality",
                            session_id=SESSION, activation_id=ACTIVATION, session=session)
    assert busy.ok is False and "still open" in busy.error

    unknown = trial_case_begin({**args, "criteria": ["AC3"]}, projection=_projection(), department="quality",
                               session_id=SESSION, activation_id=ACTIVATION, session=session)
    assert unknown.ok is False and "AC3" in unknown.error

    bad_shape = trial_case_begin({**args, "criteria": ["a1"]}, projection=_projection(), department="quality",
                                 session_id=SESSION, activation_id=ACTIVATION, session=session)
    assert bad_shape.ok is False and "AC<position>" in bad_shape.error

    opened = trial_case_begin(args, projection=_projection(), department="quality",
                              session_id=SESSION, activation_id=ACTIVATION, session=session)
    assert opened.ok is True and opened.event_type == EventType.TRIAL_CASE_OPENED
    assert opened.payload["session_id"] == SESSION and opened.payload["tree_digest"] == TREE_DIGEST
    assert opened.payload["product_spec_hash"] == SPEC_HASH and opened.payload["criteria"] == ["AC1"]


def test_end_requires_evidence_of_this_case_a_reason_when_unverified_and_no_unknown_steps():
    # trial_case_end 的主机核对（设计说明第 8.2 节）。守 R3
    session = {"session_id": SESSION, "tree_digest": TREE_DIGEST}
    steps = [TrialCaseStep("call-1", "browser_verify_text_visible", status="completed")]
    projection = _projection(cases=[_open_case(steps=steps)])

    none_open = trial_case_end({"result": "passed", "observed": "x", "evidence_steps": ["call-1"]},
                               projection=_projection(), department="quality", session_id=SESSION, session=session)
    assert none_open.ok is False and "no open trial case" in none_open.error

    stranger = trial_case_end({"result": "passed", "observed": "x", "evidence_steps": ["call-9"]},
                              projection=projection, department="quality", session_id=SESSION, session=session)
    assert stranger.ok is False and "not a step of trial case" in stranger.error

    no_evidence = trial_case_end({"result": "passed", "observed": "x", "evidence_steps": []},
                                 projection=projection, department="quality", session_id=SESSION, session=session)
    assert no_evidence.ok is False and "at least one evidence step" in no_evidence.error

    no_reason = trial_case_end({"result": "unverified", "observed": "x", "evidence_steps": []},
                               projection=projection, department="quality", session_id=SESSION, session=session)
    assert no_reason.ok is False and "requires a reason" in no_reason.error

    bad_result = trial_case_end({"result": "interrupted", "observed": "x", "evidence_steps": []},
                                projection=projection, department="quality", session_id=SESSION, session=session)
    assert bad_result.ok is False and "passed, failed, or unverified" in bad_result.error

    passed = trial_case_end({"result": "passed", "observed": "列表里有这条待办", "evidence_steps": ["call-1"]},
                            projection=projection, department="quality", session_id=SESSION, session=session)
    assert passed.ok is True and passed.event_type == EventType.TRIAL_CASE_CONCLUDED
    assert passed.payload["evidence_steps"] == ["call-1"] and passed.payload["result"] == "passed"


# ---------------------------------------------------------------------------
# 6. 放行引用的用例


def _review_criterion(case_id: str, result: str = "passed", method: str = "trial") -> dict:
    return {"criterion": "AC1", "method": method, "result": result, "checks": [], "trial_cases": [case_id]}


def test_a_case_from_another_activation_or_another_tree_digest_is_rejected():
    # 用例属于本次激活、所在会话的试用副本树摘要等于当前交付的 code_snapshot_hash（设计说明第 8.3 节）。守 R3
    old = _open_case(case_id="case_old", activation_id="act_older", result="passed")
    errors = _trial_case_errors([_review_criterion("case_old")], _projection(cases=[old]),
                                department="quality", spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST)
    assert [error.field for error in errors] == ["criteria[0].trial_cases[0]"]
    assert "another activation" in errors[0].message

    elsewhere = _open_case(case_id="case_elsewhere", tree_digest="sha256:other", result="passed")
    errors = _trial_case_errors([_review_criterion("case_elsewhere")], _projection(cases=[elsewhere]),
                                department="quality", spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST)
    assert [error.field for error in errors] == ["criteria[0].trial_cases[0]"]
    assert "does not equal the current delivery snapshot" in errors[0].message

    other_spec = _open_case(case_id="case_spec")
    other_spec.product_spec_hash = "sha256:older-spec"
    other_spec.status, other_spec.result = "concluded", "passed"
    errors = _trial_case_errors([_review_criterion("case_spec")], _projection(cases=[other_spec]),
                                department="quality", spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST)
    assert "another ProductSpec" in errors[0].message

    missing = _trial_case_errors([_review_criterion("case_missing")], _projection(),
                                 department="quality", spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST)
    assert "does not belong to this run" in missing[0].message


def test_the_case_conclusion_must_equal_the_criterion_result_and_be_concluded():
    # 结论与该项的 result 一致；还没有结束的用例不能引用；引用它的条目必须写在用例的 criteria 里。守 R3
    open_case = _open_case()
    errors = _trial_case_errors([_review_criterion("case_1")], _projection(cases=[open_case]),
                                department="quality", spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST)
    assert "still open" in errors[0].message

    failed_case = _open_case(case_id="case_2", criteria=("AC2",), result="failed")
    errors = _trial_case_errors([_review_criterion("case_2", result="passed")],
                                _projection(cases=[failed_case]),
                                department="quality", spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST)
    assert "concluded failed but this criterion says passed" in errors[0].message

    other_criterion = _open_case(case_id="case_3", criteria=("AC2",), result="passed")
    errors = _trial_case_errors([_review_criterion("case_3")], _projection(cases=[other_criterion]),
                                department="quality", spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST)
    assert "was not opened for AC1" in errors[0].message

    good = _open_case(case_id="case_4", result="passed")
    assert _trial_case_errors([_review_criterion("case_4")], _projection(cases=[good]),
                              department="quality", spec_hash=SPEC_HASH, snapshot_hash=TREE_DIGEST) == []


def test_a_passed_trial_case_is_evidence_and_a_model_reading_case_is_open():
    # passed 的可执行检验要有证据：检查回执或通过的用例；只凭模型阅读的用例让条件算模型阅读（开环）。守 R3
    assert _criteria_evidence_errors([_review_criterion("case_1")], "quality") == []
    assert _criteria_evidence_errors(
        [{"criterion": "AC1", "method": "trial", "result": "passed", "checks": [], "trial_cases": []}],
        "quality")

    cases = {"case_read": [TrialCaseStep("call-1", "browser_take_screenshot")]}
    reading = _review_criterion("case_read")
    # 只凭截图：放行时不要求它通过，列进开环明细
    assert _release_criteria_errors([{**reading, "result": "unverified"}], cases) == []
    # 没有步骤可以分类时按检验方式算：试用是可执行的检验，放行要求它通过
    errors = _release_criteria_errors([{**reading, "result": "unverified"}], {})
    assert [error.field for error in errors] == ["criteria[0].result"]


def test_the_two_tools_are_offered_to_quality_only():
    # 两个主机工具只在质检的工具清单里（设计说明第 6.3 节）。守 R2
    for department in DEFINITIONS.departments:
        tools = DEFINITIONS.tools_for(department, "change")
        if DEFINITIONS.is_verifier(department):
            assert {"trial_case_begin", "trial_case_end"} <= set(tools)
        else:
            assert "trial_case_begin" not in tools and "trial_case_end" not in tools

# 质检结论对独立判断的引用与改判（验证的独立性设计说明第 4 节，工单 #1190）。
#
# 这份测试守的行为：
# 1. 引用校验：结论引用的独立判断必须存在、属于这次核验（对当前交付与当前 PRD，写在这份交付被接纳
#    之后），并且覆盖当前 PRD 的全部验收条件；不满足的结论被拒绝，字段级错误指向 judgement_event。
# 2. 改判：结论与判断结果不一致的条目要写 change_reason（改判理由），没写的结论被拒绝；
#    写了就接纳，同一条记录里留下判断当时的结果。
# 3. 放行记录带改判条数：coverage.changed 写进 qa_submitted 的事件载荷，并记下引用的判断事件编号，
#    以后算解释翻转率时从这里取。
# 4. 不写编号时由主机取当前交付的独立判断：结论照样引用一条判断。
#
# 层：模块层（真实事件日志、真实写入口与收紧检查，假模型脚本；最多用到 activate_once，不进完整三部门循环）。
# 守 R3（独立证据：结论引用独立判断、改判写理由）与 R2（放行记录的字段）。

from dataclasses import replace

from harness.actions import CheckReceipt, TreeFacts
from harness.adapters.fake import FakeAdapter
from harness.kernel_events import Event
from harness.models import (ArtifactRef, DeliverySpec, EffectiveContract, EventType, SessionRecord)
from harness.proposals import delivery_turn, judgement_turn, product_spec, review, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import minimal_of
from harness.tightening import WATCHED_OUTPUTS
from harness.validation import TightenRequest

TREE = "sha256:" + "e" * 64
DELIVERY = "sha256:" + "d" * 64
OTHER_DELIVERY = "sha256:" + "1" * 64
CONTRACT = "sha256:" + "c" * 64
REASON = "看过解释以后补了检查，改判为通过"


def _facts(*checks: CheckReceipt) -> TreeFacts:
    return TreeFacts(digest=TREE, files=("src/echo.py",), hashes=("h",), checks=checks)


def _ref(kind: str, content_hash: str) -> ArtifactRef:
    return ArtifactRef(kind=kind, content_hash=content_hash, path=f"{kind}/{content_hash[7:9]}/{content_hash[7:]}")


def _receipt(spec_hash: str, name: str = "smoke") -> CheckReceipt:
    # 一条本次激活的质检检查回执：绑定当前快照、当前 PRD 与当前交付
    return CheckReceipt(name=name, department="quality", exit_code=0, summary="ran", snapshot_hash=TREE,
                        bindings={"product_spec": spec_hash, "delivery_spec": DELIVERY, "contract": CONTRACT},
                        product_spec_hash=spec_hash, delivery_spec_hash=DELIVERY, activation_id="act_q",
                        effective_contract_hash=CONTRACT, qa_tests_hash=None)


def _accepted(tmp_path, acceptance: list[str]) -> tuple[LoopSystem, str]:
    # 产品提交第一版 PRD 并让它被接纳：投影里有当前 PRD 与当前合同
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(acceptance=acceptance)]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    return system, run_id


def _working(projection, department: str):
    # 这个部门正在工作（按调度算出来的当前工作由既有用例覆盖）
    return replace(projection, sessions={**projection.sessions, department: SessionRecord(
        session_id=f"ses_{department}", department=department, status="active")})


def _delivery_ready(projection):
    # 一份可以核验的交付：当前合同、当前交付与这一轮质检的一条检查回执
    spec = projection.product_spec
    contract = EffectiveContract(content_hash=CONTRACT, revision=1, product_spec_hash=spec.content_hash,
                                 input_version=spec.input_version, decision_hashes=[],
                                 created_event_id="evt_contract", prd_ref=_ref("prd", spec.content_hash))
    delivery = DeliverySpec(id="delivery_1", run_id=projection.run_id, revision=1, parent_hash=None,
                            content_hash=DELIVERY, issuer="engineering", status="active",
                            created_event_id="evt_delivery", product_spec_hash=spec.content_hash,
                            effective_contract_hash=CONTRACT, summary="implemented", files=["src/echo.py"],
                            check_names=["smoke"], checks=[], known_risks=[], code_tree_digest=TREE,
                            tree_ref=_ref("tree", TREE))
    ready = replace(projection, effective_contract=contract, delivery_spec=delivery,
                    last_activations={"quality": "act_q"})
    return _working(ready, "quality")


def _delivery_event(spec_hash: str, position: int = 5) -> Event:
    # 当前交付被接纳的那一条事件：判断写在它之后才算这一轮核验的依据
    return _event("evt_delivery", EventType.DELIVERY_ACCEPTED, position,
                  {"content_hash": DELIVERY, "product_spec_hash": spec_hash})


def _judgement(spec_hash: str, event_id: str = "evt_judgement", *, position: int = 9,
               delivery_hash: str = DELIVERY, criteria: list[dict] | None = None) -> Event:
    # 一条独立判断事件（工单 #358）：默认对当前交付与当前 PRD 写一条通过 AC1 的判断
    rows = [{"criterion": "AC1", "method": "check", "result": "passed", "checks": ["smoke"],
             "trial_cases": [], "note": ""}] if criteria is None else criteria
    return _event(event_id, EventType.INDEPENDENT_JUDGEMENT_COMMITTED, position, {
        "kind": "independent_judgement", "product_spec_hash": spec_hash, "delivery_spec_hash": delivery_hash,
        "checks": ["smoke"], "criteria_count": len(rows), "criteria": rows})


def _event(event_id: str, event_type: str, position: int, payload: dict) -> Event:
    return Event(event_id=event_id, run_id="run_test", type=event_type, role=None, parent_event_id=None,
                 state_before="running", state_after="running", payload=payload, artifact_hashes=[],
                 session_id="ses_quality", provider=None, model=None, context_digest=None, stop_reason=None,
                 error=None, created_at="2026-10-31T00:00:00Z", position=position, stream="run:run_test",
                 stream_version=position, project_id=None, work_item_id=None, department="quality")


def _request(projection, proposal: dict, *, events: list[Event]) -> TightenRequest:
    spec_hash = projection.product_spec.content_hash
    return TightenRequest(department="quality", state=projection, proposal=proposal,
                          minimal=minimal_of(projection), facts=_facts(_receipt(spec_hash)), events=tuple(events))


def _errors(tightened) -> list[tuple[str, str]]:
    return [(error.field, error.message) for error in tightened.errors]


def _criteria(result: str = "passed", *, change_reason: str | None = None) -> list[dict]:
    # 结论的逐条结论：AC1 用本次激活的 smoke 回执
    row = {"criterion": "AC1", "method": "check", "result": result, "checks": ["smoke"],
           "trial_cases": [], "note": ""}
    if change_reason is not None:
        row["change_reason"] = change_reason
    return [row]


def _review(**overrides) -> dict:
    values = dict(verdict="release", rationale="交付通过", checks=["smoke"],
                  basis_delivery_spec_hash=DELIVERY, criteria=_criteria())
    values.update(overrides)
    return review(**values)


def test_a_conclusion_citing_a_judgement_that_does_not_exist_is_rejected(tmp_path):
    # 引用存在：写了一个日志里没有的判断编号，结论被拒绝，错误指向 judgement_event
    system, run_id = _accepted(tmp_path, ["prints the word"])
    projection = _delivery_ready(system.project(run_id))
    spec_hash = projection.product_spec.content_hash
    tightened = WATCHED_OUTPUTS.submission(_request(
        projection, _review(judgement_event="evt_missing"),
        events=[_delivery_event(spec_hash), _judgement(spec_hash)]))
    assert _errors(tightened) == [
        ("judgement_event", "the referenced independent judgement does not exist in this work item: evt_missing")]


def test_a_judgement_of_another_delivery_does_not_belong_to_this_round(tmp_path):
    # 属于本次激活：上一份交付的判断不能拿来当这一份交付的依据
    system, run_id = _accepted(tmp_path, ["prints the word"])
    projection = _delivery_ready(system.project(run_id))
    spec_hash = projection.product_spec.content_hash
    events = [_delivery_event(spec_hash), _judgement(spec_hash, "evt_previous", delivery_hash=OTHER_DELIVERY)]
    tightened = WATCHED_OUTPUTS.submission(_request(
        projection, _review(judgement_event="evt_previous"), events=events))
    [field, message] = _errors(tightened)[0]
    assert field == "judgement_event"
    assert "not for the current delivery" in message
    # 不写编号时也取不到这一份交付的判断：门拒绝，错误同样指向 judgement_event
    tightened = WATCHED_OUTPUTS.submission(_request(projection, _review(), events=events))
    [field, message] = _errors(tightened)[0]
    assert field == "judgement_event"
    assert "commit the independent judgement" in message


def test_a_judgement_committed_before_the_delivery_was_accepted_does_not_count(tmp_path):
    # 属于本次激活：判断写在当前交付被接纳之前，不算这一轮核验的依据
    system, run_id = _accepted(tmp_path, ["prints the word"])
    projection = _delivery_ready(system.project(run_id))
    spec_hash = projection.product_spec.content_hash
    events = [_judgement(spec_hash, position=3), _delivery_event(spec_hash, position=5)]
    tightened = WATCHED_OUTPUTS.submission(_request(
        projection, _review(judgement_event="evt_judgement"), events=events))
    [field, message] = _errors(tightened)[0]
    assert field == "judgement_event"
    assert "before the current delivery was accepted" in message


def test_a_judgement_that_does_not_cover_every_criterion_is_rejected(tmp_path):
    # 覆盖全部验收条件：PRD 有两条验收条件，判断只写了一条，结论被拒绝并写明缺哪一条
    system, run_id = _accepted(tmp_path, ["prints the word", "prints usage without arguments"])
    projection = _delivery_ready(system.project(run_id))
    spec_hash = projection.product_spec.content_hash
    events = [_delivery_event(spec_hash), _judgement(spec_hash)]
    tightened = WATCHED_OUTPUTS.submission(_request(
        projection, _review(criteria=_criteria() + [{"criterion": "AC2", "method": "check", "result": "passed",
                                                     "checks": ["smoke"], "trial_cases": [], "note": ""}]),
        events=events))
    [field, message] = _errors(tightened)[0]
    assert field == "judgement_event"
    assert "does not cover every acceptance criterion" in message
    assert "AC2" in message


def test_a_changed_result_needs_a_reason_and_is_recorded_with_the_count(tmp_path):
    # 改判：判断当时 AC1 是 unverified，结论改成 passed，没有写理由被拒绝；写了理由就接纳，
    # 记录里同时留下判断当时的结果与改判条数（第 2、3 条验收标准）
    system, run_id = _accepted(tmp_path, ["prints the word"])
    projection = _delivery_ready(system.project(run_id))
    spec_hash = projection.product_spec.content_hash
    judged_open = [{"criterion": "AC1", "method": "open", "result": "unverified", "checks": [],
                    "trial_cases": [], "note": "还没有可执行的检验"}]
    events = [_delivery_event(spec_hash), _judgement(spec_hash, criteria=judged_open)]

    tightened = WATCHED_OUTPUTS.submission(_request(projection, _review(), events=events))
    [field, message] = _errors(tightened)[0]
    assert field == "criteria[0].change_reason"
    assert "the independent judgement recorded unverified" in message

    tightened = WATCHED_OUTPUTS.submission(_request(
        projection, _review(criteria=_criteria(change_reason=REASON)), events=events))
    assert tightened.accepted, tightened.errors
    assert tightened.ends_run
    content = tightened.content
    assert content["judgement_event"] == "evt_judgement"
    assert content["coverage"]["changed"] == 1
    assert content["criteria"][0]["judged"] == "unverified"
    assert content["criteria"][0]["change_reason"] == REASON

    # 判断与结论一致时改判条数是 0：没有改判理由也可以放行
    tightened = WATCHED_OUTPUTS.submission(_request(
        projection, _review(), events=[_delivery_event(spec_hash), _judgement(spec_hash)]))
    assert tightened.accepted, tightened.errors
    assert tightened.content["coverage"]["changed"] == 0
    assert tightened.content["criteria"][0]["judged"] == "passed"
    assert tightened.content["criteria"][0]["change_reason"] == ""


def test_the_release_record_carries_the_change_count_in_a_real_run(tmp_path):
    # 真实运行（写入口与收紧检查，模块层）：质检先交判断（AC1 开环、未核验），看过解释以后改判为通过
    # 并写明理由；放行记录记下引用的判断事件与改判条数
    judged_open = [{"criterion": "AC1", "method": "open", "result": "unverified", "checks": [],
                    "trial_cases": [], "note": "先按开环判断"}]
    script = {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [judgement_turn(criteria=judged_open),
                    review_turn("release", "看过解释以后补了检查，改判为通过",
                                criteria=_criteria(change_reason=REASON))],
    }
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(script))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)   # 产品提交 PRD
    system.activate_once(run_id)   # 工程交付
    system.activate_once(run_id)   # 质检提交独立判断
    projection = system.activate_once(run_id)   # 质检放行
    assert projection.status == "done", projection.stop_reason

    events = system.store.list_events(run_id)
    [judged] = [event for event in events if event.type == EventType.INDEPENDENT_JUDGEMENT_COMMITTED]
    [reviewed] = [event for event in events if event.type == EventType.QA_SUBMITTED]
    payload = reviewed.payload
    assert payload["judgement_event"] == judged.event_id
    assert payload["coverage"]["changed"] == 1
    assert payload["criteria"][0]["judged"] == "unverified"
    assert payload["criteria"][0]["change_reason"] == REASON
    # 判断事件里没有结论才有的这两项（判断不改判）
    assert "change_reason" not in judged.payload["criteria"][0]
    # 投影里同样读得到这两项（查询与以后算翻转率的报告从这里取）
    review_state = system.project(run_id).last_review
    assert review_state is not None
    assert review_state.judgement_event == judged.event_id
    assert review_state.changed == 1

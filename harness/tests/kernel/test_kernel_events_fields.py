# 内核事件模块的封闭取值、序列化摘要、信封默认值、决定请求折叠与派发编号过滤（S5a，工单 #828、#1397、#1761）：
# 直接构造内存中的事件并调用 harness/kernel_events.py 的公开函数与类型，不打开数据库、不使用子进程、不访问网络，属于单元层。
# 守护 R1（第三环的不变式：决定请求跨三个流确定性折叠、重派迟到事件按流与会话过滤、内容摘要按规范 JSON 计算）
# 与 R2（第二环的合同：状态与质检封闭取值、应用事件登记边界、信封与决定请求字段默认值、摘要白名单、流处理者协议签名）。

from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from harness.kernel_events import (
    BASELINE_STATUSES,
    QA_METHODS,
    QA_RESULTS,
    QA_VERDICTS,
    RUN_STATUSES,
    TERMINAL_STATUSES,
    CatalogEvent,
    CatalogEventType,
    DecisionRequest,
    Event,
    ProjectEvent,
    ProjectEventType,
    SkeletonEventType,
    StreamHandler,
    accepted,
    application_event_types,
    apply_decision_event,
    canonical_hash,
    event_type_owner,
    json_dumps,
    new_id,
    register_application_event_types,
    replay_decisions,
    spec_content_hash,
    utc_now,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_METHODS_FIXTURE = REPO_ROOT / "harness" / "tests" / "fixtures" / "check_methods.json"


def _make_run_event(
    event_type: str,
    event_id: str = "evt_1",
    *,
    payload: dict | None = None,
    position: int = 1,
    stream: str = "run:run_1",
    run_id: str = "run_1",
    project_id: str | None = "prj_1",
    work_item_id: str | None = "wi_1",
    session_id: str | None = "ses_1",
    created_at: str = "2026-10-28T00:00:00+00:00",
    **overrides,
) -> Event:
    base = dict(
        event_id=event_id,
        run_id=run_id,
        type=event_type,
        role=None,
        parent_event_id=None,
        state_before="running",
        state_after="running",
        payload={} if payload is None else payload,
        artifact_hashes=[],
        session_id=session_id,
        provider=None,
        model=None,
        context_digest=None,
        stop_reason=None,
        error=None,
        created_at=created_at,
        position=position,
        stream=stream,
        stream_version=position,
        project_id=project_id,
        work_item_id=work_item_id,
        department=None,
    )
    base.update(overrides)
    return Event(**base)


def test_the_closed_vocabularies_match_the_contract_and_the_fixture():
    # 守护 R2：运行状态、终态集合、质检结论与基线状态属于骨架合同的封闭取值；质检检验方式与公共夹具 check_methods.json 保持一致
    assert RUN_STATUSES == ("running", "done", "paused", "failed")
    assert isinstance(TERMINAL_STATUSES, frozenset)
    assert TERMINAL_STATUSES == frozenset({"done", "paused", "failed"})
    assert QA_VERDICTS == ("rework_engineering", "release", "cannot_verify")
    assert BASELINE_STATUSES == ("verified", "read_only", "existing_defect", "unsupported")
    assert QA_METHODS == ("check", "trial", "measure", "judgement", "human", "open")
    fixture_codes = tuple(
        item["code"] for item in json.loads(CHECK_METHODS_FIXTURE.read_text(encoding="utf-8"))["methods"]
    )
    assert QA_METHODS == fixture_codes
    assert QA_RESULTS == ("passed", "failed", "unverified")


def test_application_event_registration_is_idempotent_atomic_and_returns_a_copy():
    # 守护 R2：同一应用重复登记同一种类保持幂等，整批校验通过后才写入登记表，读取接口返回独立副本
    register_application_event_types("测试应用甲", ["probe_idempotent_kind"])
    register_application_event_types("测试应用甲", ["probe_idempotent_kind"])
    assert event_type_owner("probe_idempotent_kind") == "测试应用甲"

    copied = application_event_types()
    copied.clear()
    assert application_event_types()["probe_idempotent_kind"] == "测试应用甲"

    with pytest.raises(ValueError):
        register_application_event_types("测试应用乙", ["probe_atomic_unwritten", "probe_idempotent_kind"])
    assert event_type_owner("probe_atomic_unwritten") is None

    with pytest.raises(ValueError):
        register_application_event_types("   ", ["probe_blank_owner_unwritten"])
    assert event_type_owner("probe_blank_owner_unwritten") is None


def test_new_id_and_utc_now_follow_the_envelope_identity_and_time_format():
    # 守护 R2：编号生成函数输出前缀加十六位小写十六进制字符且每次调用互异，时间函数输出带 UTC 时区的 ISO 8601 时间戳
    first = new_id("evt")
    second = new_id("evt")
    assert first != second
    prefix, suffix = first.split("_", 1)
    assert prefix == "evt"
    assert len(suffix) == 16
    assert all(ch in "0123456789abcdef" for ch in suffix)

    parsed = datetime.fromisoformat(utc_now())
    assert parsed.tzinfo == timezone.utc


def test_json_dumps_and_hashes_are_canonical_and_serialize_dataclasses():
    # 守护 R1 与 R2：序列化保留非 ASCII 字符、按键名排序并采用紧凑分隔符，数据类实例按字段字典写出，数据类类型与不可序列化对象抛出 TypeError；内容摘要对字典键序无感且覆盖全部四个输入项
    serialized = json_dumps({"b": [1, 2], "a": "中文"})
    assert serialized == '{"a":"中文","b":[1,2]}'

    catalog_event = CatalogEvent(
        event_id="cevt_hash",
        type=CatalogEventType.HOME_SEEN,
        payload={"page": "overview"},
        created_at="2026-10-28T00:00:00+00:00",
        position=1,
        stream="catalog:main",
        stream_version=1,
    )
    assert json.loads(json_dumps(catalog_event)) == catalog_event.to_dict()

    decision = DecisionRequest(
        decision_id="dec_1",
        stream="run:run_1",
        run_id="run_1",
        project_id="prj_1",
        work_item_id="wi_1",
        requested_at="2026-10-28T00:00:00+00:00",
        request={"kind": "product_input", "blocks": "run"},
    )
    assert json.loads(json_dumps(decision))["decision_id"] == "dec_1"

    with pytest.raises(TypeError):
        json_dumps(CatalogEvent)
    with pytest.raises(TypeError):
        json_dumps(DecisionRequest)

    expected_digest = "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert canonical_hash({"b": [1, 2], "a": "中文"}) == expected_digest
    assert canonical_hash({"a": "中文", "b": (1, 2)}) == expected_digest

    base_spec_hash = spec_content_hash(
        "product_spec",
        {"z": 1, "a": "目标"},
        parent_hash="sha256:parent",
        revision=2,
    )
    assert base_spec_hash == canonical_hash(
        {
            "kind": "product_spec",
            "parent_hash": "sha256:parent",
            "payload": {"a": "目标", "z": 1},
            "revision": 2,
        }
    )
    assert base_spec_hash != spec_content_hash(
        "contract",
        {"z": 1, "a": "目标"},
        parent_hash="sha256:parent",
        revision=2,
    )
    assert base_spec_hash != spec_content_hash(
        "product_spec",
        {"z": 2, "a": "目标"},
        parent_hash="sha256:parent",
        revision=2,
    )
    assert base_spec_hash != spec_content_hash(
        "product_spec",
        {"z": 1, "a": "目标"},
        parent_hash=None,
        revision=2,
    )
    assert base_spec_hash != spec_content_hash(
        "product_spec",
        {"z": 1, "a": "目标"},
        parent_hash="sha256:parent",
        revision=3,
    )


def test_envelopes_and_decision_request_keep_their_documented_defaults():
    # 守护 R2：三种事件信封与决定请求的可选字段保持约定的默认值，读取旧事件或缺省构造时语义稳定
    run_event = _make_run_event(SkeletonEventType.RUN_CREATED, "evt_defaults")
    assert run_event.epoch is None
    assert run_event.execution_right is None
    assert run_event.command_id is None
    assert run_event.actor is None
    assert run_event.dispatch_number is None

    project_event = ProjectEvent(
        event_id="pevt_defaults",
        project_id="prj_1",
        type=ProjectEventType.PROJECT_REGISTERED,
        payload={},
        created_at="2026-10-28T00:00:00+00:00",
        position=1,
        stream="project:prj_1",
        stream_version=1,
        work_item_id=None,
        run_id=None,
        department=None,
    )
    assert project_event.epoch is None
    assert project_event.command_id is None
    assert project_event.actor is None

    catalog_event = CatalogEvent(
        event_id="cevt_defaults",
        type=CatalogEventType.CATALOG_REVISED,
        payload={},
        created_at="2026-10-28T00:00:00+00:00",
        position=1,
        stream="catalog:main",
        stream_version=1,
    )
    assert catalog_event.project_id is None
    assert catalog_event.work_item_id is None
    assert catalog_event.run_id is None
    assert catalog_event.department is None
    assert catalog_event.epoch is None
    assert catalog_event.command_id is None
    assert catalog_event.actor is None

    decision = DecisionRequest(
        decision_id="dec_defaults",
        stream="run:run_1",
        run_id="run_1",
        project_id="prj_1",
        work_item_id="wi_1",
        requested_at="2026-10-28T00:00:00+00:00",
        request={"kind": "product_input", "blocks": "run"},
    )
    assert decision.version == 1
    assert decision.status == "open"
    assert decision.answer is None
    assert decision.withdrawal is None


def test_event_summary_extracts_only_the_eight_non_empty_fields():
    # 守护 R2：事件摘要只提取白名单内的八个字段，过滤 None、空列表与空字典，保留其余非空取值并忽略白名单外的字段
    full_payload = {
        "kind": "change",
        "decision": "continue",
        "verdict": "release",
        "goal": "补齐内核事件测试",
        "question": "是否需要额外说明",
        "summary": "全部检查通过",
        "errors": ["第一条错误"],
        "human_action": {"step": "confirm"},
        "content_hash": "sha256:ignored",
        "extra_field": "ignored",
    }
    assert _make_run_event(SkeletonEventType.QA_SUBMITTED, payload=full_payload).summary() == {
        "kind": "change",
        "decision": "continue",
        "verdict": "release",
        "goal": "补齐内核事件测试",
        "question": "是否需要额外说明",
        "summary": "全部检查通过",
        "errors": ["第一条错误"],
        "human_action": {"step": "confirm"},
    }

    filtered_payload = {
        "kind": None,
        "decision": "",
        "verdict": "cannot_verify",
        "goal": None,
        "question": None,
        "summary": 0,
        "errors": [],
        "human_action": {},
    }
    assert _make_run_event(SkeletonEventType.QA_SUBMITTED, payload=filtered_payload).summary() == {
        "decision": "",
        "verdict": "cannot_verify",
        "summary": 0,
    }


def test_apply_decision_event_returns_changed_ids_and_records_all_fields_across_streams():
    # 守护 R1 与 R2：决定请求在事项流、项目流与目录流中处理请求、回答与撤销三类事件，返回变更的决定编号并隔离载荷副本，无关事件返回空值
    decisions: dict[str, DecisionRequest] = {}
    unrelated = _make_run_event(SkeletonEventType.RUN_CREATED, "evt_unrelated")
    assert apply_decision_event(decisions, unrelated) is None
    assert decisions == {}

    run_payload = {"kind": "product_input", "blocks": "run"}
    run_req = _make_run_event(
        SkeletonEventType.DECISION_REQUESTED,
        "evt_run_req_1",
        payload=run_payload,
        run_id="run_42",
        project_id="prj_42",
        work_item_id="wi_42",
        stream="run:run_42",
        created_at="2026-10-28T01:00:00+00:00",
    )
    assert apply_decision_event(decisions, run_req) == "evt_run_req_1"
    run_payload["kind"] = "mutated_outside"
    recorded_run = decisions["evt_run_req_1"]
    assert recorded_run == DecisionRequest(
        decision_id="evt_run_req_1",
        stream="run:run_42",
        run_id="run_42",
        project_id="prj_42",
        work_item_id="wi_42",
        requested_at="2026-10-28T01:00:00+00:00",
        request={"kind": "product_input", "blocks": "run"},
        version=1,
        status="open",
        answer=None,
        withdrawal=None,
    )

    run_ans = _make_run_event(
        SkeletonEventType.DECISION_ANSWERED,
        "evt_run_ans_1",
        position=2,
        stream="run:run_42",
        created_at="2026-10-28T01:05:00+00:00",
        actor="user_alice",
        command_id="cmd_ans_1",
        payload={
            "decision_id": "evt_run_req_1",
            "option": "approve",
            "note": "确认继续",
            "base_version": 1,
        },
    )
    assert apply_decision_event(decisions, run_ans) == "evt_run_req_1"
    assert recorded_run.status == "answered"
    assert recorded_run.answer == {
        "event_id": "evt_run_ans_1",
        "option": "approve",
        "note": "确认继续",
        "base_version": 1,
        "actor": "user_alice",
        "command_id": "cmd_ans_1",
        "answered_at": "2026-10-28T01:05:00+00:00",
    }

    run_req_2 = _make_run_event(
        SkeletonEventType.DECISION_REQUESTED,
        "evt_run_req_2",
        position=3,
        stream="run:run_42",
        created_at="2026-10-28T01:10:00+00:00",
        payload={"kind": "pause", "blocks": "run"},
    )
    assert apply_decision_event(decisions, run_req_2) == "evt_run_req_2"
    run_withdraw = _make_run_event(
        SkeletonEventType.DECISION_WITHDRAWN,
        "evt_run_wdr_2",
        position=4,
        stream="run:run_42",
        created_at="2026-10-28T01:12:00+00:00",
        payload={"decision_id": "evt_run_req_2", "reason": "事项状态变更"},
    )
    assert apply_decision_event(decisions, run_withdraw) == "evt_run_req_2"
    assert decisions["evt_run_req_2"].status == "withdrawn"
    assert decisions["evt_run_req_2"].withdrawal == {
        "event_id": "evt_run_wdr_2",
        "reason": "事项状态变更",
        "withdrawn_at": "2026-10-28T01:12:00+00:00",
    }

    project_decisions: dict[str, DecisionRequest] = {}
    project_payload = {"kind": "confirm_initial_prd", "blocks": "project", "work_item_id": "wi_from_payload"}
    proj_req = ProjectEvent(
        event_id="pevt_req_1",
        project_id="prj_9",
        type=ProjectEventType.PROJECT_DECISION_REQUESTED,
        payload=project_payload,
        created_at="2026-10-28T02:00:00+00:00",
        position=1,
        stream="project:prj_9",
        stream_version=1,
        work_item_id="wi_envelope_unused",
        run_id="run_envelope_unused",
        department=None,
    )
    assert apply_decision_event(project_decisions, proj_req) == "pevt_req_1"
    project_payload["kind"] = "tampered"
    assert project_decisions["pevt_req_1"] == DecisionRequest(
        decision_id="pevt_req_1",
        stream="project:prj_9",
        run_id=None,
        project_id="prj_9",
        work_item_id="wi_from_payload",
        requested_at="2026-10-28T02:00:00+00:00",
        request={"kind": "confirm_initial_prd", "blocks": "project", "work_item_id": "wi_from_payload"},
    )
    proj_ans = ProjectEvent(
        event_id="pevt_ans_1",
        project_id="prj_9",
        type=ProjectEventType.PROJECT_DECISION_ANSWERED,
        payload={"decision_id": "pevt_req_1", "option": "adopt", "note": "通过基线", "base_version": 1},
        created_at="2026-10-28T02:10:00+00:00",
        position=2,
        stream="project:prj_9",
        stream_version=2,
        work_item_id=None,
        run_id=None,
        department=None,
        command_id="cmd_proj_ans",
        actor="user_bob",
    )
    assert apply_decision_event(project_decisions, proj_ans) == "pevt_req_1"
    assert project_decisions["pevt_req_1"].status == "answered"
    assert project_decisions["pevt_req_1"].answer == {
        "event_id": "pevt_ans_1",
        "option": "adopt",
        "note": "通过基线",
        "base_version": 1,
        "actor": "user_bob",
        "command_id": "cmd_proj_ans",
        "answered_at": "2026-10-28T02:10:00+00:00",
    }

    catalog_decisions: dict[str, DecisionRequest] = {}
    catalog_payload = {"kind": "instance_upgrade", "blocks": "instance"}
    cat_req_1 = CatalogEvent(
        event_id="cevt_req_1",
        type=CatalogEventType.INSTANCE_UPGRADE_REQUESTED,
        payload=catalog_payload,
        created_at="2026-10-28T03:00:00+00:00",
        position=1,
        stream="catalog:main",
        stream_version=1,
        project_id="prj_unused",
        work_item_id="wi_unused",
        run_id="run_unused",
    )
    assert apply_decision_event(catalog_decisions, cat_req_1) == "cevt_req_1"
    catalog_payload["blocks"] = "tampered"
    assert catalog_decisions["cevt_req_1"] == DecisionRequest(
        decision_id="cevt_req_1",
        stream="catalog:main",
        run_id=None,
        project_id=None,
        work_item_id=None,
        requested_at="2026-10-28T03:00:00+00:00",
        request={"kind": "instance_upgrade", "blocks": "instance"},
    )
    cat_ans_1 = CatalogEvent(
        event_id="cevt_ans_1",
        type=CatalogEventType.INSTANCE_UPGRADE_ANSWERED,
        payload={"decision_id": "cevt_req_1", "option": "upgrade_now", "note": "立即升级", "base_version": 1},
        created_at="2026-10-28T03:05:00+00:00",
        position=2,
        stream="catalog:main",
        stream_version=2,
        command_id="cmd_cat_ans",
        actor="admin",
    )
    assert apply_decision_event(catalog_decisions, cat_ans_1) == "cevt_req_1"
    assert catalog_decisions["cevt_req_1"].status == "answered"
    assert catalog_decisions["cevt_req_1"].answer == {
        "event_id": "cevt_ans_1",
        "option": "upgrade_now",
        "note": "立即升级",
        "base_version": 1,
        "actor": "admin",
        "command_id": "cmd_cat_ans",
        "answered_at": "2026-10-28T03:05:00+00:00",
    }

    cat_req_2 = CatalogEvent(
        event_id="cevt_req_2",
        type=CatalogEventType.INSTANCE_UPGRADE_REQUESTED,
        payload={"kind": "instance_upgrade", "blocks": "instance"},
        created_at="2026-10-28T03:10:00+00:00",
        position=3,
        stream="catalog:main",
        stream_version=3,
    )
    cat_wdr_2 = CatalogEvent(
        event_id="cevt_wdr_2",
        type=CatalogEventType.INSTANCE_UPGRADE_WITHDRAWN,
        payload={"decision_id": "cevt_req_2", "reason": "取消升级"},
        created_at="2026-10-28T03:12:00+00:00",
        position=4,
        stream="catalog:main",
        stream_version=4,
    )
    assert apply_decision_event(catalog_decisions, cat_req_2) == "cevt_req_2"
    assert apply_decision_event(catalog_decisions, cat_wdr_2) == "cevt_req_2"
    assert catalog_decisions["cevt_req_2"].status == "withdrawn"
    assert catalog_decisions["cevt_req_2"].withdrawal == {
        "event_id": "cevt_wdr_2",
        "reason": "取消升级",
        "withdrawn_at": "2026-10-28T03:12:00+00:00",
    }


def test_accepted_filters_late_dispatches_per_stream_and_session():
    # 守护 R1：派发编号按流与会话独立维护单调水位，无编号事件与不小于当前水位的事件保留，低于当前水位的迟到事件过滤
    stream_a_high = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_sa_5", stream="run:a", session_id="ses_shared", dispatch_number=5
    )
    stream_b_low = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_sb_1", stream="run:b", session_id="ses_shared", dispatch_number=1
    )
    assert accepted([stream_a_high, stream_b_low]) == [stream_a_high, stream_b_low]

    ses_a_high = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_ses_a_5", stream="run:a", session_id="ses_a", dispatch_number=5
    )
    ses_b_low = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_ses_b_1", stream="run:a", session_id="ses_b", dispatch_number=1
    )
    assert accepted([ses_a_high, ses_b_low]) == [ses_a_high, ses_b_low]

    first_zero = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_zero_first", stream="run:zero", session_id="ses_0", dispatch_number=0
    )
    assert accepted([first_zero]) == [first_zero]

    e_none_1 = _make_run_event(
        SkeletonEventType.RUN_CREATED, "evt_none_1", stream="run:seq", session_id="ses_seq", dispatch_number=None
    )
    e_zero = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_0", stream="run:seq", session_id="ses_seq", dispatch_number=0
    )
    e_one_a = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_1a", stream="run:seq", session_id="ses_seq", dispatch_number=1
    )
    e_one_b = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_1b", stream="run:seq", session_id="ses_seq", dispatch_number=1
    )
    e_zero_late = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_0_late", stream="run:seq", session_id="ses_seq", dispatch_number=0
    )
    e_two = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_2", stream="run:seq", session_id="ses_seq", dispatch_number=2
    )
    e_one_late = _make_run_event(
        SkeletonEventType.MODEL_REQUESTED, "evt_1_late", stream="run:seq", session_id="ses_seq", dispatch_number=1
    )
    e_none_2 = _make_run_event(
        SkeletonEventType.RUN_PAUSED, "evt_none_2", stream="run:seq", session_id="ses_seq", dispatch_number=None
    )
    assert accepted([e_none_1, e_zero, e_one_a, e_one_b, e_zero_late, e_two, e_one_late, e_none_2]) == [
        e_none_1,
        e_zero,
        e_one_a,
        e_one_b,
        e_two,
        e_none_2,
    ]

    req = _make_run_event(
        SkeletonEventType.DECISION_REQUESTED,
        "evt_dec_open",
        stream="run:dec",
        session_id="ses_dec",
        dispatch_number=1,
        payload={"kind": "product_input", "blocks": "run"},
    )
    acquired_next = _make_run_event(
        SkeletonEventType.DISPATCH_NUMBER_ACQUIRED,
        "evt_disp_2",
        position=2,
        stream="run:dec",
        session_id="ses_dec",
        dispatch_number=2,
    )
    late_answer = _make_run_event(
        SkeletonEventType.DECISION_ANSWERED,
        "evt_dec_late_ans",
        position=3,
        stream="run:dec",
        session_id="ses_dec",
        dispatch_number=1,
        payload={"decision_id": "evt_dec_open", "option": "continue", "note": "", "base_version": 1},
    )
    replayed = replay_decisions([req, acquired_next, late_answer])
    assert replayed["evt_dec_open"].status == "open"
    assert replayed["evt_dec_open"].answer is None


def test_stream_handler_protocol_declares_the_five_methods_and_signatures():
    # 守护 R2：流处理者协议声明五个固定方法与各自的参数列表，供写入口统一调用各条流的投影实现
    expected = {
        "empty": ("self",),
        "load": ("self", "saved"),
        "dump": ("self", "state"),
        "fold": ("self", "state", "event"),
        "replay": ("self", "stream", "events"),
    }
    declared = {
        name: tuple(inspect.signature(getattr(StreamHandler, name)).parameters)
        for name in expected
        if hasattr(StreamHandler, name)
    }
    assert declared == expected

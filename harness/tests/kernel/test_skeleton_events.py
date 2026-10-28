# 骨架事件的登记表（S5a，工单 #828）：内核事件模块给出内核写入或读取的事件种类；应用事件的种类由应用
# 自己登记，应用登记一种新的种类不改内核文件（设计说明第 5.4 节第 1 条）。
#
# 这张表与设计说明第 7 节逐项对照，含 S1b 的成果失效；第 4 节 2026-10-25 第 1 条把「模型请求」改为骨架事件
# （模型步数按请求一条条数，最小投影读它），所以它也在表里：第 7 节的表把它列在应用事件里，按第 4 节更正。
#
# 读仓库里的静态声明与内存中的登记表，不开数据库、不用子进程、不用网络，属于单元层。
# 守第 13 节的 R2（第二环的合同：骨架事件只增，种类与设计说明第 7 节一致）。

import pytest

from harness.kernel_events import (
    SKELETON_CATALOG_EVENTS,
    SKELETON_EVENTS,
    SKELETON_PROJECT_EVENTS,
    SKELETON_RUN_EVENTS,
    CatalogEvent,
    CatalogEventType,
    Event,
    ProjectEvent,
    ProjectEventType,
    SkeletonEventType,
    application_event_types,
    event_type_owner,
    json_dumps,
    register_application_event_types,
    replay_decisions,
)

# 设计说明第 7 节「骨架事件」一列，加第 4 节 2026-10-25 第 1 条的「模型请求」
DESIGN_SKELETON_RUN_EVENTS = frozenset({
    "run_created", "run_done", "run_paused", "run_failed", "run_resumed", "run_continued",
    "department_activated", "activation_finished",
    "tool_called", "tool_started",
    "model_requested",
    "artifact_invalidated", "proposal_submitted", "proposal_rejected",
    "spec_accepted", "spec_superseded", "contract_accepted", "delivery_accepted", "qa_submitted",
    "structure_accepted", "baseline_review_accepted", "artifact_accepted", "product_decision_accepted",
    "decision_requested", "decision_answered", "decision_withdrawn",
})


def _kinds(declaration: type) -> frozenset[str]:
    return frozenset({value for name, value in vars(declaration).items()
                      if not name.startswith("_") and isinstance(value, str)})


def test_the_skeleton_run_events_match_the_design_table():
    # 登记表与设计说明第 7 节一致：多出的种类没有位置，缺的种类内核的读取会漏掉
    assert SKELETON_RUN_EVENTS == DESIGN_SKELETON_RUN_EVENTS, (
        f"登记表多出 {sorted(SKELETON_RUN_EVENTS - DESIGN_SKELETON_RUN_EVENTS)}，"
        f"缺少 {sorted(DESIGN_SKELETON_RUN_EVENTS - SKELETON_RUN_EVENTS)}"
    )


def test_the_skeleton_declaration_is_the_registry():
    # 种类声明（SkeletonEventType）与登记表是同一份东西：两处不许各写一份
    assert _kinds(SkeletonEventType) == SKELETON_RUN_EVENTS


def test_the_project_and_catalog_streams_are_entirely_skeleton():
    # 项目流与目录流的事件全部是骨架事件（设计说明第 7 节）：它们是长期事实，跨版本保存
    assert _kinds(ProjectEventType) == SKELETON_PROJECT_EVENTS
    assert _kinds(CatalogEventType) == SKELETON_CATALOG_EVENTS
    assert SKELETON_PROJECT_EVENTS <= SKELETON_EVENTS
    assert SKELETON_CATALOG_EVENTS <= SKELETON_EVENTS
    assert SKELETON_PROJECT_EVENTS & SKELETON_RUN_EVENTS == frozenset()
    assert SKELETON_CATALOG_EVENTS & SKELETON_RUN_EVENTS == frozenset()


def test_artifact_invalidation_is_a_skeleton_event():
    # S1b（工单 #858）的成果失效是骨架事件：失效是记下来的事实，最小投影只折叠这一条
    assert SkeletonEventType.ARTIFACT_INVALIDATED == "artifact_invalidated"
    assert "artifact_invalidated" in SKELETON_EVENTS


def test_the_model_request_is_a_skeleton_event():
    # 最小投影按「模型请求」数模型步数（设计说明第 4 节 2026-10-25 第 1 条），所以它只加字段、不删改
    assert "model_requested" in SKELETON_EVENTS


def test_an_application_registers_its_own_event_kinds():
    # 应用登记一种新的应用事件：登记表认得它，骨架事件的登记表不变（第 5.4 节第 1 条）
    before = frozenset(SKELETON_EVENTS)
    novel = "task_pool_task_published"
    assert event_type_owner(novel) is None
    register_application_event_types("测试里的任务池路由", [novel])
    assert application_event_types()[novel] == "测试里的任务池路由"
    assert event_type_owner(novel) == "测试里的任务池路由"
    assert event_type_owner("run_created") == "skeleton"
    assert frozenset(SKELETON_EVENTS) == before


def test_a_skeleton_event_cannot_be_registered_by_an_application():
    # 骨架事件的种类由内核给出：应用登记它们会让内核的种类随应用变
    with pytest.raises(ValueError):
        register_application_event_types("测试里的任务池路由", ["run_created"])


def test_a_kind_belongs_to_the_application_that_registered_it_first():
    # 同一个种类不能由两个应用各登记一次，登记也要写明是哪个应用
    register_application_event_types("路由甲", ["probe_kind_a"])
    with pytest.raises(ValueError):
        register_application_event_types("路由乙", ["probe_kind_a"])
    with pytest.raises(ValueError):
        register_application_event_types("  ", ["probe_kind_b"])


def _run_event(type_: str, payload: dict, event_id: str, position: int = 1, **overrides) -> Event:
    fields = dict(
        event_id=event_id, run_id="run_probe", type=type_, role=None, parent_event_id=None,
        state_before="running", state_after="running", payload=payload, artifact_hashes=[], session_id=None,
        provider=None, model=None, context_digest=None, stop_reason=None, error=None,
        created_at="2026-10-28T00:00:00+00:00", position=position, stream="run:run_probe", stream_version=position,
        project_id=None, work_item_id=None, department=None,
    )
    fields.update(overrides)
    return Event(**fields)


def test_the_envelope_hands_back_its_fields_and_summarizes_the_payload():
    # R2：信封的字段只增，序列化把它们原样交出来；摘要只取载荷里固定的那几样，没有的不写空
    event = _run_event("run_created", {"kind": "change", "goal": "逐行文本处理工具", "question": None}, "evt_1")
    assert event.to_dict()["stream_version"] == 1
    assert event.to_dict()["type"] == "run_created"
    assert event.summary() == {"kind": "change", "goal": "逐行文本处理工具"}
    project = ProjectEvent(event_id="pevt_1", project_id="proj_1", type=ProjectEventType.PROJECT_REGISTERED,
                           payload={"name": "项目"}, created_at="2026-10-28T00:00:00+00:00", position=2,
                           stream="project:proj_1", stream_version=1, work_item_id=None, run_id=None,
                           department=None)
    assert project.to_dict()["project_id"] == "proj_1"
    catalog = CatalogEvent(event_id="cevt_1", type=CatalogEventType.CATALOG_REVISED, payload={},
                           created_at="2026-10-28T00:00:00+00:00", position=3, stream="catalog:main",
                           stream_version=1)
    assert catalog.to_dict()["stream"] == "catalog:main"


def test_json_dumps_writes_tuples_as_arrays_and_refuses_what_it_cannot_write():
    # 载荷里的元组按数组写进日志：写进去什么，重放读回来就是什么；写不下的在这里失败，不留下半条事件
    assert json_dumps({"paths": ("a", "b")}) == '{"paths":["a","b"]}'
    with pytest.raises(TypeError):
        json_dumps({"bad": object()})


def test_a_decision_request_is_folded_from_the_events_of_its_stream():
    # R1：决定请求由请求、回答与撤销三种事件折叠而成，重放出同样的状态；三个流各走一次
    request = _run_event(SkeletonEventType.DECISION_REQUESTED, {"kind": "product_input", "blocks": "run"}, "evt_q")
    answered = _run_event(SkeletonEventType.DECISION_ANSWERED, {
        "decision_id": "evt_q", "option": "continue", "note": "", "base_version": 1}, "evt_a", position=2)
    decisions = replay_decisions([request, answered])
    assert list(decisions) == ["evt_q"]
    assert decisions["evt_q"].status == "answered"
    assert decisions["evt_q"].answer["option"] == "continue"
    assert (decisions["evt_q"].kind, decisions["evt_q"].blocks) == ("product_input", "run")

    project_request = ProjectEvent(
        event_id="pevt_q", project_id="proj_1", type=ProjectEventType.PROJECT_DECISION_REQUESTED,
        payload={"kind": "confirm_initial_prd", "blocks": "project", "work_item_id": "wi_1"},
        created_at="2026-10-28T00:00:00+00:00", position=1, stream="project:proj_1", stream_version=1,
        work_item_id=None, run_id=None, department=None)
    project_withdrawn = ProjectEvent(
        event_id="pevt_w", project_id="proj_1", type=ProjectEventType.PROJECT_DECISION_WITHDRAWN,
        payload={"decision_id": "pevt_q", "reason": "用户改了要求"}, created_at="2026-10-28T00:00:00+00:00",
        position=2, stream="project:proj_1", stream_version=2, work_item_id=None, run_id=None, department=None)
    project_decisions = replay_decisions([project_request, project_withdrawn])
    assert project_decisions["pevt_q"].status == "withdrawn"
    assert project_decisions["pevt_q"].withdrawal["reason"] == "用户改了要求"

    upgrade = CatalogEvent(event_id="cevt_q", type=CatalogEventType.INSTANCE_UPGRADE_REQUESTED,
                          payload={"kind": "instance_upgrade", "blocks": "instance"},
                          created_at="2026-10-28T00:00:00+00:00", position=1, stream="catalog:main",
                          stream_version=1)
    catalog_decisions = replay_decisions([upgrade])
    assert catalog_decisions["cevt_q"].status == "open"
    assert catalog_decisions["cevt_q"].run_id is None and catalog_decisions["cevt_q"].project_id is None

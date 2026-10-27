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
    CatalogEventType,
    ProjectEventType,
    SkeletonEventType,
    application_event_types,
    event_type_owner,
    register_application_event_types,
)

# 设计说明第 7 节「骨架事件」一列，加第 4 节 2026-10-25 第 1 条的「模型请求」
DESIGN_SKELETON_RUN_EVENTS = frozenset({
    "run_created", "run_done", "run_paused", "run_failed", "run_resumed", "run_continued",
    "department_activated", "activation_finished",
    "tool_called", "tool_started",
    "model_requested",
    "artifact_invalidated", "proposal_submitted", "proposal_rejected",
    "spec_accepted", "spec_superseded", "contract_accepted", "delivery_accepted", "qa_submitted",
    "structure_accepted", "baseline_review_accepted", "product_decision_accepted",
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

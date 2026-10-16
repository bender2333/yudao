# 每种事件都声明属于项目流或 run 流（ADR-0019，工单 #126）。项目流与目录事件跨 Yudao 版本保存，
# run 流跟随应用版本。分类的注册处是 harness/streams.py 的三份字面值清单，它们不从 models.py 派生：
# 派生会把新增的种类自动归为一类，声明就失去作用。models.py 中的事件种类与这里的清单由测试互相比对，
# 任一侧多出的种类都使测试失败。

from harness.app.payloads import PAYLOADS
from harness.models import CatalogEventType, EventType, ProjectEventType
from harness.streams import (
    CATALOG_EVENT_TYPES, DECLARED_EVENT_TYPES, PROJECT_EVENT_TYPES, RUN_EVENT_TYPES, RUN_EVENT_VERSION,
)

def _kinds(cls) -> frozenset[str]:
    return frozenset({value for name, value in vars(cls).items() if not name.startswith("_")})

def test_models_event_kinds_match_the_run_declaration():
    # run 流的声明与 models.EventType 的种类完全相同：多出的种类没有声明分类，清单中缺的种类已经不存在
    assert _kinds(EventType) == RUN_EVENT_TYPES, (
        f"run 流的声明与 models.EventType 不一致：没有声明的 {sorted(_kinds(EventType) - RUN_EVENT_TYPES)}，"
        f"清单中已不存在的 {sorted(RUN_EVENT_TYPES - _kinds(EventType))}"
    )

def test_models_event_kinds_match_the_project_declaration():
    assert _kinds(ProjectEventType) == PROJECT_EVENT_TYPES, (
        f"项目流的声明与 models.ProjectEventType 不一致："
        f"没有声明的 {sorted(_kinds(ProjectEventType) - PROJECT_EVENT_TYPES)}，"
        f"清单中已不存在的 {sorted(PROJECT_EVENT_TYPES - _kinds(ProjectEventType))}"
    )

def test_models_event_kinds_match_the_catalog_declaration():
    assert _kinds(CatalogEventType) == CATALOG_EVENT_TYPES, (
        f"目录流的声明与 models.CatalogEventType 不一致："
        f"没有声明的 {sorted(_kinds(CatalogEventType) - CATALOG_EVENT_TYPES)}，"
        f"清单中已不存在的 {sorted(CATALOG_EVENT_TYPES - _kinds(CatalogEventType))}"
    )

def test_every_event_kind_declares_its_stream():
    # 注册处（payloads.PAYLOADS）声明的每种事件都出现在某一流的清单中
    assert set(PAYLOADS) - DECLARED_EVENT_TYPES == set()

def test_stream_lists_partition_the_registered_kinds():
    assert RUN_EVENT_TYPES | PROJECT_EVENT_TYPES | CATALOG_EVENT_TYPES == DECLARED_EVENT_TYPES
    assert RUN_EVENT_TYPES & PROJECT_EVENT_TYPES == frozenset()
    assert RUN_EVENT_TYPES & CATALOG_EVENT_TYPES == frozenset()
    assert PROJECT_EVENT_TYPES & CATALOG_EVENT_TYPES == frozenset()

def test_project_stream_records_the_projects_long_lived_facts():
    # 项目流是项目的长期事实：项目、当前 PRD 与采纳成果、事项的存在与最终结果、项目部门设置
    assert {"project_registered", "work_item_created", "deliverable_adopted", "adoption_held",
            "department_prompt_configured", "material_recorded"} <= PROJECT_EVENT_TYPES

def test_run_stream_records_the_course_of_a_work_item():
    # 事项的进行过程属于 run 流
    assert {"run_created", "department_activated", "model_requested", "proposal_submitted", "qa_submitted",
            "run_done", "run_failed", "decision_requested"} <= RUN_EVENT_TYPES
    assert "work_item_created" not in RUN_EVENT_TYPES

def test_the_run_event_version_is_a_positive_integer():
    assert isinstance(RUN_EVENT_VERSION, int) and RUN_EVENT_VERSION >= 1

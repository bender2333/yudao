# 每种事件都声明属于项目流或 run 流（ADR-0019，工单 #126）。项目流与目录事件跨 Yudao 版本保存，
# run 流跟随应用版本。分类的注册处是 harness/streams.py 的三份字面值清单，它们不从 models.py 派生：
# 派生会把新增的种类自动归为一类，声明就失去作用。models.py 中的事件种类与这里的清单由测试互相比对，
# 任一侧多出的种类都使测试失败。
#
# 事件种类与中文说明的对应同样由这里核对（工单 #664）：少了说明，事件流播到这一条就断掉。

import string

from harness.app.labels import _LABELS
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


def test_every_event_kind_has_a_chinese_label():
    # 三份事件种类清单里的每一种都要有中文说明（工单 #664）：
    # 少了说明，事件流播到这一条就断掉，客户端每秒重连一次，永远过不去
    missing = sorted(DECLARED_EVENT_TYPES - set(_LABELS))
    assert missing == [], f"没有中文说明的事件种类：{missing}"


def test_every_label_template_only_uses_fields_of_its_payload():
    # 说明里出现的字段必须在那条事件的载荷里：说明里不出现空白的占位（工单 #319）
    for event_type, template in _LABELS.items():
        payload = PAYLOADS.get(event_type)
        assert payload is not None, f"{event_type} 没有登记载荷类型"
        # 载荷有多种形态时（工具调用有两种结果），字段取并集；
        # 字段名带别名时（transition 的 from）按写入事件的那个键算
        members = getattr(payload, "__args__", (payload,))
        fields = set()
        for member in members:
            for name, field in member.model_fields.items():
                fields.add(field.alias or name)
        used = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        missing = sorted(used - fields)
        assert missing == [], f"{event_type} 的说明用了载荷里没有的字段：{missing}"

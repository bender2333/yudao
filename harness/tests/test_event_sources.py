# 事件来源表（工单 #396）：每种事件一条来源，来源种类在封闭清单里；按字段的覆盖只落在载荷里真实存在的测量
# 字段与检查回执上。表在定义里（harness/definitions/event_sources.json），事件种类的清单在应用层
# （harness/app/payloads.py）：内核不能导入应用层，两边的对齐由这条测试核对。登记为单元层。

import pytest

from harness.app.payloads import PAYLOADS
from harness.definitions import DEFINITIONS

# 来源种类的封闭清单（设计说明第 5.2 节，与客户端画面合同的 SOURCES 一致）
SOURCES = {"rule", "decision_model", "role_statement", "host_measurement", "user"}


def test_every_event_type_has_a_source_row():
    # 守 R2（事件对象的合同）：能力清单里的每种事件都能给出 source，表里也没有多出来的行
    assert set(DEFINITIONS.event_sources) == set(PAYLOADS)
    assert all(entry.source in SOURCES for entry in DEFINITIONS.event_sources.values())


def test_field_overrides_name_real_fields_and_come_from_the_host():
    # 守 R2：按字段的覆盖指向这个种类真实的载荷字段，取值都是主机测量（设计说明第 5.2 节）
    for name, entry in DEFINITIONS.event_sources.items():
        fields = getattr(PAYLOADS[name], "model_fields", {})
        for field, kind in entry.fields.items():
            assert field in fields, (name, field)
            assert kind == "host_measurement", (name, field)


def test_an_event_type_without_a_row_raises():
    # 守 R2：读来源时不留回退取值——表里没有这种事件就报错，缺行不会被静默当成某一种来源
    with pytest.raises(ValueError):
        DEFINITIONS.event_source("no_such_event")


def test_measurements_and_check_receipts_are_marked_as_host_measurement():
    # 守 R3（画面诚实性 H4 与服务端的来源口径）：已用时间、已用次数与步数、检查回执的结果来源是主机测量，
    # 这些事件的主要事实则是另一回事——激活的结束由规则的判定给出，质检的结论由角色的陈述给出
    finished = DEFINITIONS.event_sources["activation_finished"]
    assert finished.source == "rule"
    assert {"elapsed_ms", "model_steps", "activations"} <= set(finished.fields)
    assert DEFINITIONS.event_sources["qa_submitted"].source == "role_statement"
    assert DEFINITIONS.event_sources["qa_submitted"].fields["checks"] == "host_measurement"
    assert DEFINITIONS.event_sources["tool_called"].source == "host_measurement"
    assert DEFINITIONS.event_sources["user_input_received"].source == "user"
    assert DEFINITIONS.event_sources["model_message"].source == "role_statement"

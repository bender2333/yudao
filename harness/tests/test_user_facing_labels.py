# 用户看到的说明文字（工单 #303）：等待说明、事件说明、流转内容、停止原因的处理说明都不出现
# 英文机器标识；阶段与停止原因的中文名必须与状态机和定义同一份取值。

import re
import string
import typing

import pytest

from harness.app.labels import PHASE_NAMES, STOP_REASON_NAMES, _LABELS, event_label, phase_name, stop_reason_name
from harness.app.payloads import PAYLOADS
from harness.definitions import DEFINITIONS
from harness.models import (DEPARTMENT_LABELS, PHASES, TERMINAL_PHASES, EventType, ProjectEventType,
                           stop_reason_name as core_name, waiting_reason_for)
from harness.tests.project_stream_fields import load_manifest

LATIN = re.compile(r"[A-Za-z]")
# 产品名在顶栏与关于页本来就显示，出现在说明里不算英文内部提示；检查前先去掉它
BRAND = re.compile(r"Yudao")


def _without_brand(text: str) -> str:
    return BRAND.sub("", text)


def _human_action_stop_reasons() -> list[str]:
    return [reason for reason, definition in DEFINITIONS.stop_reasons.items()
            if definition.human_action is not None]


def test_phase_names_cover_the_state_machine_exactly():
    assert set(PHASE_NAMES) == set(PHASES)
    assert all(LATIN.search(name) is None for name in PHASE_NAMES.values())


def test_stop_reason_names_cover_the_definitions_exactly():
    assert set(STOP_REASON_NAMES) == set(DEFINITIONS.stop_reasons)
    assert all(LATIN.search(_without_brand(name)) is None for name in STOP_REASON_NAMES.values())
    assert core_name("released") == stop_reason_name("released")


def test_unknown_values_are_shown_verbatim_instead_of_being_guessed():
    assert phase_name("NOT_A_PHASE") == "NOT_A_PHASE"
    assert stop_reason_name("not_a_reason") == "not_a_reason"
    assert stop_reason_name(None) == ""


@pytest.mark.parametrize("phase", PHASES)
def test_waiting_reason_is_written_in_chinese_for_every_phase(phase):
    reason = waiting_reason_for(phase, "cancelled")
    if phase == "DONE":
        assert reason is None
        return
    assert reason is not None
    assert LATIN.search(reason) is None, reason


@pytest.mark.parametrize("phase", sorted(TERMINAL_PHASES - {"DONE"}))
def test_terminal_waiting_reason_names_the_stop_reason_in_chinese(phase):
    reason = waiting_reason_for(phase, "provider_timeout")
    assert reason is not None and "模型服务请求超时" in reason
    assert LATIN.search(reason) is None, reason


def test_department_labels_cover_the_organizations_departments():
    assert set(DEPARTMENT_LABELS) == set(DEFINITIONS.departments)


@pytest.mark.parametrize("reason", _human_action_stop_reasons())
def test_human_action_text_is_written_in_chinese(reason):
    action = DEFINITIONS.stop_reasons[reason].human_action
    assert action is not None
    assert LATIN.search(_without_brand(action)) is None, f"{reason}: {action}"


def test_transition_and_stop_events_name_phases_and_stop_reasons_in_chinese():
    assert event_label(EventType.TRANSITION, {"from": "PRODUCT_SPEC", "to": "ENGINEERING"}) == \
        "运行状态从 产品处理中 变为 工程处理中"
    assert event_label(EventType.RUN_DONE, {"stop_reason": "released"}) == "运行结束：已完成并放行"
    assert event_label(EventType.RUN_PAUSED, {"stop_reason": "max_cycles"}) == \
        "运行暂停，等待用户处理：循环次数已达上限"
    assert event_label(EventType.RUN_CONTINUED, {"resumed_at_phase": "QUALITY"}) == \
        "运行从暂停位置继续：质检处理中"


def _placeholders(template: str) -> set[str]:
    return {field for _text, field, _spec, _conv in string.Formatter().parse(template) if field}


def _payload_fields(kind: str) -> set[str]:
    # 一个事件种类的载荷字段：联合载荷取各成员字段的并集，别名是载荷里的键（工单 #319）
    fields: set[str] = set()
    for model in typing.get_args(PAYLOADS[kind]) or (PAYLOADS[kind],):
        for field, info in model.model_fields.items():
            fields.add(info.alias or field)
    return fields


@pytest.mark.parametrize("kind", sorted(_LABELS))
def test_every_label_placeholder_is_a_field_of_that_events_payload(kind):
    # 说明里的占位必须能由该事件的载荷填出，否则用户看到的是空白的占位（工单 #319）
    manifest = load_manifest()
    fields = set(manifest["fields"][kind]) if kind in manifest["fields"] else _payload_fields(kind)
    assert _placeholders(_LABELS[kind]) <= fields


@pytest.mark.parametrize("kind", sorted(_LABELS))
def test_every_label_renders_without_a_blank_placeholder(kind):
    # 各字段按字段名填充以后，说明里不留下没有填出的占位（工单 #319）
    payload = {field: field for field in _payload_fields(kind)}
    label = event_label(kind, payload)
    assert "{" not in label and "}" not in label, label
    assert "  " not in label and "（）" not in label, label
    # 部门的中文名后面不再重复写一个「部门」两个字（工单 #319）
    assert "部门部门" not in label, label


def test_adoption_line_shows_the_adopted_result_instead_of_a_missing_version():
    # 工单 #319：采纳交付物的那一行原来按第几版写，而载荷里没有版本字段，用户看到空白的括号
    payload = {field: field for field in _payload_fields(ProjectEventType.DELIVERABLE_ADOPTED)}
    payload["summary"] = "把首页换成公司动态"
    assert event_label(ProjectEventType.DELIVERABLE_ADOPTED, payload) == "采纳了交付物：把首页换成公司动态"


def test_collaboration_line_names_both_departments_in_chinese():
    payload = {"requester": "product", "recipient": "engineering", "question": "接口定不下来"}
    assert event_label(EventType.COLLABORATION_REQUESTED, payload) == "产品部门向工程部门提出请求：接口定不下来"
# 用户看到的说明文字（工单 #303）：等待说明、事件说明、流转内容、停止原因的处理说明都不出现
# 英文机器标识；阶段与停止原因的中文名必须与状态机和定义同一份取值。

import re

import pytest

from harness.app.labels import PHASE_NAMES, STOP_REASON_NAMES, event_label, phase_name, stop_reason_name
from harness.definitions import DEFINITIONS
from harness.models import (DEPARTMENT_LABELS, PHASES, TERMINAL_PHASES, EventType, stop_reason_name as core_name,
                           waiting_reason_for)

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
    assert event_label(EventType.TRANSITION,
                       {"from_phase": "PRODUCT_SPEC", "to_phase": "ENGINEERING"}) == \
        "运行状态从 产品处理中 变为 工程处理中"
    assert event_label(EventType.RUN_DONE, {"stop_reason": "released"}) == "运行结束：已完成并放行"
    assert event_label(EventType.RUN_PAUSED, {"stop_reason": "max_cycles"}) == \
        "运行暂停，等待用户处理：循环次数已达上限"
    assert event_label(EventType.RUN_CONTINUED, {"resumed_at_phase": "QUALITY"}) == \
        "运行从暂停位置继续：质检处理中"
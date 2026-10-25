# 用户看到的说明文字（工单 #303）：run 状态与停止原因的中文名必须与控制核心和定义同一份取值，
# 说明文字里的内容与中文名一致。
# 页面直接显示原始标识与原文，不再要求翻译（决策记录 2026-10-22，工单 #717），
# 因此这里不再检查说明文字里有没有英文内部标识。

import string
import typing

import pytest

from harness.app.labels import (DECISION_KIND_NAMES, STATUS_NAMES, STOP_REASON_NAMES, _LABELS, decision_kind_name,
                                event_label, status_name, stop_reason_name)
from harness.app.payloads import PAYLOADS
from harness.definitions import DEFINITIONS
from harness.models import (
    RUN_STATUSES,
    TERMINAL_STATUSES,
    EventType,
    stop_reason_name as core_name,
    waiting_reason_for,
)
from harness.tests.project_stream_fields import load_manifest

def test_status_names_cover_the_run_statuses_exactly():
    assert set(STATUS_NAMES) == set(RUN_STATUSES)


def test_stop_reason_names_cover_the_definitions_exactly():
    assert set(STOP_REASON_NAMES) == set(DEFINITIONS.stop_reasons)
    assert core_name("released") == stop_reason_name("released")


def test_unknown_values_are_shown_verbatim_instead_of_being_guessed():
    assert status_name("NOT_A_STATUS") == "NOT_A_STATUS"
    assert stop_reason_name("not_a_reason") == "not_a_reason"
    assert stop_reason_name(None) == ""


@pytest.mark.parametrize("status", RUN_STATUSES)
def test_every_status_has_a_waiting_reason(status):
    reason = waiting_reason_for(status, "cancelled")
    if status in {"done", "running"}:
        # 完成没有等待原因；进行中也没有——部门进行到哪一步不记（进度从成果推算，工单 #556）
        assert reason is None
        return
    assert reason is not None


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES - {"done"}))
def test_terminal_waiting_reason_names_the_stop_reason_in_chinese(status):
    reason = waiting_reason_for(status, "provider_timeout")
    assert reason is not None and "模型服务请求超时" in reason


def test_stop_events_name_stop_reasons_in_chinese():
    assert event_label(EventType.RUN_DONE, {"stop_reason": "released"}) == "运行结束：已完成并放行"
    assert event_label(EventType.RUN_PAUSED, {"stop_reason": "max_cycles"}) == \
        "运行暂停，等待用户处理：循环次数已达上限"
    assert event_label(EventType.RUN_CONTINUED, {"decision_id": "d1"}) == "运行从暂停位置继续"

def test_decision_kind_names_cover_all_decision_kinds():
    from harness.decisions import DECISION_KINDS
    assert set(DECISION_KIND_NAMES) == set(DECISION_KINDS)
    assert decision_kind_name("not_a_kind") == "not_a_kind"


# 决定请求事件的载荷从没有 question 字段（工单 #301）：说明用 description，正文不出现英文种类名
@pytest.mark.parametrize("kind", ["model_unavailable", "definitions_changed",
                                  "no_tool_call", "workspace_unrepresentable"])
def test_decision_requested_names_the_kind_in_chinese_with_description(kind):
    text = event_label(EventType.DECISION_REQUESTED, {"kind": kind, "description": "需要人工处理"})
    assert DECISION_KIND_NAMES[kind] in text
    assert "需要人工处理" in text


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



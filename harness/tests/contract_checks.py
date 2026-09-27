from collections.abc import Iterable
from typing import Any

from pydantic import TypeAdapter

from harness.app.payloads import PAYLOADS

# 核对控制核心写入的事件符合应用层合同中的载荷类型：事件种类必须有载荷类型，载荷不能缺少或多出字段

_ADAPTERS: dict[str, TypeAdapter[Any]] = {}


def assert_payloads_follow_contract(events: Iterable[Any]) -> None:
    for event in events:
        assert event.type in PAYLOADS, f"event type {event.type} has no payload type in harness/app/payloads.py"
        if event.type not in _ADAPTERS:
            _ADAPTERS[event.type] = TypeAdapter(PAYLOADS[event.type])
        _ADAPTERS[event.type].validate_python(event.payload)

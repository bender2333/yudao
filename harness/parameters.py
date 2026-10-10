# 参数的现值与修改历史：由目录流中的参数事件折叠而成。参数是全局的，事件写进目录流（跨版本保存的长期事实）。
# 定义里的条目是初始值与取值界限，现值是事件日志折叠的结果；run 创建时冻结参数版本，运行中不再跟随。
# 设计说明第 3、5 节。

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .definitions import DEFINITIONS
from .models import CatalogEvent, CatalogEventType, ProjectEventType, json_dumps


@dataclass(frozen=True)
class ParameterChange:
    # 一次参数修改：谁在什么时候把哪个参数从什么改成什么、理由是什么，以及修改以后的参数版本
    name: str
    old_value: Any
    new_value: Any
    reason: str
    modified_by: str
    parameters_version: str
    event_id: str
    created_at: str
    stream_version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "modified_by": self.modified_by,
            "parameters_version": self.parameters_version,
            "event_id": self.event_id,
            "created_at": self.created_at,
            "stream_version": self.stream_version,
        }


class ParameterOutOfBoundsError(ValueError):
    """新值超出该参数在定义里的取值界限，或取值类型不对；`bounds` 是这次核对用的界限。"""

    def __init__(self, message: str, *, bounds: Any) -> None:
        super().__init__(message)
        self.bounds = bounds


class ParameterNotFoundError(KeyError):
    """没有这个参数：名字不在规则登记里，或不是 kind 为 parameter 的条目。"""


def fold_parameters(events: list[CatalogEvent]) -> tuple[dict[str, Any], list[ParameterChange]]:
    # 按事件顺序折叠参数事件：现值是最后一次修改的新值，历史是全部修改记录
    values = initial_values()
    history: list[ParameterChange] = []
    for event in events:
        if event.type != CatalogEventType.PARAMETER_SET:
            continue
        payload = event.payload
        values[payload["name"]] = payload["new_value"]
        history.append(ParameterChange(
            name=payload["name"], old_value=payload["old_value"], new_value=payload["new_value"],
            reason=payload["reason"], modified_by=payload["modified_by"],
            parameters_version=payload["parameters_version"], event_id=event.event_id,
            created_at=event.created_at, stream_version=event.stream_version,
        ))
    return values, history


def parameters_version(values: dict[str, Any]) -> str:
    # 参数现值的版本摘要：全部参数条目当前取值的规范化 JSON 的 sha256；内容相同则版本相同
    text = json_dumps({name: values[name] for name in sorted(values)})
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def initial_values() -> dict[str, Any]:
    # 定义里的参数初始值：没有任何参数事件时的现值
    return {name: rule.value for name, rule in DEFINITIONS.rules.items() if rule.kind == "parameter"}


def initial_version() -> str:
    # 定义里的参数初始版本：事件序列基线按它规整
    return parameters_version(initial_values())


def current_values(store: Any) -> dict[str, Any]:
    # 参数现值：目录流事件折叠的结果，没有修改过时是定义的初始值
    from .event_store import catalog_stream

    values, _ = fold_parameters([event for event in store.stream_events(catalog_stream())
                                 if isinstance(event, CatalogEvent)])
    return values


def current_version(store: Any) -> str:
    # 参数现值的版本摘要
    return parameters_version(current_values(store))


def history(store: Any) -> list[ParameterChange]:
    # 参数修改历史：按事件顺序
    from .event_store import catalog_stream

    _, changes = fold_parameters([event for event in store.stream_events(catalog_stream())
                                  if isinstance(event, CatalogEvent)])
    return changes


# 按项目设置的参数只有这两项：其余参数按项目设置没有意义，项目级取值也只在这两项上生效。
# 事件种类字符串是 project_parameter_set：目录流已有同名种类 parameter_set，载荷类型表按字符串索引，
# 同名的两种事件会取到同一种载荷类型，流的分类也分不开（ADR-0019 只约束已存在的种类不变，新增种类属于新增）
PROJECT_PARAMETERS = ("check_timeout_sec", "onboarding.round_time_limit_sec")


def check_project_parameter(name: str, value: Any) -> Any:
    # 项目级参数的新值核对：条目必须是可按项目设置的那两项，取值按全局的界限核对
    if name not in PROJECT_PARAMETERS:
        raise ParameterNotFoundError(f"参数 {name} 不能按项目设置")
    return check_bounds(name, value)


def project_values(store: Any, project_id: str) -> dict[str, Any]:
    # 项目的参数取值：项目流事件折叠的结果；没有设置过的项目为空
    from .event_store import project_stream

    events = store.stream_events(project_stream(project_id))
    return fold_project_parameters(events)


def fold_project_parameters(events: list[Any]) -> dict[str, Any]:
    # 按事件顺序折叠项目流的参数事件：现值是最后一次修改的新值
    values: dict[str, Any] = {}
    for event in events:
        if event.type != ProjectEventType.PARAMETER_SET:
            continue
        values[event.payload["name"]] = event.payload["new_value"]
    return values


def value_for_project(store: Any, project_id: str | None, name: str) -> Any:
    # 一个参数的生效取值：项目设置过用项目值，否则用全局现值（工单 #351 验收第 1、2 条）
    if project_id is not None:
        project = project_values(store, project_id)
        if name in project:
            return project[name]
    return current_values(store)[name]

def frozen_check_timeout(store: Any, run_id: str) -> int:
    # 一个 run 中检查的时限（迭代底座 B3，工单 #351）：run_created 事件里冻结的取值，运行中不再跟随修改。
    # 旧事件没有这个字段时按当时的全局现值。取值不进运行投影：投影是内核模块，行数受内核清单上限约束
    from .event_store import run_stream
    from .models import EventType

    for event in store.stream_events(run_stream(run_id), through_version=1):
        if event.type == EventType.RUN_CREATED:
            return int(event.payload.get("check_timeout_sec", DEFINITIONS.rule_value("check_timeout_sec")))
    raise KeyError(run_id)


def check_bounds(name: str, value: Any) -> Any:
    # 新值核对：类型必须与定义的现值一致，数值与可见范围条目数必须落在界限之内；
    # 开关与档位名只核对类型（定义加载时同样只核对界限的写法，见 Rule._within_bounds）。
    # 通过时返回原值；条目不存在时抛出 ParameterNotFoundError，超界或类型不对时抛出 ParameterOutOfBoundsError
    rule = DEFINITIONS.rules.get(name)
    if rule is None or rule.kind != "parameter":
        raise ParameterNotFoundError(f"没有这个参数：{name}")
    current = rule.value
    if isinstance(current, bool) or isinstance(value, bool):
        if not isinstance(value, bool) or not isinstance(current, bool):
            raise ParameterOutOfBoundsError(
                f"参数 {name} 的取值应为开关（true 或 false），收到 {value!r}，界限为 {list(rule.bounds)!r}",
                bounds=rule.bounds)
        return value
    if isinstance(current, (int, float)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ParameterOutOfBoundsError(
                f"参数 {name} 的取值应为数字，收到 {value!r}，界限为 {list(rule.bounds)!r}",
                bounds=rule.bounds)
        if isinstance(current, int) and (not isinstance(value, int)):
            raise ParameterOutOfBoundsError(
                f"参数 {name} 的取值应为整数，收到 {value!r}，界限为 {list(rule.bounds)!r}",
                bounds=rule.bounds)
        low, high = rule.bounds
        if not low <= value <= high:
            raise ParameterOutOfBoundsError(
                f"参数 {name} 的取值 {value!r} 超出界限 {list(rule.bounds)!r}", bounds=rule.bounds)
        return value
    if isinstance(current, list):
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ParameterOutOfBoundsError(
                f"参数 {name} 的取值应为字符串列表，收到 {value!r}，界限为 {list(rule.bounds)!r}",
                bounds=rule.bounds)
        low, high = rule.bounds
        if not low <= len(value) <= high:
            raise ParameterOutOfBoundsError(
                f"参数 {name} 的取值共 {len(value)} 项，超出界限 {list(rule.bounds)!r}", bounds=rule.bounds)
        return value
    if not isinstance(value, str):
        raise ParameterOutOfBoundsError(
            f"参数 {name} 的取值应为档位名（字符串），收到 {value!r}，界限为 {list(rule.bounds)!r}",
            bounds=rule.bounds)
    return value

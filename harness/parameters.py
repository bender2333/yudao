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


class ParameterNotWiredError(ValueError):
    """这条登记还没有接入行为：改动它不会改变任何行为，拒绝修改。原因逐字来自接入清单（工单 #643）。"""


# 接入清单（工单 #643）：每条登记一项结论，已接入的条目为空字符串，未接入的写可以直接显示的中文原因。
# 「接入」指代码按这条登记取值改变实际行为：parameter 条目要有代码读它的现值（参数事件折叠的结果，或创建
# run 时从现值冻结下来的值），structure 条目要有代码读定义里的取值。把值写进参数事件、登记查询或 run 的
# 冻结容器本身不算消费；只有同一提交已经提供实际消费者时才标为接入。
# #1189 接入的冻结读取参数与三条可见范围、#397 接入的三项收敛参数在各自的实现提交里改这一份清单。
NOT_WIRED_REASONS: dict[str, str] = {
    # 已接入：代码按现值改变行为
    "run_time_limit_sec": "",
    "max_cycles": "",
    "check_timeout_sec": "",
    "onboarding.round_time_limit_sec": "",
    # 已接入：裁决按定义里的取值判断询问链的层数
    "organization.ask_chain_max_depth": "",

    # 由 #1189 接入：现在读的是定义文件里的初值，参数事件改不了它
    "tool_call_required_limit": "读的是定义文件里的初值（harness/engine.py 的 DEFINITIONS.rule_value），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "max_model_steps": "读的是定义文件里的初值（harness/execution_contract.py 的 StepLimits 默认值），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "max_provider_attempts": "读的是定义文件里的初值（harness/execution_contract.py 的 StepLimits 默认值），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "retry_initial_delay_sec": "读的是定义文件里的初值（harness/execution_contract.py 的 StepLimits 默认值），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "retry_max_delay_sec": "读的是定义文件里的初值（harness/execution_contract.py 的 StepLimits 默认值），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "tool_output_limit": "读的是定义文件里的初值（harness/environment.py 的模块常量 _OUTPUT_LIMIT），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "bash_timeout_default_sec": "读的是定义文件里的初值（harness/environment.py 的模块常量 _BASH_TIMEOUT_DEFAULT），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "bash_timeout_max_sec": "读的是定义文件里的初值（harness/environment.py 的模块常量 _BASH_TIMEOUT_MAX），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "check_timeout_max_sec": "读的是定义文件里的初值（harness/environment.py 的模块常量 _CHECK_TIMEOUT_MAX），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    "compaction.stalled_limit": "读的是定义文件里的初值（harness/engine.py 的 DEFINITIONS.rule_value），参数事件改不了它；由 #1189 改为读 run 创建时冻结的值",
    # 由 #1189 接入：可见范围现在读的是 roles.json
    "roles.product.visibility": "可见范围读定义文件 harness/definitions/roles.json（harness/context.py 的 DEFINITIONS.role），参数事件改不了它；由 #1189 改为读 run 创建时冻结的取值",
    "roles.engineering.visibility": "可见范围读定义文件 harness/definitions/roles.json（harness/context.py 的 DEFINITIONS.role），参数事件改不了它；由 #1189 改为读 run 创建时冻结的取值",
    "roles.quality.visibility": "可见范围读定义文件 harness/definitions/roles.json（harness/context.py 的 DEFINITIONS.role），参数事件改不了它；由 #1189 改为读 run 创建时冻结的取值",

    # 还没有读取方：取值不影响任何行为
    "adjudication.plan_before_write": "没有代码读取这条登记的取值：写入前的计划检查还没有实现",
    "review.isolation": "没有代码读取这条登记的取值：部门内的审查者与它的信息隔离还没有实现",
    "review.ratio": "没有代码读取这条登记的取值：部门内的审查者与按比例抽审还没有实现",
    "loop.single_work_item": "没有代码读取这条登记的取值：同一项目一次只进行一个事项现在是固定行为，不看这条开关",
    "loop.single_writer": "没有代码读取这条登记的取值：同一时刻只有一个角色写代码现在是固定行为，不看这条开关",
    "loop.nesting_max": "没有代码读取这条登记的取值：子循环与嵌套深度还没有实现",
    "creation.resolve_all_roles": "没有代码读取这条登记的取值：新建事项前解析每个部门的每个角色是固定行为，不看这条开关",
    "desktop.consent_per_session": "没有代码读取这条登记的取值：桌面会话与每个会话开始前的用户同意还没有实现",
    "stall.rounds": "还没有代码读取它：停滞的判定与重新规划还没有实现",
    "plan_item.rejection_reminder": "还没有代码读取它：同一计划条目被反复退回时提醒用户还没有实现",
    "ops.repair_max_failures": "还没有代码读取它：运维部门的修复循环还没有实现",
    "ops.observation_window_hours": "还没有代码读取它：修复后的观察窗口还没有实现",
    "ops.backup_keep": "还没有代码读取它：部署前的备份与回滚还没有实现",
    "evaluation.runs_per_side": "还没有代码读取它：评测运行器的运行次数由命令行给出，不读运行时规则",
    "evaluation.runs_per_side_max": "还没有代码读取它：评测运行器的补跑次数由命令行给出，不读运行时规则",
    "evaluation.run_minutes": "评测运行器读自己的常量（evals/runner/run_eval.py 与 run_yudao_eval.py 的 TIME_LIMIT_SECONDS），不读运行时规则；两个运行器共同的 120 分钟默认值已由 #324 统一，同样不读这条参数",
    "calibration.batch_size": "还没有代码读取它：判定点的校准样本还没有实现",
    "calibration.sample_ratio": "还没有代码读取它：判定点的校准抽样还没有实现",
    "calibration.min_precision": "还没有代码读取它：判定点的启用条件与校准还没有实现",
    "verification.recheck_ratio": "还没有代码读取它：质检只接受本次激活的回执是固定行为，按比例重复运行的调节规则还没有实现",
    "execution.slots": "还没有代码读取它：执行槽位的调度还没有实现，现在一次只执行一个事项",
    "context.work_limit_tokens": "读的是定义文件里的初值（harness/assembly.py 的 work_limit_tokens()），参数事件改不了它；#1189 的清单里没有这一条，#1236 把它留作旧工具结果折叠的触发线",
    "context.tool_result_keep_tokens": "还没有代码读取它：旧工具结果的清理还没有实现",
    "context.tool_result_clear_min_tokens": "还没有代码读取它：旧工具结果的清理还没有实现",
    "context.history_keep_tokens": "还没有代码读取它：压缩时保留多长的历史还没有实现",
    "context.compaction_output_tokens": "还没有代码读取它：整理请求的输出上限用 harness/compaction.py 里的固定常量 4096",
    "context.column_limit.catalog": "还没有代码读取它：语义系统的栏目上限还没有实现",
    "context.column_limit.project_profile": "还没有代码读取它：语义系统的栏目上限还没有实现",
    "context.column_limit.lessons": "还没有代码读取它：语义系统的栏目上限还没有实现",
    "context.column_limit.department_ledger": "还没有代码读取它：语义系统的栏目上限还没有实现",
    "context.column_limit.review_queue": "还没有代码读取它：语义系统的栏目上限还没有实现",
    "context.column_limit.touch_added": "还没有代码读取它：语义系统的栏目上限还没有实现",
    "context.column_limit.trajectory_excerpt": "还没有代码读取它：语义系统的栏目上限还没有实现",
    "context.role_result_chars": "还没有代码读取它：角色结果摘要的长度上限还没有实现",
    "compaction.min_reasoning_effort": "还没有代码读取它：整理请求的最低推理档位还没有实现",
    "screenshot.max_width": "还没有代码读取它：浏览器截图的等比缩小还没有实现",
    "screenshot.max_height": "还没有代码读取它：浏览器截图的等比缩小还没有实现",
    "execution.readiness_timeout_sec": "还没有代码读取它：执行环境服务的就绪时限还没有实现",
    "execution.heartbeat_interval_sec": "还没有代码读取它：执行代理的心跳还没有实现",
    "execution.heartbeat_timeout_sec": "还没有代码读取它：执行代理的心跳还没有实现",
    "execution.dispatch_ack_timeout_sec": "还没有代码读取它：动作派发的确认时限还没有实现",
    "execution.probe_interval_sec": "还没有代码读取它：机器的在线探测还没有实现",
    "execution.probe_timeout_sec": "还没有代码读取它：机器的在线探测还没有实现",
    "execution.offline_after_sec": "还没有代码读取它：机器的离线判断还没有实现",
    "wait.model_service.max_sec": "还没有代码读取它：等待超过时长上限时发出决定请求的判定还没有实现",
    "wait.machine.max_sec": "还没有代码读取它：等待超过时长上限时发出决定请求的判定还没有实现",
    "wait.desktop.max_sec": "还没有代码读取它：等待超过时长上限时发出决定请求的判定还没有实现",
    "wait.desktop_unlock.max_sec": "还没有代码读取它：等待超过时长上限时发出决定请求的判定还没有实现",
}


def not_wired_reason(name: str) -> str:
    # 这条登记的未接入原因，已接入时为空字符串。清单漏了一条就是清单没有写完，当场报错（KeyError）
    return NOT_WIRED_REASONS[name]


def wired(name: str) -> bool:
    # 这条登记是否已经接入行为
    return not not_wired_reason(name)


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
    # 项目级参数的新值核对：条目存在且是参数、已经接入行为、可以按项目设置，取值按全局的界限核对。
    # 未接入的条目在全局与项目两个入口都拒绝修改，不写事件（工单 #643）
    _require_wired(name)
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


def check_parameter(name: str, value: Any) -> Any:
    # 全局参数的新值核对：条目存在且是参数、已经接入行为，取值落在界限以内（工单 #643）
    _require_wired(name)
    return check_bounds(name, value)


def _parameter_rule(name: str) -> Any:
    # 条目必须存在且 kind 为 parameter，否则抛出 ParameterNotFoundError
    rule = DEFINITIONS.rules.get(name)
    if rule is None or rule.kind != "parameter":
        raise ParameterNotFoundError(f"没有这个参数：{name}")
    return rule


def _require_wired(name: str) -> None:
    # 没有接入行为的条目拒绝修改，原因逐字复用接入清单里的未接入原因
    _parameter_rule(name)
    reason = not_wired_reason(name)
    if reason:
        raise ParameterNotWiredError(reason)


def check_bounds(name: str, value: Any) -> Any:
    # 新值核对：类型必须与定义的现值一致，数值与可见范围条目数必须落在界限之内；
    # 开关与档位名只核对类型（定义加载时同样只核对界限的写法，见 Rule._within_bounds）。
    # 通过时返回原值；条目不存在时抛出 ParameterNotFoundError，超界或类型不对时抛出 ParameterOutOfBoundsError
    rule = _parameter_rule(name)
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

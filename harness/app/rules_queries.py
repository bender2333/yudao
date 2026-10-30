# 规则登记的查询（设计说明第 2 节「规则登记」与第 8 节的表格，工单 #343）。
# 规则登记就是定义里的全部条目，不另建系统：这一条查询把登记的现值、四项记录、取值界限、来源、种类与形式读出来。

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ..definitions import DEFINITIONS
from ..models import CatalogEventType, EventType
from ..parameters import current_values, current_version, history, not_wired_reason, wired
from .contracts import Contract, Snapshot
from .registry import QueryDefinition, UnchangedEvent
from .replay import ReplayRequest, check_position

if TYPE_CHECKING:
    from .application import Application


class ParameterChangeEntry(Contract):
    # 参数的一次修改：原值、新值、理由、修改者与修改以后的参数版本，时间与事件编号按目录流事件给出
    old_value: Any
    new_value: Any
    reason: str
    modified_by: str
    parameters_version: str
    event_id: str
    created_at: str
    stream_version: int


class RuleEntry(Contract):
    # 登记里的一个条目：拦截什么、花费多少、放松与收紧的证据，加起来说明为什么保留这条规则、为什么是这个现值。
    # 价值类型与界限类型：kind 为 structure 的条目现值是发布时的默认取值，取值范围由候选与用户批准保证
    name: str
    value: Any
    # 默认值：定义里的初值（Rule.value）。参数被修改过时现值 value 可能不同于默认值；
    # structure 条目与从未修改的参数两者相同（工单 #1262，设计说明第 2 节「登记照着实现」）
    default_value: Any
    bounds: list[Any]
    kind: Literal["parameter", "structure"]
    form: Literal["permission", "boundary", "admission"]
    # 是否已经接入行为，未接入时给出可以直接显示的中文原因；两条都取自 harness/parameters.py 的接入清单
    # （工单 #643）。未接入的条目参数命令以 not_wired 拒绝修改，说明逐字复用这里的 not_wired_reason
    wired: bool
    not_wired_reason: str
    guards: str
    cost: str
    relax_when: str
    tighten_when: str
    # 来源：这条数值与它的理由写在哪一份文档或哪一条需求里
    origin: str
    # 参数现值被修改过时，这里的 value 是参数事件折叠的现值，changes 是它的全部修改记录；
    # structure 条目与从未修改的参数没有修改记录
    changes: list[ParameterChangeEntry] = []


class RuleRegistry(Contract):
    # 全部条目按名称排列；definitions_version 指出这批条目出自哪一版的定义，
    # 读取历史位置时给出当时生效的定义版本，查询结果里不混入现在才有的条目。
    # parameters_version 是当前全局参数版本（全部参数现值的内容摘要，设计说明第 4.3 节）：
    # 页面把它作为 parameter.set 与 parameter.withdraw 的基准版本 base_version 提交（工单 #1262）
    rules: list[RuleEntry]
    definitions_version: str
    parameters_version: str


class RulesRegistryRequest(ReplayRequest):
    # 可回放（设计说明第 8 节表格）：at 是全局位置，省略时读取现在的登记
    pass


def _rules_registry(application: Application, request: RulesRegistryRequest) -> Snapshot[RuleRegistry]:
    store = application.system.store
    # 参数现值与修改历史由参数事件折叠（工单 #349）：登记里的 value 是参数的现值（目录流事件折叠的结果），
    # changes 是它的全部修改记录；structure 条目与从未修改的参数没有修改记录。
    # default_value 取定义条目自己的初值（Rule.value，工单 #1262）：不改变定义格式或规则登记文件结构，
    # 定义改版时默认值跟着定义走。按位置读取只核对 at 不超过日志末尾，返回当前定义与当前参数事件的内容
    check_position(application, request.at)

    values = current_values(store)
    by_name: dict[str, list[ParameterChangeEntry]] = {}
    for change in history(store):
        by_name.setdefault(change.name, []).append(ParameterChangeEntry(
            old_value=change.old_value, new_value=change.new_value, reason=change.reason,
            modified_by=change.modified_by, parameters_version=change.parameters_version,
            event_id=change.event_id, created_at=change.created_at, stream_version=change.stream_version,
        ))
    definitions = DEFINITIONS
    entries = [
        RuleEntry(
            name=name, value=values.get(name, rule.value), default_value=rule.value, bounds=list(rule.bounds),
            kind=rule.kind,
            form=rule.form, wired=wired(name), not_wired_reason=not_wired_reason(name),
            guards=rule.guards, cost=rule.cost, relax_when=rule.relax_when,
            tighten_when=rule.tighten_when, origin=rule.origin, changes=by_name.get(name, []),
        )
        for name, rule in sorted(definitions.rules.items())
    ]
    return Snapshot[RuleRegistry](
        position=store.end_position(),
        data=RuleRegistry(rules=entries, definitions_version=definitions.version,
                          parameters_version=current_version(store)),
    )


RULES_REGISTRY = QueryDefinition(
    name="rules.registry", request=RulesRegistryRequest, result=RuleRegistry,
    handle=_rules_registry, changed_by=(CatalogEventType.PARAMETER_SET,), replayable=True,
    unchanged_by=(
        UnchangedEvent(EventType.CONTEXT_ASSEMBLED, "上下文装配不改变规则登记：登记的现值只由参数事件改变"),
        UnchangedEvent(EventType.MODEL_REQUEST_SERIALIZED, "请求序列化不改变规则登记：登记的现值只由参数事件改变"),
        UnchangedEvent(EventType.MODEL_REQUESTED, "发出模型请求不改变规则登记：登记的现值只由参数事件改变"),
        UnchangedEvent(EventType.MODEL_MESSAGE, "模型消息不改变规则登记：登记的现值只由参数事件改变"),
        UnchangedEvent(EventType.MODEL_REASONING, "模型的推理内容不改变规则登记：登记的现值只由参数事件改变"),
        UnchangedEvent(EventType.MODEL_STREAM_PROGRESS, "流式进度不改变规则登记：登记的现值只由参数事件改变"),
        UnchangedEvent(EventType.TOOL_STARTED, "工具开始不改变规则登记：登记的现值只由参数事件改变"),
        UnchangedEvent(EventType.TOOL_CALLED, "工具调用不改变规则登记：登记的现值只由参数事件改变"),
    ),
)
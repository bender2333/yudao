# 规则登记的查询（设计说明第 2 节「规则登记」与第 8 节的表格，工单 #343）。
# 规则登记就是定义里的全部条目，不另建系统：这一条查询把登记的现值、四项记录、取值界限、来源、种类与形式读出来。

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ..definitions import DEFINITIONS
from .contracts import Contract, Snapshot
from .registry import QueryDefinition
from .replay import ReplayRequest, check_position

if TYPE_CHECKING:
    from .application import Application


class RuleEntry(Contract):
    # 登记里的一个条目：拦截什么、花费多少、放松与收紧的证据，加起来说明为什么保留这条规则、为什么是这个现值。
    # 价值类型与界限类型：kind 为 structure 的条目现值是发布时的默认取值，取值范围由候选与用户批准保证
    name: str
    value: Any
    bounds: list[Any]
    kind: Literal["parameter", "structure"]
    form: Literal["permission", "boundary", "admission"]
    guards: str
    cost: str
    relax_when: str
    tighten_when: str
    # 来源：这条数值与它的理由写在哪一份文档或哪一条需求里
    origin: str


class RuleRegistry(Contract):
    # 全部条目按名称排列；definitions_version 指出这批条目出自哪一版的定义，
    # 读取历史位置时给出当时生效的定义版本，查询结果里不混入现在才有的条目
    rules: list[RuleEntry]
    definitions_version: str


class RulesRegistryRequest(ReplayRequest):
    # 可回放（设计说明第 8 节表格）：at 是全局位置，省略时读取现在的登记
    pass


def _rules_registry(application: Application, request: RulesRegistryRequest) -> Snapshot[RuleRegistry]:
    store = application.system.store
    # 规则登记是事件日志之外的状态：参数事件记录修改历史属于参数事件的工单（#349）。
    # 现在按位置读取只核对 at 不超过日志末尾，返回的登记是当前这一版定义的内容
    check_position(application, request.at)
    definitions = DEFINITIONS
    entries = [
        RuleEntry(
            name=name, value=rule.value, bounds=list(rule.bounds), kind=rule.kind, form=rule.form,
            guards=rule.guards, cost=rule.cost, relax_when=rule.relax_when,
            tighten_when=rule.tighten_when, origin=rule.origin,
        )
        for name, rule in sorted(definitions.rules.items())
    ]
    return Snapshot[RuleRegistry](
        position=store.end_position(),
        data=RuleRegistry(rules=entries, definitions_version=definitions.version),
    )


RULES_REGISTRY = QueryDefinition(
    name="rules.registry", request=RulesRegistryRequest, result=RuleRegistry,
    handle=_rules_registry, changed_by=(), replayable=True,
)
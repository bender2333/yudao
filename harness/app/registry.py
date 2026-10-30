# 注册表：登记每个命令与查询的名称、请求类型、结果类型、处理函数、可能的拒绝原因与改变查询结果的事件种类。
# 接口层的路由、OpenAPI 与能力清单都由它生成，不另写清单（设计说明第 2.2、6.1 节）。

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ..event_store import Command
from ..models import Event, ProjectEvent
from .contracts import (
    EVENT_TYPES, REJECTION_REASONS, Capabilities, CommandCapability, CommandRequest, Deployment,
    OverlayCapability, QueryCapability, RejectionReason, Snapshot, StreamCapability,
)

if TYPE_CHECKING:
    from .application import Application


@dataclass(frozen=True)
class CommandDefinition:
    # 一个命令。handle 把 Command（身份、名称、内容摘要与提出者）交给控制核心，由写入口在同一个事务中登记命令身份、
    # 核对、判断并追加；需要拒绝时抛出 Rejection。refs 由这次命令追加的事件得出，重复提交时由原来的事件得出
    name: str
    request: type[CommandRequest]
    refs: type[BaseModel]
    handle: Callable[[Application, Command, Any], Awaitable[None]]
    derive_refs: Callable[[list[Event | ProjectEvent]], BaseModel]
    reasons: tuple[RejectionReason, ...] = ()


@dataclass(frozen=True)
class UnchangedEvent:
    # 「不刷新」清单里的一种事件种类与一句理由：这种事件不改变这个查询的结果，客户端收到它不必重新查询。
    # 理由写在这里，是为了说明「为什么不刷新」这件事本身是可核对的（设计说明第 4.2 节）
    kind: str
    reason: str


@dataclass(frozen=True)
class QueryDefinition:
    # 一个查询。handle 只读取，返回快照（数据与它已经包含的最大全局位置）；changed_by 是会改变结果的事件种类，
    # 客户端收到这些事件时重新查询；unchanged_by 是已核对过不改变结果的事件种类与理由，两份清单合起来覆盖
    # 全部已登记的事件种类；replayable 为真时接受设计说明第 4.1 节的 at（全局位置，按位置读取）
    name: str
    request: type[BaseModel] | None
    result: type[Any]
    handle: Callable[[Application, Any], Snapshot[Any]]
    changed_by: tuple[str, ...] = ()
    unchanged_by: tuple[UnchangedEvent, ...] = ()
    replayable: bool = False


@dataclass(frozen=True)
class OverlayDefinition:
    # 一个覆盖层：名称与它依赖的查询（设计说明第 6.1 节）。定义登记在注册表中，
    # 能力清单按依赖的查询是否都已登记自动列出
    name: str
    queries: tuple[str, ...]


# 覆盖层的清单（标识：名称，依赖的查询）
OVERLAYS: tuple[OverlayDefinition, ...] = (
    OverlayDefinition(name="flow", queries=("project.flow",)),
    OverlayDefinition(name="waiting", queries=("project.loop", "decisions.list")),
    OverlayDefinition(name="recovery", queries=("run.recovery",)),
    OverlayDefinition(name="context_usage", queries=("overlay.context_usage",)),
    OverlayDefinition(name="semantic_records", queries=("semantic.records",)),
    # 事实来源：事件对象的 source 字段（设计说明第 4.3 节），覆盖在楼层的事实上。它依赖楼层查询，
    # 楼层查询登记以后才列出（工单 #396）
    OverlayDefinition(name="sources", queries=("project.loop",)),
)


class Registry:
    def __init__(self, commands: Sequence[CommandDefinition], queries: Sequence[QueryDefinition], *,
                 decisions: Sequence[str] = (), overlays: Sequence[OverlayDefinition] = OVERLAYS) -> None:
        names = [item.name for item in commands] + [item.name for item in queries]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate registered names: {sorted(name for name in names if names.count(name) > 1)}")
        for query in queries:
            unknown = set(query.changed_by) - set(EVENT_TYPES)
            if unknown:
                raise ValueError(f"query {query.name} declares unknown event types: {sorted(unknown)}")
            # 「不刷新」清单的两项检查：其中的种类都已登记；与刷新清单不重叠（设计说明第 4.2 节）
            unchanged = [item.kind for item in query.unchanged_by]
            unknown = set(unchanged) - set(EVENT_TYPES)
            if unknown:
                raise ValueError(f"query {query.name} declares unknown unchanged event types: {sorted(unknown)}")
            overlap = sorted(set(query.changed_by) & set(unchanged))
            if overlap:
                raise ValueError(f"query {query.name} declares the same event types in both lists: {overlap}")
            repeated = sorted({kind for kind in unchanged if unchanged.count(kind) > 1})
            if repeated:
                raise ValueError(f"query {query.name} repeats unchanged event types: {repeated}")
        for command in commands:
            unknown = set(command.reasons) - set(REJECTION_REASONS)
            if unknown:
                raise ValueError(f"command {command.name} declares unknown rejection reasons: {sorted(unknown)}")
        self.commands = {item.name: item for item in commands}
        self.queries = {item.name: item for item in queries}
        self.decisions = tuple(decisions)
        self.overlays = tuple(overlays)

    def reasons(self, name: str) -> tuple[RejectionReason, ...]:
        # 命令可能返回的全部拒绝原因：自己声明的原因，加上每个命令都可能返回的命令身份重复使用
        return (*self.commands[name].reasons, "command_id_reused")

    # 事件流的片段能力（第 6.1 节）：提供模型输出片段，连接可以按这些范围参数筛选
    stream = StreamCapability(deltas=True, scopes=["project", "work_item", "run", "department", "role", "type"])

    def capabilities(self, deployment: Deployment) -> Capabilities:
        return Capabilities(
            deployment=deployment,
            queries=[QueryCapability(name=item.name, changed_by=list(item.changed_by), replayable=item.replayable)
                     for item in self.queries.values()],
            commands=[CommandCapability(name=name, reasons=list(self.reasons(name))) for name in self.commands],
            decisions=list(self.decisions),
            event_types=list(EVENT_TYPES),
            overlays=[
                OverlayCapability(name=item.name, queries=list(item.queries))
                for item in self.overlays
                if set(item.queries) <= set(self.queries)
            ],
            stream=self.stream,
        )

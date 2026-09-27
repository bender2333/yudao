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
    EVENT_TYPES, REJECTION_REASONS, Capabilities, CommandCapability, CommandRequest, Deployment, QueryCapability,
    RejectionReason, Snapshot,
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
class QueryDefinition:
    # 一个查询。handle 只读取，返回快照（数据与它已经包含的最大全局位置）；changed_by 是会改变结果的事件种类，
    # 客户端收到这些事件时重新查询
    name: str
    request: type[BaseModel] | None
    result: type[Any]
    handle: Callable[[Application, Any], Snapshot[Any]]
    changed_by: tuple[str, ...] = ()


class Registry:
    def __init__(self, commands: Sequence[CommandDefinition], queries: Sequence[QueryDefinition], *,
                 decisions: Sequence[str] = ()) -> None:
        names = [item.name for item in commands] + [item.name for item in queries]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate registered names: {sorted(name for name in names if names.count(name) > 1)}")
        for query in queries:
            unknown = set(query.changed_by) - set(EVENT_TYPES)
            if unknown:
                raise ValueError(f"query {query.name} declares unknown event types: {sorted(unknown)}")
        for command in commands:
            unknown = set(command.reasons) - set(REJECTION_REASONS)
            if unknown:
                raise ValueError(f"command {command.name} declares unknown rejection reasons: {sorted(unknown)}")
        self.commands = {item.name: item for item in commands}
        self.queries = {item.name: item for item in queries}
        self.decisions = tuple(decisions)

    def reasons(self, name: str) -> tuple[RejectionReason, ...]:
        # 命令可能返回的全部拒绝原因：自己声明的原因，加上每个命令都可能返回的命令身份重复使用
        return (*self.commands[name].reasons, "command_id_reused")

    def capabilities(self, deployment: Deployment) -> Capabilities:
        return Capabilities(
            deployment=deployment,
            queries=[QueryCapability(name=item.name, changed_by=list(item.changed_by)) for item in self.queries.values()],
            commands=[CommandCapability(name=name, reasons=list(self.reasons(name))) for name in self.commands],
            decisions=list(self.decisions),
            event_types=list(EVENT_TYPES),
        )

# 命令处理（设计说明第 3.1 节）：由请求得出命令（身份、名称、内容摘要与提出者），交给已登记的处理函数；
# 处理函数经控制核心的写入口，在同一个事务中登记命令身份、核对基准版本与对象状态、判断并追加事件。
# 同一身份、同一内容再次提交时返回原来的接受结果（duplicate），内容不同时拒绝（command_id_reused）；
# 被拒绝的命令不登记，客户端用同一身份重试时重新判断。

from __future__ import annotations

from typing import TYPE_CHECKING

from ..event_store import Command, CommandIdReused, DuplicateCommand
from ..models import canonical_hash
from .contracts import Accepted, CommandRequest, Rejected, RejectionReason
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


class Rejection(Exception):
    # 处理函数拒绝这次命令：原因来自封闭清单并且是这个命令声明过的，message 是给用户的中文说明；
    # 修改类命令的基准版本过期时带对象的当前版本（版本可以是流版本那样的序号，也可以是参数版本
    # 这样的内容摘要，工单 #1262：只要与同一对象的查询返回的版本同一种读法即可）
    def __init__(self, reason: RejectionReason, message: str, *, current_version: int | str | None = None) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.message = message
        self.current_version = current_version


def command_digest(name: str, request: CommandRequest) -> str:
    # 请求内容的摘要：命令名称与除命令身份以外的全部字段
    return canonical_hash({"name": name, "request": request.model_dump(mode="json", exclude={"command_id"})})


async def execute(application: Application, definition: CommandDefinition, request: CommandRequest, *,
                  actor: str) -> Accepted | Rejected:
    if type(request) is not definition.request:
        raise TypeError(f"command {definition.name} takes {definition.request.__name__}, not {type(request).__name__}")
    command = Command(request.command_id, definition.name, command_digest(definition.name, request), actor)
    try:
        await definition.handle(application, command, request)
    except DuplicateCommand:
        return _accepted(application, definition, request, duplicate=True)
    except CommandIdReused:
        return Rejected(command_id=request.command_id, reason="command_id_reused",
                        message="这个命令身份已经用于内容不同的另一次提交，请为新的操作生成新的命令身份")
    except Rejection as rejection:
        if rejection.reason not in definition.reasons:
            raise ValueError(f"command {definition.name} rejected with undeclared reason {rejection.reason}") from rejection
        return Rejected(command_id=request.command_id, reason=rejection.reason, message=rejection.message,
                        current_version=rejection.current_version)
    return _accepted(application, definition, request, duplicate=False)


def _accepted(application: Application, definition: CommandDefinition, request: CommandRequest, *,
              duplicate: bool) -> Accepted:
    # 位置与 refs 都取自命令的登记与它追加的事件，第一次接受与重复提交得到同样的结果
    store = application.system.store
    record = store.command(request.command_id)
    if record is None:
        raise RuntimeError(f"command {definition.name} returned without registering {request.command_id} at the write path")
    refs = definition.derive_refs(store.command_events(request.command_id))
    return Accepted[definition.refs](command_id=request.command_id, position=record.position, refs=refs,
                                     duplicate=duplicate)

# 排空与强制升级的命令（应用层与接口层设计说明第 3.2 节「升级」，ADR-0019，工单 #126）。
# 排空：Yudao 停止开始新事项，新建的事项排队，正在进行的 run 照常结束；排空状态由 system.status 返回。
# 强制升级只在排空期间可用：正在进行的 run 记为因升级停止，对应的事项用已采纳成果重新开始，
# 并记下「因升级重新开始」的优先级。两个命令的基准版本是排空状态的版本，只作为依据记录，不要求相等。

from __future__ import annotations

from typing import TYPE_CHECKING

from ..event_store import Command
from ..models import Event, ProjectEvent
from .commands import Rejection
from .contracts import CommandRequest, NoRefs
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application

class RuntimeStartDrain(CommandRequest):
    # 开始排空；基准版本是排空状态的版本，记录依据
    base_version: int | None = None

class RuntimeForceUpgrade(CommandRequest):
    # 强制升级；基准版本是排空状态的版本，记录依据
    base_version: int | None = None

def _no_refs(_events: list[Event | ProjectEvent]) -> NoRefs:
    return NoRefs()

async def _start_drain(application: Application, command: Command, request: RuntimeStartDrain) -> None:
    system = application.system
    if system.drain.state != "idle":
        raise Rejection("not_allowed", "排空已经开始，不需要再次开始")
    system.start_drain(command=command)

async def _force_upgrade(application: Application, command: Command, request: RuntimeForceUpgrade) -> None:
    system = application.system
    if system.drain.state != "draining":
        raise Rejection("not_allowed", "强制升级只在排空期间可用，请先开始排空")
    system.force_upgrade(command=command)

RUNTIME_START_DRAIN = CommandDefinition(
    name="runtime.start_drain", request=RuntimeStartDrain, refs=NoRefs, handle=_start_drain,
    derive_refs=_no_refs, reasons=("not_allowed",),
)
RUNTIME_FORCE_UPGRADE = CommandDefinition(
    name="runtime.force_upgrade", request=RuntimeForceUpgrade, refs=NoRefs, handle=_force_upgrade,
    derive_refs=_no_refs, reasons=("not_allowed",),
)

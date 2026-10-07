# 参数修改的命令（迭代底座 B3，工单 #349，设计说明第 3、5 节）：
# 界内修改一次全局参数的现值，事件写进目录流。超出界限时拒绝，不写事件。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from .. import parameters as parameter_values
from ..event_store import Command
from .commands import Rejection
from .contracts import CommandRequest, NoRefs
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


class ParameterSet(CommandRequest):
    # 把一个全局参数改成新值：name 必须是 kind 为 parameter 的条目，value 按条目的界限核对
    name: str = Field(min_length=1)
    value: Any
    reason: str = Field(min_length=1)
    modified_by: str = Field(min_length=1)


def _parameter_set_refs(_events: list[Any]) -> NoRefs:
    return NoRefs()


async def _set_parameter(application: Application, command: Command, request: ParameterSet) -> None:
    try:
        application.system.set_parameter(request.name, request.value, reason=request.reason,
                                         modified_by=request.modified_by, command=command)
    except parameter_values.ParameterNotFoundError as exc:
        raise Rejection("not_found", str(exc)) from exc
    except parameter_values.ParameterOutOfBoundsError as exc:
        raise Rejection("out_of_bounds", str(exc)) from exc


PARAMETER_SET = CommandDefinition(
    name="parameter.set", request=ParameterSet, refs=NoRefs, handle=_set_parameter,
    derive_refs=_parameter_set_refs,
    reasons=("not_found", "out_of_bounds"),
)

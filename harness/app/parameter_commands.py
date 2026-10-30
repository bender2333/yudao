# 参数修改的命令（迭代底座 B3，工单 #349、#351，设计说明第 3、5 节）：
# 界内修改一次全局参数或项目级参数的现值。全局参数的事件写进目录流，项目级参数的事件写进项目流。
# 超出界限时拒绝，不写事件。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from .. import parameters as parameter_values
from ..event_store import Command
from ..projects import ProjectNotFoundError
from .commands import Rejection
from .contracts import CommandRequest, NoRefs
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


class ParameterSet(CommandRequest):
    # 把一个参数改成新值：name 必须是 kind 为 parameter 的条目，value 按条目的界限核对；
    # 带 project_id 时只能是可按项目设置的那些条目（工单 #351）
    name: str = Field(min_length=1)
    value: Any
    reason: str = Field(min_length=1)
    modified_by: str = Field(min_length=1)
    project_id: str | None = None


def _parameter_set_refs(_events: list[Any]) -> NoRefs:
    return NoRefs()


async def _set_parameter(application: Application, command: Command, request: ParameterSet) -> None:
    try:
        if request.project_id is None:
            application.system.set_parameter(request.name, request.value, reason=request.reason,
                                             modified_by=request.modified_by, command=command)
            return
        application.system.projects.set_parameter(
            request.project_id, request.name, request.value,
            reason=request.reason, modified_by=request.modified_by, command=command)
    except parameter_values.ParameterNotFoundError as exc:
        raise Rejection("not_found", str(exc)) from exc
    except parameter_values.ParameterNotWiredError as exc:
        # 未接入的条目拒绝修改：说明逐字复用规则登记里的未接入原因（工单 #643）
        raise Rejection("not_wired", str(exc)) from exc
    except parameter_values.ParameterOutOfBoundsError as exc:
        raise Rejection("out_of_bounds", str(exc)) from exc
    except ProjectNotFoundError as exc:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from exc


PARAMETER_SET = CommandDefinition(
    name="parameter.set", request=ParameterSet, refs=NoRefs, handle=_set_parameter,
    derive_refs=_parameter_set_refs,
    reasons=("not_found", "not_wired", "out_of_bounds"),
)

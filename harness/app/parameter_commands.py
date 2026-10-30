# 参数修改的命令（迭代底座 B3，工单 #349、#351，设计说明第 3、5 节；工单 #1262 的认证身份、基准版本与撤回）：
# 界内修改一次全局参数或项目级参数的现值。全局参数的事件写进目录流，项目级参数的事件写进项目流。
# 超出界限时拒绝，不写事件。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from .. import parameters as parameter_values
from ..event_store import Command
from ..models import ProjectEventType
from ..projects import ProjectNotFoundError
from .commands import Rejection
from .contracts import CommandRequest, NoRefs, Text
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


class ParameterSet(CommandRequest):
    # 把一个参数改成新值：name 必须是 kind 为 parameter 的条目，value 按条目的界限核对；
    # 带 project_id 时只能是可按项目设置的那些条目（工单 #351）。
    # modified_by 是工单 #1262 以前的旧请求字段：现在可省略，提供时继续接受旧请求，
    # 但事件里的提出者与历史都以认证身份为准，请求体里的值不进入事件。
    # base_version 是规则登记返回的参数版本：全局参数是全局参数版本，项目级参数是这个项目有效参数的版本；
    # 缺省时保持旧请求的兼容行为，不按版本核对。
    # expected_change_id 是撤回时目标修改记录的稳定身份（设计说明第 4.3 节「撤回」）：给出时在同一写事务
    # 核对它仍是这个参数最近的一次修改，任一不符以 stale_base 拒绝；普通修改省略，原有请求继续有效
    name: str = Field(min_length=1)
    value: Any
    # 非空理由（设计说明第 4.3 节）：空字符串与全空白都过不了合同校验，接口层返回 422（工单 #1262）
    reason: Text
    modified_by: str | None = None
    project_id: str | None = None
    base_version: str | None = None
    expected_change_id: str | None = None


def _parameter_set_refs(_events: list[Any]) -> NoRefs:
    return NoRefs()


async def _set_parameter(application: Application, command: Command, request: ParameterSet) -> None:
    try:
        if request.project_id is None:
            application.system.set_parameter(
                request.name, request.value, reason=request.reason,
                base_version=request.base_version, expected_change_id=request.expected_change_id,
                command=command)
            return
        application.system.projects.set_parameter(
            request.project_id, request.name, request.value,
            reason=request.reason, base_version=request.base_version,
            expected_change_id=request.expected_change_id, command=command)
    except parameter_values.ParameterNotFoundError as exc:
        raise Rejection("not_found", str(exc)) from exc
    except parameter_values.ParameterNotWiredError as exc:
        # 未接入的条目拒绝修改：说明逐字复用规则登记里的未接入原因（工单 #643）
        raise Rejection("not_wired", str(exc)) from exc
    except parameter_values.ParameterOutOfBoundsError as exc:
        raise Rejection("out_of_bounds", str(exc)) from exc
    except parameter_values.ParameterStaleError as exc:
        # 基准版本过期（工单 #1262）：带当前的参数版本，页面重新读取规则登记以后再提交
        raise Rejection("stale_base", str(exc), current_version=exc.current_version) from exc
    except ProjectNotFoundError as exc:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from exc


PARAMETER_SET = CommandDefinition(
    name="parameter.set", request=ParameterSet, refs=NoRefs, handle=_set_parameter,
    derive_refs=_parameter_set_refs,
    reasons=("not_found", "not_wired", "out_of_bounds", "stale_base"),
)


class ParameterWithdraw(CommandRequest):
    # 撤回一次参数修改（工单 #1262，设计说明第 4.3 节「撤回」）：把参数改回目标修改记录的原值，
    # 仍然经 parameter.set 的同一条核对路径完成。expected_change_id 是目标修改记录的稳定身份，
    # 必须给出；服务在同一写事务核对它仍是该参数最近的一次修改并检查基准版本，任一不符返回 stale_base。
    # 撤回不删除历史记录：它自己也是一次修改，理由按「撤回：」与原理由（页面提交时已按这个格式给出）
    name: str = Field(min_length=1)
    expected_change_id: str
    # 非空理由（设计说明第 4.3 节）：空字符串与全空白都过不了合同校验，接口层返回 422（工单 #1262）
    reason: Text
    modified_by: str | None = None
    project_id: str | None = None
    base_version: str | None = None


async def _withdraw_parameter(application: Application, command: Command, request: ParameterWithdraw) -> None:
    store = application.system.store
    try:
        if request.project_id is None:
            original = _withdraw_target(parameter_values.history(store), request)
            application.system.set_parameter(
                request.name, original.old_value, reason=request.reason,
                base_version=request.base_version, expected_change_id=request.expected_change_id,
                command=command)
            return
        project = application.system.projects
        overrides = parameter_values.project_values(store, request.project_id)
        if request.name not in overrides:
            raise Rejection("not_found", f"参数 {request.name} 在这个项目没有设置过，没有可撤回的修改")
        original = _withdraw_target(_withdraw_project_history(store, request.project_id), request)
        project.set_parameter(
            request.project_id, request.name, original.old_value, reason=request.reason,
            base_version=request.base_version, expected_change_id=request.expected_change_id,
            command=command)
    except parameter_values.ParameterNotFoundError as exc:
        raise Rejection("not_found", str(exc)) from exc
    except parameter_values.ParameterNotWiredError as exc:
        raise Rejection("not_wired", str(exc)) from exc
    except parameter_values.ParameterOutOfBoundsError as exc:
        raise Rejection("out_of_bounds", str(exc)) from exc
    except parameter_values.ParameterStaleError as exc:
        raise Rejection("stale_base", str(exc), current_version=exc.current_version) from exc
    except ProjectNotFoundError as exc:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from exc


def _withdraw_target(history: list[Any], request: ParameterWithdraw) -> Any:
    # 撤回的目标记录：按身份在修改历史里找（工单 #1262）；身份不存在或记录的不是这个参数时
    # 以 stale_base 拒绝——原值只取自同一条登记的最近修改，不按参数名重找
    for change in reversed(history):
        if change.event_id == request.expected_change_id:
            if change.name != request.name:
                raise Rejection("stale_base", "要撤回的修改记录不是这个参数的，请重新读取以后再提交")
            return change
    raise Rejection("stale_base", "要撤回的修改不在参数的历史里，请重新读取以后再提交")


def _withdraw_project_history(store: Any, project_id: str) -> list[Any]:
    # 项目流里的项目级参数修改记录：按事件顺序，带事件编号供撤回核对
    from ..event_store import project_stream

    changes: list[Any] = []
    for event in store.stream_events(project_stream(project_id)):
        if event.type != ProjectEventType.PARAMETER_SET:
            continue
        payload = event.payload
        changes.append(parameter_values.ParameterChange(
            name=payload["name"], old_value=payload["old_value"], new_value=payload["new_value"],
            reason=payload["reason"], modified_by=payload["modified_by"],
            parameters_version="", event_id=event.event_id, created_at=event.created_at,
            stream_version=event.stream_version))
    return changes


PARAMETER_WITHDRAW = CommandDefinition(
    name="parameter.withdraw", request=ParameterWithdraw, refs=NoRefs, handle=_withdraw_parameter,
    derive_refs=_parameter_set_refs,
    reasons=("not_found", "not_wired", "out_of_bounds", "stale_base"),
)

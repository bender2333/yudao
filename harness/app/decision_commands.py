# 用户决定的命令（设计说明第 3.3 节）：所有决定种类共用同一个命令 decision.answer，可选项由决定请求给出。
# 回答在写入口的一个事务中核对请求仍未回答、基准版本与选项，并追加回答事件；需要继续执行时由流程编排的开始
# 入口在当前事件循环中把这个 run 作为任务继续运行，结果以后续事件出现（第 3.1 节「处理」）。

from __future__ import annotations

from typing import TYPE_CHECKING

from ..decisions import DecisionClosed, DecisionNotFound, InvalidOption, NoteRequired, StaleDecision
from ..event_store import Command
from ..models import Event, ProjectEvent
from .commands import Rejection
from .contracts import CommandRequest, Contract, Text
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


class DecisionAnswer(CommandRequest):
    # 回答一个决定请求：基准版本是决定请求的版本，取自 decisions.list 的结果
    base_version: int
    decision_id: str
    option: str
    note: Text | None = None


class DecisionRefs(Contract):
    # 被回答的决定请求，以及它所属的 run
    decision_id: str
    run_id: str | None


async def _answer_decision(application: Application, command: Command, request: DecisionAnswer) -> None:
    try:
        run_id = application.system.orchestrator.answer_decision(
            request.decision_id, request.option, request.note, base_version=request.base_version, command=command)
    except DecisionNotFound as missing:
        raise Rejection("not_found", "没有这个决定请求，请重新读取以后提交") from missing
    except DecisionClosed as closed:
        state = "已经回答" if closed.status == "answered" else "已经撤销"
        raise Rejection("decision_closed", f"这个决定请求{state}，不能再次回答") from closed
    except StaleDecision as stale:
        raise Rejection("stale_base", "决定请求的版本已经改变，请重新读取以后提交",
                        current_version=stale.version) from stale
    except InvalidOption as invalid:
        offered = "、".join(invalid.options)
        raise Rejection("option_invalid", f"所选选项不是这个决定请求给出的选项，可选的选项：{offered}") from invalid
    except NoteRequired as missing_note:
        raise Rejection("not_allowed", f"选择「{missing_note.option}」必须填写说明") from missing_note
    if run_id is not None:
        application.system.orchestrator.start(run_id)


def _decision_refs(events: list[Event | ProjectEvent]) -> DecisionRefs:
    # 回答首先写入，结束运行的事件跟在它后面。项目流中的请求属于事项、不属于任何 run（工单 #136），
    # 项目事件的 run_id 由载荷给出，载荷没有 run_id 时为空
    [answered] = events[:1]
    return DecisionRefs(decision_id=answered.payload["decision_id"], run_id=answered.run_id)


DECISION_ANSWER = CommandDefinition(
    name="decision.answer", request=DecisionAnswer, refs=DecisionRefs, handle=_answer_decision,
    derive_refs=_decision_refs,
    reasons=("not_found", "decision_closed", "stale_base", "option_invalid", "not_allowed"),
)

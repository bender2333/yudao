# 决定请求的查询（设计说明第 4.3 节「外壳」）：列出决定请求，按项目、事项、种类与状态筛选（状态可以多选，
# 省略时不限制）；位置是与决定请求在同一个读取事务中看到的日志末尾。查询不写入任何内容。

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, Field

from ..models import DecisionRequest, EventType
from ..projection import saved_decisions
from .contracts import CommandId, Contract, Snapshot
from .payloads import DecisionRequestedPayload
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application


class DecisionsList(Contract):
    # 筛选条件：省略的条件不限制；状态可以给出多个（HTTP 上是重复的同名参数），省略状态时不限制。等待用户的
    # 列表只取「等待回答」（status=open），run 结束时撤销的请求不在其中
    project_id: str | None = None
    work_item_id: str | None = None
    kind: str | None = None
    status: list[Literal["open", "answered", "withdrawn"]] = Field(default_factory=list)


class DecisionAnswerRecord(Contract):
    # 回答：所选的选项、说明、回答所依据的请求版本、提出者与引起它的命令
    event_id: str
    option: str
    note: str | None
    base_version: int
    actor: str
    command_id: CommandId
    answered_at: AwareDatetime


class DecisionView(Contract):
    # 决定请求的全部内容：身份、所属的项目、事项与 run、种类、阻塞范围、版本、状态、请求的载荷（选项与说明、
    # 涉及的事实引用与种类自己的内容）与回答
    decision_id: str
    project_id: str | None
    work_item_id: str | None
    run_id: str | None
    kind: str
    blocks: str
    version: int
    status: Literal["open", "answered", "withdrawn"]
    requested_at: AwareDatetime
    request: DecisionRequestedPayload
    answer: DecisionAnswerRecord | None


class DecisionList(Contract):
    decisions: list[DecisionView]


def _view(decision: DecisionRequest) -> DecisionView:
    return DecisionView(
        decision_id=decision.decision_id, project_id=decision.project_id, work_item_id=decision.work_item_id,
        run_id=decision.run_id, kind=decision.kind, blocks=decision.blocks, version=decision.version,
        status=decision.status, requested_at=decision.requested_at, request=decision.request,
        answer=None if decision.answer is None else DecisionAnswerRecord(**decision.answer),
    )


def _decisions_list(application: Application, request: DecisionsList) -> Snapshot[DecisionList]:
    position, decisions = saved_decisions(
        application.system.store,
        projects=() if request.project_id is None else (request.project_id,),
        work_items=() if request.work_item_id is None else (request.work_item_id,),
        kinds=() if request.kind is None else (request.kind,),
        statuses=tuple(request.status),
    )
    return Snapshot[DecisionList](position=position,
                                  data=DecisionList(decisions=[_view(item) for item in decisions]))


DECISIONS_LIST = QueryDefinition(
    name="decisions.list", request=DecisionsList, result=DecisionList, handle=_decisions_list,
    changed_by=(EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN),
)

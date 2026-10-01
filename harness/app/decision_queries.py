# 决定请求的查询（设计说明第 4.3 节「外壳」）：列出决定请求，按项目、事项、种类与状态筛选（状态可以多选，
# 省略时不限制）；位置是与决定请求在同一个读取事务中看到的日志末尾，按位置读取时等于 at（第 4.1 节）。
# 查询不写入任何内容。

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import AwareDatetime, Field

from ..models import DecisionRequest, EventType
from ..projects import ProjectNotFoundError, project_projection
from ..projection import saved_decisions
from .contracts import CommandId, Contract, Snapshot
from .payloads import DecisionRequestedPayload
from .registry import QueryDefinition
from .replay import ReplayRequest, check_position, decisions_through

if TYPE_CHECKING:
    from .application import Application

class DecisionsList(ReplayRequest):
    # 可回放（设计说明第 4.1 节）：at 是全局位置，省略时读取现在的快照。
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

class BlockedObjects(Contract):
    # 挡住的对象（界面工作线，工单 #127）：被阻塞的事项，以及同一项目中排在它后面的事项数量。
    # 阻塞范围为 run 的请求阻塞它所在的事项；项目层面的请求（项目流中）没有具体事项时为空
    work_item_id: str | None
    queued_after: int

class DecisionView(Contract):
    # 决定请求的全部内容：身份、所属的项目、事项与 run、种类、阻塞范围、版本、状态、请求的载荷（选项与说明、
    # 涉及的事实引用与种类自己的内容）与回答；发出时间（界面据此显示已经等待的时长）与挡住的对象
    decision_id: str
    project_id: str | None
    work_item_id: str | None
    run_id: str | None
    kind: str
    blocks: str
    version: int
    status: Literal["open", "answered", "withdrawn"]
    requested_at: AwareDatetime
    blocked: BlockedObjects | None
    request: DecisionRequestedPayload
    answer: DecisionAnswerRecord | None

class DecisionList(Contract):
    decisions: list[DecisionView]

def _view(decision: DecisionRequest, blocked: BlockedObjects | None) -> DecisionView:
    return DecisionView(
        decision_id=decision.decision_id, project_id=decision.project_id, work_item_id=decision.work_item_id,
        run_id=decision.run_id, kind=decision.kind, blocks=decision.blocks, version=decision.version,
        status=decision.status, requested_at=decision.requested_at, blocked=blocked, request=decision.request,
        answer=None if decision.answer is None else DecisionAnswerRecord(**decision.answer),
    )

def _decisions_list(application: Application, request: DecisionsList) -> Snapshot[DecisionList]:
    store = application.system.store
    through = check_position(application, request.at)
    if through is None:
        position, decisions = saved_decisions(
            store,
            projects=() if request.project_id is None else (request.project_id,),
            work_items=() if request.work_item_id is None else (request.work_item_id,),
            kinds=() if request.kind is None else (request.kind,),
            statuses=tuple(request.status),
        )
    else:
        position = through
        decisions = [
            item for item in decisions_through(store, through)
            if (request.project_id is None or item.project_id == request.project_id)
            and (request.work_item_id is None or item.work_item_id == request.work_item_id)
            and (request.kind is None or item.kind == request.kind)
            and (not request.status or item.status in request.status)
        ]
    projects: dict[str, Any] = {}

    def blocked_of(item: DecisionRequest) -> BlockedObjects | None:
        if item.project_id is None:
            return None
        if item.project_id not in projects:
            projects[item.project_id] = _project_at(application, item.project_id, through)
        return _blocked(projects[item.project_id], item)

    return Snapshot[DecisionList](position=position,
                                  data=DecisionList(decisions=[_view(item, blocked_of(item))
                                                               for item in decisions]))

def _project_at(application: Application, project_id: str, through: int | None) -> Any | None:
    try:
        return project_projection(application.system.store, application.system.artifacts, project_id,
                                  through=through)
    except ProjectNotFoundError:
        return None

def _blocked(state: Any, decision: DecisionRequest) -> BlockedObjects | None:
    # 决定请求挡住的对象：被阻塞的事项，以及同一项目中排在它后面、还没有开始的事项数量（工单 #127）
    if state is None or decision.work_item_id is None:
        return None
    order = [item.work_item_id for item in state.work_items]
    blocked_id = decision.work_item_id
    if blocked_id not in order:
        return None
    after = order[order.index(blocked_id) + 1:]
    queued_after = sum(1 for item in state.work_items
                       if item.work_item_id in after and item.status in {"not_started", "held"})
    return BlockedObjects(work_item_id=blocked_id, queued_after=queued_after)

DECISIONS_LIST = QueryDefinition(
    name="decisions.list", request=DecisionsList, result=DecisionList, handle=_decisions_list,
    changed_by=(EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN),
    replayable=True,
)

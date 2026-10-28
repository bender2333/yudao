# 第二种路由：任务池（工单 #864；骨架与应用设计说明第 3.2、5.1、5.4 节「证明」；总图第四节「路由」缝）。
#
# **只在测试里用，产品代码不导入它。** 它证明的是骨架：同一副骨架接上另一套应用——形状像任务池的路由，
# 有自己的那份定义（`harness/tests/task_pool_definitions/`，用 `load_definitions(<测试目录>)` 加载）、
# 自己的成果种类、自己的提议方式、自己的应用事件种类与自己声明的结束原因；产品的 `harness/definitions/`
# 一个条目都不加，骨架的模块一行不改。
#
# 形状：
# - 发任务的部门把用户的输入写成池子里的一条任务（提议方式 `submit_task`，成果种类 `pool_task`）；
# - 路由把池子里待办的任务**指派**给能做它的部门：这一轮工作的路由自己的工作引用就是那件任务
#   （设计说明第 5.1 节输出、第 5.4 节第 4 条，原样交给装配与执行）；
# - 领到任务的部门交完成说明（`complete_task` / `task_completion`）；
# - 另一个部门给结论：接纳或者打回（`judge_task` / `task_verdict`）。打回以后任务回到池子，由完成它的
#   部门重做。完成一件事的部门不能自己宣布它合格（基础规则 3）：这一条由本路由的收紧检查判（第 5.5 节
#   「路由提供收紧检查」），不靠内核。
# - 池子里没有待办的任务时事项结束，结束原因是**它自己那份定义里声明的** `pool_drained`
#   （设计说明第 5.4 节第 7 条，不进内核的停止原因清单）。
#
# 成果怎么被接纳（2026-10-28 总架构师补的做法）：三种成果都不新增内核事件种类，经工具许可与提案校验以后
# 写通用的一种「成果接纳」事件（`artifact_accepted`，S2c 工单 #1098），最小投影按它带的统一字段折叠出
# 当前版本。路由自己的应用事件种类按 #828 的登记方式登记，不进骨架事件的登记表。
#
# 状态从事件折叠：路由自己从运行流的事件折出池子的现状（设计说明第 5.1 节输入），不保存事件之外的状态。
# 契约给的入口是运行流的投影，而投影不折叠通用的成果接纳事件（见 docs/architecture-issues.md 2026-10-28
# 的一条），所以这里让组装处在测试里把只读的事件库交给它：`bind(store)`。

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness import kernel_events, routing_contract, tightening_contract
from harness.definitions import Definitions, load_definitions
from harness.kernel_events import Event, canonical_hash
from harness.models import EventType
from harness.tools import offers_with_input, proposal_kinds, tools_for
from harness.validation import FieldError, TightenRequest, Tightened

# 这个应用的名字：登记自己的事件种类与路由实现时用它（#828 的登记方式）
APPLICATION = "只在测试里用的任务池路由（工单 #864）"

# 这一份定义只在测试目录里（2026-10-28 总架构师补的做法）：不去动产品的 harness/definitions/
DEFINITIONS_DIR = Path(__file__).parent / "task_pool_definitions"
DEFINITIONS: Definitions = load_definitions(DEFINITIONS_DIR)

# 组织定义 organization.json 的 routing 里写这个名称
ROUTING_NAME = "task_pool"

# 三种成果的种类：由 tools.json 里的提交类工具提交，写通用的一种成果接纳事件（S2c）
TASK_KIND = "pool_task"
COMPLETION_KIND = "task_completion"
VERDICT_KIND = "task_verdict"
# 结论的两个取值：接纳、打回
ACCEPT = "accept"
RETURN = "return"

# 路由自己的应用事件种类（设计说明第 5.4 节第 1 条、第 7 节）：任务池自己记的两件事——一件任务被指派出去、
# 一件任务被打回以后回到池子。登记归登记，内核不解释它们的内容；它们不进骨架事件的那张表
TAKEN_EVENT = "task_pool_task_taken"
RETURNED_EVENT = "task_pool_task_returned"
APPLICATION_EVENT_KINDS = (TAKEN_EVENT, RETURNED_EVENT)
kernel_events.register_application_event_types(APPLICATION, APPLICATION_EVENT_KINDS)

# 事项结束用的原因：写在 routings.json 的那一条里，属于那份路由定义版本的封闭清单
ITEM_END_REASON = "pool_drained"

# 这个路由自己的部门与提议方式（它自己那份定义里写的）：一次只让一个部门开始一轮工作，按这里的顺序挑
_DEPARTMENTS = tuple(DEFINITIONS.routing_definition().departments)
_PROPOSAL_METHODS = frozenset(DEFINITIONS.routing_definition().proposal_methods)

# 一轮没有正常结束的两种状态：暂停与失败（与成果驱动同一个口径，设计说明第 5.3 节输出）
_NOT_A_NORMAL_ROUND_END = frozenset({"paused", "failed"})


# ---------------------------------------------------------------------------
# 池子的现状：从运行流的事件折出来，不保存事件之外的状态
# ---------------------------------------------------------------------------


@dataclass
class PoolState:
    # 发出来的任务（按发布的先后）、交上来的完成说明与它们各自的结论（都按事件的先后）
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    completions: list[dict[str, Any]] = field(default_factory=list)
    verdicts: list[dict[str, Any]] = field(default_factory=list)

    def completions_of(self, task_id: str) -> list[dict[str, Any]]:
        return [item for item in self.completions if item.get("task") == task_id]

    def verdict_of(self, completion: dict[str, Any]) -> dict[str, Any] | None:
        # 一份完成说明的结论：按结论记下的那份完成说明的内容摘要找；还没有结论时为空
        content_hash = completion.get("content_hash")
        return next((item for item in self.verdicts if item.get("completion") == content_hash), None)

    def open_task(self) -> str | None:
        # 池子里第一件还能做的任务：还没有人交，或者最近一份完成说明被打回了
        for task_id in self.tasks:
            completions = self.completions_of(task_id)
            if not completions:
                return task_id
            verdict = self.verdict_of(completions[-1])
            if verdict is not None and verdict.get("verdict") == RETURN:
                return task_id
        return None

    def pending_completion(self) -> dict[str, Any] | None:
        # 交上来还没有结论的完成说明（最后一份）：验收的部门这一轮要给它一个结论
        for completion in reversed(self.completions):
            if self.verdict_of(completion) is None:
                return completion
        return None

    def drained(self) -> bool:
        # 池子里没有待办的任务：每一件任务都有了接纳的结论
        return self.open_task() is None and self.pending_completion() is None


def fold(events: list[Event]) -> PoolState:
    """从运行流的事件折出池子的现状（设计说明第 5.1 节输入）。

    三种成果都写在通用的成果接纳事件里（S2c 工单 #1098）：种类与作者部门都在载荷的统一字段里，
    内容由本路由的收紧检查组装。内核不解释它们，这里也不读最小投影。
    """
    state = PoolState()
    for event in events:
        if event.type != EventType.ARTIFACT_ACCEPTED:
            continue
        payload = dict(event.payload or {})
        kind = payload.get("artifact_kind")
        if kind == TASK_KIND:
            state.tasks.setdefault(str(payload.get("task")), payload)
        elif kind == COMPLETION_KIND:
            state.completions.append(payload)
        elif kind == VERDICT_KIND:
            state.verdicts.append(payload)
    return state


def _task_id(title: str) -> str:
    # 一件任务的编号由它的标题定：同一次提交在提案校验与提交判断里各算一次，两次要得出同一个编号
    return "task-" + canonical_hash({"title": title})[len("sha256:"):][:12]


def _text(proposal: dict[str, Any], field_name: str) -> str:
    value = proposal.get(field_name)
    return value.strip() if isinstance(value, str) else ""


# ---------------------------------------------------------------------------
# 谁能开工：路由按池子的现状指派
# ---------------------------------------------------------------------------


def open_kinds(state: PoolState, department: str) -> set[str]:
    """这个部门此刻能为池子交的那几种成果。

    发任务的部门在没有任务时发一件任务；领任务的部门拿到待办的任务时交完成说明；
    验收的部门在有完成说明等着结论时给结论——完成它的部门不能给（基础规则 3）。
    """
    kinds: set[str] = set()
    if department == _publishing_department():
        if not state.tasks:
            kinds.add(TASK_KIND)
        return kinds
    if department == _working_department():
        if state.open_task() is not None:
            kinds.add(COMPLETION_KIND)
        return kinds
    if department == _judging_department():
        pending = state.pending_completion()
        if pending is not None and pending.get("artifact_issuer") != department:
            kinds.add(VERDICT_KIND)
    return kinds


def _department_with(kind: str) -> str:
    # 交得出这种成果的部门：它的工具清单里有提交这种成果的工具（部门身份取自定义，不写死名称）。
    # 任务池跑的是普通事项（work_items.json 的 change），部门工具清单按它取
    for department in _DEPARTMENTS:
        if kind in proposal_kinds(department, "change", definitions=DEFINITIONS):
            return department
    raise routing_contract.InvalidRoutingDefinition(
        ROUTING_NAME, [f"proposal_methods：没有部门能交 {kind}"])


def _publishing_department() -> str:
    return _department_with(TASK_KIND)


def _working_department() -> str:
    return _department_with(COMPLETION_KIND)


def _judging_department() -> str:
    return _department_with(VERDICT_KIND)


def _free(department: str, waiting: set[str] | None) -> bool:
    # 部门在等待工作：给出时按它判断，没有给出时按「可以开工」处理
    return True if waiting is None else department in waiting


def work_reference(state: PoolState, department: str) -> Any:
    """这一轮工作的路由自己的工作引用（设计说明第 5.1 节输出、第 5.4 节第 4 条）：指派给它的那件任务。

    发任务的一轮没有任务可指派（任务由这一轮写出来），为空。原样交给装配与执行，骨架不解释它。
    """
    if department == _working_department():
        task_id = state.open_task()
        if task_id is None:
            return None
        return {"task": task_id, "title": state.tasks[task_id].get("title")}
    if department == _judging_department():
        pending = state.pending_completion()
        if pending is None:
            return None
        return {"task": pending.get("task"), "completion": pending.get("content_hash")}
    return None


# ---------------------------------------------------------------------------
# 一轮、事项以什么结束
# ---------------------------------------------------------------------------


def submitted_in_round(events: list[Event], *, session_id: str | None, activation_id: str) -> bool:
    """这一轮经本路由的提议方式交上了东西没有：提交被接纳记 proposal_accepted，其余正常结束记 text_reply。

    判据是这一轮写下的事件（与成果驱动同一个口径）：提交经写入口写入时看提交与拒绝的事件；提交还没有
    写入时（薄驱动拿到一轮结果以后先问路由，再经写入口提交）看这一轮记下的提议方式——提交类工具的调用。
    """
    started = None
    for index, event in enumerate(events):
        if (event.type == EventType.DEPARTMENT_ACTIVATED and event.session_id == session_id
                and (event.payload or {}).get("activation_id") == activation_id):
            started = index
            break
    submitted = False
    for event in ([] if started is None else events[started + 1:]):
        if event.session_id != session_id:
            continue
        if event.type == EventType.PROPOSAL_SUBMITTED:
            submitted = True
        elif event.type == EventType.PROPOSAL_REJECTED:
            submitted = False
        elif (event.type == EventType.TOOL_CALLED
              and (event.payload or {}).get("name") in _PROPOSAL_METHODS):
            submitted = True
    return submitted


def check_definition(definitions: Any) -> None:
    """校验任务池这份定义的内容（设计说明第 5.4 节第 2 条）：内核只核对结构，内容归路由自己。"""
    declared = routing_contract.definition_of(definitions, ROUTING_NAME)
    if declared is None:
        raise routing_contract.InvalidRoutingDefinition(
            ROUTING_NAME, ["routings.json：没有这一种路由的定义"])
    issues: list[str] = []
    departments = tuple(item.id for item in definitions.organization.departments)
    for index, department in enumerate(declared.departments):
        if department not in departments:
            issues.append(f"departments[{index}]：部门 {department} 不在组织定义里")
    for department in departments:
        if department not in declared.departments:
            issues.append(f"departments：组织定义里的部门 {department} 没有列进路由的部门清单")
    for index, method in enumerate(declared.proposal_methods):
        if method not in definitions.tools or definitions.tools[method].proposal is None:
            issues.append(f"proposal_methods[{index}]：工具 {method} 不是定义里的提交类工具")
    submitted = [definitions.tools[method].proposal for method in declared.proposal_methods
                 if method in definitions.tools and definitions.tools[method].proposal is not None]
    for index, kind in enumerate(declared.outcome_kinds):
        if kind not in submitted:
            issues.append(f"outcome_kinds[{index}]：成果种类 {kind} 没有由这里列出的提议方式提交")
    for kind in [tool.proposal for tool in definitions.tools.values() if tool.proposal is not None]:
        if kind not in declared.outcome_kinds:
            issues.append(f"outcome_kinds：提交类工具提交的成果种类 {kind} 没有列进成果种类")
    for reason in declared.end_reasons:
        if reason in definitions.stop_reasons:
            issues.append(f"end_reasons.{reason}：与内核的停止原因同名")
    if ITEM_END_REASON not in declared.end_reasons:
        issues.append(f"end_reasons：没有声明事项结束用的原因 {ITEM_END_REASON}")
    if issues:
        raise routing_contract.InvalidRoutingDefinition(ROUTING_NAME, issues)


class TaskPool:
    """任务池路由（路由契约第二版的第二种实现）。

    实现在测试里；薄驱动只按契约的三个问题调用它。它读运行流的事件折出池子的现状，不写事件、不调模型、
    不核对边界、不执行工具（设计说明第 5.1 节「不做」）。
    """

    NAME = ROUTING_NAME
    CONTRACT_VERSION = routing_contract.CURRENT_VERSION

    def __init__(self) -> None:
        # 只读事件库由组装处在测试里交给它：契约给的入口只有运行流的投影，投影不折叠通用的成果接纳事件
        self._store: Any = None

    def bind(self, store: Any) -> "TaskPool":
        """把只读的事件库交给这个路由（测试的组装处做这件事；产品里由运行时的组装处做）。"""
        self._store = store
        return self

    # ---- 配置 ----

    def definitions(self) -> Definitions:
        return DEFINITIONS

    def state(self, run_id: str) -> PoolState:
        if self._store is None:
            raise RuntimeError("the task pool routing needs the read-only event store: bind(store) first")
        return fold(list(self._store.list_events(run_id)))

    # ---- 契约 ----

    def check_definition(self, definitions: Any) -> None:
        check_definition(definitions)

    def ready_departments(self, view: Any, *, waiting: set[str] | None = None) -> list[str]:
        # 一次一个部门：池子的指派按定义里的部门顺序挑第一个能做这件事的，几轮之间没有并列
        department = self.next_department(view, waiting=waiting)
        return [] if department is None else [department]

    def next_department(self, view: Any, *, waiting: set[str] | None = None) -> str | None:
        state = self.state(view.run_id)
        for department in _DEPARTMENTS:
            if not _free(department, waiting):
                continue
            if open_kinds(state, department):
                return department
        return None

    def department_ready(self, view: Any, *, department: str,
                         waiting: set[str] | None = None) -> bool:
        if not _free(department, waiting):
            return False
        return bool(open_kinds(self.state(view.run_id), department))

    def work_reference(self, view: Any, *, department: str) -> Any:
        return work_reference(self.state(view.run_id), department)

    def round_end(self, view: Any, events: list[Event], *, department: str, session_id: str | None,
                  activation_id: str) -> routing_contract.RoundEnd | None:
        if view.status in _NOT_A_NORMAL_ROUND_END:
            return None
        submitted = submitted_in_round(events, session_id=session_id, activation_id=activation_id)
        return routing_contract.RoundEnd(outcome="proposal_accepted" if submitted else "text_reply")

    def item_end(self, view: Any) -> routing_contract.ItemEnd | None:
        # 池子里没有待办的任务：事项以这条路由自己声明的结束原因结束（设计说明第 5.4 节第 7 条）
        if not self.state(view.run_id).drained():
            return None
        return routing_contract.ItemEnd(stop_reason=ITEM_END_REASON,
                                        message="no task in the pool is waiting for anyone")

    def ask_branch(self, view: Any, events: list[Event], *, requester: str, session_id: str,
                   call: dict[str, Any], limits: routing_contract.AskLimits):
        # 任务池这一版没有询问：池子里的事都由路由指派，部门之间不互相提问
        return routing_contract.AskRejection(message="the task pool routing has no asks")

    def ask_outcome(self, view: Any, *, branch: routing_contract.AskBranch,
                    result: routing_contract.AskRoundResult) -> routing_contract.AskOutcome:
        return routing_contract.AskOutcome(status="unable", session_id=branch.session_id,
                                           reason="the task pool routing has no asks")


class TaskPoolTightening:
    """任务池的收紧检查（设计说明第 5.5 节「路由提供收紧检查」）：同一条路由的另一半。

    内核的通用检查通过以后，在这个写入事务里由内核问它三件事：这个部门此刻能为池子交哪几种成果、
    请求里提供哪些工具、这一次提交能不能收。三种成果的内容由它组装（格式检查也在这里）。
    基础规则 3「生成者不裁决自己」由它判：交完成说明的部门不能给这份完成说明结论。
    """

    CONTRACT_VERSION = tightening_contract.CURRENT_VERSION

    def definitions(self) -> Definitions:
        return DEFINITIONS

    def kinds(self, request: TightenRequest) -> set[str]:
        state = fold(list(request.events))
        return open_kinds(state, request.department)

    def offered(self, request: TightenRequest) -> list[str]:
        # 部门的工具清单来自它自己那份定义；请求里不再按内容取舍（任务池这一版不排队、不分支）
        names = tools_for(request.department, _kind_of(request.state), definitions=DEFINITIONS)
        return offers_with_input(list(names), request.input_modalities, definitions=DEFINITIONS)

    def tool(self, request: TightenRequest) -> Tightened:
        # 工具许可在内核那一侧（部门有没有这个工具）；这一版没有推迟与等待
        return Tightened()

    def submission(self, request: TightenRequest) -> Tightened:
        proposal = dict(request.proposal or {})
        kind = proposal.get("kind")
        state = fold(list(request.events))
        if kind == TASK_KIND:
            title = _text(proposal, "title")
            if not title:
                return Tightened(errors=(FieldError("title", "a task needs a non-empty title"),))
            return Tightened(content={"task": _task_id(title), "title": title})
        if kind == COMPLETION_KIND:
            task_id = state.open_task()
            if task_id is None:
                return Tightened(reason="no task in the pool is waiting for a completion")
            summary = _text(proposal, "summary")
            if not summary:
                return Tightened(errors=(FieldError("summary", "a completion needs a non-empty summary"),))
            return Tightened(content={"task": task_id, "summary": summary})
        if kind == VERDICT_KIND:
            pending = state.pending_completion()
            if pending is None:
                return Tightened(reason="no completion is waiting for a verdict")
            author = pending.get("artifact_issuer")
            if author == request.department:
                # 基础规则 3：完成一件事的部门不能自己宣布它合格
                return Tightened(reason=(f"{request.department} completed this task and cannot judge it "
                                         "(the author of a completion does not issue its verdict)"))
            verdict = proposal.get("verdict")
            if verdict not in (ACCEPT, RETURN):
                return Tightened(errors=(FieldError("verdict", "a verdict is accept or return"),))
            reason = _text(proposal, "reason")
            if not reason:
                return Tightened(errors=(FieldError("reason", "a verdict needs a non-empty reason"),))
            return Tightened(content={"task": pending.get("task"),
                                      "completion": pending.get("content_hash"),
                                      "verdict": verdict, "reason": reason})
        return Tightened(reason=f"the task pool does not take {kind!r}")


def _kind_of(state: Any) -> str:
    # 事项种类（RunProjection.kind）：部门工具清单按它取；没有给出时按普通事项
    return str(getattr(state, "kind", "change") or "change")


# 实现在模块加载时按名称登记（与 watched_outputs 同样的登记办法）：组织定义的 routing 写 task_pool
ROUTING = routing_contract.register(TaskPool())
TIGHTENING = TaskPoolTightening()

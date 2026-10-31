# 循环与收敛状态的查询（工单 #397，应用层与接口层设计说明第 4.3 节 `run.loops`）：按运行实例标识请求
# 一个事项树的投影。投影本身在 harness/loops.py（纯函数、只读）；这一层只负责取事件、按位置回放与把结果
# 换成接口合同，不另行计数，也不做判定。
#
# 可回放：at 是全局位置，按它截取 run 的事件以后重算，跨会话重放同一段事件流得到同一棵树。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .. import loops
from .contracts import Contract, Snapshot
from .project_queries import NotFound
from .registry import QueryDefinition, UnchangedEvent
from .replay import ReplayRequest, check_position

if TYPE_CHECKING:
    from .application import Application


class LoopAmount(Contract):
    # 一个已用量与它的上限：不设上限时仍然带数值，unlimited 为真（画面显示「不设上限」）
    used: int
    limit: int
    unlimited: bool


class LoopFact(Contract):
    # 一条被接纳的主机事实：种类与它所在事件的全局位置
    kind: str
    position: int


class LoopStep(Contract):
    # 一步 = 一次模型请求：请求时间、尝试次数、被接纳的事实与这一步发出的调用（名称与参数摘要）
    step_id: int
    activation_id: str
    purpose: str
    requested_at: str
    attempts: int
    accepted: bool
    facts: list[LoopFact]
    calls: list[str]


class LoopActivation(Contract):
    # 一次激活：开始与结束时间、部门、判定（本工单为不判定）与缺失的事实、步骤
    activation_id: str
    department: str | None
    started_at: str
    finished_at: str | None
    state: str
    missing: str
    steps: list[LoopStep]


class LoopLayer(Contract):
    # 树的一层：名称、判定、不判定时缺少的事实与这一层的已用量
    name: str
    state: str
    missing: str | None
    amounts: dict[str, LoopAmount]


class LoopTrend(Contract):
    # 轮数达到方法常量时改用趋势检验的说明：方法与两个固定常量、秩相关系数与它还缺少的事实
    method: str
    switch_rounds: int
    flip_threshold: int
    rho: float
    step_state: str
    note: str


class RunLoopsResult(Contract):
    # 一个事项树的投影：五层、激活与步骤、三项冻结参数、方法常量、轮数与趋势检验
    run_id: str
    project_id: str | None
    work_item_id: str | None
    status: str
    stop_reason: str | None
    parameters: dict[str, int]
    method: dict[str, int]
    layers: list[LoopLayer]
    activations: list[LoopActivation]
    rounds: int
    trend: LoopTrend | None


class RunLoops(ReplayRequest):
    # 可回放（设计说明第 4.1 节）：at 是全局位置，省略时读取现在的树
    run_id: str


def _amount(values: Any) -> LoopAmount:
    return LoopAmount(used=values.used, limit=values.limit, unlimited=values.unlimited)


def _step(step: loops.Step) -> LoopStep:
    return LoopStep(
        step_id=step.step_id, activation_id=step.activation_id, purpose=step.purpose,
        requested_at=step.requested_at, attempts=step.attempts, accepted=step.accepted,
        facts=[LoopFact(kind=fact.kind, position=fact.position) for fact in step.facts],
        calls=list(step.calls),
    )


def _activation(activation: loops.Activation) -> LoopActivation:
    return LoopActivation(
        activation_id=activation.activation_id, department=activation.department,
        started_at=activation.started_at, finished_at=activation.finished_at,
        state=activation.state, missing=activation.missing,
        steps=[_step(step) for step in activation.steps],
    )


def _layer(layer: loops.Layer) -> LoopLayer:
    return LoopLayer(
        name=layer.name, state=layer.state, missing=layer.missing,
        amounts={name: _amount(value) for name, value in layer.amounts.items()},
    )


def _trend(trend: Any) -> LoopTrend | None:
    if trend is None:
        return None
    return LoopTrend(
        method=str(trend["method"]), switch_rounds=int(trend["switch_rounds"]),
        flip_threshold=int(trend["flip_threshold"]), rho=float(trend["rho"]),
        step_state=str(trend["step_state"]), note=str(trend["note"]),
    )


def _run_loops(application: Application, request: RunLoops) -> Snapshot[RunLoopsResult]:
    store = application.system.store
    through = check_position(application, request.at)
    events = store.list_events(request.run_id, through_position=through)
    if not events:
        raise NotFound(f"没有这个运行：{request.run_id}")
    tree = loops.build_loop_tree(events)
    return Snapshot[RunLoopsResult](
        position=store.end_position() if through is None else through,
        data=RunLoopsResult(
            run_id=tree.run_id, project_id=tree.project_id, work_item_id=tree.work_item_id,
            status=tree.status, stop_reason=tree.stop_reason,
            parameters=dict(tree.parameters), method=dict(tree.method),
            layers=[_layer(layer) for layer in tree.layers],
            activations=[_activation(activation) for activation in tree.activations],
            rounds=tree.rounds, trend=_trend(tree.trend),
        ),
    )


RUN_LOOPS = QueryDefinition(
    name="run.loops", request=RunLoops, result=RunLoopsResult, handle=_run_loops,
    replayable=True,
    changed_by=(
        # 五层树的成员与被接纳的事实：建 run、激活的开始与结束、每一步的请求、工具回执、询问获答、
        # 成果接纳与 run 的结束都改变它的结果
        "run_created", "department_activated", "activation_finished", "model_requested", "tool_called",
        "ask_answered", "artifact_accepted", "spec_accepted", "contract_accepted", "delivery_accepted",
        "qa_submitted", "structure_accepted", "baseline_review_accepted", "product_decision_accepted",
        "run_done", "run_paused", "run_failed", "run_continued", "run_resumed",
    ),
    unchanged_by=(
        UnchangedEvent("compaction_recorded", "压缩步不改变被接纳的事实、步骤构成与已用量"),
        UnchangedEvent("model_stream_progress", "流式进度不改变树：它不写事实，也不构成一步"),
        UnchangedEvent("model_message", "模型的文字不参与判定：进展只按主机记录的事实"),
        UnchangedEvent("model_reasoning", "模型的推理不参与判定：中心角色的陈述只作参考"),
    ),
)

# 循环与收敛状态的只读投影（工单 #397，循环与收敛设计说明第 5、5.1 节；总图第三节的边界、停止与
# 子循环）：只由事件计算，不写事实、不调用模型。判定是确定的阈值规则，短序列的趋势不交给模型。
#
# 五层：项目循环 → 事项（项目循环的一轮，事项树的根）→ run → 激活 → 步骤。步骤以一次模型请求为单位
# （重试与它重试的那一步算一步，按 root_step_id 归组）。已用量复用最小投影的事件折叠结果，这里不另行
# 计数；run 层的逐条核验结论由 #1194 接入，本工单在这一格只给「不判定」与缺少的事实。三项判定参数在
# 建 run 时冻结（工单 #1189），这里从 run_created 的冻结字典里取。
#
# 「被接纳的主机事实」四类：成果接纳、检查回执、改变工作区树的写入、询问获答。压缩步、失败的模型调用与
# 没有改变事实的读取都不算。中心角色自己的进展陈述不参与判定。

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .definitions import DEFINITIONS
from .minimal_projection import MinimalProjection, fold_events
from .models import Event, EventType, json_dumps
from .parameters import frozen_values

# 三项可登记、可在创建循环实例时冻结的运行参数（设计第 5.1 节）
CONVERGENCE_ROUNDS = "convergence.rounds"
STEP_WINDOW = "convergence.step_window"
STEP_REPEAT = "convergence.step_repeat"
CONVERGENCE_PARAMETERS = (CONVERGENCE_ROUNDS, STEP_WINDOW, STEP_REPEAT)

# 判定方法的固定常量（同一事件流不因配置差异选择不同统计方法）：轮数达到 8 改用秩相关的趋势检验，
# 同一条件的结论翻转达到 2 次算震荡
TREND_SWITCH_ROUNDS = 8
FLIP_THRESHOLD = 2

# 限额类停止原因（封闭清单）：达到边界只看停止原因，不比较已用数值与上限
LIMIT_STOP_REASONS = ("time_limit", "max_cycles", "model_steps_exhausted")

CONVERGING = "converging"
STALLED = "stalled"
OSCILLATING = "oscillating"
BOUNDARY = "boundary"
# 本工单不判定的层与状态（写明缺少的事实，设计第 5 节末段）
UNDETERMINED = "undetermined"

FACT_ARTIFACT = "artifact"
FACT_CHECK = "check"
FACT_WRITE = "write"
FACT_ANSWER = "answer"

# 成果接纳事件（设计：「成果被接纳」）：通用成果与现有的几种成果各一条，只增
ACCEPTANCE_EVENTS = (
    EventType.ARTIFACT_ACCEPTED, EventType.SPEC_ACCEPTED, EventType.CONTRACT_ACCEPTED,
    EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED, EventType.STRUCTURE_ACCEPTED,
    EventType.BASELINE_REVIEW_ACCEPTED, EventType.PRODUCT_DECISION_ACCEPTED,
)

MISSING_PROJECT = "项目层缺少故障记录：运维记录故障以后判定"
MISSING_WORK_ITEM = "事项层缺少计划条目完成的主机事实"
MISSING_RUN = "run 层缺少逐条核验结论：核验角色提交带逐条结论的放行记录以后判定"
MISSING_RUN_WINDOW = "run 层缺少事实：逐条核验结论还没满一个判定窗口（{rounds} 轮）"
MISSING_RUN_RISING = "run 层未满足数在上升：判定规则没有定义这一状态"
MISSING_ACTIVATION = "激活层缺少计划条目完成的主机事实"


@dataclass(frozen=True)
class Limit:
    # 一个已用量与它的上限：不设上限时仍然带数值，unlimited 为真（设计第 5 节末，画面显示「不设上限」）
    used: int
    limit: int
    unlimited: bool


@dataclass(frozen=True)
class Fact:
    # 一条被接纳的主机事实：种类与它所在事件的全局位置
    kind: str
    position: int


@dataclass(frozen=True)
class Step:
    # 一步 = 一次模型请求（重试与它重试的那一步算一步）：请求时间、尝试次数、被接纳的事实与这一步发出的
    # 调用（名称与参数摘要，用于震荡）；accepted 表示这一步有被接纳的主机事实
    step_id: int
    activation_id: str
    purpose: str
    requested_at: str
    attempts: int
    facts: tuple[Fact, ...]
    calls: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return len(self.facts) > 0


@dataclass(frozen=True)
class Activation:
    # 一次激活：开始与结束时间、部门、步骤与这一层的判定（本工单为不判定，写明缺少的事实）
    activation_id: str
    department: str | None
    started_at: str
    finished_at: str | None
    steps: tuple[Step, ...]
    state: str = UNDETERMINED
    missing: str = MISSING_ACTIVATION


@dataclass(frozen=True)
class Layer:
    # 树的一层：名称、判定、不判定时缺少的事实与这一层的已用量
    name: str
    state: str
    missing: str | None = None
    amounts: Mapping[str, Limit] = field(default_factory=dict)


@dataclass(frozen=True)
class LoopTree:
    # 一个事项树的投影：五层、激活与步骤、三项冻结参数、方法常量、轮数、趋势检验的说明与快照位置
    run_id: str
    project_id: str | None
    work_item_id: str | None
    status: str
    stop_reason: str | None
    parameters: Mapping[str, int]
    method: Mapping[str, int]
    layers: tuple[Layer, ...]
    activations: tuple[Activation, ...]
    rounds: int
    trend: Mapping[str, Any] | None
    position: int


def frozen_convergence_parameters(events: Sequence[Event]) -> dict[str, int]:
    # 建 run 时冻结的三项判定参数：取 run_created 里的冻结字典（工单 #1189），旧事件没有字典时按定义初值
    values = frozen_values(_frozen(events))
    return {name: int(values[name]) for name in CONVERGENCE_PARAMETERS}


def rank_trend(values: Sequence[float]) -> float:
    # 秩相关系数（Spearman）：轮数达到 TREND_SWITCH_ROUNDS 时用这个固定方法看趋势，不用可调参数；
    # 下降为负、上升为正，并列取平均秩
    count = len(values)
    if count < 2:
        return 0.0
    ranks = _ranks(values)
    mean = (count + 1) / 2
    numerator = sum((index + 1 - mean) * (rank - mean) for index, rank in enumerate(ranks))
    denominator = sum((index + 1 - mean) ** 2 for index in range(count))
    return 0.0 if denominator == 0 else numerator / denominator


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2 + 1
        for index in order[position:end + 1]:
            ranks[index] = average
        position = end + 1
    return ranks


def limit_amount(used: int, rule_name: str, limit: int) -> Limit:
    # 一个已用量与它的上限：上限达到该参数登记界限的上沿、且登记说明它拦截不到失败时标为不设上限；
    # 无论是否不设上限都带数值（设计第 5 节末）
    rule = DEFINITIONS.rules.get(rule_name)
    bounds = tuple(getattr(rule, "bounds", ()) or ())
    unlimited = bool(bounds) and limit >= bounds[-1] and "拦截不到任何失败" in getattr(rule, "guards", "")
    return Limit(used=used, limit=limit, unlimited=unlimited)


def step_state(steps: Sequence[Step], *, window: int, repeat: int, stop_reason: str | None) -> str:
    # 步骤层的判定（设计第 5 节）：停止原因属于限额类 → 达到边界；最近一个步骤窗口内同一调用达到重复
    # 次数 → 震荡；窗口内有被接纳的记录 → 收敛中；窗口满了都没有 → 停滞；步数还没满一个窗口 → 不判定
    if stop_reason in LIMIT_STOP_REASONS:
        return BOUNDARY
    recent = [step for step in steps if step.purpose != "compaction"][-window:]
    if len(recent) < window:
        return UNDETERMINED
    counts: dict[str, int] = {}
    for step in recent:
        for call in step.calls:
            counts[call] = counts.get(call, 0) + 1
    if any(count >= repeat for count in counts.values()):
        return OSCILLATING
    if any(step.accepted for step in recent):
        return CONVERGING
    return STALLED


def missing_for_step(steps: Sequence[Step], *, window: int, state: str) -> str | None:
    # 步骤层不判定时写明缺少的事实：步数还没满一个窗口
    if state != UNDETERMINED:
        return None
    return f"步骤层缺少事实：步数还没满一个判定窗口（{window} 步）"


def _reviews(events: Sequence[Event]) -> list[Mapping[str, Any]]:
    # 放行记录：qa_submitted 事件上的逐条结论与覆盖数（验证的独立性设计说明第 7.1 节，工单 #151/#1194）。
    # 旧事件没有这两项，交给 run_state 当作「缺少逐条结论」
    return [event.payload for event in events
            if event.type == EventType.QA_SUBMITTED and isinstance(event.payload, dict)]


def _flips(reviews: Sequence[Mapping[str, Any]]) -> int:
    # 同一条验收条件的结论在窗口里翻转了几次（相邻两轮不同即一次）；取翻转最多的一条
    results: dict[str, list[str]] = {}
    for review in reviews:
        for item in review.get("criteria") or ():
            if not isinstance(item, dict):
                continue
            criterion = str(item.get("criterion") or "")
            results.setdefault(criterion, []).append(str(item.get("result") or ""))
    return max((sum(1 for earlier, later in zip(sequence, sequence[1:]) if earlier != later)
                for sequence in results.values()), default=0)


def run_state(reviews: Sequence[Mapping[str, Any]], *, rounds: int,
              stop_reason: str | None) -> tuple[str, str | None]:
    # run 层的判定（设计第 5 节，工单 #1194）：只按放行记录里算好的覆盖数——未满足数 =
    # coverage.executable − coverage.covered（可执行检验里还没在当前快照上运行并通过的条数），
    # 不重新算逐条结论、不读文件。停止原因属于限额类 → 达到边界；没有逐条结论的旧 run 不判定并写明
    # 缺少的事实；窗口里同一条结论翻转达到方法常量 → 震荡；未满足数严格下降或为 0 → 收敛中；
    # 不变 → 停滞；轮数达到趋势检验的固定轮数时用秩相关（下降收敛中、不变停滞）；
    # 上升在设计里没有对应状态，按不判定并写明（自定的边界，记在日记里）
    if stop_reason in LIMIT_STOP_REASONS:
        return BOUNDARY, None
    usable = [review for review in reviews
              if isinstance(review.get("coverage"), dict) and isinstance(review.get("criteria"), list)]
    if not usable:
        return UNDETERMINED, MISSING_RUN
    window = usable[-max(rounds, 2):]
    unsatisfied = [int(review["coverage"].get("executable", 0)) - int(review["coverage"].get("covered", 0))
                   for review in window]
    if unsatisfied[-1] <= 0:
        return CONVERGING, None
    if len(window) < 2:
        return UNDETERMINED, MISSING_RUN_WINDOW.format(rounds=rounds)
    if _flips(window) >= FLIP_THRESHOLD:
        return OSCILLATING, None
    if len(window) >= TREND_SWITCH_ROUNDS:
        rho = rank_trend(unsatisfied)
        if rho < 0:
            return CONVERGING, None
        if rho == 0:
            return STALLED, None
        return UNDETERMINED, MISSING_RUN_RISING
    if all(later < earlier for earlier, later in zip(unsatisfied, unsatisfied[1:])):
        return CONVERGING, None
    if all(later == earlier for earlier, later in zip(unsatisfied, unsatisfied[1:])):
        return STALLED, None
    return UNDETERMINED, MISSING_RUN_RISING


def build_loop_tree(events: Sequence[Event]) -> LoopTree:
    # 从一个 run 的事件（按全局位置）与建 run 时冻结的参数得到五层循环树。只读：不写事件、不调用模型
    ordered = sorted(events, key=lambda event: event.position)
    projection = fold_events(ordered)
    parameters = frozen_convergence_parameters(ordered)
    stop_reason = _stop_reason(ordered) or projection.stop_reason
    activations = _activations(ordered, repeat=parameters[STEP_REPEAT])
    steps = [step for activation in activations for step in activation.steps]
    window = parameters[STEP_WINDOW]
    state = step_state(steps, window=window, repeat=parameters[STEP_REPEAT], stop_reason=stop_reason)
    rounds = projection.used.activations
    amounts = _amounts(ordered, projection)
    run_convergence, run_missing = run_state(_reviews(ordered), rounds=parameters[CONVERGENCE_ROUNDS],
                                             stop_reason=stop_reason)
    layers = (
        Layer(name="project_loop", state=UNDETERMINED, missing=MISSING_PROJECT),
        Layer(name="work_item", state=UNDETERMINED, missing=MISSING_WORK_ITEM),
        Layer(name="run", state=run_convergence, missing=run_missing,
              amounts={"elapsed_ms": amounts["elapsed_ms"], "model_steps": amounts["model_steps"]}),
        Layer(name="activation", state=UNDETERMINED, missing=MISSING_ACTIVATION,
              amounts={"activations": amounts["activations"]}),
        Layer(name="step", state=state, missing=missing_for_step(steps, window=window, state=state),
              amounts={"model_steps": amounts["model_steps"]}),
    )
    return LoopTree(
        run_id=projection.run_id, project_id=projection.project_id, work_item_id=projection.work_item_id,
        status=projection.status, stop_reason=stop_reason, parameters=parameters,
        method={"trend_switch_rounds": TREND_SWITCH_ROUNDS, "flip_threshold": FLIP_THRESHOLD},
        layers=layers, activations=activations, rounds=rounds,
        trend=_trend(rounds, steps, state), position=max((event.position for event in ordered), default=0),
    )


def _stop_reason(events: Sequence[Event]) -> str | None:
    # 停止原因：最后一条结束或等待事件上的原因；限额判定读这条原文
    for event in reversed(events):
        if event.type in (EventType.RUN_DONE, EventType.RUN_PAUSED, EventType.RUN_FAILED):
            return event.payload.get("stop_reason") or event.stop_reason
    return None


def _amounts(events: Sequence[Event], projection: MinimalProjection) -> dict[str, Limit]:
    # 已用量：时间、激活次数与模型步数都取最小投影的折叠结果（不另行计数）；上限取 run_created 与冻结参数
    created = _run_created(events)
    frozen = frozen_values(_frozen(events))
    limit_sec = int(created.get("run_time_limit_sec", 0) or 0)
    max_cycles = int(created.get("max_cycles", 0) or 0)
    model_steps = int(frozen.get("max_model_steps", 0) or 0)
    return {
        "elapsed_ms": limit_amount(projection.used.settled_ms, "run_time_limit_sec", limit_sec * 1000),
        "activations": limit_amount(projection.used.activations, "max_cycles", max_cycles),
        "model_steps": limit_amount(projection.used.model_steps, "max_model_steps", model_steps),
    }


def _run_created(events: Sequence[Event]) -> Mapping[str, Any]:
    for event in events:
        if event.type == EventType.RUN_CREATED:
            return event.payload
    return {}


def _frozen(events: Sequence[Event]) -> Mapping[str, Any] | None:
    frozen = _run_created(events).get("parameters")
    return frozen if isinstance(frozen, Mapping) else None


def _trend(rounds: int, steps: Sequence[Step], state: str) -> Mapping[str, Any] | None:
    # 轮数达到 TREND_SWITCH_ROUNDS 时说明改用趋势检验：这里给步骤层被接纳记录的秩相关；
    # run 层的逐条核验结论与它自己的趋势由 run_state 判定（工单 #1194）
    if rounds < TREND_SWITCH_ROUNDS:
        return None
    accepted = [1.0 if step.accepted else 0.0 for step in steps]
    return {"method": "spearman", "switch_rounds": TREND_SWITCH_ROUNDS, "flip_threshold": FLIP_THRESHOLD,
            "rho": round(rank_trend(accepted), 6), "step_state": state,
            "note": "步骤层的趋势检验：被接纳记录的秩相关"}


def _activations(events: Sequence[Event], *, repeat: int) -> tuple[Activation, ...]:
    # 激活与步骤：按 department_activated 的顺序分组；一步按 (activation_id, root_step_id) 归组。
    # 不是模型请求的事件按位置归到同一部门当前那一步（提案被接纳、询问获答都在那一步之后写入）
    order: list[str] = []
    started: dict[str, str] = {}
    finished: dict[str, str | None] = {}
    departments: dict[str, str | None] = {}
    step_keys: dict[tuple[str, int], dict[str, Any]] = {}
    step_order: list[tuple[str, int]] = []
    current: dict[str | None, tuple[str, int]] = {}
    for event in events:
        kind = event.type
        if kind == EventType.DEPARTMENT_ACTIVATED:
            activation_id = str(event.payload.get("activation_id") or event.event_id)
            if activation_id not in started:
                order.append(activation_id)
                started[activation_id] = str(event.payload.get("activated_at") or event.created_at)
                departments[activation_id] = event.department
                finished[activation_id] = None
            continue
        if kind == EventType.ACTIVATION_FINISHED:
            activation_id = str(event.payload.get("activation_id") or "")
            if activation_id in started:
                finished[activation_id] = event.created_at
            continue
        if kind == EventType.MODEL_REQUESTED:
            activation_id = str(event.payload.get("activation_id") or "")
            root = int(event.payload.get("root_step_id") or event.payload.get("step_id") or 0)
            key = (activation_id, root)
            if key not in step_keys:
                step_keys[key] = {"step_id": root, "activation_id": activation_id,
                                  "purpose": str(event.payload.get("purpose") or "work"),
                                  "requested_at": str(event.payload.get("started_at") or event.created_at),
                                  "attempts": 0, "facts": [], "calls": []}
                step_order.append(key)
            step_keys[key]["attempts"] += 1
            current[event.department] = key
            continue
        key = current.get(event.department)
        if key is None:
            continue
        fact = _fact_of(event)
        if fact is not None:
            step_keys[key]["facts"].append(fact)
        elif kind == EventType.TOOL_CALLED:
            call = _call_identity(event)
            if call is not None:
                step_keys[key]["calls"].append(call)
    steps_by_activation: dict[str, list[Step]] = {activation_id: [] for activation_id in order}
    for key in step_order:
        record = step_keys[key]
        steps_by_activation.setdefault(record["activation_id"], []).append(Step(
            step_id=record["step_id"], activation_id=record["activation_id"], purpose=record["purpose"],
            requested_at=record["requested_at"], attempts=record["attempts"],
            facts=tuple(record["facts"]), calls=tuple(record["calls"])))
    return tuple(
        Activation(activation_id=activation_id, department=departments.get(activation_id),
                   started_at=started[activation_id], finished_at=finished.get(activation_id),
                   steps=tuple(steps_by_activation.get(activation_id, ())))
        for activation_id in order
    )


def _fact_of(event: Event) -> Fact | None:
    # 一条事件是不是被接纳的主机事实：成果接纳、检查回执、改变工作区树的写入、询问获答
    if event.type in ACCEPTANCE_EVENTS:
        return Fact(kind=FACT_ARTIFACT, position=event.position)
    if event.type == EventType.ASK_ANSWERED:
        return Fact(kind=FACT_ANSWER, position=event.position)
    if event.type != EventType.TOOL_CALLED:
        return None
    payload = event.payload
    if "name" not in payload or payload.get("refused"):
        return None
    action = _tool_action(str(payload.get("name")))
    if action == "check":
        return Fact(kind=FACT_CHECK, position=event.position)
    if action == "write" and payload.get("ok"):
        return Fact(kind=FACT_WRITE, position=event.position)
    return None


def _tool_action(name: str) -> str | None:
    tool = DEFINITIONS.tools.get(name)
    return getattr(tool, "action", None) if tool is not None else None


def _call_identity(event: Event) -> str | None:
    # 调用标识：工具名与参数的摘要相同即相同（震荡判定用）；记账事件没有工具名，不算调用
    payload = event.payload
    if "name" not in payload or "args" not in payload:
        return None
    return f"{payload['name']}:{hashlib.sha256(json_dumps(payload.get('args')).encode('utf-8')).hexdigest()[:16]}"

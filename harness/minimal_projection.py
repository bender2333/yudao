# 最小投影（骨架与应用设计说明第 4 节）：裁决只读这一份，由骨架事件折叠而成，纯函数，可以重算。
# 折叠的内容是第 4 节那张表的六项与之后补齐的几样：每条流的当前版本、谁持有执行权、已用的时间与次数、
# 每种正式成果的当前版本与工件引用、运行状态与待回答的决定请求、当前定义版本与参数版本，
# 以及事项种类、项目与事项的编号、上限的数值与每个会话当前这一轮的编号。
#
# 三条不按事件种类逐个写的规则（设计说明第 4 节末尾与第 5.4 节第 6 条）：
# 1. 成果按接纳事件的统一字段（成果种类、版本、依据、内容摘要）折叠，加一种成果种类不改这里的代码，
#    内核也不认识具体有哪几种；契约（contract_accepted）同样是这些字段里的一种。
# 2. 模型步数按「模型请求」事件一条条数（2026-10-25 第 1 条），不读一轮结束事件里的用量字段：
#    进程在一轮中间崩溃时没有结束事件，按请求数算中断以后上限仍然准确。时间与激活次数仍来自一轮工作
#    开始与结束事件里的用量字段，中断那一轮还没结算的运行时间不计（第 2 条）。
# 3. 重试次数不是上限，不在这里（第 4 条）；应用的查询与恢复页改读这一份是 S1e 的事。
#
# 这一张只建模块，不接给裁决用：调用方仍是 RunProjection（S1d、S1e 改读这一份）。

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from .models import Event, EventType


@dataclass(frozen=True)
class UsedAmount:
    # 已用量：已结算的运行时间（毫秒）、激活次数与模型步数
    settled_ms: int = 0
    activations: int = 0
    model_steps: int = 0


@dataclass(frozen=True)
class SessionState:
    # 一个会话的已用量与当前这一轮的编号：检查回执要来自这一轮，所以记下最近一次激活的编号
    settled_ms: int = 0
    activations: int = 0
    model_steps: int = 0
    round_id: str | None = None


@dataclass(frozen=True)
class AcceptedArtifact:
    # 一种正式成果的当前版本：版本号、内容摘要、它依据的成果版本（种类 → 内容摘要）与工件引用
    version: int
    content_hash: str
    basis: dict[str, str] = field(default_factory=dict)
    ref: dict[str, Any] | None = None


@dataclass(frozen=True)
class MinimalProjection:
    # 裁决要读的全部内容。run_id 为空表示还没有读到 run_created 事件
    run_id: str = ""
    project_id: str | None = None
    work_item_id: str | None = None
    work_item_kind: str = "change"
    status: str = "running"
    stop_reason: str | None = None
    definitions_version: str = ""
    parameters_version: str = ""
    max_cycles: int = 0
    run_time_limit_sec: int = 0
    # 执行权编号：每次取得执行权加一，写入方的编号小于流上记录的编号时由写入口拒绝
    execution_right: int = 0
    # 每条流的当前版本，按流名（例如 run:<run_id>）
    stream_versions: dict[str, int] = field(default_factory=dict)
    # 事项一级与会话一级的已用量
    used: UsedAmount = field(default_factory=UsedAmount)
    sessions: dict[str, SessionState] = field(default_factory=dict)
    # 每种正式成果的当前版本，键是定义里的成果种类
    artifacts: dict[str, AcceptedArtifact] = field(default_factory=dict)
    # 还没回答的决定请求，按请求事件的编号
    pending_decisions: tuple[str, ...] = ()


def fold_events(events: Iterable[Event]) -> MinimalProjection:
    # 从骨架事件重算最小投影：同一组事件重算的结果相同，不读时钟、不读定义、不写任何东西
    state = MinimalProjection()
    sessions: dict[str, SessionState] = {}
    artifacts: dict[str, AcceptedArtifact] = {}
    used = UsedAmount()
    stream_versions: dict[str, int] = {}
    execution_right = 0
    pending: list[str] = []
    for event in events:
        if event.stream and event.stream_version:
            stream_versions[event.stream] = event.stream_version
        if event.epoch is not None:
            execution_right = max(execution_right, int(event.epoch))
        state = _fold_run(state, event)
        used, session_id, session = _fold_usage(event, used, sessions, pending)
        if session is not None:
            sessions[session_id] = session
        accepted = _accepted_artifact(event)
        if accepted is not None:
            kind, artifact = accepted
            artifacts[kind] = artifact
    return replace(state, execution_right=execution_right, stream_versions=stream_versions, used=used,
                   sessions=sessions, artifacts=artifacts, pending_decisions=tuple(pending))


def _fold_run(state: MinimalProjection, event: Event) -> MinimalProjection:
    # 事项的编号、种类、冻结的定义与参数版本、上限，以及运行状态。
    # 状态只看事项的状态事件（设计说明第 4 节）：其他事件的前后状态不在这里重新推断
    payload = event.payload if isinstance(event.payload, dict) else {}
    etype = event.type
    if etype == EventType.RUN_CREATED:
        return replace(
            state,
            run_id=state.run_id or event.run_id,
            project_id=payload.get("project_id"),
            work_item_id=payload.get("work_item_id"),
            work_item_kind=str(payload.get("kind", "change")),
            status="running",
            stop_reason=None,
            definitions_version=str(payload.get("definitions_version", "")),
            parameters_version=str(payload.get("parameters_version", "")),
            max_cycles=int(payload.get("max_cycles") or 0),
            run_time_limit_sec=int(payload.get("run_time_limit_sec") or 0),
        )
    if etype == EventType.RUN_DONE:
        return replace(state, status="done", stop_reason=event.stop_reason)
    if etype == EventType.RUN_PAUSED:
        return replace(state, status="paused", stop_reason=event.stop_reason)
    if etype == EventType.RUN_FAILED:
        return replace(state, status="failed", stop_reason=event.stop_reason)
    if etype == EventType.RUN_CONTINUED:
        # 用户处理完暂停的原因以后继续：已用量保持在暂停时的值，不在这里重置
        return replace(state, status="running", stop_reason=None)
    return state


def _fold_usage(event: Event, used: UsedAmount, sessions: dict[str, SessionState],
                pending: list[str]) -> tuple[UsedAmount, str, SessionState | None]:
    # 已用的时间与次数，以及待回答的决定请求；返回更新后的事项已用量、会话编号与会话状态（没有变化时为空）
    payload = event.payload if isinstance(event.payload, dict) else {}
    etype = event.type
    session_id = event.session_id or ""
    if etype == EventType.RUN_CREATED:
        # 事项创建时记下的会话：每个部门一个，还没有激活的会话已用量为零
        created = payload.get("sessions")
        if isinstance(created, dict):
            for name in created.values():
                sessions.setdefault(str(name), SessionState())
        return used, "", None
    if etype == EventType.DEPARTMENT_ACTIVATED:
        # 一轮工作的开始：轮次编号由主线会话递增，询问分支沿用当前的轮次，所以事项一级的激活次数
        # 取出现过的最大轮次编号（询问分支不推进轮次，工单 #857）
        cycle = int(payload.get("cycle") or 0)
        used = replace(used, activations=max(used.activations, cycle))
        session = sessions.get(session_id, SessionState())
        return used, session_id, replace(session, activations=session.activations + 1,
                                         round_id=payload.get("activation_id") or session.round_id)
    if etype == EventType.ACTIVATION_FINISHED:
        # 一轮工作的结束：已结算的运行时间是这一刻为止的累计值，中断的那一段不计
        used = replace(used, settled_ms=max(used.settled_ms, int(payload.get("elapsed_ms") or 0)))
        session = sessions.get(session_id, SessionState())
        return used, session_id, replace(session, settled_ms=max(session.settled_ms,
                                                                 int(payload.get("session_elapsed_ms") or 0)))
    if etype == EventType.MODEL_REQUESTED:
        # 模型步数按请求一条条数（设计说明第 4 节 2026-10-25 第 1 条）
        used = replace(used, model_steps=used.model_steps + 1)
        session = sessions.get(session_id, SessionState())
        return used, session_id, replace(session, model_steps=session.model_steps + 1)
    if etype == EventType.DECISION_REQUESTED:
        pending.append(event.event_id)
        return used, session_id, None
    if etype in (EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN):
        decision_id = payload.get("decision_id")
        if isinstance(decision_id, str) and decision_id in pending:
            pending.remove(decision_id)
        return used, session_id, None
    return used, session_id, None


def _accepted_artifact(event: Event) -> tuple[str, AcceptedArtifact] | None:
    # 成果接纳事件的统一字段：成果种类、版本、依据与内容摘要。不按事件种类逐个写，
    # 所以加一种成果种类（由定义带来）不改这里；没有这组字段的事件不是成果接纳
    payload = event.payload if isinstance(event.payload, dict) else {}
    kind = payload.get("artifact_kind")
    version = payload.get("artifact_version")
    content_hash = payload.get("content_hash")
    if not isinstance(kind, str) or not kind or version is None or not isinstance(content_hash, str):
        return None
    basis = payload.get("artifact_basis")
    ref = payload.get("artifact_ref")
    return kind, AcceptedArtifact(
        version=int(version),
        content_hash=content_hash,
        basis={str(name): str(value) for name, value in basis.items()} if isinstance(basis, dict) else {},
        ref=dict(ref) if isinstance(ref, dict) else None,
    )

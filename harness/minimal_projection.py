# 最小投影（骨架与应用设计说明第 4 节）：裁决只读这一份，由骨架事件折叠而成，纯函数，可以重算。
# 折叠的内容是第 4 节那张表的六项与之后补齐的几样：每条流的当前版本、谁持有执行权、已用的时间与次数、
# 每种正式成果的当前版本与工件引用、运行状态与待回答的决定请求、当前定义版本与参数版本，
# 以及事项种类、项目与事项的编号、上限的数值与每个部门主线会话当前这一轮的编号。
#
# 三条不按事件种类逐个写的规则（设计说明第 4 节末尾与第 5.4 节第 6 条）：
# 1. 成果按接纳事件的统一字段（成果种类、版本、依据、内容摘要、作者部门、记下的树摘要）折叠，
#    加一种成果种类不改这里的代码，内核也不认识具体有哪几种；契约（contract_accepted）同样是这些字段里的一种。
#    成果失效按「成果失效」事件（artifact_invalidated）折叠：失效是记下来的事实，不从这里从别的事件推出，
#    失效以后这种成果没有当前版本，直到它被重新接纳（S1b，工单 #858）。
# 2. 模型步数按「模型请求」事件一条条数（2026-10-25 第 1 条），不读一轮结束事件里的用量字段：
#    进程在一轮中间崩溃时没有结束事件，按请求数算中断以后上限仍然准确。时间与激活次数仍来自一轮工作
#    开始与结束事件里的用量字段，中断那一轮还没结算的运行时间不计（第 2 条）。
# 3. 重试次数不是上限，不在这里（第 4 条）；应用的查询与恢复页改读这一份是 S1e 的事。
#
# 2026-10-27（S1d，工单 #860）为第 5.5 节的六条通用条件补的几样，仍然只来自接纳事件与骨架事件，不是成果的内容：
# - 接纳事件的统一字段加作者部门（issuer）与记下的树摘要（有这一项的成果才带，交付记代码树、建档记快照的树）：
#   通用条件 5 的作者分离与条件 4 的树一致读它们；
# - 一种成果可以多版并存时（现在只有产品决定），按种类记当前有效各版的摘要清单，通用条件 6 读它；
# - 每个部门主线会话当前这一轮的编号按部门取（一轮工作开始事件带部门），通用条件 3 的「回执来自这一轮」读它。
# 不在这里、归收紧检查的：质检测试材料的摘要、PRD 的内容、用户输入与指导的版本（设计说明第 4 节）。

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from .kernel_events import Event, SkeletonEventType

# 事项创建事件里记下的代码树快照在这种成果种类下折叠：建档的树一致条件（通用条件 4）读它的树摘要
SNAPSHOT_KIND = "snapshot"


@dataclass(frozen=True)
class UsedAmount:
    # 已用量：已结算的运行时间（毫秒）、激活次数与模型步数
    settled_ms: int = 0
    activations: int = 0
    model_steps: int = 0


@dataclass(frozen=True)
class SessionState:
    # 一个会话的已用量与结算值、当前这一轮的编号与它属于哪个部门：settled_ms 与 settled_steps 是上一次
    # 一轮工作结束时已结算的那一份（S1e，工单 #1015）；检查回执要来自这一轮，所以留着最近一次激活的编号
    settled_ms: int = 0
    settled_steps: int = 0
    activations: int = 0
    model_steps: int = 0
    round_id: str | None = None
    department: str | None = None


@dataclass(frozen=True)
class AcceptedArtifact:
    # 一种正式成果的一版：版本号、内容摘要、作者部门、记下的树摘要、它依据的成果版本（种类 → 内容摘要）
    # 与工件引用。作者部门与树摘要由接纳事件的统一字段带来，没有这一项的成果为空。
    version: int
    content_hash: str
    issuer: str | None = None
    tree_digest: str | None = None
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
    # 建 run 时冻结的 MCP 服务器设置版本（工单 #236）：最小投影只取版本，不取设置的内容；
    # 旧事件没有这个字段时为 0（空设置）
    mcp_servers_version: int = 0
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
    # 多版并存的成果种类（现在只有产品决定）当前有效的各版；单版的种类只有最新这一版
    versions: dict[str, tuple[AcceptedArtifact, ...]] = field(default_factory=dict)
    # 每种成果最后一次被接纳的那一版，失效以后仍然记着：接下一版时由它给出上一版与版本号（S1d，工单 #860）
    accepted: dict[str, AcceptedArtifact] = field(default_factory=dict)
    # 每个部门主线会话当前这一轮的编号：检查回执要来自这一轮（通用条件 3）
    rounds: dict[str, str] = field(default_factory=dict)
    # 还没回答的决定请求，按请求事件的编号
    pending_decisions: tuple[str, ...] = ()

    def artifact(self, kind: str) -> AcceptedArtifact | None:
        # 这种成果的当前版本（失效以后没有当前版本，直到重新接纳）
        return self.artifacts.get(kind)

    def latest(self, kind: str) -> AcceptedArtifact | None:
        # 这种成果最后一次被接纳的那一版，失效以后仍然记着：接下一版时由它给出上一版与版本号（S1d，工单 #860）
        return self.accepted.get(kind)

    def artifact_hash(self, kind: str) -> str | None:
        # 这种成果当前版本的内容摘要
        current = self.artifacts.get(kind)
        return None if current is None else current.content_hash

    def versions_of(self, kind: str) -> tuple[AcceptedArtifact, ...]:
        # 这种成果当前有效的各版：单版的种类只有最新这一版，多版并存的种类按接纳顺序
        return self.versions.get(kind, ())


def fold_events(events: Iterable[Event]) -> MinimalProjection:
    # 从骨架事件重算最小投影：同一组事件重算的结果相同，不读时钟、不读定义、不写任何东西
    return fold_more(MinimalProjection(), events)


def fold_more(state: MinimalProjection, events: Iterable[Event]) -> MinimalProjection:
    # 在已有的最小投影上接着折后面的事件（事件必须接在已经折过的事件之后）：
    # 写入口在同一个事务里折一份交给裁决，事务里追加的事件接在读取到的那一份后面折，不必整条流重算
    fold = _Fold(state)
    for event in events:
        fold.feed(event)
    return fold.result()


class _Fold:
    # 折叠过程中可变的累积状态：只在折叠内部使用，结果冻结成 MinimalProjection
    def __init__(self, state: MinimalProjection) -> None:
        self.state = state
        self.stream_versions = dict(state.stream_versions)
        self.sessions = dict(state.sessions)
        self.rounds = dict(state.rounds)
        self.artifacts = dict(state.artifacts)
        self.versions = dict(state.versions)
        self.accepted = dict(state.accepted)
        self.used = state.used
        self.execution_right = state.execution_right
        self.pending = list(state.pending_decisions)
        self.main_activations = max(state.used.activations, 0)  # 主线会话的激活数：询问分支不算轮次（#857）

    def feed(self, event: Event) -> None:
        if event.stream and event.stream_version:
            self.stream_versions[event.stream] = event.stream_version
        if event.epoch is not None:
            self.execution_right = max(self.execution_right, int(event.epoch))
        self.state = _fold_run(self.state, event)
        self._fold_usage(event)
        accepted = _accepted_artifact(event)
        if accepted is not None:
            kind, artifact, multiple = accepted
            self._accept(kind, artifact, multiple)
        invalidated = _invalidated_artifact(event)
        if invalidated is not None:
            self._invalidate(*invalidated)
        snapshot = _created_snapshot(event)
        if snapshot is not None:
            self._accept(SNAPSHOT_KIND, snapshot, False)
        for session_id, department in _created_sessions(event).items():
            # 事项创建时记下的会话：每个部门一个主线会话，还没有激活的会话已用量为零
            self.sessions.setdefault(session_id, SessionState(department=department))

    def _invalidate(self, kind: str, version: int) -> None:
        # 这一版失效（S1b）：它不再是当前版本，最小投影里没有它；最后接纳的那一版仍然记着，
        # 重新接纳时接着它编版本号（S1d，工单 #860）
        self.versions[kind] = tuple(item for item in self.versions.get(kind, ()) if item.version != version)
        known = self.artifacts.get(kind)
        if known is not None and known.version == version:
            self.artifacts.pop(kind, None)

    def _accept(self, kind: str, artifact: AcceptedArtifact, multiple: bool) -> None:
        # 接纳一版成果：当前版本换成这一版；多版并存的种类把这一版加在清单末尾，单版的种类只有这一版
        self.artifacts[kind] = artifact
        self.accepted[kind] = artifact
        self.versions[kind] = (self.versions.get(kind, ()) if multiple else ()) + (artifact,)

    def _fold_usage(self, event: Event) -> None:
        # 已用的时间与次数、每个部门主线会话这一轮的编号，以及待回答的决定请求
        payload = event.payload if isinstance(event.payload, dict) else {}
        etype = event.type
        session_id = event.session_id or ""
        if etype == SkeletonEventType.DEPARTMENT_ACTIVATED:
            # 一轮工作的开始：轮次编号由主线会话递增，询问分支沿用当前的轮次，所以事项一级的激活次数
            # 取出现过的最大轮次编号与主线会话的激活次数里较大的那一个（工单 #857）
            cycle = int(payload.get("cycle") or 0)
            session = self.sessions.get(session_id, SessionState())
            main = session.department is not None and session.department == event.department
            if main:
                self.main_activations += 1
                activation_id = payload.get("activation_id")
                if event.department and activation_id:
                    self.rounds[event.department] = str(activation_id)
            self.used = replace(self.used, activations=max(self.used.activations, self.main_activations, cycle))
            self.sessions[session_id] = replace(session, activations=session.activations + 1,
                                                round_id=payload.get("activation_id") or session.round_id)
            return
        if etype == SkeletonEventType.ACTIVATION_FINISHED:
            # 一轮工作的结束：已结算的运行时间与模型步数是这一刻为止的累计值，中断的那一段不计
            self.used = replace(self.used, settled_ms=max(self.used.settled_ms, int(payload.get("elapsed_ms") or 0)))
            session = self.sessions.get(session_id, SessionState())
            self.sessions[session_id] = replace(session, settled_ms=max(
                session.settled_ms, int(payload.get("session_elapsed_ms") or 0)), settled_steps=session.model_steps)
            return
        if etype == SkeletonEventType.MODEL_REQUESTED:
            # 模型步数按请求一条条数（设计说明第 4 节 2026-10-25 第 1 条）
            self.used = replace(self.used, model_steps=self.used.model_steps + 1)
            session = self.sessions.get(session_id, SessionState())
            self.sessions[session_id] = replace(session, model_steps=session.model_steps + 1)
            return
        if etype == SkeletonEventType.DECISION_REQUESTED:
            self.pending.append(event.event_id)
            return
        if etype in (SkeletonEventType.DECISION_ANSWERED, SkeletonEventType.DECISION_WITHDRAWN):
            decision_id = payload.get("decision_id")
            if isinstance(decision_id, str) and decision_id in self.pending:
                self.pending.remove(decision_id)
            return

    def result(self) -> MinimalProjection:
        return replace(self.state, execution_right=self.execution_right, stream_versions=self.stream_versions,
                       used=self.used, sessions=self.sessions, artifacts=self.artifacts,
                       versions=self.versions, accepted=self.accepted, rounds=self.rounds,
                       pending_decisions=tuple(self.pending))


def _fold_run(state: MinimalProjection, event: Event) -> MinimalProjection:
    # 事项的编号、种类、冻结的定义与参数版本、上限，以及运行状态；事项创建时记下每个部门的主线会话。
    # 状态只看事项的状态事件（设计说明第 4 节）：其他事件的前后状态不在这里重新推断
    payload = event.payload if isinstance(event.payload, dict) else {}
    etype = event.type
    if etype == SkeletonEventType.RUN_CREATED:
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
            mcp_servers_version=int((payload.get("mcp_servers") or {}).get("version") or 0),
            max_cycles=int(payload.get("max_cycles") or 0),
            run_time_limit_sec=int(payload.get("run_time_limit_sec") or 0),
        )
    if etype == SkeletonEventType.RUN_DONE:
        return replace(state, status="done", stop_reason=event.stop_reason)
    if etype == SkeletonEventType.RUN_PAUSED:
        return replace(state, status="paused", stop_reason=event.stop_reason)
    if etype == SkeletonEventType.RUN_FAILED:
        return replace(state, status="failed", stop_reason=event.stop_reason)
    if etype == SkeletonEventType.RUN_CONTINUED:
        # 用户处理完暂停的原因以后继续：已用量保持在暂停时的值，不在这里重置
        return replace(state, status="running", stop_reason=None)
    return state


def _created_snapshot(event: Event) -> AcceptedArtifact | None:
    # 事项创建事件里记下的代码树快照（建档时的工作区）：树摘要供通用条件 4 核对，
    # 不让最小投影读成果的内容。还没有快照的事项没有这一项
    if event.type != SkeletonEventType.RUN_CREATED:
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    digest = snapshot.get("tree_digest")
    if not isinstance(digest, str) or not digest:
        return None
    content_hash = snapshot.get("content_hash")
    return AcceptedArtifact(version=1, content_hash=digest if not isinstance(content_hash, str) else content_hash,
                            tree_digest=digest)


def _created_sessions(event: Event) -> dict[str, str]:
    # 事项创建事件里记下的会话：部门 → 会话编号。这些是部门的主线会话，
    # 询问分支是另一条会话（它不在这一组里），它的激活不推进轮次、不改这一轮的编号（工单 #473、#857）
    if event.type != SkeletonEventType.RUN_CREATED:
        return {}
    payload = event.payload if isinstance(event.payload, dict) else {}
    created = payload.get("sessions")
    if not isinstance(created, dict):
        return {}
    return {str(session_id): str(department) for department, session_id in created.items()}


def _accepted_artifact(event: Event) -> tuple[str, AcceptedArtifact, bool] | None:
    # 成果接纳事件的统一字段：成果种类、版本、依据、内容摘要、作者部门与记下的树摘要，以及这一种成果是否多版并存。
    # 不按事件种类逐个写，所以加一种成果种类（由定义带来）不改这里；没有这组字段的事件不是成果接纳
    payload = event.payload if isinstance(event.payload, dict) else {}
    kind = payload.get("artifact_kind")
    version = payload.get("artifact_version")
    content_hash = payload.get("content_hash")
    if not isinstance(kind, str) or not kind or version is None or not isinstance(content_hash, str):
        return None
    basis = payload.get("artifact_basis")
    ref = payload.get("artifact_ref")
    issuer = payload.get("artifact_issuer")
    tree = payload.get("artifact_tree_digest")
    return kind, AcceptedArtifact(
        version=int(version),
        content_hash=content_hash,
        issuer=issuer if isinstance(issuer, str) and issuer else None,
        tree_digest=tree if isinstance(tree, str) and tree else None,
        basis={str(name): str(value) for name, value in basis.items()} if isinstance(basis, dict) else {},
        ref=dict(ref) if isinstance(ref, dict) else None,
    ), bool(payload.get("artifact_multiple"))


def _invalidated_artifact(event: Event) -> tuple[str, int] | None:
    # 成果失效事件（骨架事件，S1b）：成果种类与版本。失效是记下来的事实，不由这里从别的事件推出；
    # 失效以后这一版不再有效，这种成果没有当前版本时一直空着，直到它被重新接纳。没有这两个字段的事件不是成果失效
    if event.type != SkeletonEventType.ARTIFACT_INVALIDATED:
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    kind = payload.get("artifact_kind")
    version = payload.get("artifact_version")
    if not isinstance(kind, str) or not kind or version is None:
        return None
    return kind, int(version)

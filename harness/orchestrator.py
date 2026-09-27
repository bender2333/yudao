# 流程编排：运行的生命周期（创建、输入、指导、提示词、取消、运行到停止）、激活的准备与收尾、新输入的分派、
# 提案接纳以后的流转、暂停与失败。一次激活内的步骤交给步骤驱动，只调用它的开始、取消与取得结果；
# 同时为步骤驱动实现安全节点接口。流程编排不调用模型。
# 每一处「读取运行状态、判断、写入」都是写入口的一个事务（WritePath.transact）：判断期间不持有锁，
# 另一方在读取以后写入了同一个 run，提交被拒绝，按写入以后的状态重新判断。

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from typing import Any

from .actions import FactsQuery, TreeFacts
from .adapters.base import ModelAdapter
from .adapters.facade_adapter import FacadeAdapter
from .adjudication import WorkBasis, commit_decision, guidance_version, proposal_decision
from .artifacts import ArtifactStore
from .assembly import PENDING_GUIDANCE, ContextAssembly, pending_guidance
from .contracts import current_contract_hash, current_plan_hash
from .collaboration import guidance_resume_phase, request_still_applicable, resume_phase
from .environment import LocalEnvironment
from .event_store import EventStore, StreamVersionConflict, run_stream
from .write_path import NewEvent, Snapshot, Transaction, WritePath
from .engine import Judgment, StepDriver, StepLimits, Stopped
from .git_versions import GitVersionStore
from .interactions import CancelledInputSaveError, InteractionWriter, RunTerminalError
from .definitions import DEFINITIONS
from .models import (
    Event as RunEvent,
    DEPARTMENTS,
    DepartmentPrompt,
    EventType,
    TERMINAL_PHASES,
    canonical_hash,
    department_for_phase,
    new_id,
)
from .providers import ProviderConnections, ProviderFacade
from .providers.resolve import FrozenTarget, ResolveSnapshot
from .projection import RunNotFoundError, RunProjection, project_run
from .public_tree import CapturedTree, capture_public_tree, materialize_tree
from .recording import ActivationScope
from .sessions import SessionFactory
from .submissions import SubmissionWriter
from .tools import normalize_registered_commands
from .validation import ProposalDecision
from .workspace import Workspace, WorkspaceSnapshot


@dataclass
class _Activation:
    # 流程编排持有的一次激活：身份、采用的版本与工作依据（scope），提示词、调用目标与适配器，
    # 中止信号，激活开始时 run 流的版本，步骤驱动，以及在安全节点等待重试时的唤醒
    scope: ActivationScope
    prompt: DepartmentPrompt
    abort_flag: Event
    adapter: ModelAdapter
    target: FrozenTarget | None
    yielded_work: dict[str, Any] | None
    version: int
    driver: StepDriver | None = None
    wakeup: tuple[asyncio.AbstractEventLoop, asyncio.Event] | None = None

    @property
    def run_id(self) -> str:
        return self.scope.run_id

    @property
    def department(self) -> str:
        return self.scope.department


class _SafeNode:
    # 流程编排为一次激活实现的安全节点接口 engine.SafeNode。接口由下层的步骤驱动定义，这里实现并在开始时交给它（依赖倒置）
    def __init__(self, orchestrator: Orchestrator, activation: _Activation) -> None:
        self._orchestrator = orchestrator
        self._activation = activation

    def proceed(self) -> Judgment:
        return self._orchestrator._at_safe_node(self._activation)

    def settle(self, transaction: Transaction) -> RunProjection:
        return self._orchestrator._close_obsolete_request(transaction)

    async def wait(self, seconds: float) -> Judgment:
        return await self._orchestrator._wait_at_safe_node(self._activation, seconds)

    def end(self, transaction: Transaction, reason: str, message: str) -> None:
        self._orchestrator._end(transaction, reason, message)


BASELINE_FIELDS = frozenset({"adoption_id", "source_run_id", "delivery_event_id", "tree_ref", "code_tree_digest"})
SNAPSHOT_FIELDS = frozenset({"source", "tree_digest", "files", "directories", "tree_ref"})


def _validate_run_ownership(
    *,
    project_id: str | None,
    work_item_id: str | None,
    baseline: dict[str, Any] | None,
    initial_tree: CapturedTree | None,
    code_snapshot: dict[str, Any] | None,
    project_context: str | None,
    department_prompts: dict[str, str] | None,
    prompt_config_versions: dict[str, int] | None,
) -> None:
    """项目归属参数要么全给（项目层）要么全不给（bare run）；基线与初始树成对出现。"""
    ownership = {
        "project_id": project_id, "work_item_id": work_item_id, "project_context": project_context,
        "department_prompts": department_prompts, "prompt_config_versions": prompt_config_versions,
    }
    given = [name for name, value in ownership.items() if value is not None]
    if given and len(given) != len(ownership):
        missing = sorted(set(ownership) - set(given))
        raise ValueError("project ownership parameters must be given together; missing: " + ", ".join(missing))
    if not given and (baseline is not None or initial_tree is not None or code_snapshot is not None):
        raise ValueError("baseline and initial_tree require project ownership parameters")
    if code_snapshot is not None:
        if baseline is not None:
            raise ValueError("snapshot and baseline cannot be given together")
        if initial_tree is None:
            raise ValueError("snapshot and initial_tree must be given together")
        if not isinstance(code_snapshot, dict) or set(code_snapshot) != SNAPSHOT_FIELDS:
            raise ValueError("snapshot must contain exactly: " + ", ".join(sorted(SNAPSHOT_FIELDS)))
        if code_snapshot["tree_digest"] != initial_tree.digest:
            raise ValueError("snapshot tree_digest does not match the initial tree digest")
    elif (baseline is None) != (initial_tree is None):
        raise ValueError("baseline and initial_tree must be given together")
    if given:
        for name in ("project_id", "work_item_id", "project_context"):
            if not isinstance(ownership[name], str) or not ownership[name].strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(department_prompts, dict) or set(department_prompts) != set(DEPARTMENTS):
            raise ValueError("department_prompts must cover exactly the three departments")
        if any(not isinstance(text, str) or not text.strip() for text in department_prompts.values()):
            raise ValueError("department prompt text must be non-empty")
        if not isinstance(prompt_config_versions, dict) or set(prompt_config_versions) != set(DEPARTMENTS):
            raise ValueError("prompt_config_versions must cover exactly the three departments")
        if any(type(version) is not int or version < 0 for version in prompt_config_versions.values()):
            raise ValueError("prompt_config_versions must be non-negative integers")
    if baseline is not None:
        if not isinstance(baseline, dict) or set(baseline) != BASELINE_FIELDS:
            raise ValueError("baseline must contain exactly: " + ", ".join(sorted(BASELINE_FIELDS)))
        if not isinstance(initial_tree, CapturedTree):
            raise ValueError("initial_tree must be a captured tree")
        if baseline["code_tree_digest"] != initial_tree.digest:
            raise ValueError("baseline code_tree_digest does not match the initial tree digest")


def _snapshot_event_dict(snapshot: ResolveSnapshot) -> dict[str, Any]:
    # 任务快照只存非敏感身份：各部门冻结目标公开身份加凭据版本，不含密钥
    departments = {}
    for key in sorted(snapshot.targets):
        frozen = snapshot.targets[key]
        payload = frozen.public_dict()
        payload["department"] = key
        payload["credential_version"] = frozen.credential_version
        departments[key] = payload
    return {"revision": snapshot.revision, "departments": departments}


def _validate_frozen_commands(registered_commands: dict[str, Any] | None,
                              command_versions: dict[str, int] | None) -> tuple[dict[str, Any], dict[str, int]]:
    # 登记命令随事项创建冻结：两份必须成对出现，键集合一致，版本号为非负整数
    if registered_commands is None and command_versions is None:
        return {}, {}
    if registered_commands is None or command_versions is None:
        raise ValueError("registered_commands and command_versions must be given together")
    normalized = normalize_registered_commands(registered_commands)
    if not isinstance(command_versions, dict) or any(
            not isinstance(name, str) or type(version) is not int or version < 1
            for name, version in command_versions.items()):
        raise ValueError("command_versions must map command names to positive integers")
    if set(normalized) != set(command_versions):
        raise ValueError("registered_commands and command_versions must cover the same commands")
    return normalized, dict(command_versions)


class Orchestrator:
    def __init__(
        self,
        store: EventStore,
        writes: WritePath,
        artifacts: ArtifactStore,
        workspace_root: str | Path,
        *,
        facade: ProviderFacade | None = None,
        test_adapter_factory: Any | None = None,
        test_provider: str = "test",
        test_adapter_name: str = "test",
        sessions: SessionFactory | None = None,
        step_limits: StepLimits = StepLimits(),
    ) -> None:
        self.store = store
        self.writes = writes
        self.step_limits = step_limits
        self.artifacts = artifacts
        self.workspace_root = Path(workspace_root)
        self.materials_root = self.workspace_root.parent / "materials"
        self.git_versions = GitVersionStore(self.workspace_root.parent / "git")
        self.submissions = SubmissionWriter(artifacts, self.materials_root, self.git_versions)
        self.interactions = InteractionWriter(store, artifacts, self.materials_root, self.git_versions)
        self.facade = facade
        self.test_adapter_factory = test_adapter_factory
        self.test_provider = test_provider
        self.test_adapter_name = test_adapter_name
        self.assembly = ContextAssembly(artifacts)
        self.sessions = sessions or SessionFactory()
        self._abort: dict[str, Event] = {}
        # 每个 run 正在进行的取消（cancel 或 /stop）
        self._cancellers: dict[str, set[object]] = {}
        # 正在激活的 run：_running 在准备激活之前以 setdefault 占用（同一 run 只能有一次激活），_active 是激活本身
        self._running: dict[str, object] = {}
        self._active: dict[str, _Activation] = {}
        self._snapshots: dict[str, ResolveSnapshot] = {}
        self._run_start_times: dict[str, float] = {}

    def create_run(
        self,
        task: str,
        *,
        max_cycles: int = DEFINITIONS.limits.max_cycles,
        run_time_limit_sec: int = DEFINITIONS.limits.run_time_limit_sec,
        context_window: int = 32_000,
        run_id: str | None = None,
        project_id: str | None = None,
        work_item_id: str | None = None,
        baseline: dict[str, Any] | None = None,
        initial_tree: CapturedTree | None = None,
        code_snapshot: dict[str, Any] | None = None,
        project_context: str | None = None,
        department_prompts: dict[str, str] | None = None,
        prompt_config_versions: dict[str, int] | None = None,
        registered_commands: dict[str, Any] | None = None,
        command_versions: dict[str, int] | None = None,
    ) -> str:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be non-empty")
        if max_cycles < 1:
            raise ValueError("max_cycles must be positive")
        if run_time_limit_sec < 1:
            raise ValueError("run_time_limit_sec must be positive")
        if context_window < 1:
            raise ValueError("context_window must be positive")
        if self.facade is None and self.test_adapter_factory is None:
            raise ValueError("provider facade is required for production runs")
        _validate_run_ownership(
            project_id=project_id, work_item_id=work_item_id, baseline=baseline, initial_tree=initial_tree,
            code_snapshot=code_snapshot,
            project_context=project_context, department_prompts=department_prompts,
            prompt_config_versions=prompt_config_versions,
        )
        frozen_commands = _validate_frozen_commands(registered_commands, command_versions)
        snapshot = None
        use_facade = self.facade is not None and (
            self.test_adapter_factory is None or bool(self.facade.get_bindings()))
        if use_facade:
            # 任务创建一次读取一致的目录版本、凭据来源与目标列表并冻结
            assert self.facade is not None
            snapshot = self.facade.resolve_departments()
        run_id = run_id or new_id("run")
        material_dir = (self.materials_root / run_id).resolve()
        if material_dir == self.materials_root.resolve() or not material_dir.is_relative_to(self.materials_root.resolve()):
            raise ValueError("run_id must stay within the run materials directory")
        # 工作区先于其余材料落盘：继承树无法恢复时不留下半个 run。
        workspace_dir = self.workspace_root / run_id
        if initial_tree is not None:
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            materialize_tree(initial_tree, workspace_dir)
        workspace = Workspace(workspace_dir)
        workspace_digest = capture_public_tree(workspace.root).digest
        initial = self.interactions.initial(run_id, task, department_prompts=department_prompts)
        sessions = self.sessions.create_run_sessions(run_id)
        self._abort[run_id] = Event()
        if snapshot is not None:
            self._snapshots[run_id] = snapshot
        provider_snapshot = {} if snapshot is None else _snapshot_event_dict(snapshot)
        if snapshot is not None:
            provider_snapshot = {
                "snapshot_id": canonical_hash(provider_snapshot),
                **provider_snapshot,
            }
        project_context_ref = None
        if project_context is not None:
            project_context_ref = asdict(self.artifacts.put(
                run_id, "project_context", project_context, media_type="text/markdown",
            ))
        run_created = NewEvent(
            EventType.RUN_CREATED,
            role="product",
            state_before="CREATED",
            state_after="PRODUCT_SPEC",
            payload={
                "task": task,
                **initial,
                "intend_path": (Path("materials") / run_id / "intend.md").as_posix(),
                "max_cycles": max_cycles,
                "run_time_limit_sec": run_time_limit_sec,
                "context_window": context_window,
                "provider": self.test_provider if snapshot is None else "directory",
                "adapter": self.test_adapter_name if snapshot is None else "directory",
                "provider_snapshot": provider_snapshot,
                "sessions": {name: session.session_id for name, session in sessions.items()},
                "project_id": project_id,
                "work_item_id": work_item_id,
                "baseline": baseline,
                "snapshot": code_snapshot,
                "workspace_digest": workspace_digest,
                "project_context_ref": project_context_ref,
                "prompt_config_versions": dict(prompt_config_versions or {}),
                "registered_commands": frozen_commands[0],
                "command_versions": frozen_commands[1],
                "definitions_version": DEFINITIONS.version,
            },
        )
        transition = NewEvent(
            EventType.TRANSITION,
            role="product",
            state_before="CREATED",
            state_after="PRODUCT_SPEC",
            payload={"from": "CREATED", "to": "PRODUCT_SPEC", "route": "CREATED->PRODUCT_SPEC"},
        )
        # 新的 run 流从版本 0 开始；同一编号的 run 已经存在时拒绝
        self.writes.transact(run_stream(run_id), lambda transaction: transaction.append(run_created, transition),
                             expected_version=0)
        return run_id

    def project(self, run_id: str) -> RunProjection:
        return project_run(self.store, run_id)

    def workspace(self, run_id: str) -> Workspace:
        return Workspace(self.workspace_root / run_id)

    def _environment(self, run_id: str) -> LocalEnvironment:
        return LocalEnvironment(self.workspace(run_id))

    def add_input(self, run_id: str, text: str) -> RunProjection:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("input must be a non-empty string")
        if text.strip() in {"/stop", "/cancel"}:
            return self._stop_by_command(run_id, text)

        def receive(transaction: Transaction) -> None:
            self._require_open(run_id, transaction.projection, "This run has ended; create a new task for this input.")
            self.interactions.receive(transaction, text, command=False)

        self.writes.transact(run_stream(run_id), receive)
        self._wake(run_id)
        return self.project(run_id)

    def _stop_by_command(self, run_id: str, text: str) -> RunProjection:
        # /stop 与 /cancel：保存命令原文并取消运行。先中止并取消正在进行的步骤，再记录命令；
        # 命令原文没有保存成功时仍然记录取消，并在取消的事件中说明保存失败的原因
        message = "This run has ended; create a new task for this input."
        with self._cancelling(run_id):
            self._require_open(run_id, self.project(run_id), message)
            activation, cancel_error = self._abort_run(run_id)
            stop_error = cancel_error

            def receive(transaction: Transaction) -> None:
                if transaction.projection.phase in TERMINAL_PHASES:
                    raise RunTerminalError(message)
                self.interactions.receive(transaction, text, command=True)

            save_error = None
            cancellation_recorded = False
            try:
                try:
                    self.writes.transact(run_stream(run_id), receive)
                except RunTerminalError:
                    raise
                except Exception as exc:
                    save_error = exc
                failure = None if save_error is None else {
                    "text": text, "error_type": type(save_error).__name__, "message": str(save_error),
                }
                try:
                    self.writes.transact(run_stream(run_id), lambda transaction: self._fail(
                        transaction, "cancelled", "run cancelled by user command", input_save_failure=failure))
                    cancellation_recorded = True
                except Exception as exc:
                    stop_error = stop_error or exc
            finally:
                if cancel_error is not None:
                    # 取消正在进行的步骤出过错：再通知一次
                    try:
                        self._cancel_driver(activation)
                    except Exception as exc:
                        stop_error = stop_error or exc
        if save_error is not None:
            raise CancelledInputSaveError(run_id, cancellation_recorded=cancellation_recorded) from save_error
        if stop_error is not None:
            raise stop_error
        return self.project(run_id)

    def _abort_run(self, run_id: str) -> tuple[_Activation | None, Exception | None]:
        # 中止运行：之后的核对都得到停止，正在进行的步骤立即取消；交回正在进行的激活与取消它时的错误
        self._abort.setdefault(run_id, Event()).set()
        activation = self._active.get(run_id)
        if activation is None:
            return None, None
        try:
            self._cancel_driver(activation)
        except Exception as exc:
            return activation, exc
        return activation, None

    @contextmanager
    def _cancelling(self, run_id: str) -> Iterator[None]:
        # 登记一个正在进行的取消：运行循环看到中止时，由它写入取消（它可能还在保存命令原文）
        token = object()
        self._cancellers.setdefault(run_id, set()).add(token)
        try:
            yield
        finally:
            self._cancellers[run_id].discard(token)

    def update_prompt(self, run_id: str, department: str, text: str) -> RunProjection:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("prompt must be a non-empty string")

        def update(transaction: Transaction) -> None:
            self._require_open(run_id, transaction.projection, "This run has ended; prompts can be edited in a new task.")
            self.interactions.update_prompt(transaction, department, text)

        self.writes.transact(run_stream(run_id), update)
        return self.project(run_id)

    def add_guidance(self, run_id: str, department: str, text: str) -> RunProjection:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")

        def receive(transaction: Transaction) -> None:
            self._require_open(run_id, transaction.projection, "This run has ended; guidance can be sent to a new task.")
            self.interactions.receive_guidance(transaction, department, text)

        self.writes.transact(run_stream(run_id), receive)
        self._wake(run_id)
        return self.project(run_id)

    def _require_open(self, run_id: str, projection: RunProjection, message: str) -> None:
        # 已经结束或已经中止的运行不再接收输入、指导与提示词
        if not projection.run_id:
            raise RunNotFoundError(run_id)
        if projection.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
            raise RunTerminalError(message)

    def _assign_new_inputs(self, transaction: Transaction) -> RunProjection:
        projection = transaction.projection
        if projection.phase in TERMINAL_PHASES or projection.input_version <= projection.product_work_input_version:
            return projection
        projection = self._close_request(transaction, status="superseded",
                                         reason="New user input requires updated product work.",
                                         return_phase="PRODUCT_SPEC", return_work_valid=False)
        transaction.append(NewEvent(
            EventType.PRODUCT_INPUT_ASSIGNED, role="product",
            state_before=projection.phase, state_after="PRODUCT_SPEC",
            payload={"through_version": projection.input_version},
        ))
        return transaction.projection

    def _at_safe_node(self, activation: _Activation) -> Judgment:
        # 安全节点：激活没有中止、运行时间没有用完时先分派新输入，再作停止判断；回答是否继续与判断时的流版本
        def judge(transaction: Transaction) -> Judgment:
            projection = transaction.projection
            if not (activation.abort_flag.is_set() or self._time_used_up(activation.run_id, projection)):
                projection = self._assign_new_inputs(transaction)
            return Judgment(not self._stop_requested(activation, projection), projection.stream_version)

        return self.writes.transact(run_stream(activation.run_id), judge)

    def _stop_requested(self, activation: _Activation, projection: RunProjection) -> bool:
        # 停止判断：中止、运行时间用完、终态、输入版本改变或有新的指导；只读取，不写入
        basis = activation.scope.basis
        return (activation.abort_flag.is_set() or self._time_used_up(activation.run_id, projection)
                or projection.phase in TERMINAL_PHASES
                or projection.input_version != basis.input_version
                or guidance_version(projection, activation.department) > basis.guidance_version)

    def _time_used_up(self, run_id: str, projection: RunProjection) -> bool:
        return self._time_left(run_id, projection) <= 0

    def _time_left(self, run_id: str, projection: RunProjection) -> float:
        return projection.run_time_limit_sec - (time.monotonic() - self._run_start_times.get(run_id, time.monotonic()))

    async def _wait_at_safe_node(self, activation: _Activation, seconds: float) -> Judgment:
        # 重试等待：在安全节点等待至多 seconds 秒；新输入、指导或取消到达时由 _wake 唤醒，运行时间用完时结束等待，
        # 醒来以后回到安全节点判断。唤醒在判断之前登记：判断之后才提交的改变，提交方调用 _wake 时一定看到这次登记
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        try:
            while True:
                changed = asyncio.Event()
                activation.wakeup = (loop, changed)
                judgment = self._at_safe_node(activation)
                if not judgment.proceed:
                    return judgment
                time_left = self._time_left(activation.run_id, self.project(activation.run_id))
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return judgment
                try:
                    await asyncio.wait_for(changed.wait(), max(0.0, min(remaining, time_left)))
                except TimeoutError:
                    pass
        finally:
            activation.wakeup = None

    def _wake(self, run_id: str) -> None:
        # 在安全节点等待重试的激活立即回到安全节点判断；在改变提交以后调用
        activation = self._active.get(run_id)
        wakeup = None if activation is None else activation.wakeup
        if wakeup is not None:
            loop, changed = wakeup
            loop.call_soon_threadsafe(changed.set)

    def _close_request(self, transaction: Transaction, *, status: str, reason: str,
                       return_phase: str, return_work_valid: bool) -> RunProjection:
        projection = transaction.projection
        request = projection.pending_request
        if request is None:
            return projection
        transaction.append(NewEvent(
            EventType.COLLABORATION_CLOSED, role=request.recipient,
            parent_event_id=request.created_event_id, state_before=projection.phase, state_after=return_phase,
            session_id=projection.sessions[request.recipient].session_id,
            payload={"request_id": request.id, "status": status, "reason": reason,
                     "return_phase": return_phase, "return_work_valid": return_work_valid},
        ))
        return transaction.projection

    def _close_obsolete_request(self, transaction: Transaction) -> RunProjection:
        # 分派新输入，关闭因此或因依据改变而过时的协作请求，交回事务中当前的运行状态
        projection = self._assign_new_inputs(transaction)
        request = projection.pending_request
        if request is None or projection.phase in TERMINAL_PHASES:
            return projection
        events = transaction.events()
        if request_still_applicable(request, projection, events):
            return projection
        tree = self._environment(projection.run_id).query(FactsQuery(tree=True)).tree
        phase, _valid = resume_phase(request, projection, events, snapshot_hash=tree.digest)
        return self._close_request(transaction, status="superseded", reason="The request basis changed outside its authorized work.",
                                   return_phase=phase, return_work_valid=False)

    def cancel(self, run_id: str) -> RunProjection:
        # 已经结束的运行不变；否则中止并取消正在进行的步骤，再写入取消。取消正在进行的步骤出错时，
        # 取消照常写入，再通知一次，错误交给调用方
        with self._cancelling(run_id):
            if self.project(run_id).phase in TERMINAL_PHASES:
                return self.project(run_id)
            activation, cancel_error = self._abort_run(run_id)
            try:
                self.writes.transact(run_stream(run_id), lambda transaction: self._fail(
                    transaction, "cancelled", "run cancelled"))
            finally:
                if cancel_error is not None:
                    self._cancel_driver(activation)
        if cancel_error is not None:
            raise cancel_error
        return self.project(run_id)

    def _cancel_driver(self, activation: _Activation) -> None:
        # 取消步骤驱动（正在进行的调用尝试按身份取消），在安全节点等待重试的激活立即醒来；取消调用尝试出错时同样唤醒
        try:
            if activation.driver is not None:
                activation.driver.cancel()
        finally:
            self._wake(activation.run_id)

    async def run_until_stop(self, run_id: str) -> RunProjection:
        # 一次运行期间的模型调用复用同一组连接，连接只在这个事件循环中使用
        connections = ProviderConnections()
        try:
            while True:
                projection = self.project(run_id)
                if projection.phase in TERMINAL_PHASES:
                    return projection
                if self._abort.get(run_id) and self._abort[run_id].is_set():
                    # 已经中止：正在进行的取消（cancel 或 /stop，可能还在保存命令原文）由它自己写入；
                    # 没有正在进行的取消（例如它的写入失败了）时在这里写入
                    if self._cancellers.get(run_id):
                        return projection
                    return self.cancel(run_id)
                await self._activate_once(run_id, connections)
        finally:
            await connections.aclose()

    async def activate_once(self, run_id: str) -> RunProjection:
        connections = ProviderConnections()
        try:
            return await self._activate_once(run_id, connections)
        finally:
            await connections.aclose()

    async def _activate_once(self, run_id: str, connections: ProviderConnections) -> RunProjection:
        claim = object()
        if self._running.setdefault(run_id, claim) is not claim:
            raise RuntimeError("run already has an active department invocation")
        try:
            activation = self.writes.transact(
                run_stream(run_id), lambda transaction: self._prepare_activation(run_id, transaction, connections))
            if activation is None:
                return self.project(run_id)
            self._active[run_id] = activation
            started = time.monotonic()
            try:
                await self._invoke_activation(activation)
            finally:
                scope = activation.scope

                def finish(transaction: Transaction) -> None:
                    current = transaction.projection
                    transaction.append(NewEvent(
                        EventType.ACTIVATION_FINISHED,
                        role=scope.department,
                        parent_event_id=scope.parent_event_id,
                        state_before=current.phase,
                        state_after=current.phase,
                        session_id=scope.session_id,
                        payload={
                            "activation_id": scope.activation_id,
                            **scope.versions(),
                            "latency_ms": int((time.monotonic() - started) * 1000),
                            "stop_reason": current.stop_reason,
                        },
                    ))

                self.writes.transact(run_stream(run_id), finish)
                self.sessions.get(run_id, scope.department).idle()
                self._active.pop(run_id, None)
            return self.project(run_id)
        finally:
            self._running.pop(run_id, None)

    def _prepare_activation(self, run_id: str, transaction: Transaction,
                            connections: ProviderConnections) -> _Activation | None:
        projection = transaction.projection
        if not projection.run_id:
            raise RunNotFoundError(run_id)
        if run_id not in self._run_start_times:
            self._run_start_times[run_id] = time.monotonic()
        if self._abort.get(run_id) and self._abort[run_id].is_set():
            return None
        projection = self._close_obsolete_request(transaction)
        if projection.phase in TERMINAL_PHASES:
            return None
        if projection.cycle_count >= projection.max_cycles:
            self._pause(transaction, "max_cycles")
            return None
        elapsed = time.monotonic() - self._run_start_times.get(run_id, time.monotonic())
        if elapsed >= projection.run_time_limit_sec:
            self._fail(transaction, "time_limit",
                       f"run wall-clock time {int(elapsed)}s exceeded limit of {projection.run_time_limit_sec}s")
            return None
        normal_department = projection.pending_request.recipient if projection.pending_request else department_for_phase(projection.phase)
        waiting_guidance = [item for item in projection.department_guidance if item.status in PENDING_GUIDANCE]
        guidance_only = False
        department = normal_department
        yielded_work = None
        if projection.pending_request is None and waiting_guidance:
            if normal_department is None or waiting_guidance[0].department != normal_department:
                department = waiting_guidance[0].department
                guidance_only = department != "product"
                yielded_work = dict(projection.yielded_work) if projection.yielded_work else self._work_basis(projection)
        if department is None:
            self._fail(transaction, "provider_error", f"no department for phase {projection.phase}")
            return None

        target: FrozenTarget | None = None
        snapshot_id: str | None = None
        run_has_frozen_provider = bool(projection.provider_snapshot.get("snapshot_id"))
        snapshot = self._snapshots.get(run_id)
        if run_has_frozen_provider or snapshot is not None:
            if snapshot is None or self.facade is None:
                self._fail(
                    transaction,
                    "provider_credentials_lost",
                    "The task's frozen provider credentials are unavailable after restart; create a new run.",
                )
                return None
            try:
                target = snapshot.target(department)
                snapshot_id = canonical_hash(_snapshot_event_dict(snapshot))
                # 旧任务工作、压缩与重试继续使用冻结目标与原认证句柄，不读当前配置
                adapter = FacadeAdapter(self.facade, target, connections=connections)
            except (KeyError, ValueError) as exc:
                self._fail(transaction, "provider_unavailable", str(exc))
                return None
        else:
            if self.test_adapter_factory is None:
                self._fail(
                    transaction,
                    "provider_credentials_lost",
                    "The task's model credentials are unavailable in this process; create a new run.",
                )
                return None
            try:
                adapter = self.test_adapter_factory(department)
            except Exception as exc:
                self._fail(transaction, "provider_unavailable", f"test adapter creation failed: {exc}")
                return None

        availability = adapter.availability()
        if not availability.available:
            self._fail(transaction, availability.reason or "provider_unavailable", availability.message)
            return None

        try:
            session = self.sessions.get(run_id, department)
        except KeyError:
            ids = {item.department: item.session_id for item in projection.sessions.values()}
            self.sessions.create_run_sessions(run_id, ids)
            session = self.sessions.get(run_id, department)

        activation_id = new_id("act")
        transaction.on_commit(lambda: session.activate(activation_id))
        prompt = projection.department_prompts[department]
        basis = WorkBasis.current(projection, department)
        guidance_ids = tuple(item.id for item in pending_guidance(projection, department))
        target_metadata = self._target_metadata(target, adapter, snapshot_id)
        parent = transaction.append(NewEvent(
            EventType.DEPARTMENT_ACTIVATED,
            role=department,
            state_before=projection.phase,
            state_after=projection.phase,
            session_id=session.session_id,
            provider=self._configured_provider(target, adapter),
            payload={"activation_id": activation_id, "cycle": projection.cycle_count + 1,
                     "effective_contract_hash": basis.effective_contract_hash,
                     "engineering_plan_hash": basis.engineering_plan_hash, "request_id": basis.request_id,
                     "guidance_ids": list(guidance_ids),
                     "guidance_only": guidance_only,
                     "yielded_work": yielded_work,
                     "guidance_version": basis.guidance_version,
                     "input_version": basis.input_version, "prompt_version": prompt.version,
                     "prompt_hash": prompt.prompt_ref.content_hash,
                     **target_metadata},
        ))[0]
        scope = ActivationScope(
            run_id, department, session.session_id, activation_id, parent.event_id,
            prompt_version=prompt.version, prompt_hash=prompt.prompt_ref.content_hash, guidance_ids=guidance_ids,
            guidance_only=guidance_only, basis=basis, provider=self._configured_provider(target, adapter),
            target=target_metadata, secret=getattr(target, "api_key", None),
        )
        return _Activation(scope, prompt, self._abort.setdefault(run_id, Event()), adapter, target, yielded_work,
                           transaction.projection.stream_version)

    @staticmethod
    def _work_basis(projection: RunProjection) -> dict[str, Any]:
        return {
            "phase": projection.phase,
            "effective_contract_hash": current_contract_hash(projection),
            "engineering_plan_hash": current_plan_hash(projection),
            "delivery_spec_hash": None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
        }

    @staticmethod
    def _configured_provider(target: FrozenTarget | None, adapter: ModelAdapter) -> str:
        return target.provider_id if target is not None else getattr(adapter, "name", "test")

    @staticmethod
    def _configured_model(target: FrozenTarget | None, adapter: ModelAdapter) -> str:
        return target.model if target is not None else getattr(adapter, "model", "unknown")

    @classmethod
    def _target_metadata(
        cls,
        target: FrozenTarget | None,
        adapter: ModelAdapter,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        if target is None:
            return {
                "snapshot_id": snapshot_id,
                "provider_config_id": None,
                "model_id": None,
                "provider_name": cls._configured_provider(target, adapter),
                "protocol": "test",
                "base_url": None,
                "requested_provider": cls._configured_provider(target, adapter),
                "requested_protocol": "test",
                "requested_model": cls._configured_model(target, adapter),
                "credential_ref": None,
                "credential_version": None,
                "context_window": None,
                "configured_max_output_tokens": None,
            }
        return {
            "snapshot_id": snapshot_id,
            "provider_config_id": target.provider_id,
            "model_id": target.model_id,
            "provider_name": target.provider_name,
            "protocol": target.protocol,
            "base_url": target.base_url,
            "requested_provider": target.provider_id,
            "requested_protocol": target.protocol,
            "requested_model": target.model,
            "credential_ref": target.credential_ref,
            "credential_version": target.credential_version,
            "context_window": target.context_window,
            "configured_max_output_tokens": target.max_output_tokens,
        }

    async def _invoke_activation(self, activation: _Activation) -> None:
        scope = activation.scope
        run_id, department = scope.run_id, scope.department
        projection = self.project(run_id)
        try:
            workspace = self.workspace(run_id)
            workspace.bind_check(
                activation_id=scope.activation_id,
                product_spec_hash=None if projection.product_spec is None else projection.product_spec.content_hash,
                delivery_spec_hash=None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
                effective_contract_hash=scope.basis.effective_contract_hash,
                engineering_plan_hash=scope.basis.engineering_plan_hash,
            )
            activation.driver = StepDriver.start(
                scope, activation.prompt, writes=self.writes, artifacts=self.artifacts,
                assembly=self.assembly, adapter=activation.adapter, target=activation.target,
                environment=LocalEnvironment(workspace, registered_commands=dict(projection.registered_commands)),
                nodes=_SafeNode(self, activation), cancelled=activation.abort_flag, limits=self.step_limits,
            )
            result = await activation.driver.result()
        except Exception as exc:
            # 步骤驱动没有开始：依据是激活开始时的运行状态
            self._end_run(activation, "provider_error", f"{type(exc).__name__}: {exc}", activation.version)
            return
        if isinstance(result, Stopped) and result.reason is not None:
            self._end_run(activation, result.reason, result.message, result.version)
            return

        current = self.project(run_id)
        if current.phase in TERMINAL_PHASES:
            return
        if isinstance(result, Stopped):
            elapsed = time.monotonic() - self._run_start_times.get(run_id, time.monotonic())
            if elapsed >= current.run_time_limit_sec:
                self._end_run(activation, "time_limit",
                              f"run wall-clock time {int(elapsed)}s exceeded limit of {current.run_time_limit_sec}s",
                              result.version)
            return
        submission = result

        try:
            transcript_ref = None
            if submission.transcript:
                ref = self.artifacts.put(run_id, "transcript", submission.transcript, media_type="text/plain")
                transcript_ref = ref.__dict__
            self._apply_proposal(
                run_id, department=department, projection=projection, proposal=submission.proposal,
                basis=scope.basis,
                transcript_ref=transcript_ref, parent_event_id=scope.parent_event_id,
                session_id=scope.session_id,
                yielded_work=activation.yielded_work,
                provider=submission.response.provider or self._configured_provider(activation.target, activation.adapter),
                model=submission.response.model,
            )
        except Exception as exc:
            self._end_run(activation, "host_commit_error", f"{type(exc).__name__}: {exc}", None)

    def _apply_proposal(
        self,
        run_id: str,
        *,
        department: str,
        projection: RunProjection,
        basis: WorkBasis,
        proposal: dict[str, Any] | None,
        transcript_ref: dict[str, Any] | None,
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
        yielded_work: dict[str, Any] | None = None,
    ) -> None:
        # 提案先按读取时的运行状态与工作区事实校验，并记下读取的流版本；提交以这个版本作为期望版本：
        # 事务中关闭过时的协作请求以后，由 U 按事务中的运行状态与工作区事实作提交判断，再写入提交、拒绝或接纳的事件。
        # 校验以后另一方写入了这个 run 时写入口拒绝提交，按写入以后的状态重新校验与判断（仍然有效就提交，
        # 否则按 execution_basis 拒绝）。
        # 工作区事实向执行环境查询；提交需要带文件内容的公开树（交付封存），提交判断使用同一次读取的事实
        environment = self._environment(run_id)
        while True:
            evaluated = self.writes.read(run_stream(run_id))
            facts = environment.query(FactsQuery(tree=True)).tree
            decision = proposal_decision(evaluated.projection, department=department, proposal=proposal,
                                         facts=facts, events=evaluated.events())
            try:
                self.writes.transact(run_stream(run_id), lambda transaction: self._commit_proposal(
                    transaction, evaluated=evaluated, facts=facts, decision=decision, environment=environment,
                    department=department, started=projection, basis=basis, proposal=proposal,
                    transcript_ref=transcript_ref, parent_event_id=parent_event_id, session_id=session_id,
                    provider=provider, model=model, yielded_work=yielded_work,
                ), expected_version=evaluated.version)
                return
            except StreamVersionConflict:
                continue

    def _commit_proposal(
        self,
        transaction: Transaction,
        *,
        evaluated: Snapshot,
        facts: TreeFacts,
        decision: ProposalDecision,
        environment: LocalEnvironment,
        department: str,
        started: RunProjection,
        basis: WorkBasis,
        proposal: dict[str, Any] | None,
        transcript_ref: dict[str, Any] | None,
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
        yielded_work: dict[str, Any] | None,
    ) -> None:
        # 提交的事务：读取的流版本就是校验时的版本
        run_id = transaction.projection.run_id
        current = transaction.projection
        if current.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
            return
        current = self._close_obsolete_request(transaction)
        snapshot = environment.snapshot()
        judged = commit_decision(
            decision, department=department, proposal=proposal, basis=basis, started=started,
            evaluated=evaluated.projection, facts=facts, current=current, current_facts=snapshot.facts,
            events=transaction.events(),
        )
        if proposal is not None:
            transaction.append(NewEvent(
                EventType.PROPOSAL_SUBMITTED, role=department,
                parent_event_id=parent_event_id,
                state_before=current.phase, state_after=current.phase,
                session_id=session_id, provider=provider, model=model,
                payload={"kind": proposal.get("kind"), "transcript_ref": transcript_ref,
                         "raw_keys": sorted(proposal.keys()), "input_version": basis.input_version,
                         "definitions_version": DEFINITIONS.version},
            ))
        if not judged.accepted:
            transaction.append(NewEvent(
                EventType.PROPOSAL_REJECTED, role=department,
                parent_event_id=parent_event_id,
                state_before=current.phase, state_after=current.phase,
                session_id=session_id, provider=provider, model=model,
                payload={
                    "errors": judged.error_dicts,
                    "transcript_ref": transcript_ref,
                    "kind": None if proposal is None else proposal.get("kind"),
                    "input_version": basis.input_version,
                    "definitions_version": DEFINITIONS.version,
                },
            ))
            return
        self._commit_accepted(
            transaction, department=department, snapshot=snapshot,
            artifact=judged.artifact or {}, transitions=judged.transitions,
            parent_event_id=parent_event_id, session_id=session_id, provider=provider, model=model,
            yielded_work=yielded_work,
        )

    def _commit_accepted(
        self,
        transaction: Transaction,
        *,
        department: str,
        snapshot: WorkspaceSnapshot,
        artifact: dict[str, Any],
        transitions: list[tuple[str, str]],
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
        yielded_work: dict[str, Any] | None = None,
    ) -> None:
        projection = transaction.projection
        run_id = projection.run_id
        if projection.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
            return
        try:
            acceptance = self.submissions.prepare(
                transaction, projection=projection, snapshot=snapshot, workspace_root=self.workspace_root / run_id,
                artifact=artifact,
                department=department, parent_event_id=parent_event_id, session_id=session_id,
                provider=provider, model=model,
            )
        except Exception as exc:
            # 接纳所需的工件、材料或 Git 版本没有保存成功：提交的记录保留，运行在同一事务中以 host_commit_error 结束
            self._fail(transaction, "host_commit_error", f"{type(exc).__name__}: {exc}")
            return
        source_event = acceptance.append(transaction)
        if artifact["kind"] == "qa_review" and artifact["verdict"] in {"rework_product", "rework_engineering"}:
            self._record_lesson_candidate(transaction, source_event, projection)
        for source, target in transitions:
            transaction.append(NewEvent(
                EventType.TRANSITION,
                role=department_for_phase(target) or department,
                parent_event_id=parent_event_id,
                state_before=source,
                state_after=target,
                session_id=session_id,
                payload={"from": source, "to": target, "route": f"{source}->{target}"},
            ))
            if target == "DONE":
                transaction.append(NewEvent(
                    EventType.RUN_DONE,
                    role="quality",
                    parent_event_id=parent_event_id,
                    state_before="QUALITY",
                    state_after="DONE",
                    session_id=session_id,
                    stop_reason="released",
                    payload={"stop_reason": "released"},
                ))
                transaction.on_commit(lambda: self.sessions.close_run(run_id))
        self._resume_yielded_work(
            transaction, artifact=artifact, yielded_work=yielded_work,
            parent_event_id=parent_event_id, session_id=session_id, department=department,
        )

    def _resume_yielded_work(
        self,
        transaction: Transaction,
        *,
        artifact: dict[str, Any],
        yielded_work: dict[str, Any] | None,
        parent_event_id: str,
        session_id: str,
        department: str,
    ) -> None:
        current = transaction.projection
        basis = current.yielded_work or yielded_work
        if artifact.get("kind") != "department_guidance_response" or not basis:
            return
        if current.phase in TERMINAL_PHASES:
            return
        target = guidance_resume_phase(basis, current)
        if target == current.phase:
            return
        transaction.append(NewEvent(
            EventType.TRANSITION,
            role=department_for_phase(target) or department,
            parent_event_id=parent_event_id,
            state_before=current.phase,
            state_after=target,
            session_id=session_id,
            payload={"from": current.phase, "to": target, "route": f"{current.phase}->{target}",
                     "yielded_work_resolved": True, "yielded_work": dict(basis)},
        ))

    @staticmethod
    def _record_lesson_candidate(transaction: Transaction, source: RunEvent, projection: RunProjection) -> None:
        if source.type == EventType.QA_SUBMITTED:
            observed = source.payload
            observation = {key: observed[key] for key in ("verdict", "rationale", "defects")}
            suggestion = "根据本次质检记录，补充能复现所述问题的检查，验证修复是否满足原验收条件。"
            spec_hash = observed["product_spec_hash"]
            delivery_hash = observed["delivery_spec_hash"]
            checks = observed["checks"]
            refs = observed["evidence_refs"]
        else:
            observation = {"stop_reason": source.stop_reason, "message": source.error}
            suggestion = "根据本次失败事件复现失败条件，验证调整是否消除该条件；原因尚待确认。"
            spec = projection.product_spec
            delivery = projection.delivery_spec
            if delivery is not None and delivery.status != "active":
                delivery = None
            spec_hash = spec.content_hash if spec is not None else None
            delivery_hash = delivery.content_hash if delivery is not None else None
            checks = delivery.checks if delivery is not None else []
            refs = [asdict(delivery.tree_ref)] if delivery is not None else []
        transaction.append(NewEvent(
            EventType.LESSON_CANDIDATE_RECORDED,
            role=source.role, parent_event_id=source.event_id,
            state_before=source.state_after, state_after=source.state_after,
            session_id=source.session_id,
            payload={
                "kind": "lesson_candidate", "id": new_id("lesson"), "status": "unverified",
                "source_event_id": source.event_id, "source_type": source.type,
                "observation": observation, "suggestion": suggestion,
                "product_spec_hash": spec_hash, "delivery_spec_hash": delivery_hash,
                "checks": checks, "evidence_refs": refs,
            },
        ))

    def _end_run(self, activation: _Activation, reason: str, message: str, version: int | None) -> None:
        # 在一个事务中按停止原因暂停或结束运行。version 是作出停止判断时 run 流的版本：同一事务中核对此后有没有
        # 用户的命令或输入写入；有写入、并且写入改变了这次激活的依据（输入或指导）时，停止判断已经过期，
        # 按安全节点停止处理，运行继续，由下一次激活处理新的输入或指导。运行时间用完不因此改变；
        # 已经结束（例如已经取消）的运行不再写入
        def end(transaction: Transaction) -> None:
            if version is not None and reason != "time_limit" and self._superseded(transaction, activation, version):
                return
            self._end(transaction, reason, message)

        self.writes.transact(run_stream(activation.run_id), end)

    def _superseded(self, transaction: Transaction, activation: _Activation, version: int) -> bool:
        if not any(event.role == "user" for event in transaction.events_after(version)):
            return False
        projection = transaction.projection
        basis = activation.scope.basis
        return (projection.input_version != basis.input_version
                or guidance_version(projection, activation.department) > basis.guidance_version)

    def _end(self, transaction: Transaction, reason: str, message: str) -> None:
        # 按定义中停止原因规定的方式暂停或结束运行；已经结束的运行不再写入
        if DEFINITIONS.stop_reason(reason).outcome == "paused":
            self._pause(transaction, reason)
        else:
            self._fail(transaction, reason, message)

    def _pause(self, transaction: Transaction, reason: str) -> None:
        projection = transaction.projection
        if projection.phase in TERMINAL_PHASES:
            return
        department = projection.active_department
        projection = self._close_request(transaction, status="stopped", reason=reason,
                                         return_phase=projection.phase, return_work_valid=False)
        transaction.append(NewEvent(
            EventType.RUN_PAUSED, role=department,
            state_before=projection.phase, state_after="PAUSED", stop_reason=reason,
            provider=projection.provider, model=projection.model,
            payload={
                "stop_reason": reason,
                "human_action": DEFINITIONS.stop_reason(reason).human_action,
                "paused_at_phase": projection.phase,
                "cycle_count": projection.cycle_count,
                "max_cycles": projection.max_cycles,
                "token_used": projection.token_used,
            },
        ))
        transaction.on_commit(lambda: self.sessions.close_run(projection.run_id))

    def _fail(self, transaction: Transaction, reason: str, message: str,
              *, input_save_failure: dict[str, str] | None = None) -> None:
        human = DEFINITIONS.stop_reason(reason).human_action
        projection = transaction.projection
        if projection.phase in TERMINAL_PHASES:
            return
        department = projection.active_department
        status = "cancelled" if reason == "cancelled" else "timed_out" if reason == "provider_timeout" else "stopped"
        projection = self._close_request(transaction, status=status, reason=reason,
                                         return_phase=projection.phase, return_work_valid=False)
        source_event = transaction.append(NewEvent(
            EventType.RUN_FAILED, role=department,
            state_before=projection.phase, state_after="FAILED", stop_reason=reason, error=message,
            provider=projection.provider, model=projection.model,
            payload={"stop_reason": reason, "human_action": human, "message": message,
                     **({"input_save_failure": input_save_failure} if input_save_failure is not None else {})},
        ))[0]
        transaction.on_commit(lambda: self.sessions.close_run(projection.run_id))
        if reason != "cancelled":
            self._record_lesson_candidate(transaction, source_event, projection)

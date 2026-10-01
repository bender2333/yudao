# 流程编排：运行的生命周期（创建、输入、指导、提示词、取消、运行到停止、作为任务开始）、激活的准备与收尾、
# 新输入的分派、提案接纳以后的流转、用户决定（发出决定请求、按回答解除阻塞、运行结束时撤销）、暂停与失败。
# 一次激活内的步骤交给步骤驱动，只调用它的开始、取消与取得结果；同时为步骤驱动实现安全节点接口。
# 流程编排不调用模型。
# 每一处「读取运行状态、判断、写入」都是写入口的一个事务（WritePath.transact）：判断期间不持有锁，
# 另一方在读取以后写入了同一个 run，提交被拒绝，按写入以后的状态重新判断。

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Condition, Event
from typing import Any

from .actions import FactsQuery, TreeFacts
from .adapters.base import ModelAdapter
from .adapters.facade_adapter import FacadeAdapter
from .adjudication import WorkBasis, commit_decision, guidance_version, proposal_decision
from .artifacts import ArtifactStore
from .assembly import PENDING_GUIDANCE, ContextAssembly, pending_guidance
from .compaction import response_reserve
from .contracts import current_contract_hash, current_plan_hash
from .collaboration import guidance_resume_phase, request_still_applicable, resume_phase
from .decisions import (
    DEFINITIONS_CHANGED, MODEL_UNAVAILABLE, DecisionClosed, DecisionNotFound, InvalidOption, StaleDecision,
    blocks_run,
)
from .environment import LocalEnvironment
from .deltas import DeltaChannel
from .event_store import Command, EventStore, StreamVersionConflict, run_stream
from .write_path import NewEvent, Snapshot, Transaction, WritePath
from .engine import Judgment, StepDriver, StepLimits, Stopped
from .streams import RUN_EVENT_VERSION, STOP_REASON_UPGRADE, classify_startup_runs
from .git_versions import GitVersionStore
from .interactions import CancelledInputSaveError, InteractionWriter, RunTerminalError
from .definitions import DEFINITIONS
from .overview import repository_overview
from .models import (
    Event as RunEvent,
    DEPARTMENTS,
    DecisionRequest,
    DepartmentPrompt,
    EventType,
    TERMINAL_PHASES,
    department_for_phase,
    new_id,
)
from .providers import ProviderConnections, ProviderFacade
from .projection import RunNotFoundError, RunProjection, project_run, saved_decision
from .public_tree import CapturedTree, UnrepresentableWorkspace
from .recording import ActivationScope
from .sessions import SessionFactory
from .snapshot import SNAPSHOT_FIELDS
from .submissions import SubmissionWriter
from .tools import normalize_registered_commands
from .validation import ProposalDecision
from .workspace import WorkspaceSnapshot

# 由用户提出的事件：输入、部门 Prompt 更新与部门指导（提出者为 user:local）
_USER_EVENTS = frozenset({EventType.USER_INPUT_RECEIVED, EventType.DEPARTMENT_PROMPT_UPDATED,
                          EventType.DEPARTMENT_GUIDANCE_RECEIVED})


@dataclass
class _Activation:
    # 流程编排持有的一次激活：身份、采用的版本与工作依据（scope），提示词与适配器，
    # 中止信号，激活开始时 run 流的版本，步骤驱动，以及在安全节点等待重试时的唤醒
    scope: ActivationScope
    prompt: DepartmentPrompt
    abort_flag: Event
    adapter: ModelAdapter
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
        test_model: str = "fake-script",
        sessions: SessionFactory | None = None,
        step_limits: StepLimits = StepLimits(),
        deltas: DeltaChannel | None = None,
    ) -> None:
        self.store = store
        self.writes = writes
        self.step_limits = step_limits
        self.deltas = deltas if deltas is not None else DeltaChannel()
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
        self.test_model = test_model
        self.assembly = ContextAssembly(artifacts)
        self.sessions = sessions or SessionFactory()
        self._abort: dict[str, Event] = {}
        # 每个 run 正在进行的取消（cancel 或 /stop）；一个取消结束时通知等待它的激活与运行循环
        self._cancellers: dict[str, set[object]] = {}
        self._cancellers_changed = Condition()
        # 正在激活的 run：_running 在准备激活之前以 setdefault 占用（同一 run 只能有一次激活），_active 是激活本身
        self._running: dict[str, object] = {}
        self._active: dict[str, _Activation] = {}
        self._run_start_times: dict[str, float] = {}
        # 作为任务开始（start）的 run 与它的任务；任务结束时移除
        self._tasks: dict[str, asyncio.Task[RunProjection]] = {}
        # 事项的执行任务与结算：run_id -> 任务；由 start_work_item 建立，任务结束时移除
        self._work_item_tasks: dict[str, asyncio.Task[Any]] = {}
        # 项目服务在装配以后回填，用于结算与判断执行槽位（busy）
        self.projects: Any = None

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
        kind: str = "change",
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
        if kind not in DEFINITIONS.work_items.kinds:
            raise ValueError(f"work item kind {kind!r} is not defined in work_items.json")
        if kind == "onboarding":
            # 建档事项由快照开始：没有采纳成果，也没有可写的工作区（工单 #134）
            if code_snapshot is None or initial_tree is None or baseline is not None:
                raise ValueError("an onboarding run requires a code snapshot with its initial tree and has no baseline")
        _validate_run_ownership(
            project_id=project_id, work_item_id=work_item_id, baseline=baseline, initial_tree=initial_tree,
            code_snapshot=code_snapshot,
            project_context=project_context, department_prompts=department_prompts,
            prompt_config_versions=prompt_config_versions,
        )
        frozen_commands = _validate_frozen_commands(registered_commands, command_versions)
        run_id = run_id or new_id("run")
        material_dir = (self.materials_root / run_id).resolve()
        if material_dir == self.materials_root.resolve() or not material_dir.is_relative_to(self.materials_root.resolve()):
            raise ValueError("run_id must stay within the run materials directory")
        # 工作区先于其余材料落盘：从封存快照建立失败时不留下半个 run。
        environment = LocalEnvironment.establish(self.workspace_root / run_id, initial_tree)
        workspace_digest = environment.snapshot().digest
        # 事项种类的部门说明优先于项目里配置的角色说明（工单 #134）：建档的读取顺序与粒度规则写在种类定义中
        fallback = department_prompts if department_prompts is not None else {
            department: DEFINITIONS.role(department).prompt for department in DEPARTMENTS
        }
        prompts = {
            department: (work.prompt if (work := DEFINITIONS.department_work(department, kind)) is not None
                         else fallback[department])
            for department in DEPARTMENTS
        }
        initial = self.interactions.initial(run_id, task, department_prompts=prompts)
        sessions = self.sessions.create_run_sessions(run_id)
        self._abort[run_id] = Event()
        project_context_ref = None
        if project_context is not None:
            project_context_ref = asdict(self.artifacts.put(
                run_id, "project_context", project_context, media_type="text/markdown",
            ))
        overview_ref = None
        if kind == "onboarding":
            # 仓库概况由快照的公开树确定性地生成，作为建档中部门读取的第一项材料（设计第 4.1、4.2 节）
            overview_ref = asdict(self.artifacts.put(
                run_id, "repository_overview", repository_overview(initial_tree), media_type="text/markdown",
            ))
        run_created = NewEvent(
            EventType.RUN_CREATED,
            actor="system",
            department="product",
            state_before="CREATED",
            state_after="PRODUCT_SPEC",
            payload={
                "task": task,
                "kind": kind,
                **initial,
                "intend_path": (Path("materials") / run_id / "intend.md").as_posix(),
                "max_cycles": max_cycles,
                "run_time_limit_sec": run_time_limit_sec,
                "context_window": context_window,
                "provider": self.test_provider if self.test_adapter_factory is not None else "directory",
                "adapter": self.test_adapter_name if self.test_adapter_factory is not None else "directory",
                "sessions": {name: session.session_id for name, session in sessions.items()},
                "project_id": project_id,
                "work_item_id": work_item_id,
                "baseline": baseline,
                "snapshot": code_snapshot,
                "overview_ref": overview_ref,
                "workspace_digest": workspace_digest,
                "project_context_ref": project_context_ref,
                "prompt_config_versions": dict(prompt_config_versions or {}),
                "registered_commands": frozen_commands[0],
                "command_versions": frozen_commands[1],
                "definitions_version": DEFINITIONS.version,
                "run_event_version": RUN_EVENT_VERSION,
            },
        )
        transition = NewEvent(
            EventType.TRANSITION,
            actor="system",
            department="product",
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

    def _install_test_call_target(self, context_window: int) -> None:
        # 测试系统的确定性适配器：用它的名称与模型名登记一个 fake 协议的模型访问定义。
        # 声明的输出上限取不改变默认保留的值，使既有的阈值行为与事项窗口一致
        if self.facade is None:
            raise ValueError("a provider facade is required for runs")
        provider_id = self.test_provider
        model_id = f"{provider_id}-model"
        self.facade.store_document({
            "providers": [{"id": provider_id, "name": provider_id, "protocol": "fake", "base_url": ""}],
            "models": [{
                "id": model_id, "provider_id": provider_id, "model": self.test_model,
                "context_window": context_window,
                "max_output_tokens": response_reserve(context_window, None),
            }],
            "bindings": {department: {"provider_id": provider_id, "model_id": model_id}
                         for department in DEPARTMENTS},
        })
    def _environment(self, run_id: str) -> LocalEnvironment:
        return LocalEnvironment.open(self.workspace_root / run_id)

    def add_input(self, run_id: str, text: str, *, base_version: int | None = None,
                  command: Command | None = None) -> RunProjection:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("input must be a non-empty string")
        if text.strip() in {"/stop", "/cancel"}:
            return self._stop_by_command(run_id, text)

        def receive(transaction: Transaction) -> None:
            self._require_open(run_id, transaction.projection, "This run has ended; create a new task for this input.")
            self.interactions.receive(transaction, text, command=False, base_version=base_version)

        self.writes.transact(run_stream(run_id), receive, command=command)
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
        with self._cancellers_changed:
            self._cancellers.setdefault(run_id, set()).add(token)
        try:
            yield
        finally:
            with self._cancellers_changed:
                self._cancellers[run_id].discard(token)
                self._cancellers_changed.notify_all()

    def _settled(self, run_id: str) -> RunProjection:
        # 激活与运行循环结束时交回的运行状态。有正在进行的取消（cancel 或 /stop），或者运行已经中止而取消还没有写入时，
        # 等待正在进行的取消结束，交回它写入以后的状态；运行已经中止而没有正在进行的取消（例如它的写入失败了）时
        # 在这里写入取消
        def aborted() -> bool:
            return bool(self._abort.get(run_id) and self._abort[run_id].is_set())

        projection = self.project(run_id)
        if projection.phase in TERMINAL_PHASES:
            return projection
        with self._cancellers_changed:
            if not self._cancellers.get(run_id) and not aborted():
                return projection
            self._cancellers_changed.wait_for(lambda: not self._cancellers.get(run_id))
        projection = self.project(run_id)
        if projection.phase in TERMINAL_PHASES or not aborted():
            return projection
        return self.cancel(run_id)

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

    def add_guidance(self, run_id: str, department: str, text: str, *,
                     base_version: int | None = None, command: Command | None = None) -> RunProjection:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")

        def receive(transaction: Transaction) -> None:
            self._require_open(run_id, transaction.projection, "This run has ended; guidance can be sent to a new task.")
            self.interactions.receive_guidance(transaction, department, text, base_version=base_version)

        self.writes.transact(run_stream(run_id), receive, command=command)
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
            EventType.PRODUCT_INPUT_ASSIGNED, actor="system", department="product",
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
            stop = self._stop_requested(activation, projection, transaction.decisions.values())
            return Judgment(not stop, projection.stream_version)

        return self.writes.transact(run_stream(activation.run_id), judge)

    def _stop_requested(self, activation: _Activation, projection: RunProjection,
                        decisions: Iterable[DecisionRequest]) -> bool:
        # 停止判断：中止、运行时间用完、终态、有未回答的阻塞 run 的决定请求、输入版本改变或有新的指导；
        # 只读取，不写入
        basis = activation.scope.basis
        return (activation.abort_flag.is_set() or self._time_used_up(activation.run_id, projection)
                or projection.phase in TERMINAL_PHASES or blocks_run(decisions)
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
            EventType.COLLABORATION_CLOSED, actor="system", department=request.recipient,
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

    def cancel(self, run_id: str, *, command: Command | None = None) -> RunProjection:
        # 已经结束的运行不变；否则中止并取消正在进行的步骤，再写入取消。取消正在进行的步骤出错时，
        # 取消照常写入，再通知一次，错误交给调用方
        with self._cancelling(run_id):
            if self.project(run_id).phase in TERMINAL_PHASES:
                return self.project(run_id)
            activation, cancel_error = self._abort_run(run_id)
            try:
                self.writes.transact(run_stream(run_id), lambda transaction: self._fail(
                    transaction, "cancelled", "run cancelled"), command=command)
            finally:
                if cancel_error is not None:
                    self._cancel_driver(activation)
        if cancel_error is not None:
            raise cancel_error
        return self.project(run_id)
    def stop_for_upgrade(self, run_id: str, *, reason: str) -> RunProjection:
        # 因升级停止（ADR-0019，工单 #126）：run 事件版本与当前版本不同的未结束 run 记为因升级停止，
        # 停止原因写在带版本定义的停止原因清单中；已经结束的 run 不变
        message = f"run event version differs from the current version: {reason}"
        self.writes.transact(run_stream(run_id), lambda transaction: self._fail(transaction, STOP_REASON_UPGRADE, message))
        return self.project(run_id)

    def resume_incomplete_run(self, run_id: str) -> tuple[int, RunProjection] | None:
        # 启动时自动继续一个因进程中断而未结束的 run（工单 #16，ADR-0018、恢复契约第 5.2 节）：
        # 先核对事项记录的定义版本，与当前加载的版本不同时发出决定请求交给用户（ADR-0014，总体架构第 7.4 节），
        # 用户选择「按新版本继续」以前不取得执行权；然后原子取得这个 run 的执行权，记下中断位置与继续的依据，
        # 再从已提交的状态继续运行到终态。已经结束的 run 不取得执行权、不写事件；
        # 有未回答、阻塞整个 run 的决定请求（模型引用无法使用或定义版本不同）时不继续，交给用户回答
        projection = self.project(run_id)
        if projection.phase in TERMINAL_PHASES:
            return None
        if blocks_run(self.writes.read(run_stream(run_id)).decisions.values()):
            return None
        if projection.definitions_version != DEFINITIONS.version:
            self._await_definitions(run_id, projection.definitions_version)
            return None
        return self._claim_and_resume(run_id)

    def _await_definitions(self, run_id: str, recorded: str) -> None:
        # 事项记录的定义版本与当前加载的版本不同（ADR-0014，#48 登记的架构问题的处理）：
        # 发出一个阻塞整个 run 的决定请求，选项为「按新版本继续」与「停止」；选择写入事件。
        # 请求只发一次：已经有过一个定义版本不同的请求时不重复
        def request(transaction: Transaction) -> None:
            projection = transaction.projection
            if projection.phase in TERMINAL_PHASES or blocks_run(transaction.decisions.values()):
                return
            if any(decision.request.get("kind") == DEFINITIONS_CHANGED.name
                   for decision in transaction.decisions.values()):
                return
            current = DEFINITIONS.version
            transaction.append(NewEvent(
                EventType.DECISION_REQUESTED, actor="system", department=projection.active_department,
                state_before=projection.phase, state_after=projection.phase,
                payload={
                    "kind": DEFINITIONS_CHANGED.name, "blocks": DEFINITIONS_CHANGED.blocks,
                    "options": [{"id": option.id, "label": option.label} for option in DEFINITIONS_CHANGED.options],
                    "description": (f"事项使用的定义版本 {recorded or '（未记录）'} 与当前加载的版本 {current} 不同。"
                                    "按新版本继续以后，后续的模型请求与裁决记录新版本；选择停止事项则运行结束。"),
                    "facts": [], "department": projection.active_department,
                    "reason": "definitions_version_changed",
                    "recorded_definitions_version": recorded, "current_definitions_version": current,
                },
            ))
            transaction.on_commit(lambda: self._wake(run_id))

        self.writes.transact(run_stream(run_id), request)

    def _claim_and_resume(self, run_id: str) -> tuple[int, RunProjection]:
        # 取得执行权并写入 run_resumed：中断位置与继续的依据取自取得执行权时的投影。
        # 恢复不写限额与计数字段（激活次数、模型步数、重试与已用运行时间保持中断时的值），
        # 也不新增部门激活：之后开始的激活由激活本身写入
        def claim(transaction: Transaction) -> int:
            projection = transaction.projection
            previous = self.store.projection(run_stream(run_id))
            # 执行权编号在写入口以已记录的编号加一确定；另一方先取得时流版本同时改变，
            # 这里的依据过期，事务因版本不符重新判断，因此这个编号与写入口确定的编号相同
            transaction.append(NewEvent(
                EventType.RUN_RESUMED, department=projection.active_department, actor="system",
                state_before=projection.phase, state_after=projection.phase,
                parent_event_id=projection.last_event_id,
                payload={
                    "basis": {
                        "interrupted_at_phase": projection.phase,
                        "interrupted_at_version": projection.stream_version,
                        "interrupted_at_event_id": projection.last_event_id,
                        "recorded_run_event_version": projection.run_event_version,
                        "current_run_event_version": RUN_EVENT_VERSION,
                    },
                    "acquired_epoch": (0 if previous is None or previous.epoch is None else previous.epoch) + 1,
                    "previous_epoch": None if previous is None else previous.epoch,
                },
            ))
            return (0 if previous is None or previous.epoch is None else previous.epoch) + 1

        epoch, _ = self.writes.claim_execution_right(run_stream(run_id), claim)
        return epoch, self.project(run_id)

    def _cancel_driver(self, activation: _Activation) -> None:
        # 取消步骤驱动（正在进行的调用尝试按身份取消），在安全节点等待重试的激活立即醒来；取消调用尝试出错时同样唤醒
        try:
            if activation.driver is not None:
                activation.driver.cancel()
        finally:
            self._wake(activation.run_id)

    async def run_until_stop(self, run_id: str) -> RunProjection:
        # 运行到终态，或者到 run 被未回答的决定请求阻塞、等待用户回答为止。
        # 一次运行期间的模型调用复用同一组连接，连接只在这个事件循环中使用
        connections = ProviderConnections()
        try:
            while True:
                snapshot = self.writes.read(run_stream(run_id))
                projection = snapshot.projection
                if not projection.run_id:
                    raise RunNotFoundError(run_id)
                if projection.phase in TERMINAL_PHASES:
                    return projection
                if self._abort.get(run_id) and self._abort[run_id].is_set():
                    return await asyncio.to_thread(self._settled, run_id)
                if blocks_run(snapshot.decisions.values()):
                    return projection
                await self._activate_once(run_id, connections)
        finally:
            await connections.aclose()

    def start(self, run_id: str) -> asyncio.Task[RunProjection]:
        # 在当前事件循环中把这个 run 作为任务运行到停止（run_until_stop）；这个 run 已有任务时，新任务在它结束以后开始。
        # 任务出错时交给事件循环的异常处理报告
        previous = self._tasks.get(run_id)
        task = asyncio.get_running_loop().create_task(self._run_after(previous, run_id))
        self._tasks[run_id] = task
        task.add_done_callback(lambda done: self._task_done(run_id, done))
        return task

    def execution(self, run_id: str) -> asyncio.Task[RunProjection] | None:
        # 这个 run 正在进行的任务；没有时为空
        return self._tasks.get(run_id)

    def work_item_execution(self, run_id: str) -> asyncio.Task[Any] | None:
        # 这个事项的 run 正在进行的执行任务（由 start_work_item 建立）；没有时为空
        return self._work_item_tasks.get(run_id)

    # 执行与结算的入口（应用层与接口层设计说明第 7.2 节）。
    # 3.4A 之前只有一个执行槽位：已有事项在执行时新建被拒绝（busy）

    def busy(self) -> bool:
        # 有事项的 run 正在作为任务运行、有 run 正在激活、有 run 正在作为任务运行（start），
        # 或有事项正在开始（run 还没有创建）时算作占用执行槽位
        if self._tasks or self._work_item_tasks or self._running or self._active:
            return True
        if getattr(self.projects, "starting", lambda: False)():
            return True
        # 任务表是进程内的瞬时状态：run 停在等待回答的决定请求上时执行任务已经结束、表中不再有它，
        # 事项却仍是进行中的（回答以后接着执行）。执行槽位是否被占用以事件日志为准：有未结束的 run 就被占用
        unfinished = classify_startup_runs(self.store)
        return bool(unfinished.same_version or unfinished.other_version)

    def start_work_item(self, run_id: str) -> asyncio.Task[ProjectEvent | None]:
        # 在接口进程的事件循环中把事项的 run 作为任务运行；run 结束以后由流程编排结算（采纳）。
        # 任务出错时交给事件循环的异常处理报告
        previous = self._work_item_tasks.get(run_id)
        task = asyncio.get_running_loop().create_task(self._run_work_item(previous, run_id))
        self._work_item_tasks[run_id] = task
        task.add_done_callback(lambda done: self._work_item_task_done(run_id, done))
        return task

    async def _run_work_item(self, previous: asyncio.Task[Any] | None, run_id: str) -> ProjectEvent | None:
        # 先运行到停止，再由流程编排结算这一次 run（幂等）
        if previous is not None:
            await asyncio.wait([previous])
        await self.run_until_stop(run_id)
        return await asyncio.to_thread(self.projects.settle, run_id)

    def _work_item_task_done(self, run_id: str, task: asyncio.Task[Any]) -> None:
        if self._work_item_tasks.get(run_id) is task:
            del self._work_item_tasks[run_id]
        if not task.cancelled() and task.exception() is not None:
            task.get_loop().call_exception_handler({
                "message": f"work item run {run_id} stopped with an error",
                "exception": task.exception(), "task": task,
            })

    async def _run_after(self, previous: asyncio.Task[RunProjection] | None, run_id: str) -> RunProjection:
        if previous is not None:
            await asyncio.wait([previous])
        return await self.run_until_stop(run_id)

    def _task_done(self, run_id: str, task: asyncio.Task[RunProjection]) -> None:
        if self._tasks.get(run_id) is task:
            del self._tasks[run_id]
        if not task.cancelled() and task.exception() is not None:
            task.get_loop().call_exception_handler({
                "message": f"run {run_id} stopped with an error", "exception": task.exception(), "task": task,
            })

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
                return await asyncio.to_thread(self._settled, run_id)
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
                        actor="system",
                        department=scope.department,
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
            return await asyncio.to_thread(self._settled, run_id)
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
        if blocks_run(transaction.decisions.values()):
            # 等待用户回答阻塞 run 的决定请求：不开始新的激活，什么也不写
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

        if self.test_adapter_factory is not None:
            # 确定性测试适配器没有目录条目：表示成一个 fake 协议的模型访问定义并绑定三个部门，
            # 声明这个事项的窗口，使步骤驱动的每次解析与真实 Provider 走同一条路径（#45 架构答复第 6 条）
            self._install_test_call_target(projection.context_window)
            try:
                adapter = self.test_adapter_factory(department)
            except Exception as exc:
                self._await_model(transaction, department, None, "provider_unavailable",
                                  f"test adapter creation failed: {exc}")
                return None
        else:
            if self.facade is None:
                self._fail(transaction, "provider_error", "provider facade is required for runs")
                return None
            # 调用目标在每次逻辑调用之前按部门默认解析（#45）：激活只建立桥接，控制核心不持有凭据
            adapter = FacadeAdapter(self.facade, connections=connections)

        availability = adapter.availability()
        if not availability.available:
            # 确定性测试适配器在激活开始时不可用：run 停在这次请求之前，等待用户修复配置后回答
            self._await_model(transaction, department, self._adapter_target_metadata(adapter),
                              availability.reason or "provider_unavailable", availability.message)
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
        provider_name = self._activation_provider(adapter)
        parent = transaction.append(NewEvent(
            EventType.DEPARTMENT_ACTIVATED,
            actor="system",
            department=department,
            state_before=projection.phase,
            state_after=projection.phase,
            session_id=session.session_id,
            provider=provider_name,
            payload={"activation_id": activation_id, "cycle": projection.cycle_count + 1,
                     "effective_contract_hash": basis.effective_contract_hash,
                     "engineering_plan_hash": basis.engineering_plan_hash, "request_id": basis.request_id,
                     "guidance_ids": list(guidance_ids),
                     "guidance_only": guidance_only,
                     "yielded_work": yielded_work,
                     "guidance_version": basis.guidance_version,
                     "input_version": basis.input_version, "prompt_version": prompt.version,
                     "prompt_hash": prompt.prompt_ref.content_hash},
        ))[0]
        scope = ActivationScope(
            run_id, department, session.session_id, activation_id, parent.event_id,
            prompt_version=prompt.version, prompt_hash=prompt.prompt_ref.content_hash, guidance_ids=guidance_ids,
            guidance_only=guidance_only, basis=basis, provider=provider_name,
        )
        return _Activation(scope, prompt, self._abort.setdefault(run_id, Event()), adapter, yielded_work,
                           transaction.projection.stream_version)

    @staticmethod
    def _work_basis(projection: RunProjection) -> dict[str, Any]:
        return {
            "phase": projection.phase,
            "effective_contract_hash": current_contract_hash(projection),
            "engineering_plan_hash": current_plan_hash(projection),
            "delivery_spec_hash": None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
        }

    def _activation_provider(self, adapter: ModelAdapter) -> str:
        # 激活事件上的提供方名称：确定性测试适配器用它的名称；目录驱动的运行在每次请求解析出连接
        return getattr(adapter, "name", "test") if self.test_adapter_factory is not None else "directory"

    @staticmethod
    def _adapter_target_metadata(adapter: ModelAdapter) -> dict[str, Any]:
        # 解析之前模型引用就不可用时写进待恢复请求的目标：身份取自确定性适配器，解析相关的项留空
        provider = getattr(adapter, "name", "test")
        return {
            "provider_config_id": None,
            "model_id": None,
            "provider_name": provider,
            "protocol": "test",
            "base_url": None,
            "requested_provider": provider,
            "requested_protocol": "test",
            "requested_model": getattr(adapter, "model", "unknown"),
            "credential_ref": None,
            "credential_version": None,
            "context_window": None,
            "configured_max_output_tokens": None,
            "selection_source": None,
            "accepts_required_tool_call": None,
            "requested_tier": None,
            "sent_tier": None,
        }

    async def _invoke_activation(self, activation: _Activation) -> None:
        scope = activation.scope
        run_id, department = scope.run_id, scope.department
        projection = self.project(run_id)
        try:
            environment = LocalEnvironment.open(
                self.workspace_root / run_id, registered_commands=dict(projection.registered_commands))
            environment.bind_check(
                activation_id=scope.activation_id,
                product_spec_hash=None if projection.product_spec is None else projection.product_spec.content_hash,
                delivery_spec_hash=None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
                effective_contract_hash=scope.basis.effective_contract_hash,
                engineering_plan_hash=scope.basis.engineering_plan_hash,
            )
            activation.driver = StepDriver.start(
                scope, activation.prompt, writes=self.writes, artifacts=self.artifacts,
                assembly=self.assembly, adapter=activation.adapter, facade=self.facade,
                environment=environment,
                nodes=_SafeNode(self, activation), cancelled=activation.abort_flag, limits=self.step_limits,
                deltas=self.deltas,
            )
            result = await activation.driver.result()
        except UnrepresentableWorkspace as exc:
            # 打开工作区或驱动开始前发现无法表示的条目：以 workspace_unrepresentable 暂停
            self._end_run(activation, "workspace_unrepresentable", str(exc), activation.version)
            return
        except Exception as exc:
            # 步骤驱动没有开始：依据是激活开始时的运行状态
            self._end_run(activation, "provider_error", f"{type(exc).__name__}: {exc}", activation.version)
            return
        if isinstance(result, Stopped) and result.reason is not None:
            self._end_run(activation, result.reason, result.message, result.version, target=result.target)
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
                provider=submission.response.provider or self._activation_provider(activation.adapter),
                model=submission.response.model,
            )
        except UnrepresentableWorkspace as exc:
            # 提案提交（提交判断读取工作区事实、交付封存取得公开树）发现无法表示的条目：暂停，错误不再归入提交错误
            self._end_run(activation, "workspace_unrepresentable", str(exc), None)
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
                EventType.PROPOSAL_SUBMITTED, actor=f"department:{department}", department=department,
                parent_event_id=parent_event_id,
                state_before=current.phase, state_after=current.phase,
                session_id=session_id, provider=provider, model=model,
                payload={"kind": proposal.get("kind"), "transcript_ref": transcript_ref,
                         "raw_keys": sorted(proposal.keys()), "input_version": basis.input_version,
                         "definitions_version": DEFINITIONS.version},
            ))
        if not judged.accepted:
            transaction.append(NewEvent(
                EventType.PROPOSAL_REJECTED, actor=f"department:{department}", department=department,
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
            transaction, department=department, snapshot=snapshot, environment=environment,
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
        environment: LocalEnvironment,
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
                transaction, projection=projection, snapshot=snapshot, environment=environment,
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
                actor="system",
                department=department_for_phase(target) or department,
                parent_event_id=parent_event_id,
                state_before=source,
                state_after=target,
                session_id=session_id,
                payload={"from": source, "to": target, "route": f"{source}->{target}"},
            ))
            if target == "DONE":
                # 进入 DONE 的停止原因按 run 的事项种类取自定义：普通事项为 released，建档事项为 baseline_verified
                stop_reason = DEFINITIONS.work_item(projection.kind).stop_reason
                self._withdraw_decisions(transaction, stop_reason)
                transaction.append(NewEvent(
                    EventType.RUN_DONE,
                    actor="system",
                    department="quality",
                    parent_event_id=parent_event_id,
                    state_before="QUALITY",
                    state_after="DONE",
                    session_id=session_id,
                    stop_reason=stop_reason,
                    payload={"stop_reason": stop_reason},
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
            actor="system",
            department=department_for_phase(target) or department,
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
            actor="system", department=source.department, parent_event_id=source.event_id,
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

    def _end_run(self, activation: _Activation, reason: str, message: str, version: int | None,
                 *, target: dict[str, Any] | None = None) -> None:
        # 在一个事务中按停止原因暂停或结束运行；模型引用无法使用（provider_unavailable）时 run 进入待恢复。
        # version 是作出停止判断时 run 流的版本：同一事务中核对此后有没有用户的命令或输入写入；有写入、并且写入
        # 改变了这次激活的依据（输入或指导）时，停止判断已经过期，按安全节点停止处理，运行继续，由下一次激活处理
        # 新的输入或指导。运行时间用完不因此改变；已经结束（例如已经取消）的运行不再写入。
        # target 是这次失败对应的调用目标公开部分，写进待恢复的请求
        def end(transaction: Transaction) -> None:
            if version is not None and reason != "time_limit" and self._superseded(transaction, activation, version):
                return
            if reason == "provider_unavailable":
                scope = activation.scope
                self._await_model(transaction, scope.department, target, reason, message,
                                  facts=self._failed_attempts(transaction, scope.activation_id))
                return
            self._end(transaction, reason, message)

        self.writes.transact(run_stream(activation.run_id), end)

    @staticmethod
    def _failed_attempts(transaction: Transaction, activation_id: str) -> list[str]:
        # 这次激活中最后一次失败的调用尝试（这次请求无法发送或被拒绝的记录）
        failed = [event.event_id for event in transaction.events()
                  if event.type == EventType.MODEL_ATTEMPT_FAILED and event.payload["activation_id"] == activation_id]
        return failed[-1:]

    def _await_model(self, transaction: Transaction, department: str, target: dict[str, Any] | None,
                     reason: str, message: str, *, facts: list[str] | None = None) -> None:
        # 模型引用无法使用（模型管理设计说明第 5.5 节）：run 进入待恢复，停在这次请求之前，发出待恢复的决定请求，
        # 写明部门、模型与具体问题；不改用其他模型。已经结束或正在取消的运行不再写入
        projection = transaction.projection
        run_id = projection.run_id
        if projection.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
            return
        kind = MODEL_UNAVAILABLE
        model = "（没有找到调用目标）" if target is None else target["requested_model"]
        transaction.append(NewEvent(
            EventType.DECISION_REQUESTED, actor="system", department=department,
            state_before=projection.phase, state_after=projection.phase,
            payload={
                "kind": kind.name, "blocks": kind.blocks,
                "options": [{"id": option.id, "label": option.label} for option in kind.options],
                "description": (f"部门 {department} 的模型 {model} 无法使用：{message}。修复模型配置或凭据以后选择"
                                "「继续执行」，事项从这次请求接着进行，已完成的工作与已用限额保留；"
                                "选择「停止事项」则运行结束。"),
                "facts": list(facts or []), "department": department, "target": target,
                "reason": reason, "message": message,
            },
        ))
        transaction.on_commit(lambda: self._wake(run_id))

    def answer_decision(self, decision_id: str, option: str, note: str | None, *, base_version: int,
                        command: Command) -> str | None:
        # 回答一个决定请求：在写入口的一个事务中登记命令身份，核对请求仍未回答、基准版本等于请求的版本、选项是
        # 请求给出的选项，追加回答，并按回答解除阻塞（待恢复选择停止事项时在同一事务中结束运行）。
        # 核对不通过时抛出 DecisionClosed、StaleDecision 或 InvalidOption，什么也不写，命令不登记。
        # 返回回答以后需要继续执行的 run，由调用方开始（start）；没有时为空
        # 命令身份先于决定请求核对：同一身份、内容不同时按 command_id_reused 拒绝，与请求是否存在无关
        self.store.check_command(command)
        saved = saved_decision(self.store, decision_id)
        if saved is None:
            raise DecisionNotFound(decision_id)

        def answer(transaction: Transaction) -> str | None:
            decision = transaction.decisions[decision_id]
            if decision.status != "open":
                raise DecisionClosed(decision)
            if base_version != decision.version:
                raise StaleDecision(decision, base_version)
            if option not in [item["id"] for item in decision.request["options"]]:
                raise InvalidOption(decision, option)
            projection = transaction.projection
            transaction.append(NewEvent(
                EventType.DECISION_ANSWERED, department=decision.request["department"], parent_event_id=decision_id,
                state_before=projection.phase, state_after=projection.phase,
                payload={"decision_id": decision_id, "option": option, "note": note, "base_version": base_version},
            ))
            transaction.on_commit(lambda: self._wake(projection.run_id))
            if option == "stop" and decision.kind in (MODEL_UNAVAILABLE.name, DEFINITIONS_CHANGED.name):
                self._fail(transaction, "cancelled", "run stopped by the user's decision")
                return None
            if blocks_run(transaction.decisions.values()):
                return None
            return projection.run_id

        return self.writes.transact(saved.stream, answer, command=command)

    def _superseded(self, transaction: Transaction, activation: _Activation, version: int) -> bool:
        # 新的输入或指导：user_input_received、department_prompt_updated 与 department_guidance_received 由用户提出，
        # 部门指导在事件载荷与 department 列中写明部门
        if not any(event.type in _USER_EVENTS for event in transaction.events_after(version)):
            return False
        projection = transaction.projection
        basis = activation.scope.basis
        return (projection.input_version != basis.input_version
                or guidance_version(projection, activation.department) > basis.guidance_version)

    def _end(self, transaction: Transaction, reason: str, message: str) -> None:
        # 按定义中停止原因规定的方式暂停或结束运行；已经结束的运行不再写入。完成（放行或基线核验）只由接纳写入。
        # 暂停与失败同样带停止说明（message）：例如 workspace_unrepresentable 的说明列出相对路径
        outcome = DEFINITIONS.stop_reason(reason).outcome
        if outcome == "paused":
            self._pause(transaction, reason, message)
        elif outcome == "failed":
            self._fail(transaction, reason, message)
        else:
            raise ValueError(f"stop reason {reason} ends a run as completed, which only an accepted final proposal records")

    def _withdraw_decisions(self, transaction: Transaction, reason: str) -> None:
        # 运行结束：撤销未回答的决定请求，reason 是结束运行的停止原因
        projection = transaction.projection
        for decision in list(transaction.decisions.values()):
            if decision.status != "open":
                continue
            transaction.append(NewEvent(
                EventType.DECISION_WITHDRAWN, actor="system", department=decision.request["department"],
                parent_event_id=decision.decision_id, state_before=projection.phase, state_after=projection.phase,
                payload={"decision_id": decision.decision_id, "reason": reason},
            ))

    def _pause(self, transaction: Transaction, reason: str, message: str | None = None) -> None:
        projection = transaction.projection
        if projection.phase in TERMINAL_PHASES:
            return
        department = projection.active_department
        projection = self._close_request(transaction, status="stopped", reason=reason,
                                         return_phase=projection.phase, return_work_valid=False)
        self._withdraw_decisions(transaction, reason)
        transaction.append(NewEvent(
            EventType.RUN_PAUSED, actor="system", department=department,
            state_before=projection.phase, state_after="PAUSED", stop_reason=reason,
            error=message,
            provider=projection.provider, model=projection.model,
            payload={
                "stop_reason": reason,
                "human_action": DEFINITIONS.stop_reason(reason).human_action,
                **({"message": message} if message else {}),
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
        self._withdraw_decisions(transaction, reason)
        source_event = transaction.append(NewEvent(
            EventType.RUN_FAILED, actor="system", department=department,
            state_before=projection.phase, state_after="FAILED", stop_reason=reason, error=message,
            provider=projection.provider, model=projection.model,
            payload={"stop_reason": reason, "human_action": human, "message": message,
                     **({"input_save_failure": input_save_failure} if input_save_failure is not None else {})},
        ))[0]
        transaction.on_commit(lambda: self.sessions.close_run(projection.run_id))
        if reason != "cancelled":
            self._record_lesson_candidate(transaction, source_event, projection)

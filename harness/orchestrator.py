"""Orchestrator：状态机、停止判定、权限与预算。状态迁移函数内不调用 LLM。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from typing import Any

from .adapters.base import ModelAdapter, ModelRequest, ProviderError
from .adapters.facade_adapter import FacadeAdapter
from .adjudication import (ToolPermission, WorkBasis, commit_decision, guidance_version, proposal_decision,
                           tool_permission)
from .artifacts import ArtifactStore
from .assembly import PENDING_GUIDANCE, ContextAssembly, StepFrame, StepRequest, model_limits, pending_guidance
from .contracts import current_contract_hash, current_plan_hash
from .collaboration import guidance_resume_phase, request_still_applicable, resume_phase
from .compaction import CompactionError
from .event_store import EventStore, NewEvent, WritePath
from .engine import TOOL_CALL_REQUIRED_LIMIT, ModelCallLoop, StepLimits, run_department
from .git_versions import GitVersionStore
from .interactions import CancelledInputSaveError, InteractionWriter, RunTerminalError
from .models import (
    Event as RunEvent,
    DEFAULT_MAX_CYCLES,
    DEFAULT_RUN_TIME_LIMIT_SEC,
    DEPARTMENTS,
    DepartmentPrompt,
    EventType,
    HUMAN_ACTIONS,
    PAUSED_REASONS,
    TERMINAL_PHASES,
    canonical_hash,
    department_for_phase,
    new_id,
)
from .providers import ProviderFacade
from .providers.call import ModelResponse
from .providers.resolve import FrozenTarget, ResolveSnapshot
from .projection import RunProjection, project_run
from .public_tree import CapturedTree, capture_public_tree, materialize_tree
from .recording import ActivationScope, StepRecorder
from .sessions import SessionFactory
from .submissions import SubmissionWriter
from .tools import ToolRuntime, normalize_registered_commands
from .workspace import Workspace, WorkspaceSnapshot


@dataclass
class _Activation:
    run_id: str
    department: str
    session_id: str
    activation_id: str
    abort_flag: Event
    parent_event_id: str
    adapter: ModelAdapter
    target: FrozenTarget | None
    snapshot_id: str | None
    input_version: int
    prompt: DepartmentPrompt
    recorder: StepRecorder
    request: ModelRequest | None = None
    step: StepRequest | None = None
    effective_contract_hash: str | None = None
    engineering_plan_hash: str | None = None
    request_id: str | None = None
    guidance_version: int = 0
    guidance_ids: tuple[str, ...] = ()
    guidance_only: bool = False
    yielded_work: dict[str, Any] | None = None

    def versions(self) -> dict[str, Any]:
        return {"input_version": self.input_version, "prompt_version": self.prompt.version,
                "prompt_hash": self.prompt.prompt_ref.content_hash,
                "guidance_ids": list(self.guidance_ids), "guidance_only": self.guidance_only}

    @property
    def basis(self) -> WorkBasis:
        return WorkBasis(self.effective_contract_hash, self.engineering_plan_hash, self.request_id,
                         self.input_version, self.guidance_version)

    @property
    def frame(self) -> StepFrame:
        return StepFrame(self.department, self.session_id, self.activation_id, self.prompt, self.guidance_only,
                         self.effective_contract_hash, self.engineering_plan_hash, self.input_version)


class _SafeNode:
    # 流程编排为一次激活实现的安全节点接口（接口由部门循环定义）
    def __init__(self, orchestrator: Orchestrator, activation: _Activation) -> None:
        self._orchestrator = orchestrator
        self._activation = activation

    def proceed(self) -> bool:
        return self._orchestrator._at_safe_node(self._activation)


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
        self.writes = WritePath(store)
        self.step_limits = step_limits
        self.artifacts = artifacts
        self.workspace_root = Path(workspace_root)
        self.materials_root = self.workspace_root.parent / "materials"
        self.git_versions = GitVersionStore(self.workspace_root.parent / "git")
        self.submissions = SubmissionWriter(self.writes, artifacts, self.materials_root, self.git_versions)
        self.interactions = InteractionWriter(self.writes, artifacts, self.materials_root, self.git_versions)
        self.facade = facade
        self.test_adapter_factory = test_adapter_factory
        self.test_provider = test_provider
        self.test_adapter_name = test_adapter_name
        self.assembly = ContextAssembly(artifacts)
        self.sessions = sessions or SessionFactory()
        self._abort: dict[str, Event] = {}
        self._active: dict[str, _Activation] = {}
        self._snapshots: dict[str, ResolveSnapshot] = {}
        self._run_start_times: dict[str, float] = {}

    def create_run(
        self,
        task: str,
        *,
        max_cycles: int = DEFAULT_MAX_CYCLES,
        run_time_limit_sec: int = DEFAULT_RUN_TIME_LIMIT_SEC,
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
        self.writes.append(run_id, NewEvent(
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
            },
        ))
        self.writes.append(run_id, NewEvent(
            EventType.TRANSITION,
            role="product",
            state_before="CREATED",
            state_after="PRODUCT_SPEC",
            payload={"from": "CREATED", "to": "PRODUCT_SPEC", "route": "CREATED->PRODUCT_SPEC"},
        ))
        return run_id

    def project(self, run_id: str) -> RunProjection:
        return project_run(self.store, run_id)

    def workspace(self, run_id: str) -> Workspace:
        return Workspace(self.workspace_root / run_id)

    def add_input(self, run_id: str, text: str) -> RunProjection:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("input must be a non-empty string")
        command = text.strip() in {"/stop", "/cancel"}
        activation = None
        abort_notified = False
        save_error = stop_error = None
        cancellation_recorded = False
        try:
            with self.writes.lock:
                current = self.project(run_id)
                if current.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
                    raise RunTerminalError("This run has ended; create a new task for this input.")
                if not command:
                    self.interactions.receive(current, text, command=False)
                else:
                    activation = self._active.get(run_id)
                    self._abort.setdefault(run_id, Event()).set()
                    if activation is not None:
                        try:
                            self._cancel_model_call(activation)
                            abort_notified = True
                        except Exception as exc:
                            stop_error = exc
                    try:
                        self.interactions.receive(current, text, command=True)
                    except Exception as exc:
                        save_error = exc
                    failure = None if save_error is None else {
                        "text": text, "error_type": type(save_error).__name__, "message": str(save_error),
                    }
                    try:
                        self._fail(run_id, self.project(run_id), "cancelled", "run cancelled by user command",
                                   input_save_failure=failure)
                        cancellation_recorded = True
                    except Exception as exc:
                        stop_error = exc
        finally:
            if command and activation is not None and not abort_notified:
                try:
                    self._cancel_model_call(activation)
                except Exception as exc:
                    stop_error = stop_error or exc
        if save_error is not None:
            raise CancelledInputSaveError(run_id, cancellation_recorded=cancellation_recorded) from save_error
        if stop_error is not None:
            raise stop_error
        return self.project(run_id)

    def update_prompt(self, run_id: str, department: str, text: str) -> RunProjection:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("prompt must be a non-empty string")
        with self.writes.lock:
            current = self.project(run_id)
            if current.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
                raise RunTerminalError("This run has ended; prompts can be edited in a new task.")
            self.interactions.update_prompt(current, department, text)
            return self.project(run_id)

    def add_guidance(self, run_id: str, department: str, text: str) -> RunProjection:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        with self.writes.lock:
            current = self.project(run_id)
            if current.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
                raise RunTerminalError("This run has ended; guidance can be sent to a new task.")
            self.interactions.receive_guidance(current, department, text)
            return self.project(run_id)

    def _assign_new_inputs(self, run_id: str, projection: RunProjection) -> RunProjection:
        if projection.phase in TERMINAL_PHASES or projection.input_version <= projection.product_work_input_version:
            return projection
        projection = self._close_request(run_id, projection, status="superseded",
                                         reason="New user input requires updated product work.",
                                         return_phase="PRODUCT_SPEC", return_work_valid=False)
        self.writes.append(run_id, NewEvent(
            EventType.PRODUCT_INPUT_ASSIGNED, role="product",
            state_before=projection.phase, state_after="PRODUCT_SPEC",
            payload={"through_version": projection.input_version},
        ))
        return self.project(run_id)

    def _at_safe_node(self, activation: _Activation) -> bool:
        # 安全节点：激活没有中止、运行时间没有用完时先分派新输入，再作停止判断；回答是否继续
        with self.writes.lock:
            projection = self.project(activation.run_id)
            if not (activation.abort_flag.is_set() or self._time_used_up(activation.run_id, projection)):
                projection = self._assign_new_inputs(activation.run_id, projection)
            return not self._stop_requested(activation, projection)

    def _stop_requested(self, activation: _Activation, projection: RunProjection) -> bool:
        # 停止判断：中止、运行时间用完、终态、输入版本改变或有新的指导；只读取，不写入
        return (activation.abort_flag.is_set() or self._time_used_up(activation.run_id, projection)
                or projection.phase in TERMINAL_PHASES
                or projection.input_version != activation.input_version
                or guidance_version(projection, activation.department) > activation.guidance_version)

    def _time_used_up(self, run_id: str, projection: RunProjection) -> bool:
        elapsed = time.monotonic() - self._run_start_times.get(run_id, time.monotonic())
        return elapsed >= projection.run_time_limit_sec

    def _close_request(self, run_id: str, projection: RunProjection, *, status: str, reason: str,
                       return_phase: str, return_work_valid: bool) -> RunProjection:
        request = projection.pending_request
        if request is None:
            return projection
        self.writes.append(run_id, NewEvent(
            EventType.COLLABORATION_CLOSED, role=request.recipient,
            parent_event_id=request.created_event_id, state_before=projection.phase, state_after=return_phase,
            session_id=projection.sessions[request.recipient].session_id,
            payload={"request_id": request.id, "status": status, "reason": reason,
                     "return_phase": return_phase, "return_work_valid": return_work_valid},
        ))
        return self.project(run_id)

    def _close_obsolete_request(self, run_id: str, projection: RunProjection) -> RunProjection:
        projection = self._assign_new_inputs(run_id, projection)
        request = projection.pending_request
        if request is None or projection.phase in TERMINAL_PHASES:
            return projection
        events = self.store.list_events(run_id)
        if request_still_applicable(request, projection, events):
            return projection
        phase, _valid = resume_phase(request, projection, events, snapshot_hash=self.workspace(run_id).digest())
        return self._close_request(run_id, projection, status="superseded", reason="The request basis changed outside its authorized work.",
                                   return_phase=phase, return_work_valid=False)

    def cancel(self, run_id: str) -> RunProjection:
        activation = None
        abort_notified = False
        try:
            with self.writes.lock:
                projection = self.project(run_id)
                if projection.phase in TERMINAL_PHASES:
                    return projection
                self._abort.setdefault(run_id, Event()).set()
                activation = self._active.get(run_id)
                if activation is not None:
                    self._cancel_model_call(activation)
                    abort_notified = True
                self._fail(run_id, projection, "cancelled", "run cancelled")
        finally:
            if activation is not None and not abort_notified:
                self._cancel_model_call(activation)
        return self.project(run_id)

    @staticmethod
    def _cancel_model_call(activation: _Activation) -> None:
        # 取消按调用尝试的身份生效：当前步骤已经准备了请求时，通知模型接入取消这次尝试；
        # 请求还没有开始时，模型接入记下这次取消，开始时立即取消
        request = activation.request
        if request is not None and request.attempt_id:
            activation.adapter.cancel(request.attempt_id)

    def run_until_stop(self, run_id: str, model_loop: ModelCallLoop) -> RunProjection:
        while True:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return projection
            if self._abort.get(run_id) and self._abort[run_id].is_set():
                return self.cancel(run_id)
            self._activate_once(run_id, model_loop)

    def activate_once(self, run_id: str, model_loop: ModelCallLoop) -> RunProjection:
        return self._activate_once(run_id, model_loop)

    def _activate_once(self, run_id: str, model_loop: ModelCallLoop) -> RunProjection:
        with self.writes.lock:
            if run_id in self._active:
                raise RuntimeError("run already has an active department invocation")
            activation = self._prepare_activation(run_id, model_loop)
            if activation is None:
                return self.project(run_id)
            self._active[run_id] = activation
        started = time.monotonic()
        try:
            self._invoke_activation(activation, model_loop)
        finally:
            with self.writes.lock:
                current = self.project(run_id)
                request = activation
                self.writes.append(run_id, NewEvent(
                    EventType.ACTIVATION_FINISHED,
                    role=request.department,
                    parent_event_id=activation.parent_event_id,
                    state_before=current.phase,
                    state_after=current.phase,
                    session_id=request.session_id,
                    payload={
                        "activation_id": request.activation_id,
                        **activation.versions(),
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "stop_reason": current.stop_reason,
                    },
                ))
                self.sessions.get(run_id, request.department).idle()
                activation.recorder.close()
                self._active.pop(run_id, None)
        return self.project(run_id)

    def _prepare_activation(self, run_id: str, model_loop: ModelCallLoop) -> _Activation | None:
        if run_id not in self._run_start_times:
            self._run_start_times[run_id] = time.monotonic()
        projection = self.project(run_id)
        if self._abort.get(run_id) and self._abort[run_id].is_set():
            return None
        projection = self._close_obsolete_request(run_id, projection)
        if projection.phase in TERMINAL_PHASES:
            return None
        if projection.cycle_count >= projection.max_cycles:
            self._pause(run_id, projection, "max_cycles")
            return None
        elapsed = time.monotonic() - self._run_start_times.get(run_id, time.monotonic())
        if elapsed >= projection.run_time_limit_sec:
            self._fail(run_id, projection, "time_limit",
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
            self._fail(run_id, projection, "provider_error", f"no department for phase {projection.phase}")
            return None

        target: FrozenTarget | None = None
        snapshot_id: str | None = None
        run_has_frozen_provider = bool(projection.provider_snapshot.get("snapshot_id"))
        snapshot = self._snapshots.get(run_id)
        if run_has_frozen_provider or snapshot is not None:
            if snapshot is None or self.facade is None:
                self._fail(
                    run_id,
                    projection,
                    "provider_credentials_lost",
                    "The task's frozen provider credentials are unavailable after restart; create a new run.",
                )
                return None
            try:
                target = snapshot.target(department)
                snapshot_id = canonical_hash(_snapshot_event_dict(snapshot))
                # 旧任务工作、压缩与重试继续使用冻结目标与原认证句柄，不读当前配置
                adapter = FacadeAdapter(self.facade, target, connections=model_loop.connections)
            except (KeyError, ValueError) as exc:
                self._fail(run_id, projection, "provider_unavailable", str(exc))
                return None
        else:
            if self.test_adapter_factory is None:
                self._fail(
                    run_id,
                    projection,
                    "provider_credentials_lost",
                    "The task's model credentials are unavailable in this process; create a new run.",
                )
                return None
            try:
                adapter = self.test_adapter_factory(department)
            except Exception as exc:
                self._fail(run_id, projection, "provider_unavailable", f"test adapter creation failed: {exc}")
                return None

        availability = adapter.availability()
        if not availability.available:
            self._fail(run_id, projection, availability.reason or "provider_unavailable", availability.message)
            return None

        try:
            session = self.sessions.get(run_id, department)
        except KeyError:
            ids = {item.department: item.session_id for item in projection.sessions.values()}
            self.sessions.create_run_sessions(run_id, ids)
            session = self.sessions.get(run_id, department)

        activation_id = session.activate()
        prompt = projection.department_prompts[department]
        basis = WorkBasis.current(projection, department)
        guidance_ids = tuple(item.id for item in pending_guidance(projection, department))
        target_metadata = self._target_metadata(target, adapter, snapshot_id)
        parent = self.writes.append(run_id, NewEvent(
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
        recorder = StepRecorder(self.store, self.writes, self.artifacts, ActivationScope(
            run_id, department, session.session_id, activation_id, parent.event_id,
            prompt_version=prompt.version, prompt_hash=prompt.prompt_ref.content_hash, guidance_ids=guidance_ids,
            guidance_only=guidance_only, basis=basis, provider=self._configured_provider(target, adapter),
            target=target_metadata, secret=getattr(target, "api_key", None),
        ), max_attempts=self.step_limits.max_provider_attempts)
        abort_flag = self._abort.setdefault(run_id, Event())
        return _Activation(run_id, department, session.session_id, activation_id, abort_flag, parent.event_id,
                           adapter, target, snapshot_id,
                           input_version=basis.input_version, prompt=prompt, recorder=recorder,
                           effective_contract_hash=basis.effective_contract_hash,
                           engineering_plan_hash=basis.engineering_plan_hash, request_id=basis.request_id,
                           guidance_version=basis.guidance_version,
                           guidance_ids=guidance_ids,
                           guidance_only=guidance_only, yielded_work=yielded_work)

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
    def _logical_call_id(activation_id: str, root_step_id: int, purpose: str) -> str:
        return f"{activation_id}:root-{root_step_id}:{purpose}"

    @staticmethod
    def _attempt_id(logical_call_id: str, attempt: int) -> str:
        return f"{logical_call_id}:attempt-{attempt}"

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

    def _invoke_activation(self, activation: _Activation, model_loop: ModelCallLoop) -> None:
        request = activation
        run_id, department = request.run_id, request.department
        projection = self.project(run_id)
        try:
            workspace = self.workspace(run_id)
            workspace.bind_check(
                activation_id=request.activation_id,
                product_spec_hash=None if projection.product_spec is None else projection.product_spec.content_hash,
                delivery_spec_hash=None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
                effective_contract_hash=request.effective_contract_hash,
                engineering_plan_hash=request.engineering_plan_hash,
            )
            submission = run_department(
                activation.adapter, ToolRuntime(workspace, registered_commands=dict(projection.registered_commands)),
                limits=self.step_limits,
                model_loop=model_loop,
                prepare_step=lambda step, attempt, root, retry_of: self._prepare_step(
                    activation, step, attempt, root, retry_of,
                ),
                record_stream=lambda event: activation.recorder.stream(activation.request, event),
                record_response=lambda response: activation.recorder.response(activation.request, response),
                record_tool=lambda call: activation.recorder.tool_called(activation.request, call),
                record_skipped_tool=lambda call: activation.recorder.tool_skipped(activation.request, call),
                begin_tool=lambda call: self._begin_tool(activation, call),
                begin_request=lambda request: self._begin_request(activation, request),
                finish_compaction=lambda response: self._finish_compaction(activation, response),
                record_attempt_finished=activation.recorder.attempt_finished,
                record_attempt_failed=activation.recorder.attempt_failed,
                record_retry_scheduled=lambda request, error, delay, next_step: self._record_retry_scheduled(
                    activation, request, error, delay, next_step,
                ),
                require_tool_call=lambda request, item, count: activation.recorder.tool_call_required(
                    request, item, count, TOOL_CALL_REQUIRED_LIMIT,
                ),
                nodes=_SafeNode(self, activation),
            )
        except ProviderError as exc:
            if exc.reason in PAUSED_REASONS:
                self._pause(run_id, projection, exc.reason)
            else:
                self._fail(run_id, projection, exc.reason, str(exc))
            return
        except Exception as exc:
            self._fail(run_id, projection, "provider_error", f"{type(exc).__name__}: {exc}")
            return

        current = self.project(run_id)
        if current.phase in TERMINAL_PHASES:
            return
        if submission is None:
            elapsed = time.monotonic() - self._run_start_times.get(run_id, time.monotonic())
            if elapsed >= current.run_time_limit_sec:
                self._fail(run_id, current, "time_limit",
                           f"run wall-clock time {int(elapsed)}s exceeded limit of {current.run_time_limit_sec}s")
            return

        try:
            transcript_ref = None
            transcript = activation.recorder.transcript
            if transcript:
                ref = self.artifacts.put(run_id, "transcript", transcript, media_type="text/plain")
                transcript_ref = ref.__dict__
            self._apply_proposal(
                run_id, department=department, projection=projection, proposal=submission.proposal,
                basis=activation.basis,
                transcript_ref=transcript_ref, parent_event_id=activation.parent_event_id,
                session_id=request.session_id,
                yielded_work=activation.yielded_work,
                provider=submission.response.provider or self._configured_provider(activation.target, activation.adapter),
                model=submission.response.model,
            )
        except Exception as exc:
            self._fail(run_id, self.project(run_id), "host_commit_error", f"{type(exc).__name__}: {exc}")

    def _prepare_step(
        self,
        activation: _Activation,
        step_id: int,
        attempt: int,
        root_step_id: int,
        retry_of_step_id: int | None,
    ) -> ModelRequest | None:
        with self.writes.lock:
            identity = activation
            current = self.project(identity.run_id)
            if current.phase in TERMINAL_PHASES or identity.abort_flag.is_set():
                return None
            current = self._close_obsolete_request(identity.run_id, current)
            if activation.basis.changed(current, activation.department):
                return None
            # 由 P 装配这一步；装配失败的原因在这里换成停止原因，部门工作消息与请求记录由编排器写入
            target = identity.target
            try:
                limits = model_limits(current.context_window,
                                      None if target is None else target.context_window,
                                      None if target is None else target.max_output_tokens)
                events = self.store.list_events(identity.run_id)
                snapshot_hash = self.workspace(identity.run_id).snapshot().digest
                pinned = self.assembly.pin(current, activation.frame, limits, step_id=step_id,
                                           events=events, snapshot_hash=snapshot_hash)
            except ValueError as exc:
                raise ProviderError(str(exc), reason="context_overflow") from exc
            input_item = pinned.department_input
            if input_item is not None:
                activation.recorder.department_input(current.phase, step_id, input_item)
            history = self.assembly.department_history(self.store.list_events(identity.run_id), identity.department)
            try:
                step = self.assembly.request(pinned, history)
            except (CompactionError, ValueError, FileNotFoundError) as exc:
                reason = "context_overflow" if pinned.fills_window else "compaction_failed"
                raise ProviderError(str(exc), reason=reason) from exc
            assembled = step.context
            activation.step = step
            logical_call_id = self._logical_call_id(
                identity.activation_id, root_step_id, assembled.manifest.purpose,
            )
            attempt_id = self._attempt_id(logical_call_id, attempt)
            request = ModelRequest(identity.run_id, identity.department, identity.session_id, identity.activation_id,
                                   step_id, assembled, assembled.tools,
                                   purpose=assembled.manifest.purpose, max_output_tokens=assembled.manifest.max_output_tokens,
                                   effective_contract_hash=activation.effective_contract_hash,
                                   engineering_plan_hash=activation.engineering_plan_hash, request_id=activation.request_id,
                                   attempt=attempt, root_step_id=root_step_id,
                                   retry_of_step_id=retry_of_step_id, attempt_id=attempt_id,
                                   logical_call_id=logical_call_id,
                                   guidance_version=activation.guidance_version, **activation.versions())
            activation.request = request
            activation.recorder.request_assembled(current.phase, request, step, snapshot_hash)
            if not step.admitted:
                self._fail(request.run_id, current, "context_overflow", "model request exceeds context_window")
                return None
            return request

    def _finish_compaction(self, activation: _Activation, response: ModelResponse) -> None:
        with self.writes.lock:
            request = activation.request
            current = self.project(activation.run_id)
            if current.phase in TERMINAL_PHASES or activation.abort_flag.is_set():
                return
            if activation.basis.changed(current, activation.department):
                return
            try:
                result = self.assembly.finish_compaction(activation.step, response.output)
            except CompactionError as exc:
                raise ProviderError(str(exc), reason="compaction_failed") from exc
            if result is None:
                return
            activation.recorder.compaction(current.phase, request, result, response)

    def _begin_request(self, activation: _Activation, request: ModelRequest) -> bool:
        with self.writes.lock:
            current = self.project(request.run_id)
            current = self._close_obsolete_request(request.run_id, current)
            if current.phase in TERMINAL_PHASES or activation.abort_flag.is_set():
                return False
            if activation.basis.changed(current, activation.department):
                return False
            activation.recorder.request_started(current.phase, request)
            return True

    def _record_retry_scheduled(
        self,
        activation: _Activation,
        request: ModelRequest,
        error: ProviderError,
        delay: float,
        next_step_id: int,
    ) -> bool:
        with self.writes.lock:
            current = self._close_obsolete_request(request.run_id, self.project(request.run_id))
            if (current.phase in TERMINAL_PHASES or activation.abort_flag.is_set()
                    or activation.basis.changed(current, activation.department)):
                return False
            activation.recorder.retry_scheduled(current.phase, request, error, delay, next_step_id)
            return True

    def _begin_tool(self, activation: _Activation, call: dict[str, Any]) -> ToolPermission:
        with self.writes.lock:
            request = activation.request
            current = self._close_obsolete_request(request.run_id, self.project(request.run_id))
            permission = tool_permission(
                current, call, department=request.department, guidance_only=activation.guidance_only,
                basis=activation.basis, aborted=activation.abort_flag.is_set(),
                workspace=self.workspace(request.run_id),
            )
            if not permission.allowed:
                return permission
            activation.recorder.tool_started(current.phase, request, call, permission.command_basis)
            return permission

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
        # 提案先在锁外校验；锁内关闭过时的协作请求以后，由 U 按最新的投影与工作区快照作提交判断
        evaluated = self.project(run_id)
        snapshot = self.workspace(run_id).snapshot()
        decision = proposal_decision(evaluated, department=department, proposal=proposal, snapshot=snapshot,
                                     events=self.store.list_events(run_id))
        with self.writes.lock:
            current = self.project(run_id)
            if current.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
                return
            current = self._close_obsolete_request(run_id, current)
            fresh_snapshot = self.workspace(run_id).snapshot()
            decision = commit_decision(
                decision, department=department, proposal=proposal, basis=basis, started=projection,
                evaluated=evaluated, snapshot=snapshot, current=current, current_snapshot=fresh_snapshot,
                events=self.store.list_events(run_id),
            )
            projection, snapshot = current, fresh_snapshot
            if proposal is not None:
                self.writes.append(run_id, NewEvent(
                    EventType.PROPOSAL_SUBMITTED, role=department,
                    parent_event_id=parent_event_id,
                    state_before=projection.phase, state_after=projection.phase,
                    session_id=session_id, provider=provider, model=model,
                    payload={"kind": proposal.get("kind"), "transcript_ref": transcript_ref,
                             "raw_keys": sorted(proposal.keys()), "input_version": basis.input_version},
                ))
            if not decision.accepted:
                self.writes.append(run_id, NewEvent(
                    EventType.PROPOSAL_REJECTED, role=department,
                    parent_event_id=parent_event_id,
                    state_before=projection.phase, state_after=projection.phase,
                    session_id=session_id, provider=provider, model=model,
                    payload={
                        "errors": decision.error_dicts,
                        "transcript_ref": transcript_ref,
                        "kind": None if proposal is None else proposal.get("kind"),
                        "input_version": basis.input_version,
                    },
                ))
                return
            self._commit_accepted(
                run_id, department=department, projection=projection, snapshot=snapshot,
                artifact=decision.artifact or {}, transitions=decision.transitions,
                parent_event_id=parent_event_id, session_id=session_id, provider=provider, model=model,
                yielded_work=yielded_work,
            )

    def _commit_accepted(
        self,
        run_id: str,
        *,
        department: str,
        projection: RunProjection,
        snapshot: WorkspaceSnapshot,
        artifact: dict[str, Any],
        transitions: list[tuple[str, str]],
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
        yielded_work: dict[str, Any] | None = None,
    ) -> None:
        if self.project(run_id).phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
            return
        source_event = self.submissions.commit(
            projection=projection, snapshot=snapshot, workspace_root=self.workspace_root / run_id,
            artifact=artifact,
            department=department, parent_event_id=parent_event_id, session_id=session_id,
            provider=provider, model=model,
        )
        if artifact["kind"] == "qa_review" and artifact["verdict"] in {"rework_product", "rework_engineering"}:
            self._record_lesson_candidate(source_event, projection)
        for source, target in transitions:
            self.writes.append(run_id, NewEvent(
                EventType.TRANSITION,
                role=department_for_phase(target) or department,
                parent_event_id=parent_event_id,
                state_before=source,
                state_after=target,
                session_id=session_id,
                payload={"from": source, "to": target, "route": f"{source}->{target}"},
            ))
            if target == "DONE":
                self.writes.append(run_id, NewEvent(
                    EventType.RUN_DONE,
                    role="quality",
                    parent_event_id=parent_event_id,
                    state_before="QUALITY",
                    state_after="DONE",
                    session_id=session_id,
                    stop_reason="released",
                    payload={"stop_reason": "released"},
                ))
                self.sessions.close_run(run_id)
        self._resume_yielded_work(
            run_id, artifact=artifact, yielded_work=yielded_work,
            parent_event_id=parent_event_id, session_id=session_id, department=department,
        )

    def _resume_yielded_work(
        self,
        run_id: str,
        *,
        artifact: dict[str, Any],
        yielded_work: dict[str, Any] | None,
        parent_event_id: str,
        session_id: str,
        department: str,
    ) -> None:
        current = self.project(run_id)
        basis = current.yielded_work or yielded_work
        if artifact.get("kind") != "department_guidance_response" or not basis:
            return
        if current.phase in TERMINAL_PHASES:
            return
        target = guidance_resume_phase(basis, current)
        if target == current.phase:
            return
        self.writes.append(run_id, NewEvent(
            EventType.TRANSITION,
            role=department_for_phase(target) or department,
            parent_event_id=parent_event_id,
            state_before=current.phase,
            state_after=target,
            session_id=session_id,
            payload={"from": current.phase, "to": target, "route": f"{current.phase}->{target}",
                     "yielded_work_resolved": True, "yielded_work": dict(basis)},
        ))

    def _record_lesson_candidate(self, source: RunEvent, projection: RunProjection) -> None:
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
        self.writes.append(source.run_id, NewEvent(
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

    def _pause(self, run_id: str, projection: RunProjection, reason: str) -> None:
        with self.writes.lock:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return
            department = projection.active_department
            projection = self._close_request(run_id, projection, status="stopped", reason=reason,
                                             return_phase=projection.phase, return_work_valid=False)
            self.writes.append(run_id, NewEvent(
                EventType.RUN_PAUSED, role=department,
                state_before=projection.phase, state_after="PAUSED", stop_reason=reason,
                provider=projection.provider, model=projection.model,
                payload={
                    "stop_reason": reason,
                    "human_action": HUMAN_ACTIONS[reason],
                    "paused_at_phase": projection.phase,
                    "cycle_count": projection.cycle_count,
                    "max_cycles": projection.max_cycles,
                    "token_used": projection.token_used,
                },
            ))
            self.sessions.close_run(run_id)

    def _fail(self, run_id: str, projection: RunProjection, reason: str, message: str,
              *, input_save_failure: dict[str, str] | None = None) -> None:
        human = {
            "provider_unavailable": "模型提供方未配置或不可用。检查模型与 API 配置后新建运行。",
            "provider_credentials_lost": "任务创建时冻结的 provider 凭据已不在当前进程中。请新建 run，不能用新凭据续跑旧任务。",
            "provider_error": "模型提供方失败。查看错误事件后新建 run 或更换 provider。",
            "provider_timeout": "模型提供方请求超时。本次未结协作已结束，查看超时事件后重新运行。",
            "cancelled": "运行已被取消。如需继续，新建 run。",
            "context_overflow": "单次装配的上下文超过窗口。缩小注入内容或提高 context_window 后新建 run。",
            "compaction_failed": "部门历史压缩失败。原始记录仍保留，请查看摘要请求与失败原因后重新运行。",
            "host_commit_error": "主机未能保存本次提交所需的工件、材料或事件。查看失败原因并处理存储或交付文件问题后重新运行。",
            "time_limit": HUMAN_ACTIONS["time_limit"],
        }.get(reason)
        with self.writes.lock:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return
            department = projection.active_department
            status = "cancelled" if reason == "cancelled" else "timed_out" if reason == "provider_timeout" else "stopped"
            projection = self._close_request(run_id, projection, status=status, reason=reason,
                                             return_phase=projection.phase, return_work_valid=False)
            source_event = self.writes.append(run_id, NewEvent(
                EventType.RUN_FAILED, role=department,
                state_before=projection.phase, state_after="FAILED", stop_reason=reason, error=message,
                provider=projection.provider, model=projection.model,
                payload={"stop_reason": reason, "human_action": human, "message": message,
                         **({"input_save_failure": input_save_failure} if input_save_failure is not None else {})},
            ))[0]
            self.sessions.close_run(run_id)
            if reason != "cancelled":
                self._record_lesson_candidate(source_event, projection)

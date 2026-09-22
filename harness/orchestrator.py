"""Orchestrator：状态机、停止判定、权限与预算。状态迁移函数内不调用 LLM。"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event, RLock
from typing import Any

from .adapters.base import ModelObservation, ModelResponse, ModelAdapter, ModelRequest, ProviderError
from .adapters.facade_adapter import FacadeAdapter
from .artifacts import ArtifactStore
from .context import ContextAssembler, GUIDANCE_ONLY_TOOLS, department_work_text
from .contracts import current_contract_hash, current_plan_hash, path_in_scope
from .collaboration import guidance_resume_phase, request_basis, request_still_applicable, resume_phase, tool_error
from .compaction import (CompactionCheckpoint, CompactionError, finish_compaction, plan_compaction, response_reserve,
                         visible_history)
from .event_store import EventStore
from .engine import MAX_PROVIDER_ATTEMPTS, ToolAdmission, run_department
from .git_versions import GitVersionStore
from .interactions import CancelledInputSaveError, InteractionWriter, RunTerminalError
from .models import (
    Event as RunEvent,
    ArtifactRef,
    DEFAULT_MAX_CYCLES,
    DEFAULT_RUN_TIME_LIMIT_SEC,
    DEPARTMENTS,
    DepartmentPrompt,
    EventType,
    HUMAN_ACTIONS,
    TERMINAL_PHASES,
    Usage,
    canonical_hash,
    department_for_phase,
    estimate_tokens,
    json_dumps,
    new_id,
    utc_now,
)
from .providers import ProviderFacade
from .providers.resolve import FrozenTarget, ResolveSnapshot
from .projection import RunProjection, project_run
from .public_tree import CapturedTree, capture_public_tree, materialize_tree
from .sessions import SessionFactory
from .submissions import SubmissionWriter
from .tools import ToolRuntime, has_tool, normalize_registered_commands
from .validation import FieldError, ProposalDecision, evaluate_proposal
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
    request: ModelRequest | None = None
    tokens_charged: int = 0
    usage: Usage = field(default_factory=lambda: Usage(reported=False))
    has_usage: bool = False
    cost_charged: float = 0.0
    seen: set[tuple[str, str]] = field(default_factory=set)
    tool_ids: set[str] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)
    message_steps: list[tuple[str, int]] = field(default_factory=list)
    step_usage: Usage | None = None
    previous_usage: Usage = field(default_factory=lambda: Usage(reported=True, cost_reported=True))
    raw_usage_ref: dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None
    compaction_plan: Any = None
    effective_contract_hash: str | None = None
    engineering_plan_hash: str | None = None
    request_id: str | None = None
    guidance_version: int = 0
    guidance_ids: tuple[str, ...] = ()
    guidance_only: bool = False
    guidance_applied: bool = False
    yielded_work: dict[str, Any] | None = None
    attempt_captures: dict[str, "_AttemptCapture"] = field(default_factory=dict)

    def versions(self) -> dict[str, Any]:
        return {"input_version": self.input_version, "prompt_version": self.prompt.version,
                "prompt_hash": self.prompt.prompt_ref.content_hash,
                "guidance_ids": list(self.guidance_ids), "guidance_only": self.guidance_only}


@dataclass
class _AttemptCapture:
    """Bounded-memory capture for one Provider SDK attempt."""

    stream: Any | None = None
    stream_event_count: int = 0
    stream_bytes: int = 0
    stream_ref: dict[str, Any] | None = None
    response_ref: dict[str, Any] | None = None
    provider_response_id: str | None = None
    actual_provider: str | None = None
    actual_model: str | None = None
    usage: Usage | None = None
    usage_ref: dict[str, Any] | None = None
    started_at: str | None = None
    progress_stage: str | None = None
    progress_last_emitted_monotonic: float | None = None
    first_observed_at: str | None = None
    first_output_at: str | None = None

    def add_stream_event(self, sequence: int | None, payload: dict[str, Any], observed_at: str) -> None:
        if self.stream is None:
            self.stream = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
        record = {"sequence": sequence if sequence is not None else self.stream_event_count,
                  "observed_at": observed_at, "event": payload}
        raw = (json_dumps(record) + "\n").encode("utf-8")
        self.stream.write(raw)
        self.stream_event_count += 1
        self.stream_bytes += len(raw)

    def stream_chunks(self, chunk_size: int = 64 * 1024):
        if self.stream is None:
            return
        self.stream.seek(0)
        while True:
            chunk = self.stream.read(chunk_size)
            if not chunk:
                return
            yield chunk

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()


_SENSITIVE_OBSERVATION_KEYS = frozenset({
    "authorization", "api_key", "apikey", "access_token", "refresh_token",
    "client_secret", "password", "cookie", "set_cookie", "credential",
    "credentials", "headers", "proxy_authorization",
})


def _stream_progress_stage(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("type") or "")
    if event_type == "response.created":
        return "response_created"
    if "output_text.delta" in event_type or "output_item.added" in event_type:
        return "output"
    if event_type == "response.output_item.done":
        return "output_item_done"
    if event_type == "response.completed":
        return "completed"
    if event_type in {"response.incomplete", "response.failed", "error"}:
        return "error"
    return "event"


def _stream_progress_summary(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("type") or "provider_event")
    if event_type == "response.output_item.done":
        item = payload.get("item")
        if isinstance(item, dict):
            return f"{event_type}: {item.get('type') or 'output_item'}"
    response = payload.get("response")
    if isinstance(response, dict) and response.get("status"):
        return f"{event_type}: {response['status']}"
    return event_type


def _redact_observation(value: Any, *, secret: str | None = None, key: str | None = None) -> Any:
    normalized_key = key.casefold().replace("-", "_") if isinstance(key, str) else ""
    if normalized_key in _SENSITIVE_OBSERVATION_KEYS or normalized_key.endswith("_api_key"):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact_observation(child_value, secret=secret, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_observation(item, secret=secret, key=key) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


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


def _run_command_basis(workspace: Workspace, projection: RunProjection,
                       args: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    # 执行前依据：命令身份（登记名与完整参数）加当时工作区快照摘要；只读核对，不执行
    name = args.get("name")
    if not isinstance(name, str) or not name:
        return "run_command requires a registered command name", {}
    entry = projection.registered_commands.get(name)
    if entry is None:
        return f"unknown registered command: {name}; only project-registered commands may run", {}
    extra = args.get("args", [])
    if extra is None:
        extra = []
    if not isinstance(extra, list) or any(not isinstance(item, str) for item in extra):
        return f"run_command {name} args must be a list of strings", {}
    for item in extra:
        if item not in entry.get("args", []):
            return f"argument not allowlisted for {name}: {item}", {}
    return None, {"registered_name": name, "registered_argv": [*entry["argv"], *extra],
                  "snapshot_hash": workspace.snapshot().digest}


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
        assembler: ContextAssembler | None = None,
        sessions: SessionFactory | None = None,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.workspace_root = Path(workspace_root)
        self.materials_root = self.workspace_root.parent / "materials"
        self.git_versions = GitVersionStore(self.workspace_root.parent / "git")
        self.submissions = SubmissionWriter(store, artifacts, self.materials_root, self.git_versions)
        self.interactions = InteractionWriter(store, artifacts, self.materials_root, self.git_versions)
        self.facade = facade
        self.test_adapter_factory = test_adapter_factory
        self.test_provider = test_provider
        self.test_adapter_name = test_adapter_name
        self.assembler = assembler or ContextAssembler(artifacts)
        self.sessions = sessions or SessionFactory()
        self._abort: dict[str, Event] = {}
        self._state_lock = RLock()
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
        self.store.append(
            run_id,
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
        )
        self.store.append(
            run_id,
            EventType.TRANSITION,
            role="product",
            state_before="CREATED",
            state_after="PRODUCT_SPEC",
            payload={"from": "CREATED", "to": "PRODUCT_SPEC", "route": "CREATED->PRODUCT_SPEC"},
        )
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
            with self._state_lock:
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
                            activation.adapter.abort(activation.session_id)
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
                    activation.adapter.abort(activation.session_id)
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
        with self._state_lock:
            current = self.project(run_id)
            if current.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
                raise RunTerminalError("This run has ended; prompts can be edited in a new task.")
            self.interactions.update_prompt(current, department, text)
            return self.project(run_id)

    def add_guidance(self, run_id: str, department: str, text: str) -> RunProjection:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        with self._state_lock:
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
        self.store.append(
            run_id, EventType.PRODUCT_INPUT_ASSIGNED, role="product",
            state_before=projection.phase, state_after="PRODUCT_SPEC",
            payload={"through_version": projection.input_version},
        )
        return self.project(run_id)

    def _activation_stopped(self, activation: _Activation) -> bool:
        with self._state_lock:
            if activation.abort_flag.is_set():
                return True
            elapsed = time.monotonic() - self._run_start_times.get(activation.run_id, time.monotonic())
            if elapsed >= self.project(activation.run_id).run_time_limit_sec:
                return True
            current = self._assign_new_inputs(activation.run_id, self.project(activation.run_id))
            return (current.phase in TERMINAL_PHASES or activation.abort_flag.is_set()
                    or current.input_version != activation.input_version
                    or self._guidance_version(current, activation.department) > activation.guidance_version)

    @staticmethod
    def _guidance_version(projection: RunProjection, department: str) -> int:
        return max((item.version for item in projection.department_guidance
                    if item.department == department), default=0)

    @staticmethod
    def _pending_guidance(projection: RunProjection, department: str) -> list[Any]:
        return [item for item in projection.department_guidance
                if item.department == department and item.status in {"received", "in_input"}]

    @staticmethod
    def _request_id(projection: RunProjection) -> str | None:
        return None if projection.pending_request is None else projection.pending_request.id

    def _close_request(self, run_id: str, projection: RunProjection, *, status: str, reason: str,
                       return_phase: str, return_work_valid: bool) -> RunProjection:
        request = projection.pending_request
        if request is None:
            return projection
        self.store.append(
            run_id, EventType.COLLABORATION_CLOSED, role=request.recipient,
            parent_event_id=request.created_event_id, state_before=projection.phase, state_after=return_phase,
            session_id=projection.sessions[request.recipient].session_id,
            payload={"request_id": request.id, "status": status, "reason": reason,
                     "return_phase": return_phase, "return_work_valid": return_work_valid},
        )
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
            with self._state_lock:
                projection = self.project(run_id)
                if projection.phase in TERMINAL_PHASES:
                    return projection
                self._abort.setdefault(run_id, Event()).set()
                activation = self._active.get(run_id)
                if activation is not None:
                    activation.adapter.abort(activation.session_id)
                    abort_notified = True
                self._fail(run_id, projection, "cancelled", "run cancelled")
        finally:
            if activation is not None and not abort_notified:
                activation.adapter.abort(activation.session_id)
        return self.project(run_id)

    def run_until_stop(self, run_id: str, execution_scope: Any | None = None) -> RunProjection:
        while True:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return projection
            if self._abort.get(run_id) and self._abort[run_id].is_set():
                return self.cancel(run_id)
            self._activate_once(run_id, execution_scope)

    def activate_once(self, run_id: str, execution_scope: Any | None = None) -> RunProjection:
        return self._activate_once(run_id, execution_scope)

    def _activate_once(self, run_id: str, execution_scope: Any | None) -> RunProjection:
        with self._state_lock:
            if run_id in self._active:
                raise RuntimeError("run already has an active department invocation")
            activation = self._prepare_activation(run_id, execution_scope)
            if activation is None:
                return self.project(run_id)
            self._active[run_id] = activation
        started = time.monotonic()
        try:
            self._invoke_activation(activation)
        finally:
            with self._state_lock:
                current = self.project(run_id)
                request = activation
                self.store.append(
                    run_id,
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
                )
                self.sessions.get(run_id, request.department).idle()
                for capture in activation.attempt_captures.values():
                    capture.close()
                self._active.pop(run_id, None)
        return self.project(run_id)

    def _prepare_activation(self, run_id: str, execution_scope: Any | None) -> _Activation | None:
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
        pending_guidance = [item for item in projection.department_guidance
                            if item.status in {"received", "in_input"}]
        guidance_only = False
        department = normal_department
        yielded_work = None
        if projection.pending_request is None and pending_guidance:
            if normal_department is None or pending_guidance[0].department != normal_department:
                department = pending_guidance[0].department
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
                adapter = FacadeAdapter(self.facade, target, execution_scope=execution_scope)
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
        parent = self.store.append(
            run_id,
            EventType.DEPARTMENT_ACTIVATED,
            role=department,
            state_before=projection.phase,
            state_after=projection.phase,
            session_id=session.session_id,
            provider=self._configured_provider(target, adapter),
            payload={"activation_id": activation_id, "cycle": projection.cycle_count + 1,
                     "effective_contract_hash": current_contract_hash(projection),
                     "engineering_plan_hash": current_plan_hash(projection), "request_id": self._request_id(projection),
                     "guidance_ids": [item.id for item in self._pending_guidance(projection, department)],
                     "guidance_only": guidance_only,
                     "yielded_work": yielded_work,
                     "guidance_version": self._guidance_version(projection, department),
                     "input_version": projection.input_version, "prompt_version": prompt.version,
                     "prompt_hash": prompt.prompt_ref.content_hash,
                     **self._target_metadata(target, adapter, snapshot_id)},
        )
        abort_flag = self._abort.setdefault(run_id, Event())
        return _Activation(run_id, department, session.session_id, activation_id, abort_flag, parent.event_id,
                           adapter, target, snapshot_id,
                           input_version=projection.input_version, prompt=prompt,
                           effective_contract_hash=current_contract_hash(projection),
                           engineering_plan_hash=current_plan_hash(projection), request_id=self._request_id(projection),
                           guidance_version=self._guidance_version(projection, department),
                           guidance_ids=tuple(item.id for item in self._pending_guidance(projection, department)),
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

    @staticmethod
    def _effective_limits(projection: RunProjection, target: FrozenTarget | None) -> tuple[int, int | None, int]:
        """(effective window, model output cap, response reserve).

        The reserve drives compaction and overflow decisions; each request's actual
        max_output_tokens is settled at assembly as min(cap, window - input estimate).
        """
        if target is None:
            window = projection.context_window
            return window, None, response_reserve(window, None)
        effective_window = min(projection.context_window, target.context_window)
        reserve = response_reserve(effective_window, target.max_output_tokens)
        if reserve < 1:
            raise ValueError("the effective context window leaves no room for model output")
        return effective_window, target.max_output_tokens, reserve

    def _invoke_activation(self, activation: _Activation) -> None:
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
                prepare_step=lambda step, attempt, root, retry_of: self._prepare_step(
                    activation, step, attempt, root, retry_of,
                ),
                record_response=lambda response: self._reconcile_response(activation, response),
                record_tool=lambda call: self._record_observation(activation, ModelObservation(call["id"], "tool", call)),
                record_skipped_tool=lambda call: self._record_observation(activation, ModelObservation(call["id"], "skipped_tool", call)),
                begin_tool=lambda call: self._begin_tool(activation, call),
                begin_request=lambda request: self._begin_request(activation, request),
                finish_compaction=lambda response: self._finish_compaction(activation, response),
                record_attempt_finished=lambda request, response: self._record_attempt_finished(
                    activation, request, response,
                ),
                record_attempt_failed=lambda request, error, will_retry: self._record_attempt_failed(
                    activation, request, error, will_retry,
                ),
                record_retry_scheduled=lambda request, error, delay, next_step: self._record_retry_scheduled(
                    activation, request, error, delay, next_step,
                ),
                stopped=lambda: self._activation_stopped(activation),
            )
        except ProviderError as exc:
            if exc.reason == "model_steps_exhausted":
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
            transcript = "\n".join(activation.messages)
            if transcript:
                ref = self.artifacts.put(run_id, "transcript", transcript, media_type="text/plain")
                transcript_ref = ref.__dict__
            self._apply_proposal(
                run_id, department=department, projection=projection, proposal=submission.proposal,
                input_version=activation.input_version,
                transcript_ref=transcript_ref, parent_event_id=activation.parent_event_id,
                session_id=request.session_id,
                guidance_version=activation.guidance_version,
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
        with self._state_lock:
            identity = activation
            current = self.project(identity.run_id)
            if current.phase in TERMINAL_PHASES or identity.abort_flag.is_set():
                return None
            current = self._close_obsolete_request(identity.run_id, current)
            if (current_contract_hash(current) != activation.effective_contract_hash
                    or current_plan_hash(current) != activation.engineering_plan_hash
                    or self._request_id(current) != activation.request_id
                    or current.input_version != activation.input_version
                    or self._guidance_version(current, activation.department) > activation.guidance_version):
                return None
            try:
                effective_window, output_limit, output_reserve = self._effective_limits(current, identity.target)
                guidance_items = self._pending_guidance(current, identity.department) if step_id == 1 else []
                events = self.store.list_events(identity.run_id)
                snapshot_hash = self.workspace(identity.run_id).snapshot().digest
                pinned = self.assembler.assemble(
                    current, department=identity.department, session_id=identity.session_id,
                    activation_id=identity.activation_id, step_id=step_id, prompt=activation.prompt,
                    context_window=effective_window, max_output_tokens=output_limit,
                    guidance=guidance_items,
                    guidance_only=identity.guidance_only,
                    events=events, snapshot_hash=snapshot_hash,
                )
            except ValueError as exc:
                raise ProviderError(str(exc), reason="context_overflow") from exc
            if step_id == 1:
                content = department_work_text(pinned)
                input_item = {"role": "user", "content": content}
                received_ref = self.artifacts.put(identity.run_id, "department_input", json_dumps(input_item), media_type="application/json")
                self.store.append(identity.run_id, EventType.DEPARTMENT_INPUT, role=identity.department,
                                  parent_event_id=activation.parent_event_id, state_before=current.phase,
                                  state_after=current.phase, session_id=identity.session_id,
                                  artifact_hashes=[received_ref.content_hash],
                                  payload={"activation_id": identity.activation_id, "step_id": step_id, "input_ref": asdict(received_ref),
                                           **activation.versions(),
                                           "effective_contract_hash": activation.effective_contract_hash,
                                           "engineering_plan_hash": activation.engineering_plan_hash, "request_id": activation.request_id})
            records = self._department_history_records(identity.run_id, identity.department)
            checkpoint_event = next((item for item in reversed(current.compactions)
                                     if item["department"] == identity.department
                                     and item["effective_contract_hash"] == activation.effective_contract_hash
                                     and item["engineering_plan_hash"] == activation.engineering_plan_hash
                                     and item["input_version"] == activation.input_version
                                     and item["prompt_version"] == activation.prompt.version
                                     and item["prompt_hash"] == activation.prompt.prompt_ref.content_hash), None)
            checkpoint = None
            checkpoint_id = None
            try:
                if checkpoint_event is not None:
                    if checkpoint_event["run_id"] != identity.run_id:
                        raise CompactionError("Compaction checkpoint belongs to a different run")
                    checkpoint = CompactionCheckpoint(**checkpoint_event["checkpoint"])
                    saved_summary = self.artifacts.get_for_run(identity.run_id, ArtifactRef(**checkpoint_event["summary_ref"])).decode("utf-8")
                    if saved_summary != checkpoint.summary:
                        raise CompactionError("Compaction summary does not match its original artifact")
                    checkpoint_id = checkpoint_event["source_event_id"]
                activation.compaction_plan = plan_compaction(
                    records, checkpoint, effective_window, pinned.input_items, pinned.tools,
                    output_limit=output_limit,
                )
                if activation.compaction_plan is not None:
                    plan = activation.compaction_plan
                    assembled = self.assembler.assemble_compaction(
                        pinned, input_items=plan.input_items, source_refs=plan.source_refs,
                        max_output_tokens=plan.max_output_tokens, compaction_event_id=checkpoint_id,
                    )
                else:
                    assembled = self.assembler.assemble(
                        current, department=identity.department, session_id=identity.session_id,
                        activation_id=identity.activation_id, step_id=step_id,
                        prompt=activation.prompt,
                        history=visible_history(records, checkpoint),
                        compaction_event_id=checkpoint_id,
                        context_window=effective_window, max_output_tokens=output_limit,
                        guidance=guidance_items, guidance_only=identity.guidance_only,
                        events=events, snapshot_hash=snapshot_hash,
                    )
            except (CompactionError, ValueError, FileNotFoundError) as exc:
                reason = "context_overflow" if pinned.manifest.token_estimate >= effective_window - output_reserve else "compaction_failed"
                raise ProviderError(str(exc), reason=reason) from exc
            logical_call_id = self._logical_call_id(
                identity.activation_id, root_step_id, assembled.manifest.purpose,
            )
            attempt_id = self._attempt_id(logical_call_id, attempt)
            request = ModelRequest(identity.run_id, identity.department, identity.session_id, identity.activation_id,
                                   step_id, assembled, assembled.tools, identity.abort_flag,
                                   purpose=assembled.manifest.purpose, max_output_tokens=assembled.manifest.max_output_tokens,
                                   effective_contract_hash=activation.effective_contract_hash,
                                   engineering_plan_hash=activation.engineering_plan_hash, request_id=activation.request_id,
                                   attempt=attempt, root_step_id=root_step_id,
                                   retry_of_step_id=retry_of_step_id, attempt_id=attempt_id,
                                   logical_call_id=logical_call_id,
                                   guidance_version=activation.guidance_version, **activation.versions())
            activation.request = request
            request.on_observation = lambda observation: self._record_observation(activation, observation)
            request.on_raw_observation = lambda observation: self._record_observation(activation, observation)
            activation.provider = None
            activation.model = None
            activation.previous_usage = activation.usage if activation.has_usage else Usage(reported=True, cost_reported=True)
            activation.step_usage = None
            activation.raw_usage_ref = None
            estimate = assembled.manifest.token_estimate
            input_estimate = estimate_tokens(json_dumps({"input": request.input_items, "tools": request.tools}))
            output_reserve = request.max_output_tokens or 0
            overflow = input_estimate + output_reserve > effective_window
            admitted = not overflow
            request_payload = {"input": request.input_items, "tools": request.tools}
            if request.max_output_tokens is not None:
                request_payload["max_output_tokens"] = request.max_output_tokens
            ref = self.artifacts.put(request.run_id, "model_request", json_dumps(request_payload), media_type="application/json")
            parts = self._context_parts(assembled)
            parts_ref = self.artifacts.put(
                request.run_id,
                "context_parts",
                json_dumps(parts),
                media_type="application/json",
            )
            payload = asdict(assembled.manifest)
            payload.update(run_id=request.run_id, request_ref=asdict(ref), admitted=admitted,
                           tokens_charged=0, step_id=step_id, attempt=attempt, root_step_id=root_step_id,
                           retry_of_step_id=retry_of_step_id,
                           **self._target_metadata(identity.target, identity.adapter, identity.snapshot_id),
                           effective_context_window=effective_window,
                           input_token_estimate=input_estimate,
                           output_reserve_tokens=output_reserve,
                           parts_ref=asdict(parts_ref),
                           snapshot_hash=snapshot_hash)
            payload.update(attempt_id=attempt_id, logical_call_id=logical_call_id,
                           collaboration_request_id=activation.request_id)
            context_event = self.store.append(request.run_id, EventType.CONTEXT_ASSEMBLED, role=request.department,
                                              parent_event_id=activation.parent_event_id, state_before=current.phase,
                                              state_after=current.phase, session_id=request.session_id,
                                              provider=self._configured_provider(identity.target, identity.adapter),
                                              context_digest=assembled.manifest.digest,
                                              artifact_hashes=[ref.content_hash, parts_ref.content_hash], payload=payload)
            request.context_event_id = context_event.event_id
            if overflow:
                self._fail(request.run_id, current, "context_overflow", "model request exceeds context_window")
                return None
            return request

    @staticmethod
    def _context_parts(assembled: Any) -> list[dict[str, Any]]:
        parts = list(getattr(assembled, "parts", []) or [])
        injected = list(getattr(assembled.manifest, "injected", []) or [])
        if len(parts) != len(injected):
            raise ProviderError("assembled context sources do not match its manifest", reason="provider_protocol")
        result = []
        for part, source in zip(parts, injected):
            digest = canonical_hash(part.text)
            if source.digest != digest:
                raise ProviderError("assembled context source digest is inconsistent", reason="provider_protocol")
            result.append({"source": part.source, "version": part.version, "text": part.text, "digest": digest})
        return result

    def _department_history_records(self, run_id: str, department: str) -> list[dict[str, Any]]:
        events = self.store.list_events(run_id)
        failed_steps = {
            (event.payload.get("activation_id"), event.payload.get("step_id"))
            for event in events
            if event.type == EventType.MODEL_ATTEMPT_FAILED and event.role == department
        }
        records: list[dict[str, Any]] = []
        for event in events:
            if event.role != department:
                continue
            if event.type in {EventType.MODEL_MESSAGE, EventType.DEPARTMENT_INPUT}:
                if event.payload.get("purpose") == "compaction":
                    continue
                if event.type == EventType.MODEL_MESSAGE and (
                    event.payload.get("activation_id"), event.payload.get("step_id")
                ) in failed_steps:
                    continue
                ref = ArtifactRef(**event.payload["message_ref" if event.type == EventType.MODEL_MESSAGE else "input_ref"])
                item = json.loads(self.artifacts.get_for_run(run_id, ref))
            elif event.type in {EventType.TOOL_CALLED, EventType.TOOL_SKIPPED} and "input_item" in event.payload:
                if (event.payload.get("activation_id"), event.payload.get("step_id")) in failed_steps:
                    continue
                item = event.payload["input_item"]
            else:
                continue
            records.append({"event_id": event.event_id, "seq": event.seq,
                            "activation_id": event.payload["activation_id"], "step_id": event.payload["step_id"],
                            "type": event.type, "item": item, "item_digest": canonical_hash(item)})
        return records

    def _finish_compaction(self, activation: _Activation, response: ModelResponse) -> None:
        with self._state_lock:
            request = activation.request
            current = self.project(activation.run_id)
            if current.phase in TERMINAL_PHASES or activation.abort_flag.is_set():
                return
            if (current_contract_hash(current) != activation.effective_contract_hash
                    or current_plan_hash(current) != activation.engineering_plan_hash
                    or self._request_id(current) != activation.request_id
                    or current.input_version != activation.input_version
                    or self._guidance_version(current, activation.department) > activation.guidance_version):
                return
            plan = activation.compaction_plan
            try:
                checkpoint = finish_compaction(plan, response.output)
            except CompactionError as exc:
                raise ProviderError(str(exc), reason="compaction_failed") from exc
            if checkpoint is None:
                # 摘要为空或超限：非致命，不记录压缩事件，后续激活重试压缩
                return
            summary_ref = self.artifacts.put(activation.run_id, "department_summary", checkpoint.summary, media_type="text/plain")
            plan_ref = self.artifacts.put(activation.run_id, "compaction_plan", json_dumps(asdict(plan)), media_type="application/json")
            self.store.append(activation.run_id, EventType.COMPACTION_RECORDED, role=activation.department,
                              parent_event_id=activation.parent_event_id, state_before=current.phase,
                              state_after=current.phase, session_id=activation.session_id,
                              provider=response.provider or self._configured_provider(activation.target, activation.adapter),
                              model=response.model,
                              context_digest=request.context.manifest.digest,
                              artifact_hashes=[summary_ref.content_hash, plan_ref.content_hash],
                              payload={"run_id": activation.run_id, "department": activation.department,
                                       **activation.versions(),
                                       "activation_id": activation.activation_id, "step_id": request.step_id,
                                       "purpose": "compaction", "checkpoint": asdict(checkpoint),
                                       "source_refs": plan.source_refs, "summary_ref": asdict(summary_ref),
                                       "plan_ref": asdict(plan_ref), "summary_token_limit": plan.summary_token_limit,
                                       "max_output_tokens": plan.max_output_tokens,
                                       "effective_contract_hash": activation.effective_contract_hash,
                                       "engineering_plan_hash": activation.engineering_plan_hash,
                                       "request_id": activation.request_id,
                                       **self._target_metadata(activation.target, activation.adapter, activation.snapshot_id),
                                       "previous_compaction_event_id": request.context.manifest.compaction_event_id})

    def _begin_request(self, activation: _Activation, request: ModelRequest) -> bool:
        with self._state_lock:
            current = self.project(request.run_id)
            current = self._close_obsolete_request(request.run_id, current)
            if current.phase in TERMINAL_PHASES or request.abort_flag.is_set():
                return False
            if (current_contract_hash(current) != request.effective_contract_hash
                    or current_plan_hash(current) != request.engineering_plan_hash
                    or self._request_id(current) != activation.request_id
                    or current.input_version != activation.input_version
                    or self._guidance_version(current, activation.department) > activation.guidance_version):
                return False
            if request.context.manifest.guidance_ids and not activation.guidance_applied:
                self.store.append(
                    request.run_id,
                    EventType.DEPARTMENT_GUIDANCE_APPLIED,
                    role=request.department,
                    parent_event_id=activation.parent_event_id,
                    state_before=current.phase,
                    state_after=current.phase,
                    session_id=request.session_id,
                    payload={
                        "guidance_ids": list(request.context.manifest.guidance_ids),
                        "activation_id": request.activation_id,
                        "context_event_id": request.context_event_id,
                        "input_version": request.input_version,
                    },
                )
                activation.guidance_applied = True
            request.attempt_started_at = request.attempt_started_at or utc_now()
            self.store.append(request.run_id, EventType.MODEL_REQUESTED, role=request.department,
                              parent_event_id=activation.parent_event_id, state_before=current.phase,
                              state_after=current.phase, session_id=request.session_id,
                              provider=self._configured_provider(activation.target, activation.adapter),
                              context_digest=request.context.manifest.digest,
                              payload={"activation_id": request.activation_id, "step_id": request.step_id,
                                       **activation.versions(),
                                       "attempt": request.attempt, "max_attempts": MAX_PROVIDER_ATTEMPTS,
                                       "root_step_id": request.root_step_id,
                                       "retry_of_step_id": request.retry_of_step_id,
                                       "attempt_id": request.attempt_id,
                                       "logical_call_id": request.logical_call_id,
                                       "context_event_id": request.context_event_id,
                                       "collaboration_request_id": request.request_id,
                                       "started_at": request.attempt_started_at,
                                       "attempted": True, "purpose": request.purpose,
                                       "effective_contract_hash": request.effective_contract_hash,
                                       "engineering_plan_hash": request.engineering_plan_hash, "request_id": activation.request_id,
                                       **self._target_metadata(activation.target, activation.adapter, activation.snapshot_id),
                                       "effective_context_window": request.context.manifest.budget,
                                       "max_output_tokens": request.max_output_tokens})
            return True

    @staticmethod
    def _attempt_collection_scope() -> dict[str, Any]:
        return {
            "request": "SDK request JSON object captured from the prepared HTTP request; authentication headers and raw HTTP bytes are excluded.",
            "response": "Complete SDK response object exposed by the provider SDK when a terminal response was received, with credential and header fields redacted.",
            "events": "SDK decoded stream event JSON objects captured as JSON Lines with credential and header fields redacted; raw HTTP/SSE bytes are not available.",
            "credentials": "excluded",
        }

    def _capture_for(self, activation: _Activation, request: ModelRequest) -> _AttemptCapture:
        attempt_id = request.attempt_id or self._attempt_id(
            request.logical_call_id or self._logical_call_id(request.activation_id, request.root_step_id or request.step_id, request.purpose),
            request.attempt,
        )
        request.attempt_id = attempt_id
        request.logical_call_id = request.logical_call_id or attempt_id.rsplit(":attempt-", 1)[0]
        capture = activation.attempt_captures.get(attempt_id)
        if capture is None:
            capture = _AttemptCapture()
            activation.attempt_captures[attempt_id] = capture
        return capture

    def _record_stream_progress(
        self,
        activation: _Activation,
        request: ModelRequest,
        capture: _AttemptCapture,
        observation: ModelObservation,
        observed_at: str,
    ) -> None:
        payload = observation.payload
        stage = _stream_progress_stage(payload)
        if capture.first_observed_at is None:
            capture.first_observed_at = observed_at
        if stage in {"output", "output_item_done"} and capture.first_output_at is None:
            capture.first_output_at = observed_at
        now = time.monotonic()
        changed = stage != capture.progress_stage
        due = capture.progress_last_emitted_monotonic is None or now - capture.progress_last_emitted_monotonic >= 0.25
        capture.progress_stage = stage
        if not changed and not due:
            return
        capture.progress_last_emitted_monotonic = now
        provider = activation.provider or self._configured_provider(activation.target, activation.adapter)
        current = self.project(request.run_id)
        self.store.append(
            request.run_id,
            EventType.MODEL_STREAM_PROGRESS,
            role=request.department,
            parent_event_id=activation.parent_event_id,
            state_before=current.phase,
            state_after=current.phase,
            session_id=request.session_id,
            provider=provider,
            model=observation.model or activation.model,
            context_digest=request.context.manifest.digest,
            payload={
                "attempt_id": request.attempt_id,
                "logical_call_id": request.logical_call_id,
                "collaboration_request_id": request.request_id,
                "context_event_id": request.context_event_id,
                "activation_id": request.activation_id,
                "step_id": request.step_id,
                "attempt": request.attempt,
                "root_step_id": request.root_step_id,
                "purpose": request.purpose,
                "source": "sdk_decoded_stream",
                "stage": stage,
                "event_type": payload.get("type"),
                "sequence": observation.sequence,
                "observed_at": observed_at,
                "first_observed_at": capture.first_observed_at,
                "first_output_at": capture.first_output_at,
                "summary": _stream_progress_summary(payload),
                **activation.versions(),
            },
        )

    def _finalize_capture(self, activation: _Activation, request: ModelRequest) -> _AttemptCapture:
        capture = activation.attempt_captures.pop(request.attempt_id or "", None)
        if capture is None:
            capture = _AttemptCapture()
        try:
            if capture.stream_event_count:
                ref = self.artifacts.put_stream(
                    request.run_id,
                    "sdk_stream_events",
                    capture.stream_chunks(),
                    media_type="application/x-ndjson",
                )
                capture.stream_ref = asdict(ref)
        finally:
            capture.close()
        return capture

    @staticmethod
    def _usage_summary(usage: Usage | None) -> dict[str, Any] | None:
        if usage is None or not (usage.reported or usage.total_tokens or usage.input_tokens
                                 or usage.output_tokens or usage.cache_read_tokens
                                 or usage.cache_write_tokens or usage.cost):
            return None
        return {
            "input_tokens": usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "total_tokens": usage.total_tokens,
            "cost": usage.cost if usage.cost_reported else None,
            "currency": None,
            "cost_source": None,
            "latency_ms": usage.latency_ms if usage.latency_ms else None,
            "reported": bool(usage.reported),
        }

    def _record_attempt_finished(
        self,
        activation: _Activation,
        request: ModelRequest,
        response: ModelResponse,
    ) -> None:
        with self._state_lock:
            current = self.project(request.run_id)
            finished_at = utc_now()
            started_monotonic = request.attempt_started_monotonic
            finished_monotonic = request.attempt_finished_monotonic or time.monotonic()
            duration_ms = None if started_monotonic is None else max(
                0, int((finished_monotonic - started_monotonic) * 1000)
            )
            capture = self._finalize_capture(activation, request)
            if capture.response_ref is None and isinstance(response.sdk_response, dict):
                safe_response = _redact_observation(
                    response.sdk_response,
                    secret=getattr(activation.target, "api_key", None),
                )
                response_ref = self.artifacts.put(
                    request.run_id,
                    "sdk_response",
                    json_dumps(safe_response),
                    media_type="application/json",
                )
                capture.response_ref = asdict(response_ref)
                capture.provider_response_id = safe_response.get("id") or response.response_id
            provider = response.provider or self._configured_provider(activation.target, activation.adapter)
            model = response.model or activation.model
            payload = {
                "attempt_id": request.attempt_id,
                "logical_call_id": request.logical_call_id,
                "collaboration_request_id": request.request_id,
                "context_event_id": request.context_event_id,
                "activation_id": request.activation_id,
                "step_id": request.step_id,
                "root_step_id": request.root_step_id,
                "retry_of_step_id": request.retry_of_step_id,
                "attempt": request.attempt,
                "purpose": request.purpose,
                "status": "completed",
                "started_at": request.attempt_started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "duration_source": "monotonic",
                "provider_response_id": response.response_id or capture.provider_response_id,
                "actual_provider": capture.actual_provider or (provider if response.response_id or response.model else None),
                "actual_model": capture.actual_model or (response.model or None),
                "response_ref": capture.response_ref,
                "stream_events_ref": getattr(capture, "stream_ref", None),
                "stream_event_count": capture.stream_event_count,
                "stream_first_observed_at": capture.first_observed_at,
                "stream_first_output_at": capture.first_output_at,
                "stream_last_stage": capture.progress_stage,
                "collection_scope": self._attempt_collection_scope(),
                "usage": self._usage_summary(capture.usage or activation.step_usage),
                "raw_usage_ref": capture.usage_ref or activation.raw_usage_ref,
                **activation.versions(),
                **self._target_metadata(activation.target, activation.adapter, activation.snapshot_id),
            }
            self.store.append(
                request.run_id,
                EventType.MODEL_ATTEMPT_FINISHED,
                role=request.department,
                parent_event_id=activation.parent_event_id,
                state_before=current.phase,
                state_after=current.phase,
                session_id=request.session_id,
                provider=provider,
                model=model or None,
                context_digest=request.context.manifest.digest,
                artifact_hashes=[ref["content_hash"] for ref in (capture.response_ref, getattr(capture, "stream_ref", None)) if ref],
                payload=payload,
            )

    def _record_attempt_failed(
        self,
        activation: _Activation,
        request: ModelRequest,
        error: ProviderError,
        will_retry: bool,
    ) -> None:
        with self._state_lock:
            current = self.project(request.run_id)
            failed_key = (request.activation_id, request.step_id)
            kept = [
                (text, key)
                for text, key in zip(activation.messages, activation.message_steps)
                if key != failed_key
            ]
            activation.messages = [text for text, _key in kept]
            activation.message_steps = [key for _text, key in kept]
            capture = self._finalize_capture(activation, request)
            provider = activation.provider or self._configured_provider(activation.target, activation.adapter)
            model = activation.model
            finished_at = utc_now()
            started_monotonic = request.attempt_started_monotonic
            finished_monotonic = request.attempt_finished_monotonic or time.monotonic()
            duration_ms = None if started_monotonic is None else max(
                0, int((finished_monotonic - started_monotonic) * 1000)
            )
            status = "cancelled" if error.reason == "cancelled" else "failed"
            safe_error = _redact_observation(
                str(error),
                secret=getattr(activation.target, "api_key", None),
            )
            safe_diagnostics = _redact_observation(
                dict(error.diagnostics or {}),
                secret=getattr(activation.target, "api_key", None),
            )
            self.store.append(
                request.run_id, EventType.MODEL_ATTEMPT_FAILED, role=request.department,
                parent_event_id=activation.parent_event_id, state_before=current.phase,
                state_after=current.phase, session_id=request.session_id,
                provider=provider,
                model=model,
                context_digest=request.context.manifest.digest,
                error=safe_error,
                artifact_hashes=[ref["content_hash"] for ref in (capture.response_ref, capture.stream_ref) if ref],
                payload={
                    "attempt_id": request.attempt_id,
                    "logical_call_id": request.logical_call_id,
                    "collaboration_request_id": request.request_id,
                    "context_event_id": request.context_event_id,
                    "activation_id": request.activation_id,
                    "step_id": request.step_id,
                    **activation.versions(),
                    "attempt": request.attempt,
                    "max_attempts": MAX_PROVIDER_ATTEMPTS,
                    "root_step_id": request.root_step_id,
                    "retry_of_step_id": request.retry_of_step_id,
                    "purpose": request.purpose,
                    "status": status,
                    "started_at": request.attempt_started_at,
                    "finished_at": finished_at,
                    "duration_ms": duration_ms,
                    "duration_source": "monotonic",
                    "actual_provider": capture.actual_provider,
                    "actual_model": capture.actual_model,
                    "provider_response_id": capture.provider_response_id,
                    "response_ref": capture.response_ref,
                    "stream_events_ref": capture.stream_ref,
                    "stream_event_count": capture.stream_event_count,
                    "stream_first_observed_at": capture.first_observed_at,
                    "stream_first_output_at": capture.first_output_at,
                    "stream_last_stage": capture.progress_stage,
                    "collection_scope": self._attempt_collection_scope(),
                    "usage": self._usage_summary(capture.usage or activation.step_usage),
                    "raw_usage_ref": capture.usage_ref or activation.raw_usage_ref,
                    "effective_contract_hash": request.effective_contract_hash,
                    "engineering_plan_hash": request.engineering_plan_hash,
                    "request_id": request.request_id,
                    "reason": error.reason,
                    "retryable": error.retryable,
                    "will_retry": will_retry,
                    "diagnostics": safe_diagnostics,
                    **self._target_metadata(activation.target, activation.adapter, activation.snapshot_id),
                },
            )

    def _record_retry_scheduled(
        self,
        activation: _Activation,
        request: ModelRequest,
        error: ProviderError,
        delay: float,
        next_step_id: int,
    ) -> bool:
        with self._state_lock:
            current = self._close_obsolete_request(request.run_id, self.project(request.run_id))
            if (current.phase in TERMINAL_PHASES or request.abort_flag.is_set()
                    or current_contract_hash(current) != request.effective_contract_hash
                    or current_plan_hash(current) != request.engineering_plan_hash
                    or self._request_id(current) != activation.request_id
                    or current.input_version != activation.input_version
                    or self._guidance_version(current, activation.department) > activation.guidance_version):
                return False
            provider = self._configured_provider(activation.target, activation.adapter)
            self.store.append(
                request.run_id, EventType.MODEL_RETRY_SCHEDULED, role=request.department,
                parent_event_id=activation.parent_event_id, state_before=current.phase,
                state_after=current.phase, session_id=request.session_id,
                provider=provider,
                context_digest=request.context.manifest.digest,
                payload={
                    "activation_id": request.activation_id,
                    "step_id": request.step_id,
                    **activation.versions(),
                    "attempt": request.attempt,
                    "max_attempts": MAX_PROVIDER_ATTEMPTS,
                    "root_step_id": request.root_step_id,
                    "retry_of_step_id": request.retry_of_step_id,
                    "attempt_id": request.attempt_id,
                    "logical_call_id": request.logical_call_id,
                    "context_event_id": request.context_event_id,
                    "collaboration_request_id": request.request_id,
                    "next_step_id": next_step_id,
                    "next_attempt": request.attempt + 1,
                    "purpose": request.purpose,
                    "effective_contract_hash": request.effective_contract_hash,
                    "engineering_plan_hash": request.engineering_plan_hash,
                    "request_id": request.request_id,
                    "reason": error.reason,
                    "retryable": True,
                    "delay_sec": delay,
                    **self._target_metadata(activation.target, activation.adapter, activation.snapshot_id),
                },
            )
            return True

    def _begin_tool(self, activation: _Activation, call: dict[str, Any]) -> ToolAdmission:
        with self._state_lock:
            request = activation.request
            current = self.project(request.run_id)
            current = self._close_obsolete_request(request.run_id, current)
            if current.phase in TERMINAL_PHASES or request.abort_flag.is_set():
                return ToolAdmission(stopped=True)
            if (current_contract_hash(current) != activation.effective_contract_hash
                    or current_plan_hash(current) != activation.engineering_plan_hash
                    or self._request_id(current) != activation.request_id
                    or current.input_version != activation.input_version
                    or self._guidance_version(current, activation.department) > activation.guidance_version):
                return ToolAdmission(stopped=True)
            if not has_tool(request.department, call["name"]):
                return ToolAdmission(error=f"{request.department} cannot use {call['name']}")
            if activation.guidance_only and call["name"] not in GUIDANCE_ONLY_TOOLS:
                return ToolAdmission(error="This guidance activation cannot change files or submit normal department work.")
            error = tool_error(current, request.department, call["name"], call["args"])
            if error:
                return ToolAdmission(error=error)
            command_basis: dict[str, Any] = {}
            if call["name"] == "run_command":
                # 登记命令在执行前核对冻结注册表：未登记的名称与越界参数在这里拒绝，不执行
                basis_error, command_basis = _run_command_basis(
                    self.workspace(request.run_id), current, call["args"])
                if basis_error:
                    return ToolAdmission(error=basis_error)
            if call["name"] in {"write_file", "edit_range", "delete_file", "move_file"}:
                plan = current.engineering_plan
                if plan is None or plan.effective_contract_hash != current_contract_hash(current):
                    return ToolAdmission(error="Submit an engineering plan for the current effective contract before writing files.")
                targets = ([call["args"].get("source"), call["args"].get("destination")]
                           if call["name"] == "move_file" else [call["args"].get("path")])
                workspace = self.workspace(request.run_id)
                for target in targets:
                    if not path_in_scope(target, plan.scope):
                        return ToolAdmission(error="The file is outside the current engineering plan scope; submit an adjusted plan with a reason first.")
                    try:
                        actual = workspace.resolve(target).relative_to(workspace.root.resolve()).as_posix()
                    except (OSError, ValueError) as exc:
                        return ToolAdmission(error=str(exc))
                    if not path_in_scope(actual, plan.scope):
                        return ToolAdmission(error="The resolved file is outside the current engineering plan scope.")
            self.store.append(request.run_id, EventType.TOOL_STARTED, role=request.department,
                              parent_event_id=activation.parent_event_id, state_before=current.phase,
                              state_after=current.phase, session_id=request.session_id,
                              payload={**call, "activation_id": request.activation_id,
                                       "attempt_id": request.attempt_id,
                                       "logical_call_id": request.logical_call_id,
                                       "collaboration_request_id": request.request_id,
                                       "context_event_id": request.context_event_id,
                                       "attempt": request.attempt,
                                       **activation.versions(),
                                       "effective_contract_hash": activation.effective_contract_hash,
                                       "engineering_plan_hash": activation.engineering_plan_hash, "request_id": activation.request_id,
                                       **command_basis})
            return ToolAdmission()

    def _record_observation(self, activation: _Activation, observation: ModelObservation) -> None:
        request = activation.request
        with self._state_lock:
            if observation.kind != "stream_event":
                key = (f"{request.attempt_id or request.step_id}:{observation.kind}", observation.id)
                if key in activation.seen:
                    return
                activation.seen.add(key)
            if observation.kind == "request":
                current = self.project(request.run_id)
                if not isinstance(observation.payload, dict):
                    raise ProviderError("Serialized provider request is not a JSON object", reason="provider_protocol")
                ref = self.artifacts.put(
                    request.run_id,
                    "sdk_request",
                    json_dumps(observation.payload),
                    media_type="application/json",
                )
                payload = {
                    "attempt_id": request.attempt_id,
                    "logical_call_id": request.logical_call_id,
                    "collaboration_request_id": request.request_id,
                    "context_event_id": request.context_event_id,
                    "activation_id": request.activation_id,
                    "step_id": request.step_id,
                    "attempt": request.attempt,
                    "root_step_id": request.root_step_id,
                    "retry_of_step_id": request.retry_of_step_id,
                    "purpose": request.purpose,
                    "request_ref": asdict(ref),
                    "request_digest": canonical_hash(observation.payload),
                    "serialization": "sdk_request_json_object",
                    "effective_contract_hash": activation.effective_contract_hash,
                    "engineering_plan_hash": activation.engineering_plan_hash,
                    "request_id": activation.request_id,
                    **activation.versions(),
                    **self._target_metadata(activation.target, activation.adapter, activation.snapshot_id),
                }
                self.store.append(
                    request.run_id,
                    EventType.MODEL_REQUEST_SERIALIZED,
                    role=request.department,
                    parent_event_id=activation.parent_event_id,
                    state_before=current.phase,
                    state_after=current.phase,
                    session_id=request.session_id,
                    provider=self._configured_provider(activation.target, activation.adapter),
                    context_digest=request.context.manifest.digest,
                    artifact_hashes=[ref.content_hash],
                    payload=payload,
                )
                return
            if observation.provider:
                activation.provider = observation.provider
            if observation.model:
                activation.model = observation.model
            provider = activation.provider or self._configured_provider(activation.target, activation.adapter)
            model = activation.model
            if observation.kind == "stream_event":
                if not isinstance(observation.payload, dict):
                    raise ProviderError("Decoded provider stream event is not a JSON object", reason="provider_protocol")
                capture = self._capture_for(activation, request)
                observation.payload = _redact_observation(
                    observation.payload,
                    secret=getattr(activation.target, "api_key", None),
                )
                capture.actual_provider = observation.provider or capture.actual_provider
                capture.actual_model = observation.model or capture.actual_model
                nested_response = observation.payload.get("response")
                if isinstance(nested_response, dict):
                    response_id = nested_response.get("id")
                    if isinstance(response_id, str) and response_id:
                        capture.provider_response_id = response_id
                    nested_model = nested_response.get("model")
                    if isinstance(nested_model, str) and nested_model.strip():
                        capture.actual_model = nested_model.strip()
                observed_at = utc_now()
                capture.add_stream_event(observation.sequence, observation.payload, observed_at)
                self._record_stream_progress(activation, request, capture, observation, observed_at)
                return
            if observation.kind == "response":
                if not isinstance(observation.payload, dict):
                    raise ProviderError("Provider response is not a JSON object", reason="provider_protocol")
                capture = self._capture_for(activation, request)
                observation.payload = _redact_observation(
                    observation.payload,
                    secret=getattr(activation.target, "api_key", None),
                )
                capture.actual_provider = observation.provider or capture.actual_provider
                capture.actual_model = observation.model or capture.actual_model
                ref = self.artifacts.put(
                    request.run_id,
                    "sdk_response",
                    json_dumps(observation.payload),
                    media_type="application/json",
                )
                capture.response_ref = asdict(ref)
                capture.provider_response_id = (
                    observation.payload.get("id") if isinstance(observation.payload.get("id"), str) else observation.id
                )
                return
            if observation.kind == "usage":
                if observation.usage is not None:
                    capture = self._capture_for(activation, request)
                    safe_usage = _redact_observation(
                        observation.payload,
                        secret=getattr(activation.target, "api_key", None),
                    )
                    ref = self.artifacts.put(request.run_id, "model_usage", json_dumps(safe_usage), media_type="application/json")
                    activation.raw_usage_ref = asdict(ref)
                    capture.usage = observation.usage
                    capture.usage_ref = asdict(ref)
                    has_usage = bool(
                        observation.usage.reported
                        or observation.usage.total_tokens
                        or observation.usage.cost
                    )
                    if has_usage:
                        activation.step_usage = observation.usage
                        usage = activation.previous_usage.plus(observation.usage)
                    else:
                        usage = activation.usage if activation.has_usage else Usage(reported=False)
                    self._record_usage(
                        activation,
                        usage,
                        provider=provider,
                        model=model,
                        force=bool(observation.model),
                        reported=(observation.usage.reported if has_usage else False),
                    )
                return
            current = self.project(request.run_id)
            if observation.kind in {"tool", "skipped_tool"}:
                payload = _redact_observation(
                    dict(observation.payload),
                    secret=getattr(activation.target, "api_key", None),
                )
                tool_id = f"{request.step_id}:{payload.get('id') or observation.id}"
                if tool_id in activation.tool_ids:
                    return
                activation.tool_ids.add(tool_id)
                output = payload.pop("output", None)
                if output is not None:
                    ref = self.artifacts.put(request.run_id, "tool_output", json_dumps(output), media_type="application/json")
                    payload["output_ref"] = asdict(ref)
                event_type = EventType.TOOL_CALLED if observation.kind == "tool" else EventType.TOOL_SKIPPED
            elif observation.kind == "message":
                safe_text = _redact_observation(
                    observation.text,
                    secret=getattr(activation.target, "api_key", None),
                )
                activation.messages.append(safe_text)
                activation.message_steps.append((request.activation_id, request.step_id))
                message = _redact_observation(
                    observation.payload or {"role": "assistant", "content": safe_text},
                    secret=getattr(activation.target, "api_key", None),
                )
                ref = self.artifacts.put(request.run_id, "model_message", json_dumps(message), media_type="application/json")
                payload = {
                    "message_ref": asdict(ref),
                    "message_index": len(activation.messages),
                    "response_id": message.get("id"),
                    "stop_reason": message.get("status"),
                    "summary": safe_text[:160],
                }
                event_type = EventType.MODEL_MESSAGE
            else:
                raise ValueError(f"unknown adapter observation: {observation.kind}")
            payload["attempt_id"] = request.attempt_id
            payload["logical_call_id"] = request.logical_call_id
            payload["collaboration_request_id"] = request.request_id
            payload["context_event_id"] = request.context_event_id
            payload["activation_id"] = request.activation_id
            payload["step_id"] = request.step_id
            payload["purpose"] = request.purpose
            payload["effective_contract_hash"] = activation.effective_contract_hash
            payload["engineering_plan_hash"] = activation.engineering_plan_hash
            payload["request_id"] = activation.request_id
            payload.update(activation.versions())
            payload.update(self._target_metadata(activation.target, activation.adapter, activation.snapshot_id))
            self.store.append(
                request.run_id, event_type, role=request.department,
                parent_event_id=activation.parent_event_id,
                state_before=current.phase, state_after=current.phase,
                session_id=request.session_id, provider=provider, model=model, payload=payload,
            )
            if observation.usage is not None and (observation.usage.reported or observation.usage.total_tokens or observation.usage.cost):
                activation.step_usage = observation.usage
                usage = activation.previous_usage.plus(observation.usage)
                self._record_usage(activation, usage, provider=provider, model=model)

    def _record_usage(
        self,
        activation: _Activation,
        usage: Usage,
        *,
        provider: str,
        model: str | None,
        force: bool = False,
        reported: bool | None = None,
    ) -> None:
        request = activation.request
        token_delta = usage.total_tokens - activation.tokens_charged
        cost_delta = usage.cost - activation.cost_charged
        first = not activation.has_usage
        activation.has_usage = True
        activation.usage = usage
        activation.tokens_charged = usage.total_tokens
        activation.cost_charged = usage.cost
        current = self.project(request.run_id)
        if first or token_delta or cost_delta or force:
            self.store.append(
                request.run_id, EventType.TOOL_CALLED, role=request.department,
                parent_event_id=activation.parent_event_id,
                state_before=current.phase, state_after=current.phase,
                session_id=request.session_id, provider=provider, model=model,
                payload={
                    "name": "provider_usage", "ok": True,
                    **activation.versions(),
                    "activation_id": request.activation_id,
                    "step_id": request.step_id,
                    "purpose": request.purpose,
                    "accounting": "activation_total_with_charge_delta",
                    "scope": "observable_main_dialogue",
                    "source": "reported" if (usage.reported if reported is None else reported) else "unreported",
                    "cost_reported": usage.cost_reported,
                    "raw_usage_ref": activation.raw_usage_ref,
                    "tokens_charged": token_delta,
                    "total_tokens": usage.total_tokens,
                    "input_tokens": usage.input_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                    "input_total_tokens": usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens,
                    "output_tokens": usage.output_tokens,
                    "cost": cost_delta, "total_cost": usage.cost,
                    **self._target_metadata(activation.target, activation.adapter, activation.snapshot_id),
                },
            )

    def _reconcile_response(self, activation: _Activation, result: ModelResponse) -> None:
        provider = result.provider or self._configured_provider(activation.target, activation.adapter)
        model = result.model
        for index, item in enumerate(result.output):
            content = item.get("content") or []
            text = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict)) if isinstance(content, list) else str(content)
            self._record_observation(activation, ModelObservation(
                str(item.get("id") or f"output-{index}"), "message", item, text,
                provider=provider, model=model,
            ))
        usage = result.usage
        if not usage or not (usage.reported or usage.total_tokens or usage.cost):
            usage = activation.step_usage or Usage(reported=False)
        activation.step_usage = usage
        with self._state_lock:
            self._record_usage(
                activation,
                activation.previous_usage.plus(usage),
                provider=provider,
                model=model,
                force=bool(result.model) and activation.model != result.model,
                reported=usage.reported,
            )

    def _apply_proposal(
        self,
        run_id: str,
        *,
        department: str,
        projection: RunProjection,
        input_version: int,
        proposal: dict[str, Any] | None,
        transcript_ref: dict[str, Any] | None,
        parent_event_id: str,
        session_id: str,
        guidance_version: int,
        provider: str | None,
        model: str | None,
        yielded_work: dict[str, Any] | None = None,
    ) -> None:
        evaluated = self.project(run_id)
        snapshot = self.workspace(run_id).snapshot()
        try:
            decision = evaluate_proposal(
                phase=evaluated.phase,
                department=department,
                proposal=proposal,
                projection=evaluated,
                snapshot=snapshot,
                events=self.store.list_events(run_id),
            )
        except Exception as exc:
            decision = ProposalDecision(
                False,
                [FieldError("proposal", f"invalid proposal payload: {type(exc).__name__}: {exc}")],
            )
        with self._state_lock:
            current = self.project(run_id)
            if current.phase in TERMINAL_PHASES or (self._abort.get(run_id) and self._abort[run_id].is_set()):
                return
            current = self._close_obsolete_request(run_id, current)
            if (current.phase != projection.phase
                    or current.input_version != input_version
                    or self._guidance_version(current, department) != guidance_version
                    or current_contract_hash(current) != current_contract_hash(projection)
                    or current_plan_hash(current) != current_plan_hash(projection)
                    or self._request_id(current) != self._request_id(projection)
                    or request_basis(current) != request_basis(evaluated)):
                decision = ProposalDecision(False, [FieldError("execution_basis", "The input, contract, plan, or current work changed after this activation began; stale results cannot be rebound.")])
            projection = current
            # 锁外获取的 snapshot 在进入本锁前可能已被并发写入改旧；若直接用
            # 它提交，submissions.commit 的字节核对会以 host_commit_error/FAILED
            # 脏收场。锁内重取快照并重算校验，陈旧则走 PROPOSAL_REJECTED 干净拒绝；
            # 接受时提交的 snapshot 与锁内投影一致，QA release 不再绑定陈旧快照。
            fresh_snapshot = self.workspace(run_id).snapshot()
            if fresh_snapshot != snapshot:
                decision = ProposalDecision(False, [FieldError("execution_basis", "The workspace snapshot changed after this activation began; stale results cannot be rebound.")])
            elif decision.accepted:
                try:
                    decision = evaluate_proposal(
                        phase=current.phase,
                        department=department,
                        proposal=proposal,
                        projection=current,
                        snapshot=fresh_snapshot,
                        events=self.store.list_events(run_id),
                    )
                except Exception as exc:
                    decision = ProposalDecision(
                        False,
                        [FieldError("proposal", f"invalid proposal payload: {type(exc).__name__}: {exc}")],
                    )
            snapshot = fresh_snapshot
            if proposal is not None:
                self.store.append(
                    run_id, EventType.PROPOSAL_SUBMITTED, role=department,
                    parent_event_id=parent_event_id,
                    state_before=projection.phase, state_after=projection.phase,
                    session_id=session_id, provider=provider, model=model,
                    payload={"kind": proposal.get("kind"), "transcript_ref": transcript_ref,
                             "raw_keys": sorted(proposal.keys()), "input_version": input_version},
                )
            if not decision.accepted:
                self.store.append(
                    run_id, EventType.PROPOSAL_REJECTED, role=department,
                    parent_event_id=parent_event_id,
                    state_before=projection.phase, state_after=projection.phase,
                    session_id=session_id, provider=provider, model=model,
                    payload={
                        "errors": decision.error_dicts,
                        "transcript_ref": transcript_ref,
                        "kind": None if proposal is None else proposal.get("kind"),
                        "input_version": input_version,
                    },
                )
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
            self.store.append(
                run_id,
                EventType.TRANSITION,
                role=department_for_phase(target) or department,
                parent_event_id=parent_event_id,
                state_before=source,
                state_after=target,
                session_id=session_id,
                payload={"from": source, "to": target, "route": f"{source}->{target}"},
            )
            if target == "DONE":
                self.store.append(
                    run_id,
                    EventType.RUN_DONE,
                    role="quality",
                    parent_event_id=parent_event_id,
                    state_before="QUALITY",
                    state_after="DONE",
                    session_id=session_id,
                    stop_reason="released",
                    payload={"stop_reason": "released"},
                )
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
        self.store.append(
            run_id,
            EventType.TRANSITION,
            role=department_for_phase(target) or department,
            parent_event_id=parent_event_id,
            state_before=current.phase,
            state_after=target,
            session_id=session_id,
            payload={"from": current.phase, "to": target, "route": f"{current.phase}->{target}",
                     "yielded_work_resolved": True, "yielded_work": dict(basis)},
        )

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
        self.store.append(
            source.run_id, EventType.LESSON_CANDIDATE_RECORDED,
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
        )

    def _pause(self, run_id: str, projection: RunProjection, reason: str) -> None:
        with self._state_lock:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return
            department = projection.active_department
            projection = self._close_request(run_id, projection, status="stopped", reason=reason,
                                             return_phase=projection.phase, return_work_valid=False)
            self.store.append(
                run_id, EventType.RUN_PAUSED, role=department,
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
            )
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
        with self._state_lock:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return
            department = projection.active_department
            status = "cancelled" if reason == "cancelled" else "timed_out" if reason == "provider_timeout" else "stopped"
            projection = self._close_request(run_id, projection, status=status, reason=reason,
                                             return_phase=projection.phase, return_work_valid=False)
            source_event = self.store.append(
                run_id, EventType.RUN_FAILED, role=department,
                state_before=projection.phase, state_after="FAILED", stop_reason=reason, error=message,
                provider=projection.provider, model=projection.model,
                payload={"stop_reason": reason, "human_action": human, "message": message,
                         **({"input_save_failure": input_save_failure} if input_save_failure is not None else {})},
            )
            self.sessions.close_run(run_id)
            if reason != "cancelled":
                self._record_lesson_candidate(source_event, projection)

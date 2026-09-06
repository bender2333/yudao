"""Orchestrator：状态机、停止判定、权限与预算。状态迁移函数内不调用 LLM。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event, RLock
from typing import Any

from .adapters.base import ModelObservation, ModelResponse, ModelAdapter, ModelRequest, ProviderError
from .artifacts import ArtifactStore
from .context import ContextAssembler
from .contracts import current_contract_hash, current_plan_hash, path_in_scope
from .compaction import CompactionCheckpoint, CompactionError, finish_compaction, plan_compaction, visible_history
from .event_store import EventStore
from .engine import ToolAdmission, run_department
from .models import (
    Event as RunEvent,
    ArtifactRef,
    EventType,
    HUMAN_ACTIONS,
    TERMINAL_PHASES,
    Usage,
    canonical_hash,
    department_for_phase,
    json_dumps,
    new_id,
)
from .projection import RunProjection, project_run
from .sessions import SessionFactory
from .submissions import SubmissionWriter
from .tools import ToolRuntime
from .validation import FieldError, ProposalDecision, evaluate_proposal
from .workspace import Workspace


@dataclass
class _Activation:
    run_id: str
    department: str
    session_id: str
    activation_id: str
    abort_flag: Event
    parent_event_id: str
    request: ModelRequest | None = None
    tokens_charged: int = 0
    usage: Usage = field(default_factory=lambda: Usage(reported=False))
    has_usage: bool = False
    cost_charged: float = 0.0
    seen: set[tuple[str, str]] = field(default_factory=set)
    tool_ids: set[str] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)
    step_usage: Usage | None = None
    previous_usage: Usage = field(default_factory=lambda: Usage(reported=True, cost_reported=True))
    raw_usage_ref: dict[str, Any] | None = None
    provider: str | None = None
    model: str | None = None
    compaction_plan: Any = None
    effective_contract_hash: str | None = None
    engineering_plan_hash: str | None = None


class Orchestrator:
    def __init__(
        self,
        store: EventStore,
        artifacts: ArtifactStore,
        workspace_root: str | Path,
        adapter: ModelAdapter,
        assembler: ContextAssembler | None = None,
        sessions: SessionFactory | None = None,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.workspace_root = Path(workspace_root)
        self.materials_root = self.workspace_root.parent / "materials"
        self.submissions = SubmissionWriter(store, artifacts, self.materials_root)
        self.adapter = adapter
        self.assembler = assembler or ContextAssembler()
        self.sessions = sessions or SessionFactory()
        self._abort: dict[str, Event] = {}
        self._state_lock = RLock()
        self._active: dict[str, _Activation] = {}

    def create_run(
        self,
        task: str,
        *,
        max_cycles: int = 8,
        context_window: int = 32_000,
        run_id: str | None = None,
    ) -> str:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be non-empty")
        if max_cycles < 1:
            raise ValueError("max_cycles must be positive")
        if context_window < 1:
            raise ValueError("context_window must be positive")
        run_id = run_id or new_id("run")
        material_dir = (self.materials_root / run_id).resolve()
        if material_dir == self.materials_root.resolve() or not material_dir.is_relative_to(self.materials_root.resolve()):
            raise ValueError("run_id must stay within the run materials directory")
        material_dir.mkdir(parents=True, exist_ok=True)
        (material_dir / "intend.md").write_bytes(task.encode("utf-8"))
        intend_ref = self.artifacts.put(run_id, "intend", task, media_type="text/markdown")
        sessions = self.sessions.create_run_sessions(run_id)
        self._abort[run_id] = Event()
        Workspace(self.workspace_root / run_id)
        self.store.append(
            run_id,
            EventType.RUN_CREATED,
            role="product",
            state_before="CREATED",
            state_after="PRODUCT_SPEC",
            payload={
                "task": task,
                "intend_ref": asdict(intend_ref),
                "intend_path": (Path("materials") / run_id / "intend.md").as_posix(),
                "max_cycles": max_cycles,
                "context_window": context_window,
                "provider": getattr(self.adapter, "name", "unknown"),
                "adapter": self.adapter.name,
                "sessions": {name: session.session_id for name, session in sessions.items()},
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

    def cancel(self, run_id: str) -> RunProjection:
        with self._state_lock:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return projection
            self._abort.setdefault(run_id, Event()).set()
            activation = self._active.get(run_id)
            self._fail(run_id, projection, "cancelled", "run cancelled")
        if activation is not None:
            self.adapter.abort(activation.session_id)
        return self.project(run_id)

    def run_until_stop(self, run_id: str) -> RunProjection:
        while True:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return projection
            if self._abort.get(run_id) and self._abort[run_id].is_set():
                return self.cancel(run_id)
            self.activate_once(run_id)

    def activate_once(self, run_id: str) -> RunProjection:
        with self._state_lock:
            if run_id in self._active:
                raise RuntimeError("run already has an active department invocation")
            activation = self._prepare_activation(run_id)
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
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "stop_reason": current.stop_reason,
                    },
                )
                self.sessions.get(run_id, request.department).idle()
                self._active.pop(run_id, None)
        return self.project(run_id)

    def _prepare_activation(self, run_id: str) -> _Activation | None:
        projection = self.project(run_id)
        if projection.phase in TERMINAL_PHASES:
            return None
        if projection.cycle_count >= projection.max_cycles:
            self._pause(run_id, projection, "max_cycles")
            return None
        department = department_for_phase(projection.phase)
        if department is None:
            self._fail(run_id, projection, "provider_error", f"no department for phase {projection.phase}")
            return None

        availability = self.adapter.availability()
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
        parent = self.store.append(
            run_id,
            EventType.DEPARTMENT_ACTIVATED,
            role=department,
            state_before=projection.phase,
            state_after=projection.phase,
            session_id=session.session_id,
            payload={"activation_id": activation_id, "cycle": projection.cycle_count + 1,
                     "effective_contract_hash": current_contract_hash(projection),
                     "engineering_plan_hash": current_plan_hash(projection)},
        )
        abort_flag = self._abort.setdefault(run_id, Event())
        return _Activation(run_id, department, session.session_id, activation_id, abort_flag, parent.event_id,
                           effective_contract_hash=current_contract_hash(projection),
                           engineering_plan_hash=current_plan_hash(projection))

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
                self.adapter, ToolRuntime(workspace),
                prepare_step=lambda step: self._prepare_step(activation, step),
                record_response=lambda response: self._reconcile_response(activation, response),
                record_tool=lambda call: self._record_observation(activation, ModelObservation(call["id"], "tool", call)),
                record_skipped_tool=lambda call: self._record_observation(activation, ModelObservation(call["id"], "skipped_tool", call)),
                begin_tool=lambda call: self._begin_tool(activation, call),
                begin_request=lambda request: self._begin_request(activation, request),
                finish_compaction=lambda response: self._finish_compaction(activation, response),
                stopped=lambda: self.project(run_id).phase in TERMINAL_PHASES or request.abort_flag.is_set(),
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
        if current.phase in TERMINAL_PHASES or submission is None:
            return

        try:
            transcript_ref = None
            transcript = "\n".join(activation.messages)
            if transcript:
                ref = self.artifacts.put(run_id, "transcript", transcript, media_type="text/plain")
                transcript_ref = ref.__dict__
            self._apply_proposal(
                run_id, department=department, projection=projection, proposal=submission.proposal,
                transcript_ref=transcript_ref, parent_event_id=activation.parent_event_id,
                session_id=request.session_id, provider=submission.response.provider, model=submission.response.model,
            )
        except Exception as exc:
            self._fail(run_id, self.project(run_id), "host_commit_error", f"{type(exc).__name__}: {exc}")

    def _prepare_step(self, activation: _Activation, step_id: int) -> ModelRequest | None:
        with self._state_lock:
            identity = activation
            current = self.project(identity.run_id)
            if current.phase in TERMINAL_PHASES or identity.abort_flag.is_set():
                return None
            if (current_contract_hash(current) != activation.effective_contract_hash
                    or current_plan_hash(current) != activation.engineering_plan_hash):
                return None
            pinned = self.assembler.assemble(
                current, department=identity.department, session_id=identity.session_id,
                activation_id=identity.activation_id, step_id=step_id,
            )
            if step_id == 1:
                static = {"intend", "department_rules", "professional_completion", "proposal_contract", "allowed_tools", "loop_limits", "department_history", "tool_schemas"}
                content = "\n\n".join(f"[{part.source}]\n{part.text}" for part in pinned.parts if part.source not in static)
                input_item = {"role": "user", "content": content}
                received_ref = self.artifacts.put(identity.run_id, "department_input", json_dumps(input_item), media_type="application/json")
                self.store.append(identity.run_id, EventType.DEPARTMENT_INPUT, role=identity.department,
                                  parent_event_id=activation.parent_event_id, state_before=current.phase,
                                  state_after=current.phase, session_id=identity.session_id,
                                  artifact_hashes=[received_ref.content_hash],
                                  payload={"activation_id": identity.activation_id, "step_id": step_id, "input_ref": asdict(received_ref),
                                           "effective_contract_hash": activation.effective_contract_hash,
                                           "engineering_plan_hash": activation.engineering_plan_hash})
            records = self._department_history_records(identity.run_id, identity.department)
            checkpoint_event = next((item for item in reversed(current.compactions)
                                     if item["department"] == identity.department
                                     and item["effective_contract_hash"] == activation.effective_contract_hash
                                     and item["engineering_plan_hash"] == activation.engineering_plan_hash), None)
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
                    records, checkpoint, current.context_window, pinned.input_items, pinned.tools,
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
                        history=visible_history(records, checkpoint),
                        compaction_event_id=checkpoint_id,
                    )
            except (CompactionError, ValueError, FileNotFoundError) as exc:
                reason = "context_overflow" if pinned.manifest.token_estimate >= current.context_window * 85 // 100 else "compaction_failed"
                raise ProviderError(str(exc), reason=reason) from exc
            request = ModelRequest(identity.run_id, identity.department, identity.session_id, identity.activation_id,
                                   step_id, assembled, assembled.tools, identity.abort_flag,
                                   purpose=assembled.manifest.purpose, max_output_tokens=assembled.manifest.max_output_tokens,
                                   effective_contract_hash=activation.effective_contract_hash,
                                   engineering_plan_hash=activation.engineering_plan_hash)
            activation.request = request
            request.on_observation = lambda observation: self._record_observation(activation, observation)
            activation.previous_usage = activation.usage if activation.has_usage else Usage(reported=True, cost_reported=True)
            activation.step_usage = None
            activation.raw_usage_ref = None
            estimate = assembled.manifest.token_estimate
            overflow = estimate > current.context_window
            admitted = not overflow
            request_payload = {"input": request.input_items, "tools": request.tools}
            if request.max_output_tokens is not None:
                request_payload["max_output_tokens"] = request.max_output_tokens
            ref = self.artifacts.put(request.run_id, "model_request", json_dumps(request_payload), media_type="application/json")
            payload = asdict(assembled.manifest)
            payload.update(run_id=request.run_id, request_ref=asdict(ref), admitted=admitted,
                           tokens_charged=0)
            self.store.append(request.run_id, EventType.CONTEXT_ASSEMBLED, role=request.department,
                              parent_event_id=activation.parent_event_id, state_before=current.phase,
                              state_after=current.phase, session_id=request.session_id,
                              context_digest=assembled.manifest.digest, artifact_hashes=[ref.content_hash], payload=payload)
            if overflow:
                self._fail(request.run_id, current, "context_overflow", "model request exceeds context_window")
                return None
            return request

    def _department_history_records(self, run_id: str, department: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for event in self.store.list_events(run_id):
            if event.role != department:
                continue
            if event.type in {EventType.MODEL_MESSAGE, EventType.DEPARTMENT_INPUT}:
                if event.payload.get("purpose") == "compaction":
                    continue
                ref = ArtifactRef(**event.payload["message_ref" if event.type == EventType.MODEL_MESSAGE else "input_ref"])
                item = json.loads(self.artifacts.get_for_run(run_id, ref))
            elif event.type in {EventType.TOOL_CALLED, EventType.TOOL_SKIPPED} and "input_item" in event.payload:
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
                    or current_plan_hash(current) != activation.engineering_plan_hash):
                return
            plan = activation.compaction_plan
            try:
                checkpoint = finish_compaction(plan, response.output)
            except CompactionError as exc:
                raise ProviderError(str(exc), reason="compaction_failed") from exc
            summary_ref = self.artifacts.put(activation.run_id, "department_summary", checkpoint.summary, media_type="text/plain")
            plan_ref = self.artifacts.put(activation.run_id, "compaction_plan", json_dumps(asdict(plan)), media_type="application/json")
            self.store.append(activation.run_id, EventType.COMPACTION_RECORDED, role=activation.department,
                              parent_event_id=activation.parent_event_id, state_before=current.phase,
                              state_after=current.phase, session_id=activation.session_id,
                              provider=response.provider, model=response.model,
                              context_digest=request.context.manifest.digest,
                              artifact_hashes=[summary_ref.content_hash, plan_ref.content_hash],
                              payload={"run_id": activation.run_id, "department": activation.department,
                                       "activation_id": activation.activation_id, "step_id": request.step_id,
                                       "purpose": "compaction", "checkpoint": asdict(checkpoint),
                                       "source_refs": plan.source_refs, "summary_ref": asdict(summary_ref),
                                       "plan_ref": asdict(plan_ref), "summary_token_limit": plan.summary_token_limit,
                                       "max_output_tokens": plan.max_output_tokens,
                                       "effective_contract_hash": activation.effective_contract_hash,
                                       "engineering_plan_hash": activation.engineering_plan_hash,
                                       "previous_compaction_event_id": request.context.manifest.compaction_event_id})

    def _begin_request(self, activation: _Activation, request: ModelRequest) -> bool:
        with self._state_lock:
            current = self.project(request.run_id)
            if current.phase in TERMINAL_PHASES or request.abort_flag.is_set():
                return False
            if (current_contract_hash(current) != request.effective_contract_hash
                    or current_plan_hash(current) != request.engineering_plan_hash):
                return False
            self.store.append(request.run_id, EventType.MODEL_REQUESTED, role=request.department,
                              parent_event_id=activation.parent_event_id, state_before=current.phase,
                              state_after=current.phase, session_id=request.session_id,
                              context_digest=request.context.manifest.digest,
                              payload={"activation_id": request.activation_id, "step_id": request.step_id,
                                       "attempted": True, "purpose": request.purpose,
                                       "effective_contract_hash": request.effective_contract_hash,
                                       "engineering_plan_hash": request.engineering_plan_hash})
            return True

    def _begin_tool(self, activation: _Activation, call: dict[str, Any]) -> ToolAdmission:
        with self._state_lock:
            request = activation.request
            current = self.project(request.run_id)
            if current.phase in TERMINAL_PHASES or request.abort_flag.is_set():
                return ToolAdmission(stopped=True)
            if (current_contract_hash(current) != activation.effective_contract_hash
                    or current_plan_hash(current) != activation.engineering_plan_hash):
                return ToolAdmission(stopped=True)
            if call["name"] == "write_file":
                plan = current.engineering_plan
                if plan is None or plan.effective_contract_hash != current_contract_hash(current):
                    return ToolAdmission(error="Submit an engineering plan for the current effective contract before writing files.")
                target = call["args"].get("path")
                if not path_in_scope(target, plan.scope):
                    return ToolAdmission(error="The file is outside the current engineering plan scope; submit an adjusted plan with a reason first.")
                workspace = self.workspace(request.run_id)
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
                                       "effective_contract_hash": activation.effective_contract_hash,
                                       "engineering_plan_hash": activation.engineering_plan_hash})
            return ToolAdmission()

    def _record_observation(self, activation: _Activation, observation: ModelObservation) -> None:
        request = activation.request
        with self._state_lock:
            key = (f"{request.step_id}:{observation.kind}", observation.id)
            if key in activation.seen:
                return
            activation.seen.add(key)
            current = self.project(request.run_id)
            if observation.provider:
                activation.provider = observation.provider
            if observation.model:
                activation.model = observation.model
            provider = activation.provider or self.adapter.name
            model = activation.model or self.adapter.model
            if observation.kind == "usage":
                if observation.usage is not None:
                    ref = self.artifacts.put(request.run_id, "model_usage", json_dumps(observation.payload), media_type="application/json")
                    activation.raw_usage_ref = asdict(ref)
                    if observation.usage.reported or observation.usage.total_tokens or observation.usage.cost:
                        activation.step_usage = observation.usage
                        self._record_usage(activation, activation.previous_usage.plus(observation.usage), provider=provider, model=model)
                return
            if observation.kind in {"tool", "skipped_tool"}:
                payload = dict(observation.payload)
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
                activation.messages.append(observation.text)
                message = observation.payload or {"role": "assistant", "content": observation.text}
                ref = self.artifacts.put(request.run_id, "model_message", json_dumps(message), media_type="application/json")
                payload = {
                    "message_ref": asdict(ref),
                    "message_index": len(activation.messages),
                    "response_id": message.get("id"),
                    "stop_reason": message.get("status"),
                    "summary": observation.text[:160],
                }
                event_type = EventType.MODEL_MESSAGE
            else:
                raise ValueError(f"unknown adapter observation: {observation.kind}")
            payload["activation_id"] = request.activation_id
            payload["step_id"] = request.step_id
            payload["purpose"] = request.purpose
            payload["effective_contract_hash"] = activation.effective_contract_hash
            payload["engineering_plan_hash"] = activation.engineering_plan_hash
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

    def _record_usage(self, activation: _Activation, usage: Usage, *, provider: str, model: str) -> None:
        request = activation.request
        token_delta = usage.total_tokens - activation.tokens_charged
        cost_delta = usage.cost - activation.cost_charged
        first = not activation.has_usage
        activation.has_usage = True
        activation.usage = usage
        activation.tokens_charged = usage.total_tokens
        activation.cost_charged = usage.cost
        current = self.project(request.run_id)
        if first or token_delta or cost_delta:
            self.store.append(
                request.run_id, EventType.TOOL_CALLED, role=request.department,
                parent_event_id=activation.parent_event_id,
                state_before=current.phase, state_after=current.phase,
                session_id=request.session_id, provider=provider, model=model,
                payload={
                    "name": "provider_usage", "ok": True,
                    "activation_id": request.activation_id,
                    "step_id": request.step_id,
                    "purpose": request.purpose,
                    "accounting": "activation_total_with_charge_delta",
                    "scope": "observable_main_dialogue",
                    "source": "reported" if usage.reported else "unreported",
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
                },
            )

    def _reconcile_response(self, activation: _Activation, result: ModelResponse) -> None:
        for index, item in enumerate(result.output):
            content = item.get("content") or []
            text = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict)) if isinstance(content, list) else str(content)
            self._record_observation(activation, ModelObservation(
                str(item.get("id") or f"output-{index}"), "message", item, text,
                provider=result.provider, model=result.model,
            ))
        usage = result.usage
        if not usage or not (usage.reported or usage.total_tokens or usage.cost):
            usage = activation.step_usage or Usage(reported=False)
        activation.step_usage = usage
        with self._state_lock:
            self._record_usage(activation, activation.previous_usage.plus(usage), provider=result.provider, model=result.model)

    def _apply_proposal(
        self,
        run_id: str,
        *,
        department: str,
        projection: RunProjection,
        proposal: dict[str, Any] | None,
        transcript_ref: dict[str, Any] | None,
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
    ) -> None:
        snapshot = self.workspace(run_id).snapshot()
        try:
            decision = evaluate_proposal(
                phase=projection.phase,
                department=department,
                proposal=proposal,
                projection=projection,
                snapshot=snapshot,
            )
        except Exception as exc:
            decision = ProposalDecision(
                False,
                [FieldError("proposal", f"invalid proposal payload: {type(exc).__name__}: {exc}")],
            )
        with self._state_lock:
            current = self.project(run_id)
            if current.phase in TERMINAL_PHASES:
                return
            if (current.phase != projection.phase
                    or current_contract_hash(current) != current_contract_hash(projection)
                    or current_plan_hash(current) != current_plan_hash(projection)):
                decision = ProposalDecision(False, [FieldError("execution_basis", "The contract, plan, or current work changed after this activation began; stale results cannot be rebound.")])
            projection = current
            if proposal is not None:
                self.store.append(
                    run_id, EventType.PROPOSAL_SUBMITTED, role=department,
                    parent_event_id=parent_event_id,
                    state_before=projection.phase, state_after=projection.phase,
                    session_id=session_id, provider=provider, model=model,
                    payload={"kind": proposal.get("kind"), "transcript_ref": transcript_ref, "raw_keys": sorted(proposal.keys())},
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
                    },
                )
                return
            self._commit_accepted(
                run_id, department=department, projection=projection,
                artifact=decision.artifact or {}, transitions=decision.transitions, extra=decision.extra,
                parent_event_id=parent_event_id, session_id=session_id, provider=provider, model=model,
            )

    def _commit_accepted(
        self,
        run_id: str,
        *,
        department: str,
        projection: RunProjection,
        artifact: dict[str, Any],
        transitions: list[tuple[str, str]],
        extra: dict[str, Any],
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
    ) -> None:
        if self.project(run_id).phase in TERMINAL_PHASES:
            return
        source_event = self.submissions.commit(
            projection=projection, workspace=self.workspace(run_id), artifact=artifact, extra=extra,
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
            refs = [asdict(ref) for ref in delivery.file_refs] if delivery is not None else []
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
            self.store.append(
                run_id, EventType.RUN_PAUSED, role=projection.active_department,
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

    def _fail(self, run_id: str, projection: RunProjection, reason: str, message: str) -> None:
        human = {
            "provider_unavailable": "模型提供方未配置或不可用。检查模型与 API 配置后新建运行。",
            "provider_error": "模型提供方失败。查看错误事件后新建 run 或更换 provider。",
            "cancelled": "运行已被取消。如需继续，新建 run。",
            "context_overflow": "单次装配的上下文超过窗口。缩小注入内容或提高 context_window 后新建 run。",
            "compaction_failed": "部门历史压缩失败。原始记录仍保留，请查看摘要请求与失败原因后重新运行。",
            "host_commit_error": "主机未能保存本次提交所需的工件、材料或事件。查看失败原因并处理存储或交付文件问题后重新运行。",
        }.get(reason)
        with self._state_lock:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return
            source_event = self.store.append(
                run_id, EventType.RUN_FAILED, role=projection.active_department,
                state_before=projection.phase, state_after="FAILED", stop_reason=reason, error=message,
                provider=projection.provider, model=projection.model,
                payload={"stop_reason": reason, "human_action": human, "message": message},
            )
            self.sessions.close_run(run_id)
            if reason != "cancelled":
                self._record_lesson_candidate(source_event, projection)

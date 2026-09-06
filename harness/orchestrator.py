"""Orchestrator：状态机、停止判定、权限与预算。状态迁移函数内不调用 LLM。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event, RLock
from typing import Any

from .adapters.base import AdapterObservation, AdapterResult, DepartmentAdapter, InvokeRequest, ProviderError
from .artifacts import ArtifactStore
from .context import ContextAssembler
from .event_store import EventStore
from .models import (
    EventType,
    HUMAN_ACTIONS,
    TERMINAL_PHASES,
    Usage,
    department_for_phase,
    estimate_tokens,
    json_dumps,
    new_id,
)
from .projection import RunProjection, project_run
from .sessions import SessionFactory
from .tools import tools_for
from .validation import FieldError, ProposalDecision, evaluate_proposal
from .workspace import Workspace


@dataclass
class _Activation:
    request: InvokeRequest
    parent_event_id: str
    tokens_charged: int
    usage: Usage = field(default_factory=lambda: Usage(reported=False))
    has_usage: bool = False
    cost_charged: float = 0.0
    seen: set[tuple[str, str]] = field(default_factory=set)
    tool_ids: set[str] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        store: EventStore,
        artifacts: ArtifactStore,
        workspace_root: str | Path,
        adapter: DepartmentAdapter,
        assembler: ContextAssembler | None = None,
        sessions: SessionFactory | None = None,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.workspace_root = Path(workspace_root)
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
        token_budget: int = 100_000,
        context_window: int = 32_000,
        run_id: str | None = None,
    ) -> str:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be non-empty")
        if max_cycles < 1:
            raise ValueError("max_cycles must be positive")
        if token_budget < 1:
            raise ValueError("token_budget must be positive")
        if context_window < 1:
            raise ValueError("context_window must be positive")
        run_id = run_id or new_id("run")
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
                "task": task.strip(),
                "max_cycles": max_cycles,
                "token_budget": token_budget,
                "context_window": context_window,
                "provider": getattr(self.adapter, "name", "unknown"),
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
            self.adapter.abort(activation.request.session_id)
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
                request = activation.request
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
        if projection.token_used >= projection.token_budget:
            self._pause(run_id, projection, "budget_exhausted")
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
            payload={"activation_id": activation_id, "cycle": projection.cycle_count + 1},
        )
        projection = self.project(run_id)
        assembled = self.assembler.assemble(
            projection,
            department=department,
            session_id=session.session_id,
            activation_id=activation_id,
        )
        self.store.append(
            run_id,
            EventType.CONTEXT_ASSEMBLED,
            role=department,
            parent_event_id=parent.event_id,
            state_before=projection.phase,
            state_after=projection.phase,
            session_id=session.session_id,
            context_digest=assembled.manifest.digest,
            payload={
                "activation_id": activation_id,
                "session_id": session.session_id,
                "department": department,
                "injected": [item.__dict__ for item in assembled.manifest.injected],
                "excluded": [item.__dict__ for item in assembled.manifest.excluded],
                "token_estimate": assembled.manifest.token_estimate,
                "budget": assembled.manifest.budget,
                "digest": assembled.manifest.digest,
                "truncated": assembled.manifest.truncated,
                "tokens_charged": assembled.manifest.token_estimate,
            },
        )
        if assembled.manifest.token_estimate > projection.context_window:
            self._fail(run_id, projection, "context_overflow", "assembled context exceeds context_window")
            session.idle()
            return None
        if projection.token_used + assembled.manifest.token_estimate > projection.token_budget:
            self._pause(run_id, projection, "budget_exhausted")
            session.idle()
            return None

        workspace = self.workspace(run_id)
        workspace.bind_check(
            activation_id=activation_id,
            product_spec_hash=None if projection.product_spec is None else projection.product_spec.content_hash,
            delivery_spec_hash=None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
        )
        abort_flag = self._abort.setdefault(run_id, Event())
        request = InvokeRequest(
            run_id=run_id,
            department=department,
            session_id=session.session_id,
            activation_id=activation_id,
            context=assembled,
            tools=tools_for(department),
            workspace=workspace,
            abort_flag=abort_flag,
        )
        activation = _Activation(request, parent.event_id, assembled.manifest.token_estimate)
        request.on_observation = lambda observation: self._record_observation(activation, observation)
        return activation

    def _invoke_activation(self, activation: _Activation) -> None:
        request = activation.request
        run_id, department = request.run_id, request.department
        projection = self.project(run_id)
        try:
            result = self.adapter.invoke(request)
        except ProviderError as exc:
            self._observe_diagnostics(activation, exc.diagnostics)
            self._fail(run_id, projection, exc.reason, str(exc))
            return
        except Exception as exc:
            self._fail(run_id, projection, "provider_error", f"{type(exc).__name__}: {exc}")
            return

        self._observe_diagnostics(activation, result.diagnostics)
        self._reconcile_result(activation, result)
        current = self.project(run_id)
        if current.phase in TERMINAL_PHASES:
            return

        transcript_ref = None
        transcript = result.transcript or "\n".join(activation.messages)
        if transcript:
            ref = self.artifacts.put(run_id, "transcript", transcript, media_type="text/plain")
            transcript_ref = ref.__dict__

        if result.finish_reason == "aborted":
            self._fail(run_id, projection, "cancelled", result.error or "adapter aborted")
            return
        if result.finish_reason == "overflow":
            self._fail(run_id, projection, "context_overflow", result.error or "provider context overflow")
            return
        if result.finish_reason == "unavailable":
            self._fail(run_id, projection, "provider_unavailable", result.error or "provider unavailable")
            return
        if result.finish_reason == "error":
            self._fail(run_id, projection, "provider_error", result.error or "provider error")
            return

        self._apply_proposal(
            run_id,
            department=department,
            projection=self.project(run_id),
            proposal=result.proposal,
            transcript_ref=transcript_ref,
            parent_event_id=activation.parent_event_id,
            session_id=request.session_id,
            provider=result.provider,
            model=result.model,
        )

    def _observe_diagnostics(self, activation: _Activation, diagnostics: dict[str, Any] | None) -> None:
        if diagnostics:
            self._record_observation(activation, AdapterObservation("host_launch", "host_launch", diagnostics))

    def _record_observation(self, activation: _Activation, observation: AdapterObservation) -> None:
        request = activation.request
        should_abort = False
        with self._state_lock:
            key = (observation.kind, observation.id)
            if key in activation.seen:
                return
            activation.seen.add(key)
            current = self.project(request.run_id)
            provider = observation.provider or self.adapter.name
            model = observation.model or self.adapter.model
            if observation.kind == "host_launch":
                self._record_host_launch(
                    request.run_id, current, activation.parent_event_id, request.session_id,
                    request.department, request.activation_id, request.context.manifest.digest,
                    observation.payload,
                )
                return
            if observation.kind == "tool":
                payload = dict(observation.payload)
                tool_id = str(payload.get("id") or observation.id)
                if tool_id in activation.tool_ids:
                    return
                activation.tool_ids.add(tool_id)
                payload["id"] = tool_id
                output = payload.pop("output", None)
                if output is not None:
                    ref = self.artifacts.put(request.run_id, "tool_output", json_dumps(output), media_type="application/json")
                    payload["output_ref"] = asdict(ref)
                event_type = EventType.TOOL_CALLED
            elif observation.kind == "message":
                activation.messages.append(observation.text)
                message = observation.payload or {"role": "assistant", "content": observation.text}
                ref = self.artifacts.put(request.run_id, "model_message", json_dumps(message), media_type="application/json")
                payload = {
                    "message_ref": asdict(ref),
                    "message_index": len(activation.messages),
                    "response_id": message.get("responseId"),
                    "stop_reason": message.get("stopReason"),
                    "summary": observation.text[:160],
                }
                event_type = EventType.MODEL_MESSAGE
            else:
                raise ValueError(f"unknown adapter observation: {observation.kind}")
            payload["activation_id"] = request.activation_id
            self.store.append(
                request.run_id, event_type, role=request.department,
                parent_event_id=activation.parent_event_id,
                state_before=current.phase, state_after=current.phase,
                session_id=request.session_id, provider=provider, model=model, payload=payload,
            )
            if observation.usage is not None:
                usage = observation.usage
                if activation.has_usage:
                    usage = activation.usage.plus(usage)
                should_abort = self._charge_usage(activation, usage, provider=provider, model=model)
        if should_abort:
            self.adapter.abort(request.session_id)

    def _charge_usage(self, activation: _Activation, usage: Usage, *, provider: str, model: str) -> bool:
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
                    "accounting": "activation_total_with_charge_delta",
                    "scope": "observable_main_dialogue",
                    "source": "reported" if usage.reported else "estimated_or_mixed",
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
        current = self.project(request.run_id)
        if current.phase not in TERMINAL_PHASES and current.token_used >= current.token_budget:
            self._pause(request.run_id, current, "budget_exhausted")
            request.abort_flag.set()
            return True
        return False

    def _reconcile_result(self, activation: _Activation, result: AdapterResult) -> None:
        for index, call in enumerate(result.tool_calls):
            self._record_observation(
                activation,
                AdapterObservation(str(call.get("id") or f"result-tool-{index}"), "tool", call,
                                   provider=result.provider, model=result.model),
            )
        if result.transcript and not activation.messages:
            self._record_observation(
                activation,
                AdapterObservation("result-message", "message", text=result.transcript,
                                   provider=result.provider, model=result.model),
            )
        usage = result.usage
        if not usage or not (usage.reported or usage.total_tokens or usage.cost):
            if activation.has_usage:
                return
            tokens = activation.request.context.manifest.token_estimate
            output_tokens = estimate_tokens(result.transcript)
            usage = Usage(input_tokens=tokens, output_tokens=output_tokens,
                          total_tokens=tokens + output_tokens, reported=False)
        with self._state_lock:
            should_abort = self._charge_usage(activation, usage, provider=result.provider, model=result.model)
        if should_abort:
            self.adapter.abort(activation.request.session_id)

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
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return
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
        kind = artifact["kind"]
        if kind == "product_spec":
            artifact = dict(artifact)
            artifact["id"] = new_id("spec")
            if projection.product_spec:
                self.store.append(
                    run_id,
                    EventType.SPEC_SUPERSEDED,
                    role=department,
                    parent_event_id=parent_event_id,
                    state_before=projection.phase,
                    state_after=projection.phase,
                    payload={"content_hash": projection.product_spec.content_hash, "revision": projection.product_spec.revision},
                )
            self.store.append(
                run_id,
                EventType.SPEC_ACCEPTED,
                role=department,
                parent_event_id=parent_event_id,
                state_before=projection.phase,
                state_after=projection.phase,
                session_id=session_id,
                provider=provider,
                model=model,
                artifact_hashes=[artifact["content_hash"]],
                payload=artifact,
            )
        elif kind == "ask_request":
            artifact = dict(artifact)
            artifact["id"] = new_id("ask")
            self.store.append(
                run_id,
                EventType.ASK_SUBMITTED,
                role=department,
                parent_event_id=parent_event_id,
                state_before=projection.phase,
                state_after=projection.phase,
                session_id=session_id,
                provider=provider,
                model=model,
                artifact_hashes=[artifact["content_hash"]],
                payload=artifact,
            )
        elif kind == "product_reaction":
            artifact = dict(artifact)
            artifact["id"] = new_id("react")
            new_spec = extra.get("new_spec") or artifact.pop("spec_update", None)
            if new_spec:
                new_spec = dict(new_spec)
                new_spec["id"] = new_id("spec")
                if projection.product_spec:
                    self.store.append(
                        run_id,
                        EventType.SPEC_SUPERSEDED,
                        role=department,
                        parent_event_id=parent_event_id,
                        state_before=projection.phase,
                        state_after=projection.phase,
                        payload={"content_hash": projection.product_spec.content_hash, "revision": projection.product_spec.revision},
                    )
                self.store.append(
                    run_id,
                    EventType.SPEC_ACCEPTED,
                    role=department,
                    parent_event_id=parent_event_id,
                    state_before=projection.phase,
                    state_after=projection.phase,
                    session_id=session_id,
                    artifact_hashes=[new_spec["content_hash"]],
                    payload=new_spec,
                )
                artifact["produces_new_spec"] = True
                artifact["new_spec_hash"] = new_spec["content_hash"]
            artifact.pop("spec_update", None)
            self.store.append(
                run_id,
                EventType.REACT_SUBMITTED,
                role=department,
                parent_event_id=parent_event_id,
                state_before=projection.phase,
                state_after=projection.phase,
                session_id=session_id,
                provider=provider,
                model=model,
                artifact_hashes=[artifact["content_hash"]],
                payload=artifact,
            )
        elif kind == "delivery_spec":
            artifact = dict(artifact)
            artifact["id"] = new_id("del")
            file_refs = []
            workspace = self.workspace(run_id)
            for rel in artifact.get("files", []):
                content = workspace.read_file(rel)
                ref = self.artifacts.put(run_id, "source_file", content, media_type="text/plain")
                file_refs.append(ref.__dict__)
            snapshot_ref = self.artifacts.put(
                run_id,
                "code_snapshot",
                "\n".join(artifact.get("files", []) + [artifact["code_tree_digest"]]),
                media_type="text/plain",
            )
            artifact["file_refs"] = file_refs
            artifact["snapshot_ref"] = snapshot_ref.__dict__
            self.store.append(
                run_id,
                EventType.DELIVERY_ACCEPTED,
                role=department,
                parent_event_id=parent_event_id,
                state_before=projection.phase,
                state_after=projection.phase,
                session_id=session_id,
                provider=provider,
                model=model,
                artifact_hashes=[artifact["content_hash"], snapshot_ref.content_hash],
                payload=artifact,
            )
        elif kind == "qa_review":
            artifact = dict(artifact)
            artifact["id"] = new_id("qa")
            evidence = self.artifacts.put(run_id, "qa_evidence", artifact["rationale"], media_type="text/plain")
            artifact["evidence_refs"] = [evidence.__dict__]
            self.store.append(
                run_id,
                EventType.QA_SUBMITTED,
                role=department,
                parent_event_id=parent_event_id,
                state_before=projection.phase,
                state_after=projection.phase,
                session_id=session_id,
                provider=provider,
                model=model,
                artifact_hashes=[artifact["content_hash"], evidence.content_hash],
                payload=artifact,
            )
        else:
            raise RuntimeError(f"unhandled artifact kind {kind}")

        phase = projection.phase
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
            phase = target
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

    def _record_host_launch(
        self,
        run_id: str,
        projection: RunProjection,
        parent_event_id: str,
        session_id: str,
        department: str,
        activation_id: str,
        context_digest: str,
        diagnostics: dict[str, Any] | None,
    ) -> None:
        if not diagnostics:
            return
        payload = dict(diagnostics)
        payload["host_launch"] = True
        payload["usage_only"] = True
        payload["tokens_charged"] = 0
        payload["run_id"] = run_id
        payload["activation_id"] = activation_id
        payload["session_id"] = session_id
        payload["department"] = department
        payload["digest"] = context_digest
        payload["context_digest"] = context_digest
        self.store.append(
            run_id,
            EventType.CONTEXT_ASSEMBLED,
            role=department,
            parent_event_id=parent_event_id,
            state_before=projection.phase,
            state_after=projection.phase,
            session_id=session_id,
            context_digest=context_digest,
            payload=payload,
        )

    def _pause(self, run_id: str, projection: RunProjection, reason: str) -> None:
        with self._state_lock:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return
            self.store.append(
                run_id, EventType.RUN_PAUSED, role=projection.active_department,
                state_before=projection.phase, state_after="PAUSED", stop_reason=reason,
                payload={
                    "stop_reason": reason,
                    "human_action": HUMAN_ACTIONS[reason],
                    "paused_at_phase": projection.phase,
                    "cycle_count": projection.cycle_count,
                    "max_cycles": projection.max_cycles,
                    "token_used": projection.token_used,
                    "token_budget": projection.token_budget,
                },
            )
            self.sessions.close_run(run_id)

    def _fail(self, run_id: str, projection: RunProjection, reason: str, message: str) -> None:
        human = {
            "provider_unavailable": "OMP 未配置或不可用。配置真实 RPC 后新建 run；不要期望系统改用 fake。",
            "provider_error": "模型提供方失败。查看错误事件后新建 run 或更换 provider。",
            "cancelled": "运行已被取消。如需继续，新建 run。",
            "context_overflow": "单次装配的上下文超过窗口。缩小注入内容或提高 context_window 后新建 run。",
        }.get(reason)
        with self._state_lock:
            projection = self.project(run_id)
            if projection.phase in TERMINAL_PHASES:
                return
            self.store.append(
                run_id, EventType.RUN_FAILED, role=projection.active_department,
                state_before=projection.phase, state_after="FAILED", stop_reason=reason, error=message,
                payload={"stop_reason": reason, "human_action": human, "message": message},
            )
            self.sessions.close_run(run_id)

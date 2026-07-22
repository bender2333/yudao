"""Three-role happy-path work-order loop with mechanical ticket bindings."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from enum import Enum

from .contracts import (
    ROLE_BY_KIND,
    TERMINAL_TO_KIND,
    TERMINAL_TOOL_DEFS,
    TicketLedger,
    TicketValidationError,
    content_hash,
    validate_payload,
)
from .agent_loop import LoopStopped
from .local_tools import LocalToolRuntime
from .role_session import RoleSession
from .workspace import Workspace, diff_manifests

REQUIREMENTS_SYSTEM = (
    "You are the Requirements department. Keep your own private history. "
    "The immutable user request and the newest validated ticket in each handoff "
    "override older memories. Investigate with read-only tools, never edit code, "
    "and end each activation with submit_acceptance."
)
ENGINEERING_SYSTEM = (
    "You are the Engineering department. Keep your own private history and never "
    "assume you can see another department's transcript. The immutable user request "
    "and newest validated acceptance ticket override older memories. Implement and "
    "run registered checks, then end with submit_delivery or submit_clarification."
)
QUALITY_SYSTEM = (
    "You are the Quality department. Keep your own private history and independently "
    "inspect the current code. Do not edit files and do not trust delivery claims "
    "without running registered checks. End with submit_defect or submit_release. "
    "The immutable user request and newest validated tickets override older memories."
)
MAX_TEAM_ACTIVATIONS = 64



class TeamState(str, Enum):
    REQUIREMENTS = "requirements"
    ENGINEERING = "engineering"
    QUALITY = "quality"
    DONE = "done"


@dataclass
class TeamResult:
    outcome: str
    stopped_reason: str
    sessions: dict[str, RoleSession]
    tickets: list[dict]
    transitions: list[str]
    reworks: int
    calls: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    duration_ms: int
    tool_invocations: int
    transient_retry_attempts: int
    content_filter_retries: int
    per_role: dict


_SYSTEM_ERROR_PHASES = frozenset(
    {
        "requirements_activation",
        "engineering_activation",
        "quality_activation",
        "ticket_callback",
        "event_callback",
        "transition_callback",
        "handoff",
        "unknown",
    }
)


def _system_error(phase: str, exc: BaseException) -> str:
    if phase not in _SYSTEM_ERROR_PHASES:
        phase = "unknown"
    return f"system_error:{phase}:{type(exc).__name__}"


_ALLOWED_TERMINALS = {
    "requirements": frozenset({"submit_acceptance"}),
    "engineering": frozenset({"submit_clarification", "submit_delivery"}),
    "quality": frozenset({"submit_defect", "submit_release"}),
}
_TERMINAL_DEFS = {
    definition["function"]["name"]: definition for definition in TERMINAL_TOOL_DEFS
}
_ACCEPTANCE_GROUPS = (
    "requirements",
    "edge_cases",
    "regressions_to_avoid",
    "fatal_conditions",
)


class TicketCollector:
    def __init__(
        self,
        role: str,
        ledger: TicketLedger,
        runtime: LocalToolRuntime,
        workspace: Workspace,
        *,
        acceptance: dict | None = None,
        trigger: dict | None = None,
        before_manifest: list[dict] | None = None,
        open_defects: set[str] | None = None,
        on_ticket=None,
        on_event=None,
        receipt_baseline: dict | None = None,
    ):
        self.role = role
        self.ledger = ledger
        self.runtime = runtime
        self.workspace = workspace
        self.acceptance = acceptance
        self.trigger = trigger
        self.before_manifest = before_manifest
        self.open_defects = set(open_defects or ())
        self.on_ticket = on_ticket
        self.on_event = on_event
        self.receipt_baseline = dict(receipt_baseline or {})
        self.ticket = None

    def handler(self, name: str):
        def collect(**payload):
            try:
                kind = TERMINAL_TO_KIND.get(name)
                if kind is None or name not in _ALLOWED_TERMINALS[self.role]:
                    raise ValueError(f"terminal {name} is not allowed for {self.role}")
                if ROLE_BY_KIND[kind] != self.role:
                    raise ValueError(f"role {self.role} cannot issue {kind}")
                validated = validate_payload(kind, payload)
                bindings, parent_hash = self._bind(kind, validated)
                ticket = self.ledger.issue(
                    kind, self.role, validated, parent_hash, bindings
                )
                self.ledger.verify_chain()
            except (TicketValidationError, ValueError) as error:
                if self.on_event is not None:
                    reason = str(error)
                    field = reason.split("payload field ", 1)[-1].split(" ", 1)[0] if "payload field " in reason else None
                    self.on_event(
                        {
                            "type": "ticket_rejected",
                            "role": self.role,
                            "kind": TERMINAL_TO_KIND.get(name),
                            "error_field": field,
                            "reason": type(error).__name__,
                        }
                    )
                return f"Error: {error}"
            self.ticket = ticket
            if self.on_ticket is not None:
                try:
                    self.on_ticket(copy.deepcopy(ticket))
                except LoopStopped:
                    raise
                except Exception as exc:
                    raise LoopStopped(_system_error("ticket_callback", exc)) from None
            if self.on_event is not None:
                try:
                    self.on_event(
                        {
                            "type": "team_ticket",
                            "kind": kind,
                            "ticket_id": ticket["ticket_id"],
                            "issuer": self.role,
                            "content_hash": ticket["content_hash"],
                            "parent_hash": ticket["parent_hash"],
                        }
                    )
                except LoopStopped:
                    raise
                except Exception as exc:
                    raise LoopStopped(_system_error("event_callback", exc)) from None
            return f"Accepted {ticket['ticket_id']}"

        return collect

    def _bind(self, kind: str, payload: dict) -> tuple[dict, str | None]:
        manifest = self.workspace.tree_manifest()
        tree_hash = self.workspace.tree_hash()
        files = [item["path"] for item in manifest]
        if kind == "acceptance":
            parent_hash = None if not self.ledger.tickets else self.trigger["content_hash"]
            return {"code_tree_hash": tree_hash, "files": files}, parent_hash
        if self.acceptance is None or self.trigger is None:
            raise ValueError("current acceptance and trigger are required")
        if kind == "delivery":
            if self.before_manifest is None:
                raise ValueError("before_manifest is required")
            changed_files = diff_manifests(self.before_manifest, manifest)
            if set(payload["changed_files"]) != set(changed_files):
                raise ValueError("changed_files must exactly match the workspace diff")
            acceptance_ids = _acceptance_ids(self.acceptance)
            mapped_files = set()
            for mapping in payload["requirement_mapping"]:
                if mapping["requirement_id"] not in acceptance_ids:
                    raise ValueError("requirement_mapping contains an unknown acceptance id")
                files_for_id = set(mapping["files"])
                if not files_for_id <= set(changed_files):
                    raise ValueError("requirement_mapping files must be changed_files")
                mapped_files.update(files_for_id)
            if mapped_files != set(changed_files):
                raise ValueError("every changed file must have a requirement mapping")
            checks = self._checks(payload["check_names"], tree_hash)
            return {
                "code_tree_hash": tree_hash,
                "files": files,
                "changed_files": changed_files,
                "checks": checks,
            }, self.trigger["content_hash"]
        if kind == "clarification":
            return {
                "code_tree_hash": tree_hash,
                "files": files,
            }, self.trigger["content_hash"]
        if kind == "release":
            if set(payload["verified_requirements"]) != _acceptance_ids(self.acceptance):
                raise ValueError("verified_requirements must exactly cover acceptance ids")
            if set(payload["closed_defects"]) != self.open_defects:
                raise ValueError("closed_defects must exactly cover open defect ids")
            checks = self._checks(payload["check_names"], tree_hash)
            return {
                "code_tree_hash": tree_hash,
                "files": files,
                "checks": checks,
            }, self.trigger["content_hash"]
        if kind == "defect":
            names = list(
                dict.fromkeys(
                    name
                    for defect in payload["defects"]
                    for name in defect["evidence_check_names"]
                )
            )
            checks = self._checks(names, tree_hash)
            return {
                "code_tree_hash": tree_hash,
                "files": files,
                "checks": checks,
            }, self.trigger["content_hash"]
        raise ValueError(f"unsupported ticket kind: {kind}")

    def _checks(self, names: list[str], tree_hash: str) -> list[dict]:
        checks = []
        for name in names:
            key = (name, tree_hash)
            receipt = self.runtime.receipt(name, tree_hash)
            if receipt is None or receipt is self.receipt_baseline.get(key):
                raise ValueError(f"check_names missing current activation receipt: {name}")
            if receipt.exit_code != 0 or receipt.timed_out:
                raise ValueError(f"check_names check did not pass: {name}")
            checks.append(asdict(receipt))
        return checks


def _acceptance_ids(ticket: dict) -> set[str]:
    payload = ticket["payload"]
    return {
        item["id"]
        for group in _ACCEPTANCE_GROUPS
        for item in payload[group]
    }

def _defect_fingerprint(ticket: dict) -> str:
    return content_hash(
        {
            "route": ticket["payload"]["route"],
            "defects": [
                {key: value for key, value in defect.items() if key != "defect_id"}
                for defect in ticket["payload"]["defects"]
            ],
        }
    )


def _handoff(task: str, acceptance: dict | None, trigger: dict | None, workspace: Workspace) -> str:
    return json.dumps(
        {
            "immutable_task": task,
            "current_acceptance": acceptance,
            "trigger": trigger,
            "code_tree_hash": workspace.tree_hash(),
            "files": [item["path"] for item in workspace.tree_manifest()],
        },
        ensure_ascii=False,
        sort_keys=True,
    )

def run_team(
    llm,
    workspace: Workspace,
    runtime: LocalToolRuntime,
    task_id: str,
    task: str,
    *,
    max_reworks: int = 8,
    max_steps: int = 40,
    on_event=None,
    on_ticket=None,
) -> TeamResult:
    if not isinstance(workspace, Workspace):
        raise TypeError("workspace must be a Workspace")
    if not isinstance(runtime, LocalToolRuntime) or runtime.workspace is not workspace:
        raise ValueError("runtime must use the supplied workspace")
    if type(task_id) is not str or not task_id:
        raise ValueError("task_id must be a non-empty string")
    if type(task) is not str or not task:
        raise ValueError("task must be a non-empty string")
    if type(max_reworks) is not int or max_reworks < 0:
        raise ValueError("max_reworks must be a nonnegative integer")
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")

    terminal_defs = lambda names: [copy.deepcopy(_TERMINAL_DEFS[name]) for name in names]
    sessions = {
        "requirements": RoleSession(
            "requirements", REQUIREMENTS_SYSTEM,
            runtime.tool_defs(False) + terminal_defs(["submit_acceptance"]),
        ),
        "engineering": RoleSession(
            "engineering", ENGINEERING_SYSTEM,
            runtime.tool_defs(True) + terminal_defs(["submit_clarification", "submit_delivery"]),
        ),
        "quality": RoleSession(
            "quality", QUALITY_SYSTEM,
            runtime.tool_defs(False) + terminal_defs(["submit_defect", "submit_release"]),
        ),
    }
    ledger = TicketLedger(task_id)
    transitions = []
    state = TeamState.REQUIREMENTS
    current_acceptance = None
    current_delivery = None
    trigger_ticket = None
    open_defects = {}
    last_defect_fingerprint = None
    consecutive_no_change_deliveries = 0
    reworks = 0
    roles = tuple(sessions)
    usage_fields = ("calls", "prompt_tokens", "completion_tokens", "reasoning_tokens", "llm_duration_ms")
    usage_before = {
        role: {field: copy.deepcopy(getattr(llm, "usage_by_role", {}).get(role, {}).get(field, 0))
               for field in usage_fields}
        for role in roles
    }
    retry_before = getattr(llm, "transient_retry_attempts", getattr(llm, "retry_attempts", 0))
    outcome = "failed"
    stopped_reason = "system_error"
    tool_invocations = 0
    content_filter_retries = 0
    activations = 0

    def external(event: dict) -> None:
        if on_event is None:
            return
        phase_name = (
            "transition_callback"
            if event.get("type") == "team_transition"
            else "event_callback"
        )
        try:
            on_event(event)
        except LoopStopped:
            raise
        except Exception as exc:
            raise LoopStopped(_system_error(phase_name, exc)) from None

    def emit(event: dict) -> None:
        nonlocal tool_invocations, content_filter_retries
        event_type = event.get("type")
        if event_type == "tool_call":
            tool_invocations += 1
        elif event_type == "provider_retry" and event.get("reason") == "content_filter":
            content_filter_retries += 1
        if event_type == "llm_call":
            external(
                {
                    "type": "llm_call",
                    "role": state.value,
                    "step": event.get("step"),
                    "failed": bool(event.get("failed")),
                    "finish_reason": event.get("finish_reason", ""),
                }
            )
        elif event_type in {"team_ticket", "team_transition", "ticket_rejected"}:
            external(event)

    def transition(target: TeamState) -> None:
        nonlocal state
        label = f"{state.value}->{target.value}"
        transitions.append(label)
        state = target
        emit({"type": "team_transition", "transition": label})

    try:
        while state is not TeamState.DONE:
            role = state.value
            engineering_before_manifest = workspace.tree_manifest() if state is TeamState.ENGINEERING else None
            receipt_baseline = dict(runtime.receipts)
            collector = TicketCollector(
                role, ledger, runtime, workspace,
                acceptance=current_acceptance,
                trigger=trigger_ticket,
                before_manifest=engineering_before_manifest,
                open_defects=set(open_defects),
                receipt_baseline=receipt_baseline,
                on_ticket=on_ticket,
                on_event=emit,
            )
            terminals = _ALLOWED_TERMINALS[role]
            terminal_handlers = {name: collector.handler(name) for name in terminals}

            def dispatch_tool(name, args):
                if name in terminal_handlers:
                    return terminal_handlers[name](**args)
                return runtime.dispatch(name, args)
            phase = "handoff"
            handoff = _handoff(task, current_acceptance, trigger_ticket, workspace)

            loop = None
            for activate_number in (1, 2):
                if activations >= MAX_TEAM_ACTIVATIONS:
                    stopped_reason = "stalled"
                    break
                collector.receipt_baseline = dict(runtime.receipts)
                activations += 1
                external(
                    {
                        "type": "role_activation",
                        "role": role,
                        "activate": sessions[role].activates + 1,
                        "tree_hash": workspace.tree_hash(),
                    }
                )
                phase = f"{role}_activation"
                loop = sessions[role].activate(
                    handoff,
                    llm=llm,
                    dispatch_tool=dispatch_tool,
                    max_steps=max_steps,
                    terminal_tools=set(terminals),
                    on_event=emit,
                )
                if loop.stopped_reason == "terminal" and collector.ticket is not None:
                    break
                if loop.stopped_reason not in {"natural", "terminal"}:
                    stopped_reason = loop.stopped_reason
                    break
                if activate_number == 2:
                    stopped_reason = "role_incomplete"
                    break
                handoff = json.dumps(
                    {
                        "correction": "A legal terminal ticket is required.",
                        "role": role,
                        "expected_allowed_terminal": sorted(terminals),
                        "last_stop": loop.stopped_reason,
                        "immutable_task": task,
                        "current_acceptance": current_acceptance,
                        "trigger": trigger_ticket,
                        "code_tree_hash": workspace.tree_hash(),
                        "files": [item["path"] for item in workspace.tree_manifest()],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            if loop is None or loop.stopped_reason != "terminal" or collector.ticket is None:
                break

            ticket = collector.ticket
            trigger_ticket = ticket
            if state is TeamState.REQUIREMENTS and ticket["kind"] == "acceptance":
                current_acceptance = ticket
                consecutive_no_change_deliveries = 0
                transition(TeamState.ENGINEERING)
            elif state is TeamState.ENGINEERING and ticket["kind"] == "clarification":
                transition(TeamState.REQUIREMENTS)
            elif state is TeamState.ENGINEERING and ticket["kind"] == "delivery":
                current_delivery = ticket
                if ticket["bindings"]["changed_files"]:
                    consecutive_no_change_deliveries = 0
                else:
                    consecutive_no_change_deliveries += 1
                    if consecutive_no_change_deliveries >= 2:
                        stopped_reason = "stalled"
                        break
                transition(TeamState.QUALITY)
            elif state is TeamState.QUALITY and ticket["kind"] == "release":
                open_defects.clear()
                transition(TeamState.DONE)
                outcome = "done"
                stopped_reason = "done"
            elif state is TeamState.QUALITY and ticket["kind"] == "defect":
                reworks += 1
                open_defects[ticket["ticket_id"]] = ticket
                fingerprint = content_hash(
                    {
                        "acceptance": current_acceptance["content_hash"],
                        "tree": workspace.tree_hash(),
                        "defect": _defect_fingerprint(ticket),
                    }
                )
                if fingerprint == last_defect_fingerprint:
                    stopped_reason = "stalled"
                    break
                last_defect_fingerprint = fingerprint
                if reworks > max_reworks:
                    stopped_reason = "max_reworks"
                    break
                route = ticket["payload"]["route"]
                transition(TeamState.REQUIREMENTS if route == "requirements" else TeamState.ENGINEERING)
            else:
                stopped_reason = "unexpected_terminal"
                break
    except LoopStopped as exc:
        stopped_reason = exc.reason
    except Exception as exc:
        stopped_reason = _system_error(phase, exc)

    usage_after = getattr(llm, "usage_by_role", {})
    per_role = {}
    for role, session in sessions.items():
        metric = {
            field: usage_after.get(role, {}).get(field, 0) - usage_before[role][field]
            for field in usage_fields
        }
        metric.update(
            activates=session.activates,
            message_count=len(session.messages),
            message_chars=sum(len(str(message.get("content") or "")) for message in session.messages),
            duration_ms=metric["llm_duration_ms"],
        )
        per_role[role] = metric
    retry_after = getattr(llm, "transient_retry_attempts", getattr(llm, "retry_attempts", 0))
    totals = {field: sum(per_role[role][field] for role in roles) for field in usage_fields}
    try:
        external({"type": "team_stop", "reason": stopped_reason, "outcome": outcome})
    except LoopStopped as exc:
        stopped_reason = exc.reason
        outcome = "failed"
    return TeamResult(
        outcome=outcome,
        stopped_reason=stopped_reason,
        sessions=sessions,
        tickets=ledger.tickets,
        transitions=transitions,
        reworks=reworks,
        calls=totals["calls"],
        prompt_tokens=totals["prompt_tokens"],
        completion_tokens=totals["completion_tokens"],
        reasoning_tokens=totals["reasoning_tokens"],
        duration_ms=totals["llm_duration_ms"],
        tool_invocations=tool_invocations,
        transient_retry_attempts=retry_after - retry_before,
        content_filter_retries=content_filter_retries,
        per_role=per_role,
    )

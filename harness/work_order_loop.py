"""三部门基础 harness 的确定性状态机。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Any

from .contracts import ContractError, Ticket


Role = str
Agent = Callable[[Role, dict[str, Any]], Ticket]


@dataclass
class LoopEvent:
    type: str
    role: Role
    detail: str = ""


@dataclass
class LoopResult:
    outcome: str
    stopped_reason: str
    transitions: list[str]
    tickets: list[Ticket]
    events: list[LoopEvent] = field(default_factory=list)


def run_three_department_loop(task: str, agent: Agent, *, max_cycles: int = 8) -> LoopResult:
    """运行需求、开发、质检闭环；路由和停止条件完全由控制层决定。"""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be non-empty")
    if max_cycles < 1:
        raise ValueError("max_cycles must be positive")

    role: Role = "requirements"
    acceptance_ticket: Ticket | None = None
    delivery_ticket: Ticket | None = None
    tickets: list[Ticket] = []
    transitions: list[str] = []
    events: list[LoopEvent] = [LoopEvent("loop_started", role)]

    for _ in range(max_cycles):
        context = {
            "task": task,
            "acceptance": acceptance_ticket,
            "delivery": delivery_ticket,
            "history": tuple(tickets),
        }
        events.append(LoopEvent("role_started", role))
        try:
            ticket = agent(role, context)
            if not isinstance(ticket, Ticket) or ticket.issuer != role:
                raise ContractError("agent returned a ticket for the wrong role")
        except Exception as exc:
            events.append(LoopEvent("loop_stopped", role, f"contract_error:{type(exc).__name__}"))
            return LoopResult("failed", "contract_error", transitions, tickets, events)

        tickets.append(ticket)
        events.append(LoopEvent("ticket_accepted", role, ticket.kind))
        previous = role
        if role == "requirements" and ticket.kind == "acceptance":
            acceptance_ticket = ticket
            role = "engineering"
        elif role == "engineering" and ticket.kind == "clarification":
            role = "requirements"
        elif role == "engineering" and ticket.kind == "delivery":
            delivery_ticket = ticket
            role = "quality"
        elif role == "quality" and ticket.kind == "defect":
            role = ticket.payload["route"]
        elif role == "quality" and ticket.kind == "release":
            transitions.append(f"{previous}->done")
            events.append(LoopEvent("loop_stopped", role, "released"))
            return LoopResult("done", "released", transitions, tickets, events)
        else:
            events.append(LoopEvent("loop_stopped", role, "unexpected_ticket"))
            return LoopResult("failed", "unexpected_ticket", transitions, tickets, events)
        transitions.append(f"{previous}->{role}")
        events.append(LoopEvent("transition", role, f"{previous}->{role}"))

    events.append(LoopEvent("loop_stopped", role, "max_cycles"))
    return LoopResult("failed", "max_cycles", transitions, tickets, events)

"""Private, persistent conversation history for one work-order role."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from .agent_loop import LoopResult, run_agent_loop
from .llm import LlmClient


@dataclass
class RoleSession:
    role: str
    system: str
    tools: list[dict]
    messages: list[dict] = field(default_factory=list, init=False)
    activates: int = 0

    def __post_init__(self) -> None:
        if type(self.role) is not str:
            raise TypeError("role must be a non-empty string")
        if not self.role.strip():
            raise ValueError("role must be a non-empty string")
        if type(self.system) is not str:
            raise TypeError("system must be a non-empty string")
        if not self.system.strip():
            raise ValueError("system must be a non-empty string")
        if type(self.tools) is not list:
            raise TypeError("tools must be a list")
        self.tools = deepcopy(self.tools)
        self.messages.append({"role": "system", "content": self.system})

    def activate(
        self,
        user_turn: str,
        *,
        llm: LlmClient,
        handlers_ctx: str,
        max_steps: int = 40,
        on_event=None,
        terminal_tools: set[str] | None = None,
        extra_handlers: dict | None = None,
    ) -> LoopResult:
        if type(user_turn) is not str:
            raise TypeError("user_turn must be a non-empty string")
        if not user_turn.strip():
            raise ValueError("user_turn must be a non-empty string")
        if type(handlers_ctx) is not str:
            raise TypeError("handlers_ctx must be a string")
        if type(max_steps) is not int:
            raise TypeError("max_steps must be a positive integer")
        if max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")

        self.activates += 1
        return run_agent_loop(
            llm=llm,
            system=self.system,
            user=user_turn,
            tools=self.tools,
            handlers_ctx=handlers_ctx,
            max_steps=max_steps,
            on_event=on_event,
            terminal_tools=terminal_tools,
            extra_handlers=extra_handlers,
            accounting_role=self.role,
            messages=self.messages,
        )

"""进程内选用状态、测试队列与序号；不依赖应用层或事件存储。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Condition, Event, RLock
from typing import Any


@dataclass(eq=False)
class SelectionAttempt:
    provider_id: str
    model_id: str
    model: str
    sequence: int
    status: str = "completing"
    missing: list[str] = field(default_factory=list)
    error: str | None = None
    cancelled: Event = field(default_factory=Event)
    attempts: set[str] = field(default_factory=set)

    def __contains__(self, _attempt_id: str) -> bool:
        # stream_invocation 在登记实际请求后再次检查，取消不会丢在登记前后的间隙。
        return self.cancelled.is_set()

    def public(self) -> dict[str, Any]:
        return {**{name: getattr(self, name) for name in
                   ("provider_id", "model_id", "model", "sequence", "status", "error")},
                "missing": list(self.missing)}


class SelectionFlow:
    def __init__(self, lock: RLock, cancel: Callable[[str], bool]) -> None:
        self._condition = Condition(lock)
        self._cancel = cancel
        self._sequence = 0
        self._current: dict[str, SelectionAttempt] = {}
        self._running: set[SelectionAttempt] = set()

    def current(self, model_id: str) -> SelectionAttempt | None:
        with self._condition:
            return self._current.get(model_id)

    def begin(self, provider_id: str, model_id: str, model: str) -> SelectionAttempt:
        with self._condition:
            self.cancel(model_id)
            self._sequence += 1
            selected = SelectionAttempt(provider_id, model_id, model, self._sequence)
            self._current[model_id] = selected
            return selected

    def is_current(self, selected: SelectionAttempt) -> bool:
        with self._condition:
            return self._current.get(selected.model_id) is selected and not selected.cancelled.is_set()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._condition:
            return [item.public() for item in self._current.values()]

    def acquire(self, selected: SelectionAttempt, limit: Callable[[], int]) -> bool:
        with self._condition:
            while self.is_current(selected):
                waiting = [item for item in self._current.values() if item.status == "waiting"]
                if waiting and waiting[0] is selected and len(self._running) < limit():
                    self._running.add(selected)
                    selected.status = "testing"
                    self._condition.notify_all()
                    return True
                self._condition.wait()
            return False

    def release(self, selected: SelectionAttempt) -> None:
        with self._condition:
            self._running.discard(selected)
            self._condition.notify_all()

    def cancel(self, model_id: str) -> None:
        with self._condition:
            selected = self._current.pop(model_id, None)
            if selected is not None:
                selected.cancelled.set()
                for attempt_id in tuple(selected.attempts):
                    self._cancel(attempt_id)
            self._condition.notify_all()

    def cancel_all(self) -> None:
        with self._condition:
            for model_id in tuple(self._current):
                self.cancel(model_id)

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def finish(self, selected: SelectionAttempt, result: dict[str, Any]) -> bool:
        with self._condition:
            if not self.is_current(selected):
                return False
            if result.get("admitted"):
                del self._current[selected.model_id]
            else:
                selected.status = "failed"
                selected.error = result.get("error")
            return True

# 进程内选用状态、测试队列与序号；不依赖应用层或事件存储。
# 候选测试与选用后的模型测试共用同一份同时测试上限与等待顺序（docs/design/model-management.md「模型访问定义与准入」中「候选测试」）。
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from threading import Condition, Event, RLock
from typing import Any


@dataclass(frozen=True)
class ProviderChange:
    provider_id: str
    version: int
    retest: bool
    connection_test: bool


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


@dataclass(eq=False)
class CandidateTest:
    # 一次候选测试的进程内状态：等待测试、测试中、通过或未通过，以及与结果一起返回的事实。
    # 参数是提交测试时「选用会得到的值」，测试过程不保存模型访问定义，也不写准入。
    provider_id: str
    model: str
    sequence: int
    protocol: str
    context_window: int
    max_output_tokens: int
    input_modalities: tuple[str, ...]
    status: str = "waiting"
    elapsed_ms: int | None = None
    actual_model: str | None = None
    accepts_required_tool_call: bool | None = None
    failure_group: str | None = None
    failure_step: str | None = None
    error: str | None = None
    cancelled: Event = field(default_factory=Event)
    attempts: set[str] = field(default_factory=set)

    def __contains__(self, _attempt_id: str) -> bool:
        # 与选用测试同一处理：取消以后已经登记的实际请求也按取消处理。
        return self.cancelled.is_set()

    def public(self) -> dict[str, Any]:
        return {**{name: getattr(self, name) for name in
                   ("sequence", "status", "elapsed_ms", "actual_model", "accepts_required_tool_call",
                    "failure_group", "failure_step", "error")}}


class SelectionFlow:
    def __init__(self, lock: RLock, cancel: Callable[[str], bool]) -> None:
        self._condition = Condition(lock)
        self._cancel = cancel
        self._sequence = 0
        self._current: dict[str, SelectionAttempt] = {}
        self._candidate_tests: dict[tuple[str, str], CandidateTest] = {}
        self._running: set[SelectionAttempt | CandidateTest] = set()

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

    def candidate(self, provider_id: str, model: str) -> CandidateTest | None:
        with self._condition:
            return self._candidate_tests.get((provider_id, model))

    def begin_candidate(self, provider_id: str, model: str, *, protocol: str, context_window: int,
                        max_output_tokens: int, input_modalities: Sequence[str]) -> CandidateTest:
        # 新的候选测试取代同一个候选上一次的测试与结果；序号与选用共用，等待顺序按它排。
        with self._condition:
            self.cancel_candidate(provider_id, model)
            self._sequence += 1
            test = CandidateTest(provider_id, model, self._sequence, protocol, context_window,
                                 max_output_tokens, tuple(input_modalities))
            self._candidate_tests[(provider_id, model)] = test
            return test

    def candidate_snapshot(self, provider_id: str) -> dict[str, dict[str, Any]]:
        with self._condition:
            return {model: test.public()
                    for (owner, model), test in self._candidate_tests.items() if owner == provider_id}

    def is_current_candidate(self, test: CandidateTest) -> bool:
        with self._condition:
            return self._is_live_candidate(test)

    def _is_live_candidate(self, test: CandidateTest) -> bool:
        return (self._candidate_tests.get((test.provider_id, test.model)) is test
                and not test.cancelled.is_set())

    def acquire(self, job: SelectionAttempt | CandidateTest, limit: Callable[[], int]) -> bool:
        # 一个测试开始：排队中的第一个且名额未满时进入测试中，否则一直等到名额释放或这次测试被取消。
        with self._condition:
            while self._is_live(job):
                queued = self._queued()
                if queued and queued[0] is job and len(self._running) < limit():
                    self._running.add(job)
                    job.status = "testing"
                    self._condition.notify_all()
                    return True
                self._condition.wait()
            return False

    def _queued(self) -> list[SelectionAttempt | CandidateTest]:
        # 选用测试与候选测试合起来按提交的先后排队，同时测试的上限对两者一起计算。
        queued = [item for item in self._current.values() if item.status == "waiting"]
        queued.extend(item for item in self._candidate_tests.values() if item.status == "waiting")
        queued.sort(key=lambda item: item.sequence)
        return queued

    def _is_live(self, job: SelectionAttempt | CandidateTest) -> bool:
        if isinstance(job, CandidateTest):
            return self._is_live_candidate(job)
        return self.is_current(job)

    def release(self, job: SelectionAttempt | CandidateTest) -> None:
        with self._condition:
            self._running.discard(job)
            self._condition.notify_all()

    def cancel(self, model_id: str) -> None:
        with self._condition:
            selected = self._current.pop(model_id, None)
            if selected is not None:
                selected.cancelled.set()
                for attempt_id in tuple(selected.attempts):
                    self._cancel(attempt_id)
            self._condition.notify_all()

    def cancel_candidate(self, provider_id: str, model: str) -> None:
        with self._condition:
            test = self._candidate_tests.pop((provider_id, model), None)
            if test is not None:
                test.cancelled.set()
                for attempt_id in tuple(test.attempts):
                    self._cancel(attempt_id)
            self._condition.notify_all()

    def clear_candidates(self, provider_id: str) -> None:
        # 重新获取这个连接的模型列表：候选连同它们的测试状态与结果一起清除。
        with self._condition:
            for provider, model in [key for key in self._candidate_tests if key[0] == provider_id]:
                self.cancel_candidate(provider, model)

    def cancel_all(self) -> None:
        with self._condition:
            for model_id in tuple(self._current):
                self.cancel(model_id)
            for provider, model in tuple(self._candidate_tests):
                self.cancel_candidate(provider, model)

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

    def finish_candidate(self, test: CandidateTest, result: dict[str, Any]) -> bool:
        # 结果到达时这次测试仍在（没有被重新获取模型列表或服务重启清掉）才写进状态。
        with self._condition:
            if not self._is_live_candidate(test):
                return False
            passed = bool(result.get("ok"))
            test.status = "passed" if passed else "failed"
            test.elapsed_ms = result.get("elapsed_ms")
            test.actual_model = result.get("model") if passed else None
            test.accepts_required_tool_call = result.get("accepts_required_tool_call") if passed else None
            test.failure_group = result.get("failure_group")
            test.failure_step = result.get("failure_step")
            test.error = result.get("error")
            self._condition.notify_all()
            return True

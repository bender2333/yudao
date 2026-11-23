# 核验是同一成果版本上独立角色的证据组合；路由和裁决共用它。
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, IntEnum


class Signal(IntEnum):
    PENDING = 0
    CANNOT_VERIFY = 1
    RELEASE = 2
    REWORK = 3


class FeedbackPhase(Enum):
    OPEN_LOOP = "open_loop"
    VERIFYING = "verifying"
    REWORK = "rework"
    RELEASED = "released"


@dataclass(frozen=True)
class ReviewSignal:
    role: str
    outcome_hash: str
    signal: Signal


@dataclass(frozen=True)
class Feedback:
    outcome_hash: str
    ports: tuple[tuple[str, Signal], ...]

    @classmethod
    def for_outcome(cls, outcome_hash: str, verifiers: Iterable[str]) -> Feedback:
        return cls(outcome_hash, tuple(dict.fromkeys(verifiers, Signal.PENDING).items()))

    def observe(self, reports: Iterable[ReviewSignal]) -> Feedback:
        # 每个角色只更新自己的位置；同一版本的打回不能被后来的放行覆盖。
        ports = dict(self.ports)
        for report in reports:
            if report.outcome_hash == self.outcome_hash and report.role in ports:
                ports[report.role] = max(ports[report.role], report.signal)
        return Feedback(self.outcome_hash, tuple(ports.items()))

    @property
    def phase(self) -> FeedbackPhase:
        if not self.ports:
            return FeedbackPhase.OPEN_LOOP
        signals = [signal for _, signal in self.ports]
        if Signal.REWORK in signals:
            return FeedbackPhase.REWORK
        if all(signal == Signal.RELEASE for signal in signals):
            return FeedbackPhase.RELEASED
        return FeedbackPhase.VERIFYING

    @property
    def pending(self) -> frozenset[str]:
        if self.phase != FeedbackPhase.VERIFYING:
            return frozenset()
        return frozenset(role for role, signal in self.ports if signal < Signal.RELEASE)

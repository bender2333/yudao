"""基础工单合同：控制层只接受结构化、可验证的部门交接。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

ROLES = ("requirements", "engineering", "quality")
ALLOWED_KINDS = {
    "requirements": {"acceptance"},
    "engineering": {"delivery", "clarification"},
    "quality": {"release", "defect"},
}


class ContractError(ValueError):
    """工单不符合当前部门合同。"""


def content_hash(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Ticket:
    kind: str
    issuer: str
    payload: dict[str, Any]
    parent_hash: str | None = None

    def __post_init__(self) -> None:
        if self.issuer not in ROLES:
            raise ContractError("unknown issuer")
        if self.kind not in ALLOWED_KINDS[self.issuer]:
            raise ContractError(f"{self.issuer} cannot issue {self.kind}")
        if not isinstance(self.payload, dict) or not self.payload:
            raise ContractError("payload must be a non-empty object")

    @property
    def content_hash(self) -> str:
        return content_hash({"kind": self.kind, "issuer": self.issuer, "payload": self.payload, "parent_hash": self.parent_hash})


def acceptance(summary: str, criteria: list[str]) -> Ticket:
    if not summary.strip() or not criteria or any(not item.strip() for item in criteria):
        raise ContractError("acceptance requires summary and criteria")
    return Ticket("acceptance", "requirements", {"summary": summary, "criteria": criteria})


def delivery(summary: str, evidence: list[str]) -> Ticket:
    if not summary.strip() or not evidence or any(not item.strip() for item in evidence):
        raise ContractError("delivery requires summary and evidence")
    return Ticket("delivery", "engineering", {"summary": summary, "evidence": evidence})


def clarification(question: str) -> Ticket:
    if not question.strip():
        raise ContractError("clarification requires question")
    return Ticket("clarification", "engineering", {"question": question})


def defect(route: str, reason: str) -> Ticket:
    if route not in ("requirements", "engineering") or not reason.strip():
        raise ContractError("defect requires a route and reason")
    return Ticket("defect", "quality", {"route": route, "reason": reason})


def release(evidence: list[str]) -> Ticket:
    if not evidence or any(not item.strip() for item in evidence):
        raise ContractError("release requires evidence")
    return Ticket("release", "quality", {"evidence": evidence})

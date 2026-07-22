import copy
import hashlib
import json
from dataclasses import dataclass, field


SCHEMA_VERSION = 1
ROLE_BY_KIND = {
    "acceptance": "requirements",
    "clarification": "engineering",
    "delivery": "engineering",
    "defect": "quality",
    "release": "quality",
    "solo_done": "solo",
}
PREFIX_BY_KIND = {
    "acceptance": "A",
    "clarification": "C",
    "delivery": "L",
    "defect": "D",
    "release": "R",
    "solo_done": "S",
}


class TicketValidationError(ValueError):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def validate_payload(kind: str, payload: object) -> dict:
    if kind not in ROLE_BY_KIND:
        raise TicketValidationError("unknown ticket kind")
    if not isinstance(payload, dict):
        raise TicketValidationError("payload must be a dict")
    if kind == "acceptance":
        fields = {
            "summary": str,
            "requirements": list,
            "edge_cases": list,
            "regressions_to_avoid": list,
            "fatal_conditions": list,
            "constraints": list,
            "non_goals": list,
            "clarification_responses": list,
        }
        for name, expected_type in fields.items():
            if not isinstance(payload.get(name), expected_type):
                raise TicketValidationError(f"acceptance payload field {name} has invalid type")
    return copy.deepcopy(payload)


def verify_ticket(ticket: object) -> None:
    if not isinstance(ticket, dict):
        raise TicketValidationError("ticket must be a dict")
    required = {
        "schema_version",
        "kind",
        "ticket_id",
        "task_id",
        "issuer",
        "revision",
        "parent_hash",
        "bindings",
        "payload",
        "content_hash",
    }
    if set(ticket) != required:
        raise TicketValidationError("ticket fields are incomplete or unknown")
    if type(ticket["schema_version"]) is not int or ticket["schema_version"] != SCHEMA_VERSION:
        raise TicketValidationError("invalid schema_version")
    kind = ticket["kind"]
    if not isinstance(kind, str) or kind not in ROLE_BY_KIND:
        raise TicketValidationError("invalid kind")
    if not isinstance(ticket["issuer"], str) or ticket["issuer"] != ROLE_BY_KIND[kind]:
        raise TicketValidationError("invalid issuer")
    revision = ticket["revision"]
    if type(revision) is not int or revision < 1:
        raise TicketValidationError("invalid revision")
    expected_id = f"{PREFIX_BY_KIND[kind]}-{revision:04d}"
    if not isinstance(ticket["ticket_id"], str) or ticket["ticket_id"] != expected_id:
        raise TicketValidationError("invalid ticket_id prefix or revision")
    if not isinstance(ticket["task_id"], str) or not ticket["task_id"]:
        raise TicketValidationError("invalid task_id")
    parent_hash = ticket["parent_hash"]
    if parent_hash is not None and not isinstance(parent_hash, str):
        raise TicketValidationError("invalid parent_hash")
    if not isinstance(ticket["bindings"], dict):
        raise TicketValidationError("bindings must be a dict")
    validate_payload(kind, ticket["payload"])
    if not isinstance(ticket["content_hash"], str):
        raise TicketValidationError("invalid content_hash type")
    body = {key: value for key, value in ticket.items() if key != "content_hash"}
    if ticket["content_hash"] != content_hash(body):
        raise TicketValidationError("content_hash mismatch")


@dataclass
class TicketLedger:
    task_id: str
    tickets: list[dict] = field(default_factory=list)
    revisions: dict[str, int] = field(default_factory=dict)

    def issue(self, kind, issuer, payload, parent_hash, bindings=None) -> dict:
        validated = validate_payload(kind, payload)
        if ROLE_BY_KIND[kind] != issuer:
            raise TicketValidationError("issuer does not own ticket kind")
        if bindings is None:
            bindings = {}
        if not isinstance(bindings, dict):
            raise TicketValidationError("bindings must be a dict")
        if parent_hash is None:
            if self.tickets or kind != "acceptance":
                raise TicketValidationError("parent_hash may be None only for initial acceptance")
        elif not isinstance(parent_hash, str) or not any(
            ticket["content_hash"] == parent_hash for ticket in self.tickets
        ):
            raise TicketValidationError("parent_hash must reference an existing ticket")

        revision = self.revisions.get(kind, 0) + 1
        body = {
            "schema_version": SCHEMA_VERSION,
            "kind": kind,
            "ticket_id": f"{PREFIX_BY_KIND[kind]}-{revision:04d}",
            "task_id": self.task_id,
            "issuer": issuer,
            "revision": revision,
            "parent_hash": parent_hash,
            "bindings": copy.deepcopy(bindings),
            "payload": validated,
        }
        ticket = {**body, "content_hash": content_hash(body)}
        verify_ticket(ticket)
        self.revisions[kind] = revision
        self.tickets.append(ticket)
        return ticket

    def verify_chain(self) -> None:
        seen_hashes = set()
        revisions = {}
        for index, ticket in enumerate(self.tickets):
            verify_ticket(ticket)
            kind = ticket["kind"]
            expected_revision = revisions.get(kind, 0) + 1
            if ticket["revision"] != expected_revision:
                raise TicketValidationError("invalid revision sequence")
            parent_hash = ticket["parent_hash"]
            if index == 0:
                if kind != "acceptance" or parent_hash is not None:
                    raise TicketValidationError("first ticket must be initial acceptance")
            elif parent_hash not in seen_hashes:
                raise TicketValidationError("parent_hash must reference an earlier ticket")
            revisions[kind] = expected_revision
            seen_hashes.add(ticket["content_hash"])

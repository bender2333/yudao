import copy
import hashlib
import json
import math

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

SUBMIT_ACCEPTANCE = "submit_acceptance"
SUBMIT_CLARIFICATION = "submit_clarification"
SUBMIT_DELIVERY = "submit_delivery"
SUBMIT_DEFECT = "submit_defect"
SUBMIT_RELEASE = "submit_release"
SUBMIT_DONE = "submit_done"

TERMINAL_TO_KIND = {
    SUBMIT_ACCEPTANCE: "acceptance",
    SUBMIT_CLARIFICATION: "clarification",
    SUBMIT_DELIVERY: "delivery",
    SUBMIT_DEFECT: "defect",
    SUBMIT_RELEASE: "release",
    SUBMIT_DONE: "solo_done",
}


def _array(items, min_items=None, unique=False):
    schema = {"type": "array", "items": items}
    if min_items is not None:
        schema["minItems"] = min_items
    if unique:
        schema["uniqueItems"] = True
    return schema


def _object(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_TEXT = {"type": "string", "minLength": 1}
_STRING = {"type": "string"}
_NONEMPTY_UNIQUE_STRINGS = _array(_TEXT, 1, True)
_PATH = {"type": "string", "pattern": r"^(?!/)(?!.*//)(?!.*(?:^|/)\.{1,2}(?:/|$))[^\\:\u0000-\u001f\u007f]+$"}
_PATHS = _array(_PATH, unique=True)
_ACCEPTANCE_ITEM = _object(
    {"id": _TEXT, "behavior": _TEXT, "evidence": _TEXT},
    ["id", "behavior", "evidence"],
)
_INTERPRETATION = _object(
    {"choice": _TEXT, "observable_result": _TEXT},
    ["choice", "observable_result"],
)
_REQUIREMENT_MAPPING = _object(
    {"requirement_id": _TEXT, "files": _PATHS},
    ["requirement_id", "files"],
)
_DEFECT = _object(
    {
        "requirement_ids": _NONEMPTY_UNIQUE_STRINGS,
        "severity": {"type": "string", "enum": ["fatal", "major", "minor"]},
        "reproduction": _array(_TEXT, 1),
        "expected": _TEXT,
        "actual": _TEXT,
        "evidence_check_names": _NONEMPTY_UNIQUE_STRINGS,
    },
    ["requirement_ids", "severity", "reproduction", "expected", "actual", "evidence_check_names"],
)

_PARAMETERS_BY_KIND = {
    "acceptance": _object(
        {
            "summary": _TEXT,
            "requirements": _array(_ACCEPTANCE_ITEM, 1),
            "edge_cases": _array(_ACCEPTANCE_ITEM, 1),
            "regressions_to_avoid": _array(_ACCEPTANCE_ITEM, 1),
            "fatal_conditions": _array(_ACCEPTANCE_ITEM, 1),
            "constraints": _array(_STRING),
            "non_goals": _array(_STRING),
            "clarification_responses": _array(_STRING),
        },
        ["summary", "requirements", "edge_cases", "regressions_to_avoid", "fatal_conditions", "constraints", "non_goals", "clarification_responses"],
    ),
    "clarification": _object(
        {
            "blocked_requirement_ids": _NONEMPTY_UNIQUE_STRINGS,
            "question": _TEXT,
            "interpretations": _array(_INTERPRETATION, 2),
            "why_blocking": _TEXT,
        },
        ["blocked_requirement_ids", "question", "interpretations", "why_blocking"],
    ),
    "delivery": _object(
        {
            "changed_files": _PATHS,
            "requirement_mapping": _array(_REQUIREMENT_MAPPING, 1),
            "check_names": _NONEMPTY_UNIQUE_STRINGS,
            "known_risks": _array(_STRING),
        },
        ["changed_files", "requirement_mapping", "check_names", "known_risks"],
    ),
    "defect": _object(
        {"route": {"type": "string", "enum": ["requirements", "engineering"]}, "defects": _array(_DEFECT, 1)},
        ["route", "defects"],
    ),
    "release": _object(
        {
            "verified_requirements": _NONEMPTY_UNIQUE_STRINGS,
            "check_names": _NONEMPTY_UNIQUE_STRINGS,
            "closed_defects": _array(_STRING, unique=True),
            "decision": {"type": "string", "enum": ["release"]},
        },
        ["verified_requirements", "check_names", "closed_defects", "decision"],
    ),
    "solo_done": _object(
        {"changed_files": _array(_PATH, 1, True), "check_names": _NONEMPTY_UNIQUE_STRINGS, "known_risks": _array(_STRING)},
        ["changed_files", "check_names", "known_risks"],
    ),
}

TERMINAL_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": terminal,
            "description": f"Submit the terminal {kind} work-order payload.",
            "parameters": copy.deepcopy(_PARAMETERS_BY_KIND[kind]),
        },
    }
    for terminal, kind in TERMINAL_TO_KIND.items()
]


class TicketValidationError(ValueError):
    pass


def _ticket_boundary(operation, *args):
    try:
        return operation(*args)
    except TicketValidationError:
        raise
    except (RecursionError, TypeError, ValueError) as exc:
        raise TicketValidationError("ticket is not canonical JSON") from exc


def _validate_json_value(value: object) -> None:
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise TicketValidationError("ticket is not canonical JSON")
    if type(value) is list:
        for item in value:
            _validate_json_value(item)
        return
    if type(value) is dict:
        if not all(type(key) is str for key in value):
            raise TicketValidationError("ticket is not canonical JSON")
        for item in value.values():
            _validate_json_value(item)
        return
    raise TicketValidationError("ticket is not canonical JSON")


def canonical_json(value: object) -> bytes:
    _validate_json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def _fail(field, detail="has invalid value"):
    raise TicketValidationError(f"payload field {field} {detail}")


def _exact_fields(value, fields, field):
    if type(value) is not dict:
        _fail(field, "must be a plain dict")
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing:
        _fail(f"{field}.{sorted(missing)[0]}", "is missing")
    if unknown:
        _fail(f"{field}.{sorted(unknown)[0]}", "is unknown")


def _required_text(value, field):
    if type(value) is not str or not value:
        _fail(field, "must be a non-empty string")


def _string_list(value, field, *, nonempty=False, unique=False):
    if type(value) is not list or (nonempty and not value):
        _fail(field, "must be a non-empty list" if nonempty else "must be a list")
    if any(type(item) is not str for item in value):
        _fail(field, "must contain only strings")
    if unique and len(set(value)) != len(value):
        _fail(field, "must contain unique strings")
    return value


def _unique_ids(value, field, *, nonempty=True):
    _string_list(value, field, nonempty=nonempty, unique=True)
    if any(not item for item in value):
        _fail(field, "must contain non-empty strings")


def _relative_paths(value, field, *, nonempty=False, unique=False):
    _string_list(value, field, nonempty=nonempty, unique=unique)
    for path in value:
        parts = path.split("/")
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or ":" in path
            or any(ord(character) < 32 or ord(character) == 127 for character in path)
            or any(part in ("", ".", "..") for part in parts)
        ):
            _fail(field, "must contain unambiguous relative paths")


def _validate_acceptance(payload):
    groups = {
        "requirements": "R-",
        "edge_cases": "E-",
        "regressions_to_avoid": "G-",
        "fatal_conditions": "F-",
    }
    _required_text(payload["summary"], "summary")
    seen = set()
    for group, prefix in groups.items():
        items = payload[group]
        if type(items) is not list or not items:
            _fail(group, "must be a non-empty list")
        for item in items:
            if type(item) is not dict or set(item) != {"id", "behavior", "evidence"}:
                _fail(group, "items must have exactly id, behavior, and evidence")
            item_id = item["id"]
            if type(item_id) is not str or not item_id.startswith(prefix) or item_id in seen:
                _fail(group, "contains an invalid or duplicate id")
            _required_text(item["behavior"], group)
            _required_text(item["evidence"], group)
            seen.add(item_id)
    for field in ("constraints", "non_goals", "clarification_responses"):
        _string_list(payload[field], field)


def _validate_clarification(payload):
    _unique_ids(payload["blocked_requirement_ids"], "blocked_requirement_ids")
    _required_text(payload["question"], "question")
    _required_text(payload["why_blocking"], "why_blocking")
    items = payload["interpretations"]
    if type(items) is not list or len(items) < 2:
        _fail("interpretations", "must contain at least two items")
    choices = []
    for item in items:
        if type(item) is not dict or set(item) != {"choice", "observable_result"}:
            _fail("interpretations", "items must have exactly choice and observable_result")
        _required_text(item["choice"], "interpretations")
        _required_text(item["observable_result"], "interpretations")
        choices.append(item["choice"])
    if len(set(choices)) != len(choices):
        _fail("interpretations", "choices must be unique")


def _validate_delivery(payload):
    _relative_paths(payload["changed_files"], "changed_files", unique=True)
    mappings = payload["requirement_mapping"]
    if type(mappings) is not list or not mappings:
        _fail("requirement_mapping", "must be a non-empty list")
    seen_requirement_ids = set()
    for item in mappings:
        if type(item) is not dict or set(item) != {"requirement_id", "files"}:
            _fail("requirement_mapping", "items must have exactly requirement_id and files")
        _required_text(item["requirement_id"], "requirement_mapping")
        requirement_id = item["requirement_id"]
        if requirement_id in seen_requirement_ids:
            _fail("requirement_mapping.requirement_id", "must be unique")
        seen_requirement_ids.add(requirement_id)
        _relative_paths(item["files"], "requirement_mapping", unique=True)
    _unique_ids(payload["check_names"], "check_names")
    _string_list(payload["known_risks"], "known_risks")


def _validate_defect(payload):
    if payload["route"] not in ("requirements", "engineering"):
        _fail("route", "must be requirements or engineering")
    defects = payload["defects"]
    fields = {"requirement_ids", "severity", "reproduction", "expected", "actual", "evidence_check_names"}
    if type(defects) is not list or not defects:
        _fail("defects", "must be a non-empty list")
    for item in defects:
        if type(item) is not dict or set(item) != fields:
            _fail("defects", "items have invalid fields")
        _unique_ids(item["requirement_ids"], "defects")
        if item["severity"] not in ("fatal", "major", "minor"):
            _fail("defects", "severity is invalid")
        _string_list(item["reproduction"], "defects", nonempty=True)
        if any(not step for step in item["reproduction"]):
            _fail("defects", "reproduction must contain non-empty strings")
        _required_text(item["expected"], "defects")
        _required_text(item["actual"], "defects")
        _unique_ids(item["evidence_check_names"], "defects")


def _validate_release(payload):
    _unique_ids(payload["verified_requirements"], "verified_requirements")
    _unique_ids(payload["check_names"], "check_names")
    _unique_ids(payload["closed_defects"], "closed_defects", nonempty=False)
    if payload["decision"] != "release":
        _fail("decision", "must be release")


def _validate_done(payload):
    _relative_paths(payload["changed_files"], "changed_files", nonempty=True, unique=True)
    _unique_ids(payload["check_names"], "check_names")
    _string_list(payload["known_risks"], "known_risks")


_PAYLOAD_VALIDATORS = {
    "acceptance": _validate_acceptance,
    "clarification": _validate_clarification,
    "delivery": _validate_delivery,
    "defect": _validate_defect,
    "release": _validate_release,
    "solo_done": _validate_done,
}


def validate_payload(kind: str, payload: object) -> dict:
    if kind not in ROLE_BY_KIND:
        raise TicketValidationError("unknown ticket kind")
    if type(payload) is not dict:
        raise TicketValidationError("payload must be a plain dict")
    fields = set(_PARAMETERS_BY_KIND[kind]["required"])
    _exact_fields(payload, fields, kind)
    _PAYLOAD_VALIDATORS[kind](payload)
    _ticket_boundary(_validate_json_value, payload)
    return _ticket_boundary(copy.deepcopy, payload)


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
    _ticket_boundary(validate_payload, kind, ticket["payload"])
    if not isinstance(ticket["content_hash"], str):
        raise TicketValidationError("invalid content_hash type")
    body = {key: value for key, value in ticket.items() if key != "content_hash"}
    expected_hash = _ticket_boundary(content_hash, body)
    if ticket["content_hash"] != expected_hash:
        raise TicketValidationError("content_hash mismatch")


@dataclass(frozen=True)
class TicketLedger:
    task_id: str
    _tickets: list[dict] = field(default_factory=list, init=False, repr=False)
    _revisions: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise TicketValidationError("invalid task_id")

    @property
    def tickets(self) -> list[dict]:
        return copy.deepcopy(self._tickets)

    @property
    def revisions(self) -> dict[str, int]:
        return copy.deepcopy(self._revisions)

    def issue(self, kind, issuer, payload, parent_hash, bindings=None) -> dict:
        validated = _ticket_boundary(validate_payload, kind, payload)
        if ROLE_BY_KIND[kind] != issuer:
            raise TicketValidationError("issuer does not own ticket kind")
        if bindings is None:
            bindings = {}
        if not isinstance(bindings, dict):
            raise TicketValidationError("bindings must be a dict")
        if parent_hash is None:
            if self._tickets or kind != "acceptance":
                raise TicketValidationError("parent_hash may be None only for initial acceptance")
        elif not isinstance(parent_hash, str) or not any(
            ticket["content_hash"] == parent_hash for ticket in self._tickets
        ):
            raise TicketValidationError("parent_hash must reference an existing ticket")

        revision = self._revisions.get(kind, 0) + 1
        body = {
            "schema_version": SCHEMA_VERSION,
            "kind": kind,
            "ticket_id": f"{PREFIX_BY_KIND[kind]}-{revision:04d}",
            "task_id": self.task_id,
            "issuer": issuer,
            "revision": revision,
            "parent_hash": parent_hash,
            "bindings": _ticket_boundary(copy.deepcopy, bindings),
            "payload": validated,
        }
        ticket = {**body, "content_hash": _ticket_boundary(content_hash, body)}
        verify_ticket(ticket)
        self._revisions[kind] = revision
        self._tickets.append(copy.deepcopy(ticket))
        return copy.deepcopy(ticket)

    def verify_chain(self) -> None:
        seen_hashes = set()
        revisions = {}
        for index, ticket in enumerate(self._tickets):
            verify_ticket(ticket)
            if ticket["task_id"] != self.task_id:
                raise TicketValidationError("ticket task_id does not match ledger task_id")
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

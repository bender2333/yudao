import copy
import json

import pytest

from harness.contracts import (
    TicketLedger,
    TicketValidationError,
    canonical_json,
    content_hash,
    validate_payload,
    verify_ticket,
)


def _valid_acceptance(summary="summary"):
    return {
        "summary": summary,
        "requirements": [{"id": "R-001", "behavior": "write VALUE=42", "evidence": "public_tests"}],
        "edge_cases": [{"id": "E-001", "behavior": "module imports cleanly", "evidence": "public_tests"}],
        "regressions_to_avoid": [{"id": "G-001", "behavior": "existing files remain importable", "evidence": "public_tests"}],
        "fatal_conditions": [{"id": "F-001", "behavior": "tests are not modified", "evidence": "tree manifest"}],
        "constraints": ["standard library only"],
        "non_goals": ["no CLI"],
        "clarification_responses": [],
    }


def test_canonical_json_is_key_order_independent_and_utf8_compact():
    assert canonical_json({"b": "雪", "a": 1}) == '{"a":1,"b":"雪"}'.encode("utf-8")
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_ledger_owns_header_revision_parent_and_hash():
    ledger = TicketLedger(task_id="task-1")
    first = ledger.issue("acceptance", "requirements", _valid_acceptance(), None)
    second = ledger.issue("acceptance", "requirements", _valid_acceptance("revised"), first["content_hash"])
    assert first["ticket_id"] == "A-0001"
    assert second["ticket_id"] == "A-0002"
    assert second["revision"] == 2
    assert second["parent_hash"] == first["content_hash"]
    verify_ticket(first)
    verify_ticket(second)


def test_tamper_hash_fails_and_reordered_ticket_still_verifies():
    ticket = TicketLedger("task-1").issue("acceptance", "requirements", _valid_acceptance(), None)
    reordered = json.loads(json.dumps(ticket, ensure_ascii=False))
    verify_ticket(reordered)
    reordered["payload"]["summary"] = "tampered"
    with pytest.raises(TicketValidationError, match="content_hash"):
        verify_ticket(reordered)


def test_issue_rejects_wrong_issuer_without_mutating_ledger():
    ledger = TicketLedger("task-1")
    with pytest.raises(TicketValidationError, match="issuer"):
        ledger.issue("acceptance", "engineering", _valid_acceptance(), None)
    assert ledger.tickets == []
    assert ledger.revisions == {}


def test_issue_rejects_unknown_kind_bad_parent_and_forward_parent_atomically():
    ledger = TicketLedger("task-1")
    with pytest.raises(TicketValidationError):
        ledger.issue("unknown", "requirements", {}, None)
    with pytest.raises(TicketValidationError, match="parent"):
        ledger.issue("acceptance", "requirements", _valid_acceptance(), "sha256:missing")
    assert ledger.tickets == []
    first = ledger.issue("acceptance", "requirements", _valid_acceptance(), None)
    with pytest.raises(TicketValidationError, match="parent"):
        ledger.issue("acceptance", "requirements", _valid_acceptance("future"), "sha256:future")
    assert ledger.tickets == [first]
    assert ledger.revisions == {"acceptance": 1}


def test_issue_snapshots_payload_and_bindings():
    payload = _valid_acceptance()
    bindings = {"source": ["one"]}
    ticket = TicketLedger("task-1").issue("acceptance", "requirements", payload, None, bindings)
    payload["summary"] = "changed"
    bindings["source"].append("two")
    assert ticket["payload"]["summary"] == "summary"
    assert ticket["bindings"] == {"source": ["one"]}


@pytest.mark.parametrize("field,value", [
    ("schema_version", "1"), ("kind", 1), ("ticket_id", 1), ("task_id", 1),
    ("issuer", 1), ("revision", "1"), ("parent_hash", 1), ("bindings", []),
    ("payload", []), ("content_hash", 1),
])
def test_verify_ticket_rejects_bad_header_types(field, value):
    ticket = TicketLedger("task-1").issue("acceptance", "requirements", _valid_acceptance(), None)
    ticket[field] = value
    with pytest.raises(TicketValidationError):
        verify_ticket(ticket)


def test_verify_ticket_rejects_bad_schema_kind_issuer_prefix_revision_and_task():
    ticket = TicketLedger("task-1").issue("acceptance", "requirements", _valid_acceptance(), None)
    for field, value in (("schema_version", 2), ("kind", "delivery"), ("issuer", "quality"),
                         ("ticket_id", "X-0001"), ("revision", 2), ("task_id", "other")):
        candidate = copy.deepcopy(ticket)
        candidate[field] = value
        with pytest.raises(TicketValidationError):
            verify_ticket(candidate)


def test_acceptance_parent_must_be_none_only_for_first_revision():
    ledger = TicketLedger("task-1")
    first = ledger.issue("acceptance", "requirements", _valid_acceptance(), None)
    with pytest.raises(TicketValidationError, match="parent"):
        ledger.issue("acceptance", "requirements", _valid_acceptance("bad"), None)
    assert ledger.tickets == [first]


def test_non_acceptance_first_ticket_cannot_have_none_parent():
    with pytest.raises(TicketValidationError, match="parent"):
        TicketLedger("task-1").issue("delivery", "engineering", {}, None)


def test_verify_chain_detects_revision_parent_and_hash_tampering():
    def ledger_with_two_tickets():
        ledger = TicketLedger("task-1")
        first = ledger.issue("acceptance", "requirements", _valid_acceptance(), None)
        ledger.issue("acceptance", "requirements", _valid_acceptance("two"), first["content_hash"])
        return ledger

    ledger = ledger_with_two_tickets()
    ledger.verify_chain()
    ledger.tickets[1]["revision"] = 3
    with pytest.raises(TicketValidationError):
        ledger.verify_chain()

    ledger = ledger_with_two_tickets()
    ledger.tickets[1]["parent_hash"] = "sha256:missing"
    ledger.tickets[1]["content_hash"] = content_hash({
        key: value for key, value in ledger.tickets[1].items() if key != "content_hash"
    })
    with pytest.raises(TicketValidationError, match="parent"):
        ledger.verify_chain()

    ledger = ledger_with_two_tickets()
    ledger.tickets[1]["payload"]["summary"] = "tampered"
    with pytest.raises(TicketValidationError, match="content_hash"):
        ledger.verify_chain()


def test_validate_payload_acceptance_requires_basic_structure_and_other_kinds_accept_dict():
    validate_payload("acceptance", _valid_acceptance())
    for key in ("requirements", "edge_cases", "regressions_to_avoid", "fatal_conditions", "constraints", "non_goals", "clarification_responses"):
        bad = _valid_acceptance()
        del bad[key]
        with pytest.raises(TicketValidationError):
            validate_payload("acceptance", bad)
    validate_payload("delivery", {"anything": "allowed for now"})
    with pytest.raises(TicketValidationError):
        validate_payload("delivery", [])

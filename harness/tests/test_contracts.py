import copy
import json
import re
from dataclasses import FrozenInstanceError

import pytest

from harness.contracts import (
    SUBMIT_ACCEPTANCE,
    SUBMIT_CLARIFICATION,
    SUBMIT_DEFECT,
    SUBMIT_DELIVERY,
    SUBMIT_DONE,
    SUBMIT_RELEASE,
    TERMINAL_TOOL_DEFS,
    TERMINAL_TO_KIND,
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


def _valid_clarification():
    return {
        "blocked_requirement_ids": ["R-001"],
        "question": "Which value?",
        "interpretations": [
            {"choice": "A", "observable_result": "41"},
            {"choice": "B", "observable_result": "42"},
        ],
        "why_blocking": "outputs differ",
    }


def _valid_delivery(changed_files=None):
    return {
        "changed_files": ["answer.py"] if changed_files is None else changed_files,
        "requirement_mapping": [{"requirement_id": "R-001", "files": ["answer.py"]}],
        "check_names": ["public_tests"],
        "known_risks": [],
    }


def _valid_defect():
    return {
        "route": "engineering",
        "defects": [{
            "requirement_ids": ["R-001"],
            "severity": "major",
            "reproduction": ["run public_tests"],
            "expected": "exit 0",
            "actual": "exit 1",
            "evidence_check_names": ["public_tests"],
        }],
    }


def _valid_release():
    return {
        "verified_requirements": ["R-001", "E-001", "G-001", "F-001"],
        "check_names": ["public_tests"],
        "closed_defects": [],
        "decision": "release",
    }


def _valid_done():
    return {"changed_files": ["answer.py"], "check_names": ["public_tests"], "known_risks": []}


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


def test_issue_and_public_views_cannot_mutate_ledger_snapshot():
    ledger = TicketLedger("task-1")
    issued = ledger.issue(
        "acceptance", "requirements", _valid_acceptance(), None, {"source": ["one"]}
    )
    snapshot = copy.deepcopy(issued)

    issued["task_id"] = "other"
    issued["payload"]["summary"] = "changed"
    issued["bindings"]["source"].append("two")
    public_tickets = ledger.tickets
    public_tickets[0]["payload"]["summary"] = "changed again"
    public_tickets.append({"fake": "ticket"})
    public_revisions = ledger.revisions
    public_revisions["acceptance"] = 99

    assert ledger.tickets == [snapshot]
    assert ledger.revisions == {"acceptance": 1}
    ledger.verify_chain()


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
        TicketLedger("task-1").issue("delivery", "engineering", _valid_delivery(), None)


def test_verify_chain_detects_revision_parent_and_hash_tampering():
    def ledger_with_two_tickets():
        ledger = TicketLedger("task-1")
        first = ledger.issue("acceptance", "requirements", _valid_acceptance(), None)
        ledger.issue("acceptance", "requirements", _valid_acceptance("two"), first["content_hash"])
        return ledger

    ledger = ledger_with_two_tickets()
    ledger.verify_chain()
    ledger._tickets[1]["revision"] = 3
    with pytest.raises(TicketValidationError):
        ledger.verify_chain()

    ledger = ledger_with_two_tickets()
    ledger._tickets[1]["parent_hash"] = "sha256:missing"
    ledger._tickets[1]["content_hash"] = content_hash({
        key: value for key, value in ledger._tickets[1].items() if key != "content_hash"
    })
    with pytest.raises(TicketValidationError, match="parent"):
        ledger.verify_chain()

    ledger = ledger_with_two_tickets()
    ledger._tickets[1]["payload"]["summary"] = "tampered"
    with pytest.raises(TicketValidationError, match="content_hash"):
        ledger.verify_chain()


def test_verify_chain_rejects_rehashed_ticket_for_another_task():
    ledger = TicketLedger("task-1")
    ledger.issue("acceptance", "requirements", _valid_acceptance(), None)
    ledger._tickets[0]["task_id"] = "task-2"
    ledger._tickets[0]["content_hash"] = content_hash({
        key: value for key, value in ledger._tickets[0].items() if key != "content_hash"
    })

    with pytest.raises(TicketValidationError, match="task_id"):
        ledger.verify_chain()


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["payload", "bindings"])
def test_issue_rejects_nonfinite_json_without_mutating_ledger(field, nonfinite):
    ledger = TicketLedger("task-1")
    payload = _valid_acceptance()
    bindings = {}
    (payload if field == "payload" else bindings)["nonfinite"] = nonfinite

    with pytest.raises(TicketValidationError):
        ledger.issue("acceptance", "requirements", payload, None, bindings)

    assert ledger.tickets == []
    assert ledger.revisions == {}


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_verify_ticket_wraps_nonfinite_json_errors(nonfinite):
    ticket = TicketLedger("task-1").issue(
        "acceptance", "requirements", _valid_acceptance(), None
    )
    ticket["payload"]["nonfinite"] = nonfinite

    with pytest.raises(TicketValidationError):
        verify_ticket(ticket)


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("acceptance", _valid_acceptance()),
        ("clarification", _valid_clarification()),
        ("delivery", _valid_delivery()),
        ("delivery", _valid_delivery([])),
        ("defect", _valid_defect()),
        ("release", _valid_release()),
        ("solo_done", _valid_done()),
    ],
)
def test_validate_payload_accepts_valid_payloads_and_returns_deepcopy(kind, payload):
    validated = validate_payload(kind, payload)
    assert validated == payload
    assert validated is not payload
    for value in validated.values():
        if isinstance(value, list) and value:
            assert value is not payload[next(key for key, item in validated.items() if item is value)]
            break


@pytest.mark.parametrize(
    ("kind", "payload", "error"),
    [
        ("acceptance", {**_valid_acceptance(), "summary": ""}, "summary"),
        ("acceptance", {**_valid_acceptance(), "requirements": []}, "requirements"),
        ("acceptance", {**_valid_acceptance(), "edge_cases": []}, "edge_cases"),
        ("acceptance", {**_valid_acceptance(), "regressions_to_avoid": []}, "regressions_to_avoid"),
        ("acceptance", {**_valid_acceptance(), "fatal_conditions": []}, "fatal_conditions"),
        ("clarification", {**_valid_clarification(), "blocked_requirement_ids": []}, "blocked_requirement_ids"),
        ("clarification", {**_valid_clarification(), "question": ""}, "question"),
        ("clarification", {**_valid_clarification(), "why_blocking": ""}, "why_blocking"),
        ("clarification", {**_valid_clarification(), "interpretations": [{}]}, "interpretations"),
        ("delivery", {**_valid_delivery(), "changed_files": ["../x.py"]}, "changed_files"),
        ("delivery", {**_valid_delivery(), "requirement_mapping": []}, "requirement_mapping"),
        ("delivery", {**_valid_delivery(), "check_names": []}, "check_names"),
        ("defect", {**_valid_defect(), "route": "both"}, "route"),
        ("defect", {**_valid_defect(), "defects": []}, "defects"),
        ("release", {**_valid_release(), "verified_requirements": []}, "verified_requirements"),
        ("release", {**_valid_release(), "check_names": []}, "check_names"),
        ("release", {**_valid_release(), "decision": "pass"}, "decision"),
        ("solo_done", {**_valid_done(), "changed_files": []}, "changed_files"),
        ("solo_done", {**_valid_done(), "check_names": []}, "check_names"),
    ],
)
def test_invalid_payloads_fail_loudly(kind, payload, error):
    with pytest.raises(TicketValidationError, match=error):
        validate_payload(kind, payload)


@pytest.mark.parametrize("kind,factory", [
    ("acceptance", _valid_acceptance), ("clarification", _valid_clarification),
    ("delivery", _valid_delivery), ("defect", _valid_defect),
    ("release", _valid_release), ("solo_done", _valid_done),
])
def test_payloads_require_exact_plain_dict_fields(kind, factory):
    payload = factory()
    missing = next(iter(payload))
    del payload[missing]
    with pytest.raises(TicketValidationError, match=missing):
        validate_payload(kind, payload)
    payload = factory()
    payload["unknown"] = True
    with pytest.raises(TicketValidationError, match="unknown"):
        validate_payload(kind, payload)

    class DictSubclass(dict):
        pass

    with pytest.raises(TicketValidationError, match="payload"):
        validate_payload(kind, DictSubclass(factory()))


@pytest.mark.parametrize("field", ["constraints", "non_goals", "clarification_responses"])
@pytest.mark.parametrize("value", ["text", [1]])
def test_acceptance_string_lists_are_typed_and_may_be_empty(field, value):
    payload = _valid_acceptance()
    payload[field] = value
    with pytest.raises(TicketValidationError, match=field):
        validate_payload("acceptance", payload)
    payload[field] = []
    validate_payload("acceptance", payload)


@pytest.mark.parametrize("group,prefix", [
    ("requirements", "R-"), ("edge_cases", "E-"),
    ("regressions_to_avoid", "G-"), ("fatal_conditions", "F-"),
])
@pytest.mark.parametrize("bad_item", [None, {}, {"id": "X-001", "behavior": "b", "evidence": "e"}, {"id": "R-001", "behavior": "", "evidence": "e"}, {"id": "R-001", "behavior": "b", "evidence": ""}])
def test_acceptance_items_are_exact_and_nonempty(group, prefix, bad_item):
    payload = _valid_acceptance()
    if isinstance(bad_item, dict) and bad_item.get("id", "").startswith("R-"):
        bad_item = {**bad_item, "id": prefix + "001"}
    payload[group] = [bad_item]
    with pytest.raises(TicketValidationError, match=group):
        validate_payload("acceptance", payload)


def test_acceptance_ids_are_globally_unique():
    payload = _valid_acceptance()
    payload["edge_cases"][0]["id"] = "R-001"
    with pytest.raises(TicketValidationError, match="edge_cases"):
        validate_payload("acceptance", payload)


@pytest.mark.parametrize("field", ["blocked_requirement_ids", "check_names", "verified_requirements", "closed_defects"])
def test_declared_unique_string_lists_reject_duplicates(field):
    kind, payload = {
        "blocked_requirement_ids": ("clarification", _valid_clarification()),
        "check_names": ("release", _valid_release()),
        "verified_requirements": ("release", _valid_release()),
        "closed_defects": ("release", _valid_release()),
    }[field]
    payload[field] = ["same", "same"]
    with pytest.raises(TicketValidationError, match=field):
        validate_payload(kind, payload)


def test_clarification_interpretations_require_unique_choices_and_exact_text_fields():
    payload = _valid_clarification()
    payload["interpretations"][1]["choice"] = "A"
    with pytest.raises(TicketValidationError, match="interpretations"):
        validate_payload("clarification", payload)
    for item in ({"choice": "A", "observable_result": ""}, {"choice": "A", "observable_result": "x", "extra": "x"}):
        payload = _valid_clarification()
        payload["interpretations"] = [item, {"choice": "B", "observable_result": "y"}]
        with pytest.raises(TicketValidationError, match="interpretations"):
            validate_payload("clarification", payload)


@pytest.mark.parametrize("path", ["/x.py", "C:/x.py", r"C:\\x.py", r"\\server\\share\\x.py", ".", "a/../x.py", r"a\\x.py", ""])
@pytest.mark.parametrize("kind", ["delivery", "solo_done"])
def test_changed_files_reject_ambiguous_or_nonrelative_paths(kind, path):
    payload = _valid_delivery() if kind == "delivery" else _valid_done()
    payload["changed_files"] = [path]
    with pytest.raises(TicketValidationError, match="changed_files"):
        validate_payload(kind, payload)


@pytest.mark.parametrize("path", ["bad\0name.py", "bad\nname.py", "bad\tname.py", "bad\x7fname.py", "dir/file:stream", "foo:bar"])
@pytest.mark.parametrize("kind,field", [("delivery", "changed_files"), ("delivery", "requirement_mapping"), ("solo_done", "changed_files")])
def test_all_payload_path_fields_reject_controls_del_and_colons(kind, field, path):
    payload = _valid_delivery() if kind == "delivery" else _valid_done()
    if field == "requirement_mapping":
        payload[field][0]["files"] = [path]
    else:
        payload[field] = [path]
    with pytest.raises(TicketValidationError, match=field):
        validate_payload(kind, payload)


def test_all_payload_path_fields_accept_plain_unicode_relative_paths():
    path = "目录/雪人.py"
    delivery = _valid_delivery([path])
    delivery["requirement_mapping"][0]["files"] = [path]
    validate_payload("delivery", delivery)
    validate_payload("solo_done", {**_valid_done(), "changed_files": [path]})


def test_delivery_mapping_files_reject_duplicates():
    payload = _valid_delivery()
    payload["requirement_mapping"][0]["files"] = ["answer.py", "answer.py"]
    with pytest.raises(TicketValidationError, match="requirement_mapping"):
        validate_payload("delivery", payload)


def test_delivery_mapping_validates_each_declared_field_without_cross_ticket_lookup():
    validate_payload("delivery", {**_valid_delivery(), "requirement_mapping": [{"requirement_id": "UNKNOWN", "files": []}]})
    bad_items = [
        {},
        {"requirement_id": "", "files": []},
        {"requirement_id": "R-001", "files": ["../x"]},
        {"requirement_id": "R-001", "files": [], "extra": True},
    ]
    for item in bad_items:
        with pytest.raises(TicketValidationError, match="requirement_mapping"):
            validate_payload("delivery", {**_valid_delivery(), "requirement_mapping": [item]})


def test_defect_items_validate_route_severity_and_evidence():
    for route in ("requirements", "engineering"):
        validate_payload("defect", {**_valid_defect(), "route": route})
    for field, value in (
        ("requirement_ids", []), ("requirement_ids", ["R", "R"]),
        ("severity", "critical"), ("reproduction", []),
        ("expected", ""), ("actual", ""), ("evidence_check_names", []),
        ("evidence_check_names", ["x", "x"]),
    ):
        payload = _valid_defect()
        payload["defects"][0][field] = value
        with pytest.raises(TicketValidationError, match="defects"):
            validate_payload("defect", payload)


@pytest.mark.parametrize("kind,field", [
    ("delivery", "changed_files"), ("delivery", "check_names"),
    ("solo_done", "changed_files"), ("solo_done", "check_names"),
])
def test_file_and_check_lists_are_unique(kind, field):
    payload = _valid_delivery() if kind == "delivery" else _valid_done()
    payload[field] = ["same", "same"]
    with pytest.raises(TicketValidationError, match=field):
        validate_payload(kind, payload)


@pytest.mark.parametrize("kind,factory", [("delivery", _valid_delivery), ("solo_done", _valid_done)])
def test_known_risks_is_a_string_list(kind, factory):
    for value in ("risk", [1]):
        with pytest.raises(TicketValidationError, match="known_risks"):
            validate_payload(kind, {**factory(), "known_risks": value})


def test_terminal_tool_defs_match_mapping_and_expose_only_payload_arguments():
    assert TERMINAL_TO_KIND == {
        SUBMIT_ACCEPTANCE: "acceptance", SUBMIT_CLARIFICATION: "clarification",
        SUBMIT_DELIVERY: "delivery", SUBMIT_DEFECT: "defect",
        SUBMIT_RELEASE: "release", SUBMIT_DONE: "solo_done",
    }
    assert {tool["function"]["name"] for tool in TERMINAL_TOOL_DEFS} == set(TERMINAL_TO_KIND)
    forbidden = {"schema_version", "ticket_id", "task_id", "issuer", "revision", "parent_hash", "bindings", "content_hash", "exit_code", "result_digest", "payload"}

    def keys(value):
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    for tool in TERMINAL_TOOL_DEFS:
        assert tool["type"] == "function"
        parameters = tool["function"]["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        assert set(parameters["properties"]) == set(parameters["required"])
        assert not forbidden.intersection(keys(parameters))


def test_path_schemas_expose_string_unique_items_and_basic_lexical_guards():
    by_kind = {tool["function"]["name"]: tool["function"]["parameters"] for tool in TERMINAL_TOOL_DEFS}
    delivery = by_kind[SUBMIT_DELIVERY]
    done = by_kind[SUBMIT_DONE]
    schemas = [
        delivery["properties"]["changed_files"],
        delivery["properties"]["requirement_mapping"]["items"]["properties"]["files"],
        done["properties"]["changed_files"],
    ]
    for schema in schemas:
        assert schema["uniqueItems"] is True
        assert schema["items"]["type"] == "string"
        pattern = re.compile(schema["items"]["pattern"])
        assert pattern.fullmatch("目录/雪人.py")
        for path in ("/x.py", "a/../x.py", r"a\x.py", "foo:bar", "bad\nname.py"):
            assert pattern.fullmatch(path) is None


@pytest.mark.parametrize("task_id", ["", None, 1])
def test_ledger_rejects_invalid_task_id(task_id):
    with pytest.raises(TicketValidationError, match="invalid task_id"):
        TicketLedger(task_id)


def test_ledger_task_id_is_frozen_after_issue():
    ledger = TicketLedger("task-1")
    issued = ledger.issue("acceptance", "requirements", _valid_acceptance(), None)

    with pytest.raises(FrozenInstanceError):
        ledger.task_id = "task-2"

    assert ledger.tickets == [issued]
    ledger.verify_chain()


@pytest.mark.parametrize("field", ["payload", "bindings"])
@pytest.mark.parametrize("invalid", [("x",), {"x"}, b"x", object(), {1: "x"}])
def test_issue_rejects_non_json_values_without_mutating_ledger(field, invalid):
    ledger = TicketLedger("task-1")
    payload = _valid_acceptance()
    bindings = {}
    (payload if field == "payload" else bindings)["invalid"] = invalid

    error = "invalid" if field == "payload" else "canonical JSON"
    with pytest.raises(TicketValidationError, match=error):
        ledger.issue("acceptance", "requirements", payload, None, bindings)

    assert ledger.tickets == []
    assert ledger.revisions == {}


def test_non_string_key_and_tuple_cannot_collide_with_json_equivalents():
    ledger = TicketLedger("task-1")
    for bindings in ({1: "x"}, {"value": ("x",)}):
        with pytest.raises(TicketValidationError, match="canonical JSON"):
            ledger.issue("acceptance", "requirements", _valid_acceptance(), None, bindings)

    ledger.issue(
        "acceptance", "requirements", _valid_acceptance(), None, {"1": "x", "value": ["x"]}
    )


@pytest.mark.parametrize("invalid", [("x",), {"x"}, b"x", object(), {1: "x"}])
def test_verify_ticket_rejects_forged_non_json_values(invalid):
    ticket = TicketLedger("task-1").issue(
        "acceptance", "requirements", _valid_acceptance(), None
    )
    ticket["bindings"]["invalid"] = invalid

    with pytest.raises(TicketValidationError, match="canonical JSON"):
        verify_ticket(ticket)


def test_issue_preserves_specific_ticket_validation_error():
    ledger = TicketLedger("task-1")
    object.__setattr__(ledger, "task_id", "")

    with pytest.raises(TicketValidationError, match="^invalid task_id$"):
        ledger.issue("acceptance", "requirements", _valid_acceptance(), None)


@pytest.mark.parametrize("field", ["payload", "bindings"])
def test_cyclic_values_are_normalized_to_ticket_validation_error(field):
    cyclic = []
    cyclic.append(cyclic)
    ledger = TicketLedger("task-1")
    payload = _valid_acceptance()
    bindings = {}
    (payload if field == "payload" else bindings)["cyclic"] = cyclic

    error = "cyclic" if field == "payload" else "canonical JSON"
    with pytest.raises(TicketValidationError, match=error):
        ledger.issue("acceptance", "requirements", payload, None, bindings)

    valid = TicketLedger("task-1").issue(
        "acceptance", "requirements", _valid_acceptance(), None
    )
    valid[field]["cyclic"] = cyclic
    error = "cyclic" if field == "payload" else "canonical JSON"
    with pytest.raises(TicketValidationError, match=error):
        verify_ticket(valid)


@pytest.mark.parametrize("field", ["payload", "bindings"])
def test_deep_acyclic_values_are_normalized_without_mutating_ledger(field):
    deep = []
    for _ in range(2000):
        deep = [deep]
    ledger = TicketLedger("task-1")
    payload = _valid_acceptance()
    bindings = {}
    (payload if field == "payload" else bindings)["deep"] = deep

    error = "deep" if field == "payload" else "canonical JSON"
    with pytest.raises(TicketValidationError, match=error):
        ledger.issue("acceptance", "requirements", payload, None, bindings)

    assert ledger.tickets == []
    assert ledger.revisions == {}

    ticket = TicketLedger("task-1").issue(
        "acceptance", "requirements", _valid_acceptance(), None
    )
    ticket[field]["deep"] = deep
    error = "deep" if field == "payload" else "canonical JSON"
    with pytest.raises(TicketValidationError, match=error):
        verify_ticket(ticket)

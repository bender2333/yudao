from dataclasses import asdict, replace

import pytest

from harness.adapters.base import ProviderError
from harness.context import ContextAssembler
from harness.department_prompts import DEFAULT_PROMPTS
from harness.models import DEPARTMENTS, EventType, json_dumps
from harness.projection import project_events
from harness.proposals import delivery_turn, plan_turn, product_spec, review, review_turn
from harness.tests.helpers import happy_script, recorded_context, run_scripted
from harness.tests.test_web import get_json, request, running_server


def rework_script(verdict="rework_engineering"):
    script = [
        product_spec(),
        plan_turn(),
        delivery_turn(),
        review_turn(verdict, "QA reported missing empty-input handling", defects=[
            {"severity": "minor", "summary": "Empty input needs review"},
        ]),
    ]
    if verdict == "rework_product":
        script.append(product_spec(acceptance=["empty input prints an empty line"], change_record={
            "changed": ["Require an empty output line for empty input"], "retained": ["Echo the provided argument"],
            "retired": [], "rationale": "Quality identified missing empty-input behavior.",
        }))
    return [
        *script,
        plan_turn(reason="Address the quality finding under the current product requirements"),
        delivery_turn(summary="handle empty input"),
        review_turn("release", "checked revised delivery"),
    ]


def assert_candidate_does_not_change_execution(system, projection):
    events = system.store.list_events(projection.run_id)
    without_candidates = project_events([
        event for event in events if event.type != EventType.LESSON_CANDIDATE_RECORDED
    ]).to_dict()
    actual = projection.to_dict()
    for field in ("lesson_candidates", "last_event_id", "last_seq"):
        actual.pop(field)
        without_candidates.pop(field)
    assert actual == without_candidates


@pytest.mark.parametrize("verdict", ["rework_engineering", "rework_product"])
def test_qa_candidate_preserves_actual_source_contract_and_evidence(tmp_path, verdict):
    script = rework_script(verdict)
    system, result = run_scripted(tmp_path, script)
    assert result.phase == "DONE"
    assert len(result.lesson_candidates) == 1
    candidate = result.lesson_candidates[0]
    source = system.store.get_event(candidate.source_event_id)
    recorded = system.store.get_event(candidate.created_event_id)
    assert source.type == candidate.source_type == EventType.QA_SUBMITTED
    assert source.run_id == candidate.run_id == result.run_id
    assert source.seq < recorded.seq
    assert recorded.parent_event_id == source.event_id
    assert candidate.status == "unverified"
    assert candidate.observation == {key: source.payload[key] for key in ("verdict", "rationale", "defects")}
    assert candidate.product_spec_hash == result.product_specs[0].content_hash
    assert candidate.delivery_spec_hash == result.delivery_specs[0].content_hash
    assert candidate.checks == source.payload["checks"]
    assert candidate.checks
    assert candidate.evidence_refs
    for ref in candidate.evidence_refs:
        assert system.artifacts.get(ref)
    receipts = [asdict(item) for item in system.workspace(result.run_id).receipts()]
    for check in candidate.checks:
        assert any(receipt["department"] == "quality" and all(check[key] == receipt[key] for key in (
            "name", "snapshot_hash", "product_spec_hash", "delivery_spec_hash", "activation_id"
        )) for receipt in receipts)
    assert len(system.test_adapter.invocations) == len(script)
    assert_candidate_does_not_change_execution(system, result)
    assert system.replay(result.run_id).canonical_state() == result.canonical_state()
    before = result.last_seq
    assert system.run_until_stop(result.run_id).last_seq == before
    assert system.activate_once(result.run_id).last_seq == before


def test_candidate_is_never_injected_into_department_context(tmp_path):
    rules = dict(DEFAULT_PROMPTS)
    system, result = run_scripted(tmp_path, rework_script())
    candidate = result.lesson_candidates[0]
    for department in DEPARTMENTS:
        assembler = ContextAssembler()
        args = {"department": department, "session_id": "test-session", "activation_id": "test-activation"}
        with_candidate = assembler.assemble(result, **args)
        without_candidate = assembler.assemble(replace(result, lesson_candidates=[]), **args)
        assert with_candidate == without_candidate
    for invocation in system.test_adapter.invocations:
        assert candidate.id not in json_dumps(invocation.input_items)
        assert candidate.suggestion not in json_dumps(invocation.input_items)
        injected = recorded_context(system, invocation).manifest.injected
        assert all("lesson" not in item.source for item in injected)
    assert DEFAULT_PROMPTS == rules
    assert (system.test_adapter.name, system.test_adapter.model) == ("fake", "fake-script")


@pytest.mark.parametrize("with_delivery", [False, True])
def test_failure_candidate_has_only_existing_evidence_and_keeps_failure(tmp_path, with_delivery):
    script = [product_spec(), plan_turn(), delivery_turn()] if with_delivery else []
    script.append(ProviderError("controlled connection failure"))
    system, result = run_scripted(tmp_path, script)
    assert result.phase == "FAILED"
    assert result.stop_reason == "provider_error"
    assert len(result.lesson_candidates) == 1
    candidate = result.lesson_candidates[0]
    source = system.store.get_event(candidate.source_event_id)
    assert source.type == EventType.RUN_FAILED
    assert candidate.observation == {"stop_reason": source.stop_reason, "message": source.error}
    assert candidate.status == "unverified"
    if with_delivery:
        assert candidate.product_spec_hash == result.product_spec.content_hash
        assert candidate.delivery_spec_hash == result.delivery_spec.content_hash
        assert candidate.checks == result.delivery_spec.checks
        assert candidate.evidence_refs == [result.delivery_spec.tree_ref]
        assert all(system.artifacts.get(ref) for ref in candidate.evidence_refs)
    else:
        assert candidate.product_spec_hash is None
        assert candidate.delivery_spec_hash is None
        assert candidate.checks == candidate.evidence_refs == []
    assert len(system.test_adapter.invocations) == len(script)
    assert_candidate_does_not_change_execution(system, result)
    assert system.replay(result.run_id).canonical_state() == result.canonical_state()


def test_success_cancel_pause_and_rejected_review_do_not_invent_candidates(tmp_path):
    _system, success = run_scripted(tmp_path / "success", happy_script())
    assert success.phase == "DONE" and success.lesson_candidates == []
    system, paused = run_scripted(tmp_path / "pause", [product_spec()], max_cycles=1)
    assert paused.phase == "PAUSED" and paused.lesson_candidates == []
    run_id = system.create_run("cancelled by developer")
    cancelled = system.cancel(run_id)
    assert cancelled.stop_reason == "cancelled" and cancelled.lesson_candidates == []
    invalid = review("rework_engineering", "unverified rejected opinion", defects=[{"severity": "minor", "summary": "claim"}])
    invalid["defects"] = None
    _system, rejected = run_scripted(
        tmp_path / "rejected", [product_spec(), plan_turn(), delivery_turn(), invalid], max_cycles=4
    )
    assert rejected.phase == "PAUSED" and rejected.rejections
    assert rejected.lesson_candidates == []


def test_release_with_defect_keeps_existing_rejection_and_does_not_create_candidate(tmp_path):
    system, result = run_scripted(tmp_path, [
        product_spec(), plan_turn(), delivery_turn(),
        review_turn("release", "nonblocking observation", defects=[{"severity": "minor", "summary": "naming could improve"}]),
        review_turn("release", "no defects remain"),
    ])
    assert result.phase == "DONE"
    assert result.lesson_candidates == []
    assert result.rejections[0]["errors"] == [{"field": "defects", "message": "release requires an empty defect list"}]
    assert len(system.test_adapter.invocations) == 5
    assert_candidate_does_not_change_execution(system, result)


def test_web_evidence_source_export_and_replay_keep_the_same_candidate(tmp_path):
    system, result = run_scripted(tmp_path, rework_script())
    candidate = result.lesson_candidates[0]
    path = f"/api/runs/{result.run_id}"
    before = result.last_seq
    with running_server(system) as (_server, host, port):
        payload = get_json(host, port, path)
        assert payload["evidence"]["lesson_candidates"] == result.to_dict()["lesson_candidates"]
        assert candidate.created_event_id not in [item["event_id"] for item in payload["events"][-12:]]
        detail = get_json(host, port, f"{path}/events/{candidate.created_event_id}")
        source = get_json(host, port, f"{path}/events/{candidate.source_event_id}")
        assert detail["payload"]["source_event_id"] == source["event_id"]
        assert source["payload"]["rationale"] == candidate.observation["rationale"]
        exported = get_json(host, port, f"{path}/export")
        assert exported["projection"]["lesson_candidates"] == payload["evidence"]["lesson_candidates"]
        source_event = dict(source)
        git_detail = source_event.pop("git_version_detail")
        assert git_detail["commit"] == source_event["payload"]["git_version"]["commit"]
        assert detail in exported["events"] and source_event in exported["events"]
        assert json_dumps(exported["projection"]["lesson_candidates"]) == json_dumps(system.replay(result.run_id).lesson_candidates)
        assert request(host, port, "POST", f"{path}/replay")[0] == 200
    assert system.project(result.run_id).last_seq == before

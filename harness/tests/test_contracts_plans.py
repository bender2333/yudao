from dataclasses import asdict

from harness.adapters.fake import FakeAdapter
from harness.contracts import contract_payload, render_prd
from harness.models import EventType
from harness.proposals import (collaboration_request, delivery_turn,
                               product_decision, product_spec, response_turn, review_turn)
from harness.runtime import LoopSystem

def test_prd_and_delivery_bind_the_same_accepted_contract(tmp_path):
    adapter = FakeAdapter([
        product_spec(), collaboration_request(request_type="action", action="revise_requirements"),
        product_decision("Treat unknown flags as an error.", "Unknown flags must not silently change the command."),
        response_turn("completed", result_types=[EventType.PRODUCT_DECISION_ACCEPTED]),
        delivery_turn(), review_turn("release", "Verified the current requirements"),
    ])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    assert len(result.product_specs) == 1
    contract = result.effective_contract
    assert contract.decision_hashes == [result.product_decisions[-1].content_hash]
    assert contract_payload(result)["content_hash"] == contract.content_hash
    expected_prd = render_prd(result, asdict(contract))
    assert system.artifacts.get_for_run(run_id, contract.prd_ref).decode("utf-8") == expected_prd
    assert (tmp_path / "materials" / run_id / "PRD.md").read_bytes() == expected_prd.encode("utf-8")
    for content in (result.effective_decisions[0].statement, result.effective_decisions[0].rationale):
        assert content in expected_prd
    assert "PRD.md" not in system.workspace(run_id).list_files()
    assert result.delivery_spec.effective_contract_hash == result.last_review.effective_contract_hash == contract.content_hash
    events = system.store.list_events(run_id)
    assert not any(event.type == "plan_accepted" for event in events)
    assert result.canonical_state() == system.replay(run_id).canonical_state()

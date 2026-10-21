import pytest

from harness.collaboration import allowed_proposal_kinds
from harness.models import (
    ArtifactRef, DeliverySpec, EffectiveContract, ProductSpec, RunProjection,
)

def work(phase="QUALITY"):
    projection = RunProjection(run_id="run", task="Build a CLI.", phase=phase)
    projection.product_spec = ProductSpec(
        "spec", "run", 1, None, "spec-hash", "product", "active", "spec-event",
        "CLI", ["Print text"], [], [], ["Text appears"], [], [], [],
        change_record=None, input_version=0,
    )
    projection.effective_contract = EffectiveContract(
        "contract-hash", 1, "spec-hash", 0, [], "contract-event", ArtifactRef("prd", "prd-hash", "PRD.md"),
    )
    projection.delivery_spec = DeliverySpec(
        "delivery", "run", 1, None, "delivery-hash", "engineering", "active", "delivery-event",
        "spec-hash", "contract-hash", "CLI", ["cli.py"], [], [], [],
        "tree-hash", ArtifactRef("tree", "tree-ref", "tree.json"),
    )
    return projection

@pytest.mark.parametrize("phase,department,kind", [
    ("PRODUCT_SPEC", "product", "product_spec"), ("REWORK_PRODUCT", "product", "product_decision"),
    ("ENGINEERING", "engineering", "delivery_spec"), ("REWORK_ENGINEERING", "engineering", "delivery_spec"),
    ("QUALITY", "quality", "qa_review"), ("DELIVERY", "quality", "qa_review"),
])
def test_normal_proposals_remain_available(phase, department, kind):
    assert kind in allowed_proposal_kinds(work(phase), department)

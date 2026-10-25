import pytest

from harness.collaboration import allowed_proposal_kinds
from harness.models import (
    ArtifactRef, DeliverySpec, EffectiveContract, ProductSpec, RunProjection, SessionRecord,
)

def work(department):
    # 部门按关注的成果开始一轮工作（工单 #556）：正在工作的部门是它主线会话的记录，
    # 不再由阶段决定
    projection = RunProjection(run_id="run", task="Build a CLI.")
    projection.sessions[department] = SessionRecord(
        session_id=f"ses_{department}", department=department, status="active")
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

@pytest.mark.parametrize("department,kind", [
    ("product", "product_spec"), ("product", "product_decision"),
    ("engineering", "delivery_spec"),
    ("quality", "qa_review"),
])
def test_normal_proposals_remain_available(department, kind):
    assert kind in allowed_proposal_kinds(work(department), department)
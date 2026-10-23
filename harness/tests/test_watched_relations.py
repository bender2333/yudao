"""工单 #556 验收第 5 条：关注关系来自组织定义。

在组织定义里去掉工程对「缺陷记录」的关注以后，缺陷记录提交后工程不开始返工：
规则只看定义里写明的关注关系，代码里不写死。
"""
import json
import shutil
from pathlib import Path

from harness import collaboration
from harness.collaboration import has_new_work
from harness.definitions import DEFINITIONS_DIR, load_definitions
from harness.models import (
    ArtifactRef, DeliverySpec, EffectiveContract, ProductSpec, QAReview, RunProjection, SessionRecord,
)


def _work(department: str) -> RunProjection:
    """一份带有效要求、有效合同与交付的投影：工程交付过一次，质检还没有结论。"""
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


def _definitions_without_defect_watch(directory: Path) -> object:
    """一份去掉工程对「缺陷记录」关注的组织定义。"""
    shutil.copytree(DEFINITIONS_DIR, directory)
    path = directory / "organization.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    for department in document["departments"]:
        if department["id"] == "engineering":
            department["watched"] = [item for item in department["watched"] if item != "defect_record"]
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def _with_defect_record():
    """一份带交付与缺陷记录的投影：质检对最新交付记了缺陷记录。"""
    projection = _work("quality")
    delivery = projection.delivery_spec
    projection.reviews.append(QAReview(
        id="review", run_id="run", revision=1, parent_hash=None, content_hash="review-hash",
        issuer="quality", status="active", created_event_id="review-event",
        product_spec_hash="spec-hash", effective_contract_hash="contract-hash",
        delivery_spec_hash=delivery.content_hash, code_snapshot_hash="tree-hash",
        verdict="rework_engineering", rationale="命名不符要求", checks=[], defects=[],
        evidence_refs=[],
    ))
    return projection


def test_the_engineering_starts_a_rework_when_the_defect_record_is_watched():
    projection = _with_defect_record()
    assert has_new_work(projection, "engineering")


def test_removing_the_watch_in_the_definition_stops_the_rework(tmp_path, monkeypatch):
    definitions = _definitions_without_defect_watch(tmp_path / "definitions")
    monkeypatch.setattr(collaboration, "DEFINITIONS", definitions)
    projection = _with_defect_record()
    assert not has_new_work(projection, "engineering")
    # 只少了这一条关注关系：其它部门的关注关系照旧
    assert definitions.watched_outputs("engineering") == ("product_spec", "guidance")
    assert definitions.watched_outputs("quality") == ("delivery", "guidance", "structure", "product_spec")

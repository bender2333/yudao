# 提案合同里的通用条件是合同数据（设计说明第 5.5 节，工单 #859）：五条写死在 validation.py 里的关系规则
# 改写成 proposal_contracts.json 里的条件以后，只改合同数据就能放宽它，代码不用动。
# 每个用例先按发布的合同拒绝同一份提案，再把定义复制到临时目录、改一处合同数据、重新装载，同一份提案被接纳。
# 另外核对合同的结构校验：条件名、参数与缺少的参数在装载时报出（definitions/__init__.py）。
#
# 守的是：
# - R1（做对了）：合同的通用条件照常生效；
# - R2（不放过错的）：写错的条件名与参数让定义装载失败，不会静默跳过一条规则；
# - R3（不放宽既有许可）：发布的合同里六种通用条件都在，删掉任何一种都要有意识地改数据。
#
# 这一层用临时目录复制定义文件、按新合同重新装载，属于模块层。
from harness.tests.helpers import adjudication_view

import json
import shutil

import pytest

import harness.tools as tools
from harness.actions import TreeFacts
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, DefinitionError, load_definitions
from harness.kernel_events import Event
from harness.models import (ArtifactRef, CheckReceipt, DeliverySpec, EffectiveContract, EventType, ProductDecision, ProductSpec,
                            RunProjection, SessionRecord, canonical_hash)
from harness.proposals import baseline_review, delivery, product_decision, review, structure
from harness.validation import evaluate_proposal
from harness.tightening import WATCHED_OUTPUTS

RUN = "run_contract"
SPEC_HASH = "sha256:" + "a" * 64
OTHER_SPEC_HASH = "sha256:" + "b" * 64
CONTRACT_HASH = "sha256:" + "c" * 64
DELIVERY_HASH = "sha256:" + "d" * 64
TREE = "sha256:" + "e" * 64
OTHER_TREE = "sha256:" + "f" * 64
REQUIREMENT = "print the given argument to stdout"
CONDITIONS = ("basis_current", "referenced_current", "check_receipts", "tree_matches", "author_separation",
              "no_duplicate_content")


def _judgement_events(delivery_hash: str = DELIVERY_HASH) -> list[Event]:
    # 一条独立判断事件的内存替身（工单 #358 的门：核对它的存在与它写的交付摘要）
    return [Event(event_id="evt_judgement", run_id=RUN, type=EventType.INDEPENDENT_JUDGEMENT_COMMITTED,
                  role=None, parent_event_id=None, state_before="running", state_after="running",
                  payload={"kind": "independent_judgement", "product_spec_hash": SPEC_HASH,
                           "delivery_spec_hash": delivery_hash, "checks": ["smoke"],
                           "criteria_count": 1, "criteria": []},
                  artifact_hashes=[], session_id="ses_quality", provider=None, model=None,
                  context_digest=None, stop_reason=None, error=None, created_at="2026-10-31T00:00:00Z",
                  position=999, stream=f"run:{RUN}", stream_version=999, project_id=None,
                  work_item_id=None, department="quality")]


def _definitions(tmp_path, change):
    # 发布的定义文件的一份副本，按 change 改 proposal_contracts.json 里的条件，再重新装载
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        shutil.copyfile(path, directory / path.name)
    target = directory / "proposal_contracts.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    change(data["conditions"])
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def _without(kind: str, name: str):
    def change(conditions):
        conditions[kind] = [item for item in conditions[kind] if item["condition"] != name]
    return change


def _ref(kind: str, content_hash: str) -> ArtifactRef:
    return ArtifactRef(kind=kind, content_hash=content_hash, path=f"{kind}/{content_hash[7:9]}/{content_hash[7:]}")


def _spec() -> ProductSpec:
    return ProductSpec(id="spec_1", run_id=RUN, revision=1, parent_hash=None, content_hash=SPEC_HASH,
                       issuer="product", status="active", created_event_id="evt_spec", goal="build an echo CLI",
                       requirements=[REQUIREMENT], boundaries=[], constraints=[], acceptance_criteria=["prints"],
                       fatal_conditions=[], non_goals=[], decision_changes=[], change_record=None, input_version=1)


def _contract() -> EffectiveContract:
    return EffectiveContract(content_hash=CONTRACT_HASH, revision=1, product_spec_hash=SPEC_HASH, input_version=1,
                             decision_hashes=[], created_event_id="evt_contract", prd_ref=_ref("prd", SPEC_HASH))


def _delivery(**overrides) -> DeliverySpec:
    values = dict(id="delivery_1", run_id=RUN, revision=1, parent_hash=None, content_hash=DELIVERY_HASH,
                  issuer="engineering", status="active", created_event_id="evt_delivery",
                  product_spec_hash=SPEC_HASH, effective_contract_hash=CONTRACT_HASH, summary="implemented",
                  files=["src/echo.py"], check_names=["smoke"], checks=[], known_risks=[], code_tree_digest=TREE,
                  tree_ref=_ref("tree", TREE))
    values.update(overrides)
    return DeliverySpec(**values)


def _receipt(department: str, *, activation: str = "act", snapshot: str = TREE,
             delivery_hash: str | None = None) -> CheckReceipt:
    return CheckReceipt(name="smoke", department=department, exit_code=0, summary="ran", snapshot_hash=snapshot,
                        product_spec_hash=SPEC_HASH, delivery_spec_hash=delivery_hash, activation_id=activation,
                        effective_contract_hash=CONTRACT_HASH)


def _facts(*checks: CheckReceipt, digest: str = TREE) -> TreeFacts:
    return TreeFacts(digest=digest, files=("src/echo.py",), hashes=("h",), checks=checks)


def _projection(department: str, *, kind: str = "change", **fields) -> RunProjection:
    sessions = {department: SessionRecord(session_id=f"ses_{department}", department=department, status="active")}
    return RunProjection(run_id=RUN, kind=kind, sessions=sessions, **fields)


def test_the_shipped_contract_declares_every_generic_condition():
    # R3：六种通用条件都在发布的合同里（删掉一种要改数据，改数据要有用例说明）
    shipped = json.loads((DEFINITIONS_DIR / "proposal_contracts.json").read_text(encoding="utf-8"))
    declared = {item["condition"] for kind in shipped["conditions"].values() for item in kind}
    assert declared == set(CONDITIONS)
    assert DEFINITIONS.proposal_conditions("qa_review"), "读出来的条件应当与文件一致"


def test_removing_the_duplicate_check_from_the_contract_accepts_the_same_decision(tmp_path, monkeypatch):
    # 第五条第 1 项：拒绝与已接纳过的产品决定内容相同的决定
    content = {"statement": "use exit code 2", "rationale": "keep failures distinguishable",
               "product_spec_hash": SPEC_HASH}
    existing = ProductDecision(id="decision_1", run_id=RUN, content_hash=canonical_hash(content),
                               created_event_id="evt_decision", product_spec_hash=SPEC_HASH,
                               statement=content["statement"], rationale=content["rationale"])
    projection = _projection("product", product_spec=_spec(), product_decisions=[existing])
    proposal = product_decision(content["statement"], content["rationale"])
    assert not evaluate_proposal(adjudication_view(projection),department="product", facts=_facts(),
                                 proposal=proposal, tightening=WATCHED_OUTPUTS).accepted
    monkeypatch.setattr(tools, "DEFINITIONS",
                        _definitions(tmp_path, _without("product_decision", "no_duplicate_content")))
    decision = evaluate_proposal(adjudication_view(projection),department="product", facts=_facts(), proposal=proposal, tightening=WATCHED_OUTPUTS)
    assert decision.accepted, decision.error_dicts


def test_removing_the_referenced_version_check_accepts_a_review_of_a_superseded_delivery(tmp_path, monkeypatch):
    # 第五条第 2 项：质检结论依据的交付要基于当前的 PRD 与契约。
    # 结论前已有当前交付的独立判断（工单 #358 的门），这里只核对引用版本这一条
    projection = _projection("quality", product_spec=_spec(), effective_contract=_contract(),
                             delivery_spec=_delivery(product_spec_hash=OTHER_SPEC_HASH),
                             last_activations={"quality": "act_q"})
    facts = _facts(_receipt("quality", activation="act_q", delivery_hash=DELIVERY_HASH))
    proposal = review("release", "the delivery passes", checks=["smoke"], basis_delivery_spec_hash=DELIVERY_HASH)
    assert not evaluate_proposal(adjudication_view(projection),department="quality", facts=facts, proposal=proposal, tightening=WATCHED_OUTPUTS).accepted
    monkeypatch.setattr(tools, "DEFINITIONS", _definitions(tmp_path, _without("qa_review", "referenced_current")))
    decision = evaluate_proposal(adjudication_view(projection),department="quality", facts=facts, proposal=proposal,
                                 tightening=WATCHED_OUTPUTS, events=_judgement_events())
    assert decision.accepted, decision.error_dicts


def test_removing_the_structure_check_accepts_a_baseline_review_without_a_structure(tmp_path, monkeypatch):
    # 第五条第 3 项：基线核验要有当前 PRD 的结构说明
    projection = _projection("quality", kind="onboarding", product_spec=_spec(), snapshot={"tree_digest": TREE},
                             last_activations={"quality": "act_q"})
    facts = _facts(_receipt("quality", activation="act_q"))
    proposal = baseline_review(conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
                               checks=["smoke"])
    assert not evaluate_proposal(adjudication_view(projection),department="quality", facts=facts, proposal=proposal, tightening=WATCHED_OUTPUTS).accepted
    monkeypatch.setattr(tools, "DEFINITIONS", _definitions(tmp_path, _without("baseline_review", "referenced_current")))
    decision = evaluate_proposal(adjudication_view(projection),department="quality", facts=facts, proposal=proposal, tightening=WATCHED_OUTPUTS)
    assert decision.accepted, decision.error_dicts


def test_clearing_the_activation_requirement_accepts_a_receipt_from_an_earlier_activation(tmp_path, monkeypatch):
    # 第五条第 4 项：回执来自这一轮；把合同里的 activation 改成 false 以后，上一轮的回执也算
    projection = _projection("engineering", product_spec=_spec(), effective_contract=_contract(),
                             last_activations={"engineering": "act_now"})
    facts = _facts(_receipt("engineering", activation="act_before"))
    proposal = delivery(basis_product_spec_hash=SPEC_HASH)
    assert not evaluate_proposal(adjudication_view(projection),department="engineering", facts=facts,
                                 proposal=proposal, tightening=WATCHED_OUTPUTS).accepted
    monkeypatch.setattr(tools, "DEFINITIONS", _definitions(
        tmp_path, lambda conditions: conditions["delivery_spec"][1].update({"activation": False})))
    decision = evaluate_proposal(adjudication_view(projection),department="engineering", facts=facts, proposal=proposal, tightening=WATCHED_OUTPUTS)
    assert decision.accepted, decision.error_dicts


def test_removing_the_tree_check_accepts_an_onboarding_proposal_over_a_changed_tree(tmp_path, monkeypatch):
    # 第五条第 5 项：建档提案的树等于快照
    projection = _projection("engineering", kind="onboarding", product_spec=_spec(),
                             snapshot={"tree_digest": TREE}, last_activations={"engineering": "act"})
    facts = _facts(_receipt("engineering", activation="act", snapshot=OTHER_TREE), digest=OTHER_TREE)
    proposal = structure(requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}])
    assert not evaluate_proposal(adjudication_view(projection),department="engineering", facts=facts,
                                 proposal=proposal, tightening=WATCHED_OUTPUTS).accepted
    monkeypatch.setattr(tools, "DEFINITIONS", _definitions(tmp_path, _without("structure", "tree_matches")))
    decision = evaluate_proposal(adjudication_view(projection),department="engineering", facts=facts, proposal=proposal, tightening=WATCHED_OUTPUTS)
    assert decision.accepted, decision.error_dicts


def test_an_unknown_condition_name_makes_the_definitions_invalid(tmp_path):
    def change(conditions):
        conditions["delivery_spec"][0]["condition"] = "same_version"
    with pytest.raises(DefinitionError) as raised:
        _definitions(tmp_path, change)
    [issue] = raised.value.issues
    assert issue[0] == "proposal_contracts.json" and issue[1].startswith("conditions.delivery_spec[0]")


def test_a_missing_condition_parameter_makes_the_definitions_invalid(tmp_path):
    def change(conditions):
        del conditions["qa_review"][0]["target"]
    with pytest.raises(DefinitionError) as raised:
        _definitions(tmp_path, change)
    [issue] = raised.value.issues
    assert issue[0] == "proposal_contracts.json" and "conditions.qa_review[0]" in issue[1]
    assert "requires target" in issue[2]


def test_a_parameter_the_condition_does_not_take_makes_the_definitions_invalid(tmp_path):
    def change(conditions):
        conditions["structure"][0]["department"] = "engineering"
    with pytest.raises(DefinitionError) as raised:
        _definitions(tmp_path, change)
    [issue] = raised.value.issues
    assert "does not take department" in issue[2]


@pytest.mark.parametrize("names", [
    {"field": "checks", "item": "name"},
    {"items": "build_and_test", "item": None},
], ids=["field-and-item", "items-without-item"])
def test_malformed_check_name_locations_make_the_definitions_invalid(tmp_path, names):
    def change(conditions):
        conditions["structure"][1]["names"] = names
    with pytest.raises(DefinitionError) as raised:
        _definitions(tmp_path, change)
    [issue] = raised.value.issues
    assert "conditions.structure[1].names" in issue[1] and "names" in issue[2]


@pytest.mark.parametrize(("parameter", "message"), [("message", "message"), ("field", "field")])
def test_an_empty_condition_message_or_field_makes_the_definitions_invalid(tmp_path, parameter, message):
    def change(conditions):
        conditions["qa_review"][2][parameter] = ""
    with pytest.raises(DefinitionError) as raised:
        _definitions(tmp_path, change)
    [issue] = raised.value.issues
    assert f"{message} must be a non-empty string" in issue[2]


def test_a_receipt_department_outside_the_organization_makes_the_definitions_invalid(tmp_path):
    def change(conditions):
        conditions["qa_review"][3]["department"] = "audit"
    with pytest.raises(DefinitionError) as raised:
        _definitions(tmp_path, change)
    [issue] = raised.value.issues
    assert issue[1] == "conditions.qa_review[3].department" and "audit" in issue[2]

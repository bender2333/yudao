# 提案合同里的通用条件（设计说明第 5.5 节，工单 #859）：六种条件各有用例，满足与不满足两种情形都有。
# 条件与参数来自 harness/definitions/proposal_contracts.json；这里在内存里构造运行状态投影与工作区事实，
# 经 evaluate_proposal 的公开入口核对，不读临时目录、不起进程。
#
# 守的是：
# - R1（做对了）：满足条件的提案照旧被接纳；
# - R2（不放过错的）：引用的版本不是当前版本、回执不是这一轮、树不一致、作者与评价者同一部门、
#   内容重复的提案被拒绝，理由指向对应的字段；
# - R3（不放宽既有许可）：六条关系规则一条都不缺（改合同数据放宽的用例在 test_proposal_conditions_contract.py）。

from harness.actions import TreeFacts
from harness.models import (ArtifactRef, CheckReceipt, DeliverySpec, EffectiveContract, ProductDecision, ProductSpec,
                            RunProjection, SessionRecord, canonical_hash)
from harness.proposals import baseline_review, delivery, product_decision, product_spec, review, structure
from harness.validation import evaluate_proposal

RUN = "run_conditions"
SPEC_HASH = "sha256:" + "a" * 64
OTHER_SPEC_HASH = "sha256:" + "b" * 64
CONTRACT_HASH = "sha256:" + "c" * 64
DELIVERY_HASH = "sha256:" + "d" * 64
TREE = "sha256:" + "e" * 64
OTHER_TREE = "sha256:" + "f" * 64
REQUIREMENT = "print the given argument to stdout"


def _ref(kind: str, content_hash: str) -> ArtifactRef:
    return ArtifactRef(kind=kind, content_hash=content_hash, path=f"{kind}/{content_hash[7:9]}/{content_hash[7:]}")


def _spec(content_hash: str = SPEC_HASH) -> ProductSpec:
    return ProductSpec(id="spec_1", run_id=RUN, revision=1, parent_hash=None, content_hash=content_hash,
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


def _receipt(department: str, *, activation: str = "act", exit_code: int = 0,
             delivery_hash: str | None = None) -> CheckReceipt:
    # 主机记录的一条 run_check 回执：绑定当前快照、当前 ProductSpec 与当前合同
    return CheckReceipt(name="smoke", department=department, exit_code=exit_code, summary="ran",
                        snapshot_hash=TREE, product_spec_hash=SPEC_HASH, delivery_spec_hash=delivery_hash,
                        activation_id=activation, effective_contract_hash=CONTRACT_HASH)


def _quality_receipt(**overrides) -> CheckReceipt:
    values = dict(department="quality", activation="act_q", delivery_hash=DELIVERY_HASH)
    values.update(overrides)
    return _receipt(**values)


def _facts(*checks: CheckReceipt, digest: str = TREE) -> TreeFacts:
    return TreeFacts(digest=digest, files=("src/echo.py",), hashes=("h",), checks=checks)


def _projection(department: str, *, kind: str = "change", **fields) -> RunProjection:
    # 部门这一轮正在工作（主线会话的记录是「工作中」），因此可以提交本部门在事项种类里的提案
    sessions = {department: SessionRecord(session_id=f"ses_{department}", department=department, status="active")}
    return RunProjection(run_id=RUN, kind=kind, sessions=sessions, **fields)


def _review_projection(**overrides) -> RunProjection:
    fields = dict(product_spec=_spec(), effective_contract=_contract(), delivery_spec=_delivery(),
                  last_activations={"quality": "act_q"})
    fields.update(overrides)
    return _projection("quality", **fields)


def _structure_projection(**overrides) -> RunProjection:
    fields = dict(product_spec=_spec(), snapshot={"tree_digest": TREE}, last_activations={"engineering": "act"})
    fields.update(overrides)
    return _projection("engineering", kind="onboarding", **fields)


STRUCTURE = {"content_hash": "sha256:" + "2" * 64, "revision": 1, "product_spec_hash": SPEC_HASH,
             "issuer": "engineering", "code_tree_digest": TREE}


def _baseline_projection(**overrides) -> RunProjection:
    fields = dict(product_spec=_spec(), structure=dict(STRUCTURE), snapshot={"tree_digest": TREE},
                  last_activations={"quality": "act_q"})
    fields.update(overrides)
    return _projection("quality", kind="onboarding", **fields)


def _structure_proposal(**overrides) -> dict:
    values = dict(requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}])
    values.update(overrides)
    return structure(**values)


def _baseline_proposal() -> dict:
    return baseline_review(conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
                           checks=["smoke"])


def _review_proposal(**overrides) -> dict:
    values = dict(verdict="release", rationale="the delivery passes", checks=["smoke"],
                  basis_delivery_spec_hash=DELIVERY_HASH)
    values.update(overrides)
    return review(**values)


def _stale_product_spec_is_rejected():
    # 通用条件 1：产品修订 PRD 时声明的依据版本与当前版本不同就拒绝
    projection = _projection("product", product_spec=_spec())
    stale = evaluate_proposal(department="product", projection=projection, facts=_facts(),
                              proposal=product_spec(basis_product_spec_hash=OTHER_SPEC_HASH))
    assert not stale.accepted
    assert [error.field for error in stale.errors] == ["basis_product_spec_hash"]
    assert SPEC_HASH in stale.errors[0].message


def test_a_product_spec_with_the_current_basis_is_accepted():
    projection = _projection("product", product_spec=_spec())
    revision = product_spec(basis_product_spec_hash=SPEC_HASH, decision_changes=[],
                            change_record={"changed": [], "retained": [REQUIREMENT], "retired": [],
                                           "rationale": "keep the requirement"})
    decision = evaluate_proposal(department="product", projection=projection, facts=_facts(), proposal=revision)
    assert decision.accepted, decision.error_dicts


def test_a_product_spec_with_a_stale_basis_is_rejected():
    _stale_product_spec_is_rejected()


def test_the_first_product_spec_declares_a_null_basis():
    # 还没有当前版本：声明 null 通过，条件不把第一次接纳当成过期依据
    projection = _projection("product")
    decision = evaluate_proposal(department="product", projection=projection, facts=_facts(),
                                 proposal=product_spec(basis_product_spec_hash=None))
    assert decision.accepted, decision.error_dicts


def test_a_product_decision_with_the_same_content_is_rejected():
    # 通用条件 6：同样内容的成果不重复接纳
    content = {"statement": "use exit code 2 for unknown flags", "rationale": "keep failures distinguishable",
               "product_spec_hash": SPEC_HASH}
    existing = ProductDecision(id="decision_1", run_id=RUN, content_hash=canonical_hash(content),
                               created_event_id="evt_decision", product_spec_hash=SPEC_HASH,
                               statement=content["statement"], rationale=content["rationale"])
    projection = _projection("product", product_spec=_spec(), product_decisions=[existing])
    duplicate = evaluate_proposal(department="product", projection=projection, facts=_facts(),
                                  proposal=product_decision(content["statement"], content["rationale"]))
    assert not duplicate.accepted
    assert [error.field for error in duplicate.errors] == ["statement"]
    fresh = evaluate_proposal(department="product", projection=projection, facts=_facts(),
                              proposal=product_decision("use exit code 3 for unknown flags", content["rationale"]))
    assert fresh.accepted, fresh.error_dicts


def test_a_delivery_with_a_stale_basis_is_rejected():
    projection = _projection("engineering", product_spec=_spec(), effective_contract=_contract(),
                             last_activations={"engineering": "act"})
    decision = evaluate_proposal(department="engineering", projection=projection, facts=_facts(_receipt("engineering")),
                                 proposal=delivery(basis_product_spec_hash=OTHER_SPEC_HASH))
    assert not decision.accepted
    assert [error.field for error in decision.errors] == ["basis_product_spec_hash"]


def test_a_delivery_with_the_current_basis_and_receipt_is_accepted():
    projection = _projection("engineering", product_spec=_spec(), effective_contract=_contract(),
                             last_activations={"engineering": "act"})
    decision = evaluate_proposal(department="engineering", projection=projection, facts=_facts(_receipt("engineering")),
                                 proposal=delivery(basis_product_spec_hash=SPEC_HASH))
    assert decision.accepted, decision.error_dicts


def test_a_check_receipt_from_another_activation_is_rejected():
    # 通用条件 3：列出的检查要有这个部门这一轮回执；上一轮的回执不算
    projection = _projection("engineering", product_spec=_spec(), effective_contract=_contract(),
                             last_activations={"engineering": "act_now"})
    decision = evaluate_proposal(department="engineering", projection=projection,
                                 facts=_facts(_receipt("engineering", activation="act_before")),
                                 proposal=delivery(basis_product_spec_hash=SPEC_HASH))
    assert not decision.accepted
    assert [error.field for error in decision.errors] == ["check_names"]
    assert "smoke" in decision.errors[0].message


def test_a_review_of_a_current_delivery_is_accepted():
    decision = evaluate_proposal(department="quality", projection=_review_projection(), facts=_facts(_quality_receipt()),
                                 proposal=_review_proposal())
    assert decision.accepted, decision.error_dicts
    assert decision.ends_run


def test_a_review_of_a_delivery_bound_to_a_superseded_spec_is_rejected():
    # 通用条件 2：引用的交付所依据的 PRD 也必须是当前版本
    projection = _review_projection(delivery_spec=_delivery(product_spec_hash=OTHER_SPEC_HASH))
    decision = evaluate_proposal(department="quality", projection=projection, facts=_facts(_quality_receipt()),
                                 proposal=_review_proposal())
    assert not decision.accepted
    assert "product_spec_hash" in [error.field for error in decision.errors]


def test_a_review_requires_the_workspace_tree_to_match_the_delivery():
    # 通用条件 4：工作区的树与交付记下的树一致
    decision = evaluate_proposal(department="quality", projection=_review_projection(),
                                 facts=_facts(_quality_receipt(), digest=OTHER_TREE),
                                 proposal=_review_proposal())
    assert not decision.accepted
    assert any(error.field == "code_snapshot_hash" for error in decision.errors)


def test_a_review_requires_a_quality_receipt_from_this_activation():
    # 通用条件 3：回执来自质检这一轮，工程的回执不能顶替
    projection = _review_projection()
    previous = _facts(_quality_receipt(activation="act_before"))
    decision = evaluate_proposal(department="quality", projection=projection, facts=previous,
                                 proposal=_review_proposal())
    assert not decision.accepted
    assert any(error.field == "checks" for error in decision.errors)


def test_a_department_cannot_evaluate_an_artifact_it_authored():
    # 通用条件 5（基础规则 3）：提出评价类成果的部门不是被评价成果的作者部门
    projection = _review_projection(delivery_spec=_delivery(issuer="quality"))
    decision = evaluate_proposal(department="quality", projection=projection, facts=_facts(_quality_receipt()),
                                 proposal=_review_proposal())
    assert not decision.accepted
    [error] = decision.errors
    assert error.field == "issuer" and "quality" in error.message


def test_an_onboarding_structure_with_a_current_receipt_is_accepted():
    decision = evaluate_proposal(department="engineering", projection=_structure_projection(),
                                 facts=_facts(_receipt("engineering")), proposal=_structure_proposal())
    assert decision.accepted, decision.error_dicts


def test_an_onboarding_structure_requires_the_snapshot_tree():
    # 通用条件 4：建档提案的工作区的树等于建档时的快照
    decision = evaluate_proposal(department="engineering", projection=_structure_projection(),
                                 facts=_facts(_receipt("engineering"), digest=OTHER_TREE),
                                 proposal=_structure_proposal())
    assert not decision.accepted
    assert any(error.field == "code_snapshot_hash" and "no longer matches the snapshot" in error.message
               for error in decision.errors)


def test_an_onboarding_structure_requires_the_snapshot_to_record_the_tree():
    # 通用条件 4：没有记下树摘要（建档前的快照缺失）时拒绝，理由与字段由合同给出
    decision = evaluate_proposal(department="engineering", projection=_structure_projection(snapshot=None),
                                 facts=_facts(_receipt("engineering")), proposal=_structure_proposal())
    assert not decision.accepted
    assert [error.field for error in decision.errors] == ["snapshot"]


def test_an_onboarding_structure_requires_a_receipt_from_this_activation():
    decision = evaluate_proposal(department="engineering", projection=_structure_projection(),
                                 facts=_facts(_receipt("engineering", activation="act_before")),
                                 proposal=_structure_proposal())
    assert not decision.accepted
    assert [error.field for error in decision.errors] == ["build_and_test[0].name"]


def test_a_baseline_review_of_the_current_structure_is_accepted():
    decision = evaluate_proposal(department="quality", projection=_baseline_projection(),
                                 facts=_facts(_quality_receipt()), proposal=_baseline_proposal())
    assert decision.accepted, decision.error_dicts
    assert decision.ends_run


def test_a_baseline_review_requires_a_structure_of_the_current_spec():
    # 通用条件 2：基线核验要有当前 PRD 的结构说明
    missing = evaluate_proposal(department="quality", projection=_baseline_projection(structure=None),
                                facts=_facts(_quality_receipt()), proposal=_baseline_proposal())
    assert not missing.accepted
    assert any(error.field == "structure" for error in missing.errors)
    stale = evaluate_proposal(department="quality",
                              projection=_baseline_projection(
                                  structure={**STRUCTURE, "product_spec_hash": OTHER_SPEC_HASH}),
                              facts=_facts(_quality_receipt()), proposal=_baseline_proposal())
    assert not stale.accepted
    assert any(error.field == "structure" for error in stale.errors)


def test_a_baseline_review_requires_the_snapshot_tree():
    decision = evaluate_proposal(department="quality", projection=_baseline_projection(),
                                 facts=_facts(_quality_receipt(), digest=OTHER_TREE),
                                 proposal=_baseline_proposal())
    assert not decision.accepted
    assert any(error.field == "code_snapshot_hash" for error in decision.errors)


def test_a_baseline_review_requires_a_receipt_from_this_activation():
    decision = evaluate_proposal(department="quality", projection=_baseline_projection(),
                                 facts=_facts(_quality_receipt(activation="act_before")),
                                 proposal=_baseline_proposal())
    assert not decision.accepted
    assert any(error.field == "checks" for error in decision.errors)


def test_a_baseline_review_of_a_structure_authored_by_quality_is_rejected():
    # 通用条件 5：提出核验的部门不是结构说明的作者部门
    projection = _baseline_projection(structure={**STRUCTURE, "issuer": "quality"})
    decision = evaluate_proposal(department="quality", projection=projection, facts=_facts(_quality_receipt()),
                                 proposal=_baseline_proposal())
    assert not decision.accepted
    assert any(error.field == "issuer" for error in decision.errors)

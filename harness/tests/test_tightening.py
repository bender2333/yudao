# 工单 #1095：成果驱动特有的检查搬进应用层的收紧检查（harness/tightening.py）。
#
# 内核的通用检查（流版本、执行权、运行状态、边界、工具许可、提案合同）通过以后，写入口在同一个事务里
# 问收紧检查一次；结果只有三种：通过、拒绝（写明原因）、等待（写入口按安全节点等，工单 #561）。
# 这里逐条核对设计说明第 5.5 节列出的每一项成果驱动检查都经过这条缝运行，读的是成果的当前内容与
# 应用状态，不是内核的通用规则：
#   - 这个部门此刻能交哪些种类、询问分支的工具限制与回问深度；
#   - 工作依据里的输入版本、放行等产品处理完输入；
#   - 探索轮不能交质检结论、放行用当前质检测试材料；
#   - 按 PRD 内容的检查：每条要求覆盖一次、有效决定逐条保留或退役、「设计中，未实施」的边界不是现有缺陷。
#
# 守 R2（缝的交换字段：TightenRequest 进去、Tightened 出来，只有通过、拒绝、等待三种，带上契约版本）
# 与 R3（设计说明第 5.5 节写明的行为，经这条缝检查，不看收紧检查内部怎么组织）。
from harness.tests.helpers import adjudication_view, minimal_of, work_basis

from dataclasses import replace

from harness.actions import CheckReceipt, TreeFacts
from harness.adapters.fake import FakeAdapter
from harness.models import (ArtifactRef, DeliverySpec, EffectiveContract, SessionRecord)
from harness.proposals import baseline_review, product_spec, review, structure
from harness.runtime import LoopSystem
from harness.tightening import WATCHED_OUTPUTS, pending_product_input
from harness.tightening_contract import accept
from harness.validation import TightenRequest

MARK = "设计中，未实施"
TREE = "sha256:" + "e" * 64
DELIVERY = "sha256:" + "d" * 64
CONTRACT = "sha256:" + "c" * 64


def _accepted(tmp_path, **extra) -> tuple[LoopSystem, str]:
    # 产品提交第一次 PRD 并让它被接纳：投影里有一份当前的 PRD
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(**extra)]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    return system, run_id


def _working(projection, department: str):
    # 这个部门正在工作：会话的记录是「工作中」（按调度算出来的当前工作由既有用例覆盖）
    return replace(projection, sessions={**projection.sessions, department: SessionRecord(
        session_id=f"ses_{department}", department=department, status="active")})


def _structured(projection, department: str, proposal: dict, *, facts=None, **extra) -> TightenRequest:
    # S2c（工单 #1098）：格式检查与成果内容的组装也在收紧检查里，所以要交最小投影与工作区事实
    return TightenRequest(department=department, state=projection, proposal=proposal,
                          minimal=minimal_of(projection), facts=_facts() if facts is None else facts, **extra)


def _facts(*checks: CheckReceipt, digest: str = TREE) -> TreeFacts:
    return TreeFacts(digest=digest, files=("src/echo.py",), hashes=("h",), checks=checks)


def _ref(kind: str, content_hash: str) -> ArtifactRef:
    return ArtifactRef(kind=kind, content_hash=content_hash, path=f"{kind}/{content_hash[7:9]}/{content_hash[7:]}")


def _receipt(name: str, department: str, *, spec_hash: str, activation: str, exit_code: int = 0,
             delivery_hash: str | None = None, qa_tests_hash: str | None = None) -> CheckReceipt:
    # 一条检查回执：绑定当前快照、当前 PRD（质检的还绑定当前交付与合同）
    return CheckReceipt(name=name, department=department, exit_code=exit_code, summary="ran", snapshot_hash=TREE,
                        product_spec_hash=spec_hash, delivery_spec_hash=delivery_hash,
                        activation_id=activation, effective_contract_hash=None if delivery_hash is None else CONTRACT,
                        qa_tests_hash=qa_tests_hash)


def _delivery_ready(projection, *, qa_tests_hash="sha256:current", receipt_material="sha256:current"):
    # 一份可以核验的交付：当前合同、当前交付与这一轮质检的一条检查回执（核质检的结论用）
    spec = projection.product_spec
    contract = EffectiveContract(content_hash=CONTRACT, revision=1, product_spec_hash=spec.content_hash,
                                 input_version=spec.input_version, decision_hashes=[],
                                 created_event_id="evt_contract", prd_ref=_ref("prd", spec.content_hash))
    delivery = DeliverySpec(id="delivery_1", run_id=projection.run_id, revision=1, parent_hash=None,
                            content_hash=DELIVERY, issuer="engineering", status="active",
                            created_event_id="evt_delivery", product_spec_hash=spec.content_hash,
                            effective_contract_hash=CONTRACT, summary="implemented", files=["src/echo.py"],
                            check_names=["smoke"], checks=[], known_risks=[], code_tree_digest=TREE,
                            tree_ref=_ref("tree", TREE))
    receipt = _receipt("smoke", "quality", spec_hash=spec.content_hash, activation="act_q",
                       delivery_hash=DELIVERY, qa_tests_hash=receipt_material)
    ready = replace(projection, effective_contract=contract, delivery_spec=delivery,
                    last_activations={"quality": "act_q"}, qa_tests_hash=qa_tests_hash)
    return _working(ready, "quality"), receipt


def _errors(tightened) -> list[tuple[str, str]]:
    return [(error.field, error.message) for error in tightened.errors]


def test_the_tightening_check_declares_the_contract_version():
    # R2：这道缝是内核与路由之间的合同，实现声明契约版本，薄的一侧按版本接受
    assert WATCHED_OUTPUTS.CONTRACT_VERSION == 1
    assert accept(WATCHED_OUTPUTS) == 1


def test_the_kinds_a_department_can_submit_come_from_the_tightening_check(tmp_path):
    # R3：部门此刻能交的种类按调度算出来的当前工作决定（清点第 D 类）
    system, run_id = _accepted(tmp_path)
    projection = _working(system.project(run_id), "product")
    assert "product_spec" in WATCHED_OUTPUTS.kinds(TightenRequest(department="product", state=projection))
    # 终态的 run 谁都不能再交；不认识的部门也没有种类
    assert WATCHED_OUTPUTS.kinds(TightenRequest(department="product",
                                                state=replace(projection, status="done"))) == set()
    assert WATCHED_OUTPUTS.kinds(TightenRequest(department="nobody", state=projection)) == set()


def test_a_submission_outside_the_current_work_is_refused_by_the_tightening_check(tmp_path):
    # R3：这一轮不该交的东西由收紧检查拒绝，内核只问一次
    system, run_id = _accepted(tmp_path)
    projection = system.project(run_id)
    # 产品此刻能交的是 PRD（可以在回答询问时修订），交付不是它这一刻的种类
    tightened = WATCHED_OUTPUTS.tool(TightenRequest(
        department="product", state=projection,
        tool={"id": "call", "name": "submit_delivery", "args": {}}))
    assert tightened.reason == "This proposal is not permitted in the current department work."
    assert not tightened.accepted and not tightened.wait and not tightened.deferred


def test_a_stale_basis_defers_a_proposal_inside_the_tightening_check(tmp_path):
    # R3：模型还没看见新输入时正式成果推迟到下一步（工单 #964），不是停止这一轮
    from harness.adjudication import WorkBasis

    system, run_id = _accepted(tmp_path)
    projection = _working(system.project(run_id), "engineering")
    basis = replace(work_basis(projection, "engineering"),
                    input_version=projection.input_version - 1)
    tightened = WATCHED_OUTPUTS.tool(TightenRequest(
        department="engineering", state=projection, basis=basis,
        tool={"id": "call", "name": "submit_delivery", "args": {}}))
    assert tightened.deferred and not tightened.accepted and not tightened.wait
    assert "not accepted now" in (tightened.reason or "")


def test_a_product_spec_waits_for_the_input_to_enter_product_work(tmp_path):
    # R3：新输入要先进入产品这一轮的模型输入，之后才能改要求
    system, run_id = _accepted(tmp_path)
    projection = system.project(run_id)
    newer = replace(projection, input_version=projection.input_version + 1)
    tightened = WATCHED_OUTPUTS.submission(_structured(newer, "product", product_spec(
        change_record={"rationale": "tightened the goal", "changed": ["goal"], "retained": [], "retired": []})))
    assert [field for field, _message in _errors(tightened)] == ["input_version"]


def test_a_revised_product_spec_must_explain_and_dispose_every_decision(tmp_path):
    # R3：修订要写改动说明，当前有效决定逐条保留、并入或退役（读 PRD 内容）
    system, run_id = _accepted(tmp_path)
    projection = system.project(run_id)
    basis = projection.product_spec.content_hash
    missing_record = WATCHED_OUTPUTS.submission(_structured(
        projection, "product", product_spec(basis_product_spec_hash=basis)))
    assert [field for field, _message in _errors(missing_record)] == ["change_record"]
    undeclared = WATCHED_OUTPUTS.submission(_structured(
        projection, "product",
        product_spec(basis_product_spec_hash=basis,
                     change_record={"rationale": "changed", "changed": [], "retained": [], "retired": []},
                     decision_changes=[{"decision_hash": "sha256:unknown", "disposition": "retain",
                                        "rationale": "keep it"}])))
    assert [field for field, _message in _errors(undeclared)] == ["decision_changes"]


def test_a_review_without_a_delivery_is_refused_as_an_exploration_round(tmp_path):
    # R3：探索轮没有可以核验的交付，交质检结论被拒绝
    system, run_id = _accepted(tmp_path)
    projection = replace(system.project(run_id),
                         department_bases={"quality": "sha256:basis"},
                         department_delivery_bases={"quality": None})
    tightened = WATCHED_OUTPUTS.submission(_structured(projection, "quality", review(
        "rework_engineering", "exploring", defects=[{"severity": "major", "summary": "进不去"}])))
    assert _errors(tightened) == [("delivery_spec", "this work has no delivery to review")]


def test_a_release_must_use_the_current_quality_test_material(tmp_path):
    # R3：测试材料变了以后，旧的检查回执不能拿来放行
    system, run_id = _accepted(tmp_path)
    projection, receipt = _delivery_ready(system.project(run_id), qa_tests_hash="sha256:current",
                                          receipt_material="sha256:older")
    tightened = WATCHED_OUTPUTS.submission(_structured(
        projection, "quality",
        review("release", "verified", checks=["smoke"], basis_delivery_spec_hash=DELIVERY),
        facts=_facts(receipt)))
    assert _errors(tightened) == [("checks", "测试材料已经改变，用当前的测试材料重新运行检查")]


def test_a_release_waits_for_the_product_input_inside_the_commit(tmp_path):
    # R3（工单 #561）：工具许可之后、提交之前产品又收到输入时，提交事务里再判一次，结果是等待；
    # 写入口按安全节点等，醒来以后按此刻的 PRD 与交付重新裁决
    system, run_id = _accepted(tmp_path)
    system.add_input(run_id, "one more requirement")
    projection, receipt = _delivery_ready(system.project(run_id))
    events = tuple(system.store.list_events(run_id))
    assert pending_product_input(projection, list(events))
    tightened = WATCHED_OUTPUTS.submission(_structured(
        projection, "quality",
        review("release", "verified", checks=["smoke"], basis_delivery_spec_hash=DELIVERY),
        facts=_facts(receipt), events=events, commit=True))
    assert tightened.wait and not tightened.accepted


def test_every_requirement_of_the_product_spec_is_recorded_exactly_once(tmp_path):
    # R3：现有结构说明按当前 PRD 的每条要求各记一次
    system, run_id = _accepted(tmp_path)
    base = system.project(run_id)
    receipt = _receipt("smoke", "engineering", spec_hash=base.product_spec.content_hash, activation="act")
    projection = replace(_working(replace(base, kind="onboarding", snapshot={"tree_digest": TREE},
                                         last_activations={"engineering": "act"}), "engineering"))
    tightened = WATCHED_OUTPUTS.submission(_structured(projection, "engineering", structure(
        requirement_locations=[{"requirement": "something else", "locations": ["src/echo.py"]}]),
        facts=_facts(receipt)))
    assert [field for field, _message in _errors(tightened)] == ["requirement_locations"]
    assert "missing:" in tightened.errors[0].message


def test_a_boundary_marked_design_not_implemented_is_not_an_existing_defect(tmp_path):
    # R3：带标记的边界条目是设计里描述、代码尚未实现的能力，不能记成现有缺陷
    system, run_id = _accepted(tmp_path, requirements=["login flow"],
                               boundaries=[f"login flow: {MARK}"])
    base = system.project(run_id)
    structure_record = {"content_hash": "sha256:" + "2" * 64, "revision": 1,
                       "product_spec_hash": base.product_spec.content_hash, "issuer": "engineering",
                       "code_tree_digest": TREE}
    receipt = _receipt("smoke", "quality", spec_hash=base.product_spec.content_hash, activation="act_q",
                       exit_code=1)
    projection = replace(_working(replace(base, kind="onboarding", structure=structure_record,
                                         snapshot={"tree_digest": TREE},
                                         last_activations={"quality": "act_q"}), "quality"))
    # 逐条结论覆盖当前 PRD 的每条要求（S1d 起这条检查也在这里）：这一条要求对应的能力还只是设计
    tightened = WATCHED_OUTPUTS.submission(_structured(projection, "quality", baseline_review(
        conclusions=[{"requirement": "login flow", "status": "existing_defect", "evidence": "smoke"}]),
        facts=_facts(receipt)))
    assert [field for field, _message in _errors(tightened)] == ["conclusions[0].status"]
    assert MARK in tightened.errors[0].message


def test_a_submission_that_the_kernel_rejects_is_never_accepted_by_the_tightening_check(tmp_path):
    # R2：收紧检查只收窄：它放行的那一次，内核的拒绝照样生效（内核先判，这里只多拒绝）
    from harness.actions import FactsQuery
    from harness.adjudication import proposal_decision
    from harness.environment import LocalEnvironment

    system, run_id = _accepted(tmp_path)
    projection = _working(system.project(run_id), "product")
    environment = LocalEnvironment(system.workspace(run_id))
    facts = environment.query(FactsQuery(tree=True)).tree
    # 依据的 PRD 版本不是当前版本：内核的提案合同拒绝；收紧检查自己的三条都通过（输入版本已进来、
    # 修订写了改动说明、有效决定为空也声明了空），所以这一次只有内核在拒绝
    proposal = product_spec(basis_product_spec_hash="sha256:not-current",
                            change_record={"rationale": "changed the goal", "changed": [], "retained": [],
                                           "retired": []})
    decision = proposal_decision(adjudication_view(projection), department="product", proposal=proposal, facts=facts,
                                 events=system.store.list_events(run_id), tightening=WATCHED_OUTPUTS)
    assert not decision.accepted
    assert decision.errors and decision.errors[0].field == "basis_product_spec_hash"

# 被核验方与核验角色之间问答的事实与解释（工单 #554，验证的独立性设计说明「先判断后看解释」；工单 #1401 按核验声明取
# 这一对角色，不按部门名）：核验角色的请求里可以放入的被核验方内容由一个纯函数算出来——事实部分总在，解释部分
# 只在它对当前交付提交结论以后进入它之后的请求；新的交付到达后按新交付重新计算。交付到达的通知只发给核验交付的
# 那个角色。同一组断言在默认定义与一份把两个角色都改名的定义下各跑一遍。
#
# 单元层：只用内存里的事件与交付说明，不起目录、不起进程、不连网络。

import json
import re
from pathlib import Path

import pytest

from harness.context import (ContextAssembler, _current_work, engineering_facts_text, prior_round_outcome,
                             quality_engineering_content, work_notifications)
from harness.definitions import DEFINITIONS, Definitions, VerificationDeclaration
from harness.models import (ArtifactRef, DeliverySpec, Event, EventType, ProductDecision, ProductSpec,
                            ProjectEventType, RunProjection)

# 一份把被核验方与核验角色都改名的定义：两个名字都不是默认定义里的角色
RENAMED = {"engineering": "build", "quality": "inspection"}


def _renamed_rule(name: str) -> str:
    # 规则登记的条目名按角色分段（roles.<角色>.visibility），跟着角色编号换
    return ".".join(RENAMED.get(part, part) for part in name.split("."))


def _renamed() -> Definitions:
    # 发布的那份定义的一份副本：按 RENAMED 换掉角色编号（内存里换，其余内容照旧）
    def name(value: str) -> str:
        return RENAMED.get(value, value)

    organization = DEFINITIONS.organization
    declaration = organization.verification or DEFINITIONS.verification
    verification = VerificationDeclaration(
        verifiers=tuple(
            verifier.model_copy(update={
                "role": name(verifier.role),
                "verifies": tuple(verified.model_copy(update={"role": name(verified.role)})
                                  for verified in verifier.verifies)})
            for verifier in declaration.verifiers),
        write_scopes={name(role): scope for role, scope in declaration.write_scopes.items()})
    return DEFINITIONS.model_copy(update={
        "organization": organization.model_copy(update={
            "departments": tuple(department.model_copy(update={
                "id": name(department.id), "roles": tuple(name(role) for role in department.roles)})
                for department in organization.departments),
            "verification": verification}),
        "roles": {name(role): definition for role, definition in DEFINITIONS.roles.items()},
        "rules": {_renamed_rule(rule): definition for rule, definition in DEFINITIONS.rules.items()},
        "proposal_contracts": DEFINITIONS.proposal_contracts.model_copy(
            update={"roles": {name(role): contract
                              for role, contract in DEFINITIONS.proposal_contracts.roles.items()}}),
        "work_items": DEFINITIONS.work_items.model_copy(update={
            "kinds": {kind: definition.model_copy(update={
                "departments": {name(role): work for role, work in definition.departments.items()}})
                for kind, definition in DEFINITIONS.work_items.kinds.items()}}),
    })


RENAMED_DEFINITIONS = _renamed()

# 两种定义：默认的三部门（核验角色叫质检），与一份把被核验方与核验角色都改名的定义
CASES = [pytest.param(DEFINITIONS, "engineering", "quality", id="default"),
         pytest.param(RENAMED_DEFINITIONS, "build", "inspection", id="renamed")]


def _event(position: int, type: str, payload: dict, *, session_id: str | None = None,
           department: str | None = None) -> Event:
    return Event(
        event_id=f"evt_{position}", run_id="run_1", type=type, role=None, parent_event_id=None,
        state_before="running", state_after="running", payload=payload, artifact_hashes=[],
        session_id=session_id, provider=None, model=None, context_digest=None, stop_reason=None,
        error=None, created_at="2026-10-24T00:00:00Z", position=position, stream="run_1",
        stream_version=position, project_id=None, work_item_id=None, department=department,
    )


def _delivery(content_hash: str = "sha256:delivery-1", *, verified: str = "engineering") -> DeliverySpec:
    return DeliverySpec(
        id="del_1", run_id="run_1", revision=1, parent_hash=None, content_hash=content_hash,
        issuer=verified, status="active", created_event_id="evt_1",
        product_spec_hash="sha256:spec-1", effective_contract_hash="sha256:contract-1",
        summary="大写输出", files=["src/echo.py"], check_names=["smoke"], checks=[],
        known_risks=["没有空行结尾"], code_tree_digest="sha256:tree-1",
        tree_ref=ArtifactRef(kind="tree", content_hash=content_hash, path="run_1/tree"),
    )


def _asked_event(position: int = 1, *, verified: str = "engineering",
                 verifier: str = "quality") -> Event:
    # 被核验方问核验角色：问题与背景分成事实与解释两部分（工单 #554）
    return _event(position, EventType.ASK_STARTED, {
        "requester": verified,
        "recipient": verifier,
        "question": "",
        "background": "",
        "expected": "结论",
        "facts": "接口：echo <文本>，大写输出",
        "explanation": "这样实现是因为历史用例要求大写",
        "branch_session_id": "ses_ask_qua_1",
    }, session_id="ses_eng_1", department=verified)


def _verifier_asked_event(position: int = 2, *, verified: str = "engineering",
                          verifier: str = "quality") -> Event:
    # 核验角色问被核验方：问题不带事实与解释的拆分（那是被核验方给出的内容才拆）
    return _event(position, EventType.ASK_STARTED, {
        "requester": verifier,
        "recipient": verified,
        "question": "检查项覆盖了换行吗？",
        "background": "缺陷记录之前核对",
        "expected": "结论",
        "branch_session_id": "ses_ask_eng_1",
    }, session_id="ses_qua_1", department=verifier)


def _answered_event(position: int = 3, *, verified: str = "engineering",
                    verifier: str = "quality") -> Event:
    # 被核验方在分支里回答核验角色：回答分成事实与解释两部分
    return _event(position, EventType.ASK_ANSWERED, {
        "requester": verifier,
        "recipient": verified,
        "status": "answered",
        "answer": "",
        "facts": "检查脚本不用改",
        "explanation": "改动风险低，评审时已确认",
    }, session_id="ses_ask_eng_1", department=verified)


def _judgement_event(position: int = 3, delivery_hash: str = "sha256:delivery-1",
                     verifier: str = "quality") -> Event:
    # 核验角色对当前交付提交结论：缺陷记录或放行都算
    return _event(position, EventType.QA_SUBMITTED, {
        "delivery_spec_hash": delivery_hash,
        "verdict": "rework_engineering",
    }, session_id="ses_qua_1", department=verifier)


@pytest.mark.parametrize("definitions, verified, verifier", CASES)
def test_the_answer_and_the_question_carry_only_facts_before_the_conclusion(definitions, verified, verifier):
    # 通道二与通道三：核验角色收到的被核验方的回答、核验角色分支看到的被核验方的问题，
    # 解释部分在它对当前交付下结论以前不给
    delivery = _delivery(verified=verified)
    events = [_event(1, EventType.DELIVERY_ACCEPTED, {"content_hash": delivery.content_hash}),
              _asked_event(2, verified=verified, verifier=verifier),
              _verifier_asked_event(3, verified=verified, verifier=verifier),
              _answered_event(4, verified=verified, verifier=verifier)]
    content = quality_engineering_content(events, delivery=delivery, definitions=definitions)
    assert content["explanation_visible"] is False
    assert len(content["answers"]) == 1
    answer = content["answers"][0]
    assert engineering_facts_text(answer, part="answer", explanation_visible=False) == "检查脚本不用改"
    # 提交结论以后：解释部分进入
    content = quality_engineering_content(events + [_judgement_event(5, verifier=verifier)], delivery=delivery,
                                          definitions=definitions)
    answer = content["answers"][0]
    assert "改动风险低" in engineering_facts_text(answer, part="answer", explanation_visible=True)
    assert content["explanations"], content


@pytest.mark.parametrize("definitions, verified, verifier", CASES)
def test_a_new_delivery_hides_the_explanation_again(definitions, verified, verifier):
    # 新的交付到达后按新交付重新计算：此前全部被核验方内容的解释部分重新藏起来
    first = _delivery("sha256:delivery-1", verified=verified)
    events = [_event(1, EventType.DELIVERY_ACCEPTED, {"content_hash": first.content_hash}),
              _asked_event(2, verified=verified, verifier=verifier),
              _verifier_asked_event(3, verified=verified, verifier=verifier),
              _answered_event(4, verified=verified, verifier=verifier),
              _judgement_event(5, verifier=verifier)]
    assert quality_engineering_content(events, delivery=first, definitions=definitions)["explanation_visible"] is True

    second = _delivery("sha256:delivery-2", verified=verified)
    events = events + [_event(6, EventType.DELIVERY_ACCEPTED, {"content_hash": second.content_hash})]
    content = quality_engineering_content(events, delivery=second, definitions=definitions)
    assert content["explanation_visible"] is False
    assert "summary" not in content["delivery"]
    assert content["explanations"] == []
    answer = content["answers"][0]
    assert engineering_facts_text(answer, part="answer", explanation_visible=False) == "检查脚本不用改"


@pytest.mark.parametrize("definitions, verified, verifier", CASES)
def test_without_a_delivery_the_explanation_never_shows(definitions, verified, verifier):
    # 还没有交付（预测性探索）：核验角色只看到事实部分
    events = [_asked_event(1, verified=verified, verifier=verifier),
              _verifier_asked_event(2, verified=verified, verifier=verifier),
              _answered_event(3, verified=verified, verifier=verifier)]
    content = quality_engineering_content(events, definitions=definitions)
    assert content["explanation_visible"] is False
    assert content["delivery"] is None


@pytest.mark.parametrize("definitions, verified, verifier", CASES)
def test_the_delivery_arrival_is_notified_to_the_role_that_verifies_it(definitions, verified, verifier):
    # 交付到达只通知核验交付的那个角色（核验声明，工单 #1401）：它面对的代码随交付变化
    delivery = _delivery(verified=verified)
    events = [_event(1, EventType.DELIVERY_ACCEPTED, {"content_hash": delivery.content_hash},
                     session_id="ses_eng_1", department=verified)]
    projection = RunProjection(run_id="run_1", delivery_specs=[delivery])
    received = work_notifications(projection, events, verifier, "ses_qua_1", definitions=definitions)
    assert [item["kind"] for item in received] == ["delivery_arrived"]
    # 交这份交付的角色自己、不核验交付的角色都不收到这条通知
    for department in (verified, "product"):
        assert work_notifications(projection, events, department, "ses_other_1",
                                  definitions=definitions) == []


REPO_ROOT = Path(__file__).resolve().parents[2]
NAMED_FILES = [REPO_ROOT / "harness" / "context.py", REPO_ROOT / "harness" / "parameters.py"]


def _department_names() -> list[str]:
    # 组织定义里的部门标识：装配与参数不带这些名称，角色由定义给出
    organization = json.loads(
        (REPO_ROOT / "harness" / "definitions" / "organization.json").read_text(encoding="utf-8"))
    return [item["id"] for item in organization["departments"]]


def _hits(source: str, names: list[str]) -> list[str]:
    # 命中：名称在源码里作为一个整词出现（`product_spec` 不含整词 `product`，下划线是词内字符）
    found: list[str] = []
    for number, line in enumerate(source.splitlines(), start=1):
        for name in names:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", line):
                found.append(f"{number}: {name} — {line.strip()}")
    return found


def test_the_assembly_and_the_parameters_name_no_role_from_the_definitions():
    # 验收第 4 条（工单 #1401）：装配与参数按定义里的角色取，两个文件里不出现部门名作为整词
    names = _department_names()
    assert names, "组织定义里没有部门"
    for path in NAMED_FILES:
        assert _hits(path.read_text(encoding="utf-8"), names) == [], path.name


def _spec(content_hash: str = "sha256:spec-1") -> ProductSpec:
    return ProductSpec(id="spec_1", run_id="run_1", revision=1, parent_hash=None, content_hash=content_hash,
                       issuer="requirements", status="active", created_event_id="evt_1", goal="echo",
                       requirements=["print the argument"], boundaries=[], constraints=[],
                       acceptance_criteria=["prints the argument"], fatal_conditions=[], non_goals=[],
                       decision_changes=[], change_record=None, input_version=1)


def _decision() -> ProductDecision:
    return ProductDecision(id="dec_1", run_id="run_1", content_hash="sha256:decision-1",
                           created_event_id="evt_2", product_spec_hash="sha256:spec-1",
                           statement="拒绝未知的参数", rationale="参数错误要与正常输出分得开")


def test_the_current_work_text_comes_from_the_definition_per_role():
    # 「现在要做的事」一段从定义里事项种类为每个角色写的那一句读（工单 #1401），两种情形的替代也写在定义里；
    # 同一句话在把角色改名的定义下按改名后的角色读到，取法里没有部门名
    change = RunProjection(run_id="run_1", kind="change")
    implementing = "依据当前产品要求实现、运行检查并提交交付。"
    assert _current_work(change, "engineering", definitions=DEFINITIONS)["work"] == implementing
    after_decision = "依据 current_product_decisions 中已正式接纳的有效决定继续当前工程工作。"
    deciding = RunProjection(run_id="run_1", kind="change", effective_decisions=[_decision()])
    assert _current_work(deciding, "engineering", definitions=DEFINITIONS)["work"] == after_decision
    assert _current_work(deciding, "build", definitions=RENAMED_DEFINITIONS)["work"] == after_decision
    # 建档里产品收到新的基线核验要求返工：读到定义里写的返工那一句
    onboarding = RunProjection(run_id="run_1", kind="onboarding", product_spec=_spec(),
                               baseline_review={"verdict": "rework_product",
                                                "product_spec_hash": "sha256:spec-1"})
    assert _current_work(onboarding, "product", definitions=DEFINITIONS)["work"] == (
        "根据基线核验中 unsupported 的结论与遗漏修改初始 PRD 的描述，并提交新的 ProductSpec。")


def test_the_prior_round_material_follows_what_the_role_submits():
    # 修改轮的常驻材料（工单 #1401）：给哪种成果的原文按角色的提案合同取，不按部门名；
    # 两种成果都不交的角色（核验角色）不给上一轮的原文
    assert prior_round_outcome({"product_spec": {}, "product_decision": {}}) == "product_spec"
    assert prior_round_outcome({"structure": {}}) == "structure"
    assert prior_round_outcome({"qa_review": {}, "independent_judgement": {}}) is None


class _CandidateEvent:
    # 上一轮建档候选的事件：修改轮的常驻材料按它的载荷取
    type = ProjectEventType.INITIAL_PRD_PROPOSED
    payload = {"run_id": "run_0", "round": 1, "prd": {"content_hash": "sha256:prd-0"},
               "structure": {"content_hash": "sha256:structure-0"}}


class _CandidateStore:
    def get_project_event(self, event_id: str) -> _CandidateEvent:
        return _CandidateEvent()


def test_a_role_that_submits_neither_outcome_gets_no_prior_round_material():
    # 核验角色即使可见范围里写了修改轮的常驻材料，也没有上一轮的原文给它：它不交这两种成果
    assembler = ContextAssembler(artifacts=object(), store=_CandidateStore(), tightening=None)
    projection = RunProjection(run_id="run_1", kind="onboarding",
                               onboarding_basis={"candidate_event_id": "evt_9"})
    assert assembler._prior_parts(projection, "inspection", ("prior_round",), RENAMED_DEFINITIONS) == []

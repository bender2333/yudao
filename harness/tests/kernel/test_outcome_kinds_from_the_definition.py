# 内核按提案合同核对一种没见过的成果种类（工单 #1456；形态与核验角色设计说明「四层各认识什么」、
# 骨架与应用设计说明「其他路由：骨架要满足的条件」中「第二种路由可以带来新的工具、提案与成果种类」、「裁决的分工：内核的通用检查与路由的收紧检查」）。
#
# 守 R1「写入先过裁决」：裁决只认「某种成果的某一版及其依据」，按定义里写的那几条通用条件核对。
# 用例只在内存里换一份定义——多一种成果种类、一个提交它的工具、几条条件——看提案能不能交、能不能按合同
# 接纳或拒绝；内核模块一行不改。条件读现有成果的那一版（PRD）与新种类自己的各版（不重复接纳），
# 检查回执绑定的是合同里写的那个名称：哪几种成果参与、有几种参与都来自定义。
#
# 不起数据库、不跑模型、不用子进程与临时目录，属于单元层。

from __future__ import annotations

import pytest

from harness import validation
from harness.actions import CheckReceipt, TreeFacts
from harness.definitions import DEFINITIONS, ConditionBinding, Definitions, ProposalCondition, Tool
from harness.kernel_events import canonical_hash
from harness.minimal_projection import AcceptedArtifact, MinimalProjection
from harness.models import RunProjection, SessionRecord
from harness.tightening import WATCHED_OUTPUTS

# 一种这份定义里本来没有的成果种类，与它读出、绑定现有成果的那一版
NEW_KIND = "matter_note"
SPEC_HASH = "sha256:" + "a" * 64
TREE = "sha256:tree"

_FACTS = TreeFacts(
    digest=TREE, files=(), hashes=(),
    checks=(CheckReceipt(name="smoke", department="engineering", exit_code=0, summary="ran", snapshot_hash=TREE,
                         bindings={"product_spec": SPEC_HASH}, activation_id="act_e"),),
)


def _conditions() -> tuple[ProposalCondition, ...]:
    # 新种类的三条通用条件：依据的是当前那一版 PRD；列出的检查有绑定这一版 PRD 的回执；
    # 同样内容的不重复接纳（比的是这一种成果自己当前有效的各版）
    return (
        ProposalCondition(condition="basis_current", field="basis_product_spec_hash", target="product_spec"),
        ProposalCondition(condition="check_receipts", department="engineering",
                          names={"field": "check_names"},
                          bind=(ConditionBinding(field="product_spec_hash", target="product_spec"),),
                          message="no run_check receipt named {name} bound to the current version"),
        ProposalCondition(condition="no_duplicate_content", collection=NEW_KIND, content=("statement",),
                          bind=(), field="statement", message="this note has already been accepted"),
    )


def _definitions() -> Definitions:
    # 只写定义：多一个提交这类成果的工具（写进工程在这一种活里的工具清单），多一组条件。
    # 内核模块一行不改
    tool = Tool(kind="host", proposal=NEW_KIND, description="交一份只在这份定义里有的成果", parameters={})
    roles = dict(DEFINITIONS.roles)
    roles["engineering"] = DEFINITIONS.roles["engineering"].model_copy(
        update={"tools": (*DEFINITIONS.roles["engineering"].tools, "submit_matter_note")})
    kinds = dict(DEFINITIONS.work_items.kinds)
    change = kinds["change"]
    departments = dict(change.departments)
    departments["engineering"] = change.departments["engineering"].model_copy(
        update={"tools": (*change.departments["engineering"].tools, "submit_matter_note")})
    kinds["change"] = change.model_copy(update={"departments": departments})
    contracts = DEFINITIONS.proposal_contracts.model_copy(
        update={"conditions": {**DEFINITIONS.proposal_contracts.conditions, NEW_KIND: _conditions()}})
    return DEFINITIONS.model_copy(update={
        "tools": {**DEFINITIONS.tools, "submit_matter_note": tool},
        "roles": roles,
        "work_items": DEFINITIONS.work_items.model_copy(update={"kinds": kinds}),
        "proposal_contracts": contracts,
    })


def _minimal(accepted: tuple[AcceptedArtifact, ...] = ()) -> MinimalProjection:
    # 一件已经接纳的 PRD 与这种新成果当前有效的各版（不重复接纳读后者）
    return MinimalProjection(
        run_id="run_matter",
        artifacts={"product_spec": AcceptedArtifact(version=1, content_hash=SPEC_HASH, issuer="product")},
        versions={NEW_KIND: accepted} if accepted else {},
    )


def _projection() -> RunProjection:
    # 工程这一轮正在工作：这个部门此刻能交的种类按定义算（收窄由路由的收紧检查给出）
    return RunProjection(run_id="run_matter", kind="change",
                         sessions={"engineering": SessionRecord(
                             session_id="ses_engineering", department="engineering", status="active")})


def _decision(proposal: dict, *, minimal: MinimalProjection | None = None,
              facts: TreeFacts = _FACTS) -> validation.ProposalDecision:
    view = validation.AdjudicationView(minimal=minimal or _minimal(), state=_projection())
    return validation.evaluate_proposal(view, department="engineering", proposal=proposal, facts=facts,
                                        tightening=WATCHED_OUTPUTS, events=[], definitions=_definitions())


def _proposal(**extra: object) -> dict:
    return {"kind": NEW_KIND, "statement": "一条只在这份定义里有的成果", "check_names": ["smoke"],
            "basis_product_spec_hash": SPEC_HASH, **extra}


def test_a_kind_only_the_definition_knows_is_accepted_by_its_contract() -> None:
    decision = _decision(_proposal())
    assert decision.accepted, [error.to_dict() for error in decision.errors]
    artifact = decision.artifact or {}
    assert (artifact["kind"], artifact["issuer"], artifact["revision"]) == (NEW_KIND, "engineering", 1)
    # 内核在合同的条件之外只盖统一字段：内容就是提案的参数（这一份收紧检查不组装新种类的内容）
    assert artifact["statement"] == "一条只在这份定义里有的成果"
    assert artifact["content_hash"] and artifact["status"] == "active"


def test_the_contract_rejects_the_new_kind_when_the_version_it_names_is_stale() -> None:
    # 条件 1 依据的是当前版本：写的不是当前那一版 PRD 时整次提交被拒绝，错误指向那个字段
    decision = _decision(_proposal(basis_product_spec_hash="sha256:" + "b" * 64))
    assert not decision.accepted
    assert [error.field for error in decision.errors] == ["basis_product_spec_hash"]


def test_the_contract_rejects_the_new_kind_when_a_check_has_no_receipt_bound_to_it() -> None:
    # 条件 2 按合同里写的名称取回执：这一版 PRD 绑定的回执不在时拒绝，错误指向列出的检查名那个字段
    decision = _decision(_proposal(check_names=["never-ran"]))
    assert not decision.accepted
    assert [error.field for error in decision.errors] == ["check_names"]
    # 回执绑定的那一版不是当前的 PRD 时同样拒绝：绑定关系来自回执，不是从部门或种类推出来的
    other = TreeFacts(digest=TREE, files=(), hashes=(),
                      checks=(CheckReceipt(name="smoke", department="engineering", exit_code=0, summary="ran",
                                           snapshot_hash=TREE,
                                           bindings={"product_spec": "sha256:" + "c" * 64}),))
    assert [error.field for error in _decision(_proposal(), facts=other).errors] == ["check_names"]


def test_the_contract_rejects_the_same_content_of_the_new_kind_twice() -> None:
    # 条件 3 比的是这一种成果自己当前有效的各版：同样内容已经被接纳过时拒绝
    statement = "一条只在这份定义里有的成果"
    accepted = AcceptedArtifact(version=1, content_hash=canonical_hash({"statement": statement}))
    decision = _decision(_proposal(), minimal=_minimal((accepted,)))
    assert not decision.accepted
    assert [error.field for error in decision.errors] == ["statement"]


def test_the_same_proposal_is_refused_by_a_definition_without_the_kind() -> None:
    # 对照：同一份提案在默认定义里交不上来，说明上面接纳的是新定义带来的种类，不是内核里写死的
    view = validation.AdjudicationView(minimal=_minimal(), state=_projection())
    decision = validation.evaluate_proposal(view, department="engineering", proposal=_proposal(), facts=_FACTS,
                                            tightening=WATCHED_OUTPUTS, events=[])
    assert [error.message for error in decision.errors] == [f"unknown proposal kind: '{NEW_KIND}'"]

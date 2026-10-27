# 基础规则第三条与第五条的收紧检查一侧：写入先过裁决，内核检查通过以后，路由的收紧检查只能拒绝或等待。
#
# 裁决分工（设计说明第 5.5 节，工单 #1095）：内核做通用检查（流版本、执行权、运行状态、边界、工具许可、
# 提案合同），通过以后在同一个写入事务里问路由的收紧检查一次，结果只有三种：通过、拒绝（写明原因）、
# 等待（写入口按安全节点等，工单 #561）。可断言的命题是：
#   ①收紧检查放行时，内核自己的拒绝照样生效——放行不是放行内核拒绝的东西；
#   ②收紧检查拒绝时提交被拒，原因取它给出的那一条；
#   ③收紧检查要等待时，提交不当场生效、工具调用不执行（等待由写入口的安全节点处理）。
# 用真实存储（LoopSystem.for_testing）与受控的收紧检查实现，不重跑运行、不开子进程，属于模块层。

import pytest

from harness.actions import FactsQuery
from harness.adapters.fake import FakeAdapter
from harness.adjudication import commit_decision, proposal_decision, tool_permission
from harness.adjudication import WorkBasis
from harness.contract_versions import ContractVersionError
from harness.environment import LocalEnvironment
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tightening_contract import accept
from harness.validation import (
    FieldError,
    TightenRequest,
    Tightened,
)

_KINDS = {"product_spec", "delivery_spec", "qa_review", "structure", "baseline_review", "product_decision"}

class _Passes:
    # 放行一切的收紧检查：用来证明内核的拒绝不因为这道检查通过而失效
    CONTRACT_VERSION = 1

    def kinds(self, request: TightenRequest) -> set[str]:
        return set(_KINDS)

    def offered(self, request: TightenRequest) -> list[str]:
        return []

    def tool(self, request: TightenRequest) -> Tightened:
        return Tightened()

    def submission(self, request: TightenRequest) -> Tightened:
        return Tightened()


class _Refuses:
    # 拒绝一切的收紧检查：原因由它给出，写入口照它的原因拒绝
    CONTRACT_VERSION = 1

    def kinds(self, request: TightenRequest) -> set[str]:
        return set(_KINDS)

    def offered(self, request: TightenRequest) -> list[str]:
        return []

    def tool(self, request: TightenRequest) -> Tightened:
        return Tightened(reason="the routing does not allow this tool now")

    def submission(self, request: TightenRequest) -> Tightened:
        return Tightened(errors=(FieldError("kind", "the routing does not allow this submission now"),))


class _Waits:
    # 要等待的收紧检查：提交不当场生效，工具调用不执行，由写入口的安全节点等（工单 #561）
    CONTRACT_VERSION = 1

    def kinds(self, request: TightenRequest) -> set[str]:
        return set(_KINDS)

    def offered(self, request: TightenRequest) -> list[str]:
        return []

    def tool(self, request: TightenRequest) -> Tightened:
        return Tightened(wait=True)

    def submission(self, request: TightenRequest) -> Tightened:
        return Tightened(wait=True)


class _RefusesWithErrors:
    # 拒绝时给的是字段错误而不是一句话：内核照第一条错误的原因拒绝
    CONTRACT_VERSION = 1

    def kinds(self, request: TightenRequest) -> set[str]:
        return set(_KINDS)

    def offered(self, request: TightenRequest) -> list[str]:
        return []

    def tool(self, request: TightenRequest) -> Tightened:
        return Tightened(errors=(FieldError("tool", "the routing does not allow this tool now"),))

    def submission(self, request: TightenRequest) -> Tightened:
        return Tightened()


class _DefersAtTheStart:
    # 工具许可时放行、等提交时才说「现在不行，以后再说」：一次推迟在提交这一步同样不当场生效
    CONTRACT_VERSION = 1

    def kinds(self, request: TightenRequest) -> set[str]:
        return set(_KINDS)

    def offered(self, request: TightenRequest) -> list[str]:
        return []

    def tool(self, request: TightenRequest) -> Tightened:
        return Tightened()

    def submission(self, request: TightenRequest) -> Tightened:
        if request.commit:
            return Tightened()
        return Tightened(reason="the routing refuses this submission now", deferred=True)


class _WaitsAtCommit:
    # 工具许可时没有等待，提交事务里新输入到达：只有提交这一步要等待（工单 #561 的那次竞态）
    CONTRACT_VERSION = 1

    def kinds(self, request: TightenRequest) -> set[str]:
        return set(_KINDS)

    def offered(self, request: TightenRequest) -> list[str]:
        return []

    def tool(self, request: TightenRequest) -> Tightened:
        return Tightened()

    def submission(self, request: TightenRequest) -> Tightened:
        return Tightened(wait=True) if request.commit else Tightened()


def _system(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([]))
    run_id = system.create_run("echo")
    projection = system.project(run_id)
    return system, run_id, projection


def _facts(system, run_id):
    return LocalEnvironment(system.workspace(run_id)).query(FactsQuery(tree=True)).tree


def test_the_three_tightening_implementations_declare_the_same_contract_version():
    # 缝的两侧按同一个契约版本对话：受控实现与内核接受的版本一致
    for implementation in (_Passes(), _Refuses(), _Waits()):
        assert accept(implementation) == 1


def test_a_kernel_rejection_stands_when_the_tightening_check_passes(tmp_path):
    # ①内核先判：提案依据的 PRD 版本不是当前版本，收紧检查放行也不改变这个结果
    system, run_id, projection = _system(tmp_path)
    facts = _facts(system, run_id)
    rejected = proposal_decision(projection, department="product",
                                 proposal=product_spec(basis_product_spec_hash="sha256:not-current"),
                                 facts=facts, events=system.store.list_events(run_id), tightening=_Passes())
    assert not rejected.accepted
    assert rejected.errors[0].field.startswith("basis"), rejected.errors[0].to_dict()


def test_a_rejection_from_the_tightening_check_is_reported_with_its_own_reason(tmp_path):
    # ②收紧检查拒绝时提交被拒，原因取它给出的那一条：内核通用检查全部通过也不行
    system, run_id, projection = _system(tmp_path)
    facts = _facts(system, run_id)
    rejected = proposal_decision(projection, department="product", proposal=product_spec(),
                                 facts=facts, events=system.store.list_events(run_id), tightening=_Refuses())
    assert not rejected.accepted
    assert [error.message for error in rejected.errors] == ["the routing does not allow this submission now"]


def test_a_tool_the_tightening_check_refuses_is_not_allowed(tmp_path):
    # ②工具许可同样只看结果：拒绝就是不允许执行，原因取收紧检查给出的那一条
    system, run_id, projection = _system(tmp_path)
    call = {"id": "call", "name": "write_file", "args": {"path": "src/echo.py", "content": "print(1)\n"}}
    permission = tool_permission(projection, call, department="engineering",
                                 basis=WorkBasis.current(projection, "engineering"), aborted=False,
                                 facts=_facts(system, run_id), events=system.store.list_events(run_id),
                                 tightening=_Refuses())
    assert not permission.allowed and not permission.stopped
    assert permission.reason == "the routing does not allow this tool now"


def test_a_waiting_tightening_check_makes_the_tool_wait_at_the_safe_node(tmp_path):
    # ③要等待时工具调用不执行：许可表达为等待，写入口在安全节点上等，醒来以后重新许可（工单 #561）
    system, run_id, projection = _system(tmp_path)
    call = {"id": "call", "name": "submit_review", "args": {"verdict": "release"}}
    permission = tool_permission(projection, call, department="quality",
                                 basis=WorkBasis.current(projection, "quality"), aborted=False,
                                 facts=_facts(system, run_id), events=system.store.list_events(run_id),
                                 tightening=_Waits())
    assert permission.wait_for_input and not permission.allowed and not permission.stopped


def test_a_waiting_tightening_check_at_commit_time_is_never_accepted(tmp_path):
    # ③提交事务里再判一次：要等待时这次提交不当场生效，交回部门等产品处理完再提交
    system, run_id, projection = _system(tmp_path)
    facts = _facts(system, run_id)
    events = system.store.list_events(run_id)
    proposal = product_spec()
    first = proposal_decision(projection, department="product", proposal=proposal, facts=facts,
                              events=events, tightening=_Passes())
    assert first.accepted, first.error_dicts
    committed = commit_decision(first, department="product", proposal=proposal, evaluated=projection,
                                facts=facts, current=projection, current_facts=facts, events=events,
                                tightening=_Waits())
    assert not committed.accepted
    assert committed.errors and committed.errors[0].field == "kind"


def test_a_tool_refused_with_field_errors_is_not_allowed(tmp_path):
    # ②拒绝也可以给字段错误：内核取第一条错误的原因拒绝，不因为它的形状不同就放行
    system, run_id, projection = _system(tmp_path)
    call = {"id": "call", "name": "write_file", "args": {"path": "src/echo.py", "content": "print(1)\n"}}
    permission = tool_permission(projection, call, department="engineering",
                                 basis=WorkBasis.current(projection, "engineering"), aborted=False,
                                 facts=_facts(system, run_id), events=system.store.list_events(run_id),
                                 tightening=_RefusesWithErrors())
    assert not permission.allowed and not permission.stopped
    assert permission.reason == "the routing does not allow this tool now"


def test_a_submission_the_tightening_check_defers_is_reported_as_a_field_error(tmp_path):
    # ②一次推迟在提案校验这一步同样不当场生效，原因写成字段错误交给部门
    system, run_id, projection = _system(tmp_path)
    facts = _facts(system, run_id)
    deferred = proposal_decision(projection, department="product", proposal=product_spec(), facts=facts,
                                 events=system.store.list_events(run_id), tightening=_DefersAtTheStart())
    assert not deferred.accepted
    assert [(error.field, error.message) for error in deferred.errors] == [
        ("proposal", "the routing refuses this submission now")]


def test_a_wait_that_only_appears_at_commit_time_leaves_the_submission_unapplied(tmp_path):
    # ③工具许可时还没有等待、提交事务里新输入到达：这次提交不当场生效（工单 #561 的那次竞态）
    system, run_id, projection = _system(tmp_path)
    facts = _facts(system, run_id)
    events = system.store.list_events(run_id)
    proposal = product_spec()
    first = proposal_decision(projection, department="product", proposal=proposal, facts=facts,
                              events=events, tightening=_WaitsAtCommit())
    assert first.accepted, first.error_dicts
    committed = commit_decision(first, department="product", proposal=proposal, evaluated=projection,
                                facts=facts, current=projection, current_facts=facts, events=events,
                                tightening=_WaitsAtCommit())
    assert not committed.accepted
    assert committed.errors and committed.errors[0].field == "kind"


def test_a_tightening_check_that_does_not_declare_a_version_is_refused(tmp_path):
    # 缝的另一侧按契约版本接受实现：没有声明版本、或者版本不在允许范围里的实现被拒绝（不静默跳过检查）
    class _NoVersion:
        def kinds(self, request: TightenRequest) -> set[str]:
            return set()

        def offered(self, request: TightenRequest) -> list[str]:
            return []

        def tool(self, request: TightenRequest) -> Tightened:
            return Tightened()

        def submission(self, request: TightenRequest) -> Tightened:
            return Tightened()

    # 契约版本不匹配是拒绝接上，不是放行
    with pytest.raises(ContractVersionError):
        accept(_NoVersion())


def test_the_tightening_check_cannot_accept_a_proposal_by_itself():
    # 缝的形状（R2 的交换字段）：收紧检查只回答通过、拒绝、等待，接纳的结论只能来自内核
    assert Tightened().accepted
    assert not Tightened(reason="because").accepted
    assert not Tightened(wait=True).accepted
    assert not Tightened(errors=(FieldError("kind", "because"),)).accepted

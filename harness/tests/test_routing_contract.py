# 路由契约与成果驱动路由（工单 #825；骨架与应用设计说明第 3.2、5.1、12 节；总图第四节「路由」缝）。
#
# 守的是 R2：契约的公开名称与版本、定义文件的格式（组织定义的 routing 与 routings.json 的对应）、
# 路由实现的导入方向；以及 R3：事项以什么结束只来自路由或边界的核对——路由给出停止原因，
# 薄驱动不再自己写这个判断。行为本身（关注的成果决定谁开工、一轮怎么结束）由现有的
# test_watched_relations.py 与事件序列基准守住，这里只补契约与那一条搬家。
#
# 读源码文件与投影对象，不起服务、不写文件，属于单元层。

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import contract_versions, routing_contract, watched_outputs
from harness.definitions import DEFINITIONS
from harness.models import EventType, RunProjection
from harness.watched_outputs import ROUTING

HARNESS = Path(__file__).resolve().parents[1]


def _imported(relative: str) -> set[str]:
    # 模块里的相对导入，按 harness 下的模块名给出（from . import x 记成 x）
    found: set[str] = set()
    for node in ast.walk(ast.parse((HARNESS / relative).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module is None:
                found.update(alias.name for alias in node.names)
            else:
                found.add(node.module)
    return found


def _event(kind: str, *, session_id: str | None = None, activation_id: str | None = None) -> object:
    payload = {"activation_id": activation_id} if activation_id is not None else {}
    return SimpleNamespace(type=kind, session_id=session_id, payload=payload)


def _running() -> RunProjection:
    return RunProjection(run_id="run", task="Build a CLI.")


def test_the_routing_implementation_declares_the_version_the_thin_driver_accepts():
    # R2：契约带版本，实现声明它实现哪一版，薄驱动在一个发布里接受当前版与上一版
    assert ROUTING.CONTRACT_VERSION == routing_contract.CURRENT_VERSION
    assert routing_contract.accept(ROUTING) == routing_contract.CURRENT_VERSION
    assert ROUTING.NAME == "watched_outputs" == DEFINITIONS.routing


def test_a_version_the_thin_driver_does_not_accept_fails_and_says_why():
    # R2：版本不合格时在开始一轮工作之前失败，说明里写明是哪一种实现、声明了哪一版、接受哪几版
    class Future:
        NAME = "future"
        CONTRACT_VERSION = routing_contract.CURRENT_VERSION + 1

    with pytest.raises(contract_versions.ContractVersionError) as raised:
        routing_contract.accept(Future)
    message = str(raised.value)
    assert "the routing implementation" in message
    assert str(Future.CONTRACT_VERSION) in message
    assert f"current {routing_contract.CURRENT_VERSION}" in message


def test_the_organization_definition_selects_the_implementation_by_name():
    # R2：定义里写明的名称按名称接上实现；名称没有实现时失败，写明有哪些可用的名称
    assert routing_contract.select(DEFINITIONS.routing) is ROUTING
    assert "watched_outputs" in routing_contract.registered()
    with pytest.raises(routing_contract.UnavailableRouting) as raised:
        routing_contract.select("task_pool")
    message = str(raised.value)
    assert "task_pool" in message and "watched_outputs" in message


def test_an_implementation_without_a_name_cannot_be_registered():
    # R2：名称是选择实现的键，声明不出来的实现接不上这条缝
    class Anonymous:
        CONTRACT_VERSION = routing_contract.CURRENT_VERSION

    with pytest.raises(routing_contract.UnavailableRouting) as raised:
        routing_contract.register(Anonymous())
    assert "NAME" in str(raised.value)


def test_the_routing_implementation_does_not_import_the_thin_driver_or_the_minimal_projection():
    # R2：路由模块不导入 orchestrator.py（薄驱动调用它，它不调用薄驱动）；路由不读最小投影
    imports = _imported("watched_outputs.py")
    assert "orchestrator" not in imports
    assert "minimal_projection" not in imports
    # 契约模块只导入内核与标准库（契约圈自己那一层由 test_contract_modules.py 核对）
    assert _imported("routing_contract.py") <= {"contract_versions", "models"}


def test_the_item_end_judgment_comes_from_the_routing():
    # R3：事项以什么结束由路由给出；薄驱动只把它的判断写成停止，不再自己写这个判断与这句话
    judgment = ROUTING.item_end(_running())
    assert judgment.stop_reason == "provider_error"
    assert judgment.message == "no department has new work"
    driver = (HARNESS / "orchestrator.py").read_text(encoding="utf-8")
    assert "no department has new work" not in driver
    assert judgment.message in (HARNESS / "watched_outputs.py").read_text(encoding="utf-8")


def test_who_is_waiting_follows_the_session_statuses():
    # R3：进程里没有正在工作的会话的部门在等待；还没有会话的部门同样在等待（重开以后可以被重新激活）
    assert watched_outputs.waiting_departments({"product": "active", "engineering": "idle"}) == {
        "engineering", "quality"}
    assert watched_outputs.waiting_departments({}) == set(DEFINITIONS.departments)


def test_the_ready_departments_are_the_watched_ones_that_are_waiting():
    # R3：关注的成果有了新东西、又在等待工作的部门开始一轮工作；一次一个部门（单步入口）
    view = _running()
    view.input_version = 1
    waiting = set(DEFINITIONS.departments)
    assert ROUTING.ready_departments(view, waiting=waiting) == ["product"]
    assert ROUTING.next_department(view, waiting=waiting) == "product"
    assert ROUTING.department_ready(view, department="product", waiting=waiting)
    assert not ROUTING.department_ready(view, department="engineering", waiting=waiting)
    # 正在工作的部门不再开始一轮工作
    assert ROUTING.ready_departments(view, waiting=set(DEFINITIONS.departments) - {"product"}) == []


def test_a_round_that_is_not_a_normal_end_has_no_outcome():
    # R3：暂停与失败不算正常结束的一轮（取消、上限、运行时间用完都落在这两种里）
    view = _running()
    for status in ("paused", "failed"):
        view.status = status
        assert ROUTING.round_end(view, [], department="engineering", session_id="ses_eng",
                                 activation_id="act_1") is None


def test_a_round_ends_by_an_accepted_proposal_or_a_text_reply():
    # R3：成果驱动的一轮以提交正式成果或回答用户结束（设计说明第 5.1 节）
    view = _running()
    started = _event(EventType.DEPARTMENT_ACTIVATED, session_id="ses_eng", activation_id="act_1")
    accepted = [_event(EventType.PROPOSAL_SUBMITTED, session_id="ses_eng")]
    ended = ROUTING.round_end(view, [started, *accepted], department="engineering",
                              session_id="ses_eng", activation_id="act_1")
    assert ended.outcome == "proposal_accepted"
    # 提交以后被拒绝的这一轮还没有交下正式成果，按文字回答记
    rejected = [_event(EventType.PROPOSAL_SUBMITTED, session_id="ses_eng"),
                _event(EventType.PROPOSAL_REJECTED, session_id="ses_eng")]
    ended = ROUTING.round_end(view, [started, *rejected], department="engineering",
                              session_id="ses_eng", activation_id="act_1")
    assert ended.outcome == "text_reply"
    ended = ROUTING.round_end(view, [started], department="engineering",
                              session_id="ses_eng", activation_id="act_1")
    assert ended.outcome == "text_reply"

# 路由契约与成果驱动路由（工单 #825 建、#861 第二版、#1164 第三版；骨架与应用设计说明第 3.2、5.1、5.4、12 节；
# 总图第四节「路由」缝）。
#
# 守的是 R2：契约的公开名称与版本、定义文件的格式（组织定义的 routing 与 routings.json 的对应）、
# 路由实现的导入方向；以及 R3：事项以什么结束只来自路由或边界的核对——路由给出停止原因，
# 薄驱动不再自己写这个判断；一轮以什么结束由路由按事件判断，执行契约的结果里没有结果种类。
# 行为本身（关注的成果决定谁开工、一轮怎么结束）由现有的 test_watched_relations.py 与事件序列基准守住，
# 这里只补契约与那几条搬家。
#
# 读源码文件与投影对象，不起服务、不写文件，属于单元层。

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import contract_versions, execution_contract, routing_contract, watched_outputs
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


def _event(kind: str, *, session_id: str | None = None, activation_id: str | None = None,
           name: str | None = None) -> object:
    payload: dict[str, object] = {}
    if activation_id is not None:
        payload["activation_id"] = activation_id
    if name is not None:
        payload["name"] = name
    return SimpleNamespace(type=kind, session_id=session_id, payload=payload)


def _running() -> RunProjection:
    return RunProjection(run_id="run", task="Build a CLI.")


@pytest.fixture
def probe_registry(monkeypatch):
    # 探针实现登记在一份临时的登记表里：这些用例不改模块加载时的那一份（工单 #1164 的用例用）
    monkeypatch.setattr(routing_contract, "_REGISTRY", dict(routing_contract._REGISTRY))

    def register(implementation: object) -> object:
        return routing_contract.register(implementation)

    return register


class _Events:
    # 事件库的替身：组装处交给路由的只读读取器只要事件库有 list_events(run_id) 这个读法
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = list(events or [])

    def list_events(self, run_id: str) -> list[object]:
        return list(self.events)

    def commit(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("the read-only reader must not write events")


class _WithFacts:
    # 声明了 use_facts 的探针路由：契约第三版的第二种路由就是这样拿到只读的事件读取器（工单 #1164）
    NAME = "with_facts"
    CONTRACT_VERSION = 3

    def __init__(self) -> None:
        self.reader: object | None = None

    def check_definition(self, definitions: object) -> None:
        return None

    def use_facts(self, reader: object) -> None:
        self.reader = reader


class _WithoutFacts:
    # 没有声明 use_facts 的探针路由：第二版的实现，照旧被接受，组装处不调用这个方法
    NAME = "without_facts"
    CONTRACT_VERSION = 2

    def check_definition(self, definitions: object) -> None:
        return None


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


def test_the_contract_accepts_the_previous_version_and_rejects_the_others():
    # R2（第三版，工单 #1164）：契约版本是 3；声明第二版的实现仍被接受（一版兼容），更早的与更高的都拒绝
    assert routing_contract.CURRENT_VERSION == 3
    assert routing_contract.PREVIOUS_VERSION == 2
    # 成果驱动的实现声明的就是这一版
    assert ROUTING.CONTRACT_VERSION == 3

    class Previous:
        NAME = "previous"
        CONTRACT_VERSION = 2

    class TooOld:
        NAME = "too_old"
        CONTRACT_VERSION = 1

    class Future:
        NAME = "future"
        CONTRACT_VERSION = 4

    assert routing_contract.accept(Previous) == 2
    for rejected in (TooOld, Future):
        with pytest.raises(contract_versions.ContractVersionError) as raised:
            routing_contract.accept(rejected)
        assert str(rejected.CONTRACT_VERSION) in str(raised.value)


def test_the_assembly_hands_a_read_only_event_reader_to_a_routing_that_declares_use_facts(probe_registry):
    # R2（第三版，工单 #1164）：组装处接上声明了 use_facts 的路由以后，把事件库的只读读取器交给它；
    # 读取器只有 list_events，没有写事件的方法，事件库本身也不交出去
    event = _event(EventType.ARTIFACT_ACCEPTED)
    implementation = _WithFacts()
    probe_registry(implementation)
    store = _Events([event])

    assert routing_contract.select(implementation.NAME, DEFINITIONS, store=store) is implementation
    reader = implementation.reader
    assert {name for name in dir(reader) if not name.startswith("_")} == {"list_events"}
    for writing in ("commit", "append", "replace_projection", "claim_execution_right", "close", "notify"):
        assert not hasattr(reader, writing), writing
    assert reader is not store
    assert reader.list_events("run") == [event]


def test_a_routing_that_does_not_declare_use_facts_is_not_called(probe_registry):
    # R2（第三版，工单 #1164）：没有声明的路由不受影响，组装处不调用这个方法，有没有事件库都照常接上
    implementation = _WithoutFacts()
    probe_registry(implementation)
    assert routing_contract.select(implementation.NAME, DEFINITIONS, store=_Events()) is implementation
    assert routing_contract.select(implementation.NAME, DEFINITIONS) is implementation
    # 成果驱动就没有这个方法
    assert not hasattr(ROUTING, "use_facts")
    assert routing_contract.select(DEFINITIONS.routing) is ROUTING


def test_a_routing_that_needs_the_event_log_cannot_be_selected_without_an_event_store(probe_registry):
    # R2（第三版，工单 #1164）：声明了 use_facts 而组装处没有事件库可交时，在开始一轮工作之前失败，
    # 不留下一个读不到事件的路由
    implementation = _WithFacts()
    probe_registry(implementation)
    with pytest.raises(routing_contract.UnavailableRouting) as raised:
        routing_contract.select(implementation.NAME, DEFINITIONS)
    message = str(raised.value)
    assert "use_facts" in message and implementation.NAME in message
    assert implementation.reader is None


def test_the_organization_definition_selects_the_implementation_by_name():
    # R2：定义里写明的名称按名称接上实现；名称没有实现时失败，写明有哪些可用的名称。
    # 例子里用的名称是「没有实现的那个」：task_pool 这个名称由只在测试里用的第二种路由登记（工单 #864），
    # 收集到这个仓库的测试时它已经接上了，不能拿它当没有实现的名称
    assert routing_contract.select(DEFINITIONS.routing) is ROUTING
    assert "watched_outputs" in routing_contract.registered()
    with pytest.raises(routing_contract.UnavailableRouting) as raised:
        routing_contract.select("task_board")
    message = str(raised.value)
    assert "task_board" in message and "watched_outputs" in message


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
    # 契约模块只导入内核（定义、事件信封所在的 kernel_events）与标准库（契约圈自己那一层由
    # test_contract_modules.py 核对）；事件信封随 S5a（工单 #828）从 models.py 搬进内核事件模块
    assert _imported("routing_contract.py") <= {"contract_versions", "definitions", "kernel_events"}


def test_the_item_end_judgment_comes_from_the_routing():
    # R3：事项以什么结束由路由给出；薄驱动只把它的判断写成停止，不再自己写这个判断与这句话。
    # 原因出自路由自己的一份定义（设计说明第 5.4 节第 7 条，工单 #861），不在内核的停止原因清单里
    judgment = ROUTING.item_end(_running())
    assert judgment.stop_reason == "no_new_work"
    assert judgment.message == "no department has new work"
    declared = DEFINITIONS.routing_definition().end_reasons
    assert judgment.stop_reason in declared
    assert judgment.stop_reason not in DEFINITIONS.stop_reasons
    assert DEFINITIONS.stop_reason(judgment.stop_reason).outcome == declared[judgment.stop_reason].outcome
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


def test_a_round_that_called_a_proposal_method_has_submitted_a_formal_output():
    # R3：薄驱动拿到一轮结果以后先问路由这一轮以什么结束、再经写入口提交（设计说明第 5.3、5.4 节第 5 条，
    # 工单 #861）：提交还没有写入时，这一轮记下的提议方式（提交类工具的调用）就是「交了正式成果」的依据。
    # 别的工具调用不算
    view = _running()
    started = _event(EventType.DEPARTMENT_ACTIVATED, session_id="ses_eng", activation_id="act_1")
    submitted = [_event(EventType.TOOL_CALLED, session_id="ses_eng", name="submit_delivery")]
    ended = ROUTING.round_end(view, [started, *submitted], department="engineering",
                              session_id="ses_eng", activation_id="act_1")
    assert ended.outcome == "proposal_accepted"
    other = [_event(EventType.TOOL_CALLED, session_id="ses_eng", name="read_file")]
    ended = ROUTING.round_end(view, [started, *other], department="engineering",
                              session_id="ses_eng", activation_id="act_1")
    assert ended.outcome == "text_reply"


def test_the_routing_work_reference_is_empty_for_watched_outputs():
    # R2：开始一轮工作的请求带路由自己的工作引用（设计说明第 5.4 节第 4 条，工单 #861）；
    # 成果驱动不用它时为空
    assert ROUTING.work_reference(_running(), department="product") is None
    # 执行契约的请求与结果都带这一项：请求里的工作引用原样交给装配（工单 #826）
    assert "work_ref" in execution_contract.RoundRequest.__dataclass_fields__
    assert {"events", "stop_reason", "version"} <= set(execution_contract.RoundResult.__dataclass_fields__)


def test_the_execution_result_has_no_outcome_kinds():
    # R2：执行契约的结果只剩这一轮写下的事件范围与停止原因（设计说明第 5.3 节输出，工单 #861）：
    # 「提交了正式成果」「回答了询问」不是契约里的种类，是成果驱动路由按事件作的判断
    contract = (HARNESS / "execution_contract.py").read_text(encoding="utf-8")
    engine = (HARNESS / "engine.py").read_text(encoding="utf-8")
    assert "RoundResult" in contract and "RoundResult" in engine
    for removed in ("class Submitted", "class Answered", "class Stopped", "StepResult"):
        assert removed not in contract.replace("RoundResult", ""), removed
        assert removed not in engine, removed

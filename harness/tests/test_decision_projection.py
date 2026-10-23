import sqlite3
import uuid

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.event_store import Command, StreamVersionConflict, run_stream
from harness.models import EventType
from harness.projection import saved_decision, saved_decisions
from harness.replay_check import PROJECTION_REASON, ReplayIntegrityError
from harness.runtime import LoopSystem
from harness.tests.contract_checks import assert_payloads_follow_contract
from harness.write_path import NewEvent

# 决定请求保存的投影：写入口在追加请求、回答与撤销事件的同一事务中更新它；按身份查找，按项目、事项、种类与状态
# 列出，并与日志末尾位置一起读取；删除保存的投影以后由重放补建。这里经写入口直接写入决定事件，检查保存的投影；
# 由流程编排发出请求、由命令回答的行为在 test_decisions.py。


def _plain_reply():
    # 部门回复文字、没有调用工具：连续 tool_call_required_limit 次以后运行在 safe node 暂停。
    # 恢复会取得执行权并推进这一步，但不会提交提案，也不进入下一个部门
    def reply(_call):
        return FakeTurn(transcript="no tool call in this reply")
    return reply

def _plain_replies(count: int = 8):
    # 一次恢复最多消费 tool_call_required_limit + 1 次回答（最后一次回答以后运行暂停）
    return [_plain_reply() for _ in range(count)]

def _requested(department: str = "product") -> NewEvent:
    return NewEvent(EventType.DECISION_REQUESTED, state_before="running", state_after="running",
                    actor="system", department=department, payload={
                        "kind": "model_unavailable", "blocks": "run",
                        "options": [{"id": "continue", "label": "继续执行"}, {"id": "stop", "label": "停止事项"}],
                        "description": f"{department} 部门的模型无法使用：Missing configuration: provider credential",
                        "facts": [], "department": department, "target": None,
                        "reason": "provider_unavailable", "message": "Missing configuration: provider credential",
                    })


def _answered(decision_id: str, option: str = "continue") -> NewEvent:
    return NewEvent(EventType.DECISION_ANSWERED, state_before="running", state_after="running",
                    actor="user:local", parent_event_id=decision_id,
                    payload={"decision_id": decision_id, "option": option, "note": None, "base_version": 1})


def _withdrawn(decision_id: str) -> NewEvent:
    return NewEvent(EventType.DECISION_WITHDRAWN, state_before="running", state_after="running",
                    actor="system", parent_event_id=decision_id,
                    payload={"decision_id": decision_id, "reason": "cancelled"})


def _command() -> Command:
    return Command(str(uuid.uuid4()), "decision.answer", "sha256:answer", "user:local")


def _runs(data_dir):
    # 两个项目各有事项与 run，另有一个不属于项目的 run
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    first = system.projects.register("项目一", "逐行文本处理工具")
    second = system.projects.register("项目二", "日志汇总工具")
    item_a, run_a = system.projects.start_work_item(first, "事项 A")
    item_b, run_b = system.projects.start_work_item(first, "事项 B")
    item_c, run_c = system.projects.start_work_item(second, "事项 C")
    bare = system.create_run("bare run")
    return system, {"first": first, "second": second, "item_a": item_a, "item_b": item_b, "item_c": item_c,
                    "run_a": run_a, "run_b": run_b, "run_c": run_c, "bare": bare}


def _append(system, run_id, *entries, command=None):
    return system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(*entries),
                                  command=command)


def _delete_saved_projections(data_dir):
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        connection.execute("DELETE FROM projections")
        connection.execute("DELETE FROM decisions")
        connection.commit()
    finally:
        connection.close()


def test_decision_requests_are_saved_with_their_events_and_listed_by_project_work_item_kind_and_status(data_dir):
    system, ids = _runs(data_dir)
    [request_a] = _append(system, ids["run_a"], _requested())
    [request_b] = _append(system, ids["run_b"], _requested("engineering"))
    [request_c] = _append(system, ids["run_c"], _requested())
    [request_bare] = _append(system, ids["bare"], _requested("quality"))
    command = _command()
    [answer] = _append(system, ids["run_b"], _answered(request_b.event_id), command=command)
    [withdrawal] = _append(system, ids["run_c"], _withdrawn(request_c.event_id))
    events = system.store.read(0, limit=10_000, types=[EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED,
                                                      EventType.DECISION_WITHDRAWN])
    assert [event.event_id for event in events] == [request_a.event_id, request_b.event_id, request_c.event_id,
                                                  request_bare.event_id, answer.event_id, withdrawal.event_id]
    assert_payloads_follow_contract(events)

    # 流程编排写入的请求与撤销由写入方声明提出者 system；命令写入的回答记下命令身份与提出者
    assert (request_a.actor, request_a.command_id) == ("system", None)
    assert (withdrawal.actor, withdrawal.command_id) == ("system", None)
    assert (answer.actor, answer.command_id) == ("user:local", command.command_id)
    stored = {event.event_id: event for event in events}
    assert (stored[answer.event_id].actor, stored[answer.event_id].command_id) == ("user:local", command.command_id)

    decision = saved_decision(system.store, request_b.event_id)
    assert (decision.stream, decision.run_id, decision.project_id, decision.work_item_id) == (
        run_stream(ids["run_b"]), ids["run_b"], ids["first"], ids["item_b"])
    assert (decision.kind, decision.blocks, decision.version, decision.status) == (
        "model_unavailable", "run", 1, "answered")
    assert decision.request == request_b.payload
    assert decision.requested_at == request_b.created_at
    assert decision.answer == {"event_id": answer.event_id, "option": "continue", "note": None, "base_version": 1,
                               "actor": "user:local", "command_id": command.command_id,
                               "answered_at": answer.created_at}
    assert saved_decision(system.store, request_c.event_id).withdrawal == {
        "event_id": withdrawal.event_id, "reason": "cancelled", "withdrawn_at": withdrawal.created_at}
    assert saved_decision(system.store, "evt_missing") is None

    def listed(**conditions):
        position, decisions = saved_decisions(system.store, **conditions)
        assert position == system.store.end_position()
        return [item.decision_id for item in decisions]

    # 按请求的先后列出；各个条件取交集，同一个条件的多个值取并集
    assert listed() == [request_a.event_id, request_b.event_id, request_c.event_id, request_bare.event_id]
    assert listed(projects=(ids["first"],)) == [request_a.event_id, request_b.event_id]
    assert listed(projects=(ids["first"],), statuses=("open",)) == [request_a.event_id]
    assert listed(work_items=(ids["item_b"], ids["item_c"])) == [request_b.event_id, request_c.event_id]
    assert listed(statuses=("open",)) == [request_a.event_id, request_bare.event_id]
    assert listed(statuses=("withdrawn", "answered")) == [request_b.event_id, request_c.event_id]
    assert listed(kinds=("model_unavailable",), projects=(ids["second"],)) == [request_c.event_id]
    assert listed(kinds=("other",)) == []

    # 决定请求随所在流保存的投影一起读取
    assert list(system.writes.read(run_stream(ids["run_b"])).decisions) == [request_b.event_id]
    assert system.writes.read(run_stream(ids["run_a"])).decisions[request_a.event_id].status == "open"


def test_a_transaction_that_does_not_commit_saves_no_decision_request(data_dir):
    system, ids = _runs(data_dir)
    stream = run_stream(ids["run_a"])
    version = system.writes.read(stream).version
    _append(system, ids["run_a"], _requested())
    end = system.store.end_position()

    # 期望版本已经过期：什么也不写，决定请求保存的投影不变
    with pytest.raises(StreamVersionConflict):
        system.writes.transact(stream, lambda transaction: transaction.append(_requested("engineering")),
                               expected_version=version)

    def fails(transaction):
        transaction.append(_requested("quality"))
        raise RuntimeError("judgment failed after appending")

    with pytest.raises(RuntimeError):
        system.writes.transact(stream, fails)
    assert system.store.end_position() == end
    _position, decisions = saved_decisions(system.store)
    assert [item.request["department"] for item in decisions] == ["product"]


def test_decision_requests_are_rebuilt_from_events_and_the_replay_check_compares_them(data_dir):
    system, ids = _runs(data_dir)
    [request_a] = _append(system, ids["run_a"], _requested())
    [request_b] = _append(system, ids["run_b"], _requested())
    _append(system, ids["run_b"], _answered(request_b.event_id, "stop"), command=_command())
    before = saved_decisions(system.store)
    saved = {run: system.store.projection(run_stream(ids[run])).decisions for run in ("run_a", "run_b", "bare")}
    system.close()
    _delete_saved_projections(data_dir)

    adapter = FakeAdapter(_plain_replies())
    restarted = LoopSystem.for_testing(data_dir, adapter)
    # 保存的投影被删除以后由重放补建：决定请求逐字相同。日志末尾位置在这一步只说明恢复写过事件
    # （取得执行权、被继续的 run 的步骤），不参与这条断言。
    # 启动自动继续会推进 run_a 与 run_b，它们因 no_tool_call 暂停并发出新的决定请求（#204）；
    # 这里只比较重建之前就存在的那些请求
    before_ids = {decision.decision_id for decision in before[1]}
    rebuilt = [decision for decision in saved_decisions(restarted.store)[1]
               if decision.decision_id in before_ids]
    assert rebuilt == before[1]
    assert saved_decisions(restarted.store)[0] > before[0]
    for run in saved:
        rebuilt_run = {decision.decision_id: decision
                       for decision in restarted.store.projection(run_stream(ids[run])).decisions}
        for decision in saved[run]:
            assert rebuilt_run[decision.decision_id] == decision
    restarted.replay(ids["run_a"])
    restarted.replay(ids["run_b"])

    # 保存的决定请求与重放不同时，重放核对报告投影不一致
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        connection.execute("UPDATE decisions SET state = replace(state, '\"open\"', '\"answered\"') "
                           "WHERE decision_id = ?", (request_a.event_id,))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ReplayIntegrityError) as mismatch:
        restarted.replay(ids["run_a"])
    assert mismatch.value.reason == PROJECTION_REASON

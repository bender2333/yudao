import threading
import uuid

import pytest

from harness.collaboration import has_new_work
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.decisions import DecisionClosed, DecisionNotFound, InvalidOption, StaleDecision
from harness.event_store import Command, DuplicateCommand, run_stream
from harness.models import EventType, Usage
from harness.projection import saved_decision, saved_decisions
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.contract_checks import assert_payloads_follow_contract
from harness.tests.helpers import quality_turns
from harness.write_path import NewEvent

# 用户决定在控制核心中的行为：模型引用无法使用时流程编排发出待恢复的决定请求，run 停在这次请求之前、不再推进；
# 回答继续执行以后从这次请求接着进行，已完成的工作与已用限额保留；选择停止事项或取消运行时结束。
# 系统整体运行，模型回答（包括提供方报告的不可用）由 FakeAdapter 脚本给出；回答经流程编排的入口并带命令，
# 应用层的命令与查询在 test_decision_api.py。

UNAVAILABLE = "Missing configuration: provider credential"

def _answer(system: LoopSystem, decision_id: str, option: str = "continue", *, base_version: int = 1,
            note: str | None = None, command_id: str | None = None) -> str | None:
    command = Command(command_id or str(uuid.uuid4()), "decision.answer", f"sha256:{option}:{base_version}",
                      "user:local")
    return system.orchestrator.answer_decision(decision_id, option, note, base_version=base_version,
                                               command=command)

def _engineering_unavailable_system(data_dir):
    # 产品规格被接纳以后，工程部门的请求被提供方报告为不可用（缺少凭据）
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    adapter = FakeAdapter({
        "product": [FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20))],
        "engineering": [ProviderError(UNAVAILABLE, reason="provider_unavailable"), delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    })
    system = LoopSystem.for_testing(data_dir, adapter)
    return system, adapter, system.create_run("build an echo CLI")

def _open(system: LoopSystem):
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    return decisions

def test_a_model_that_cannot_be_used_blocks_the_run_until_the_answer_and_the_run_then_continues(data_dir):
    system, adapter, run_id = _engineering_unavailable_system(data_dir)
    blocked = system.run_until_stop(run_id)

    # 工程部门的请求没有发出成功：run 没有结束，产品的成果与已用的用量都在。
    # 同时运行的会话各自记下自己结束的时刻，最后激活的是哪个部门不再固定（工单 #557）：
    # 这里断言的是结果，不是哪个部门最后激活
    assert (blocked.stop_reason, blocked.status) == (None, "running")
    assert blocked.product_spec is not None and blocked.token_used == 120
    [decision] = _open(system)
    events = system.store.list_events(run_id)
    [failed] = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    [requested] = [event for event in events if event.type == EventType.DECISION_REQUESTED]
    assert failed.payload["reason"] == "provider_unavailable" and failed.payload["will_retry"] is False
    assert (requested.actor, requested.command_id, requested.department) == ("system", None, "engineering")
    assert decision.decision_id == requested.event_id and decision.run_id == run_id
    request = decision.request
    assert (request["kind"], request["blocks"], request["department"], request["reason"], request["message"]) == (
        "model_unavailable", "run", "engineering", "provider_unavailable", UNAVAILABLE)
    assert request["options"] == [{"id": "continue", "label": "继续执行"}, {"id": "stop", "label": "停止事项"}]
    assert request["facts"] == [failed.event_id]
    assert request["target"]["requested_model"] == "fake-script" and UNAVAILABLE in request["description"]
    assert not any(event.type in {EventType.RUN_FAILED, EventType.RUN_PAUSED} for event in events)

    # 回答之前 run 不推进：再次运行或激活都不写入，也不调用模型
    end = system.store.end_position()
    calls = len(adapter.invocations)
    assert has_new_work(system.run_until_stop(run_id), "engineering")
    assert has_new_work(system.activate_once(run_id), "engineering")
    assert system.store.end_position() == end and len(adapter.invocations) == calls

    # 回答继续执行：从工程部门的这次请求接着进行，产品不再调用，走完交付与放行
    assert _answer(system, decision.decision_id, note="凭据已经补上") == run_id
    answered = saved_decision(system.store, decision.decision_id)
    assert (answered.status, answered.answer["option"], answered.answer["note"]) == ("answered", "continue",
                                                                                       "凭据已经补上")
    finished = system.run_until_stop(run_id)
    assert finished.status == "done"
    # 产品只提交过一次 PRD；工程在阻塞以后接着做完了交付，质检核验并放行。
    # 质检在交付到达以前还有一轮预测性探索（工单 #557），因此这里不数模型调用的次数
    departments = [call.department for call in adapter.invocations]
    assert departments.count("product") == 1
    assert departments.count("engineering") >= 2
    assert "quality" in departments
    assert finished.product_specs == blocked.product_specs
    assert finished.cycle_count > blocked.cycle_count and finished.token_used >= 120
    assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()
    assert_payloads_follow_contract(system.store.list_events(run_id))

def test_choosing_to_stop_ends_the_run_in_the_same_transaction_as_the_answer(data_dir):
    system, adapter, run_id = _engineering_unavailable_system(data_dir)
    system.run_until_stop(run_id)
    [decision] = _open(system)
    calls = len(adapter.invocations)
    assert _answer(system, decision.decision_id, "stop") is None
    events = system.store.list_events(run_id)
    assert [event.type for event in events[-2:]] == [EventType.DECISION_ANSWERED, EventType.RUN_FAILED]
    assert events[-1].stop_reason == "cancelled" and events[-2].command_id == events[-1].command_id
    assert system.run_until_stop(run_id).status == "failed"
    assert len(adapter.invocations) == calls
    with pytest.raises(DecisionClosed):
        _answer(system, decision.decision_id)

def test_cancelling_a_blocked_run_withdraws_its_decision_request(data_dir):
    system, adapter, run_id = _engineering_unavailable_system(data_dir)
    system.run_until_stop(run_id)
    [decision] = _open(system)
    cancelled = system.cancel(run_id)
    assert (cancelled.status, cancelled.stop_reason) == ("failed", "cancelled")
    events = system.store.list_events(run_id)
    assert [event.type for event in events[-2:]] == [EventType.DECISION_WITHDRAWN, EventType.RUN_FAILED]
    assert events[-2].actor == "system" and events[-2].payload == {"decision_id": decision.decision_id,
                                                                    "reason": "cancelled"}
    withdrawn = saved_decision(system.store, decision.decision_id)
    assert (withdrawn.status, withdrawn.withdrawal["reason"]) == ("withdrawn", "cancelled")
    with pytest.raises(DecisionClosed):
        _answer(system, decision.decision_id)
    assert_payloads_follow_contract(events)

def test_an_answer_that_does_not_hold_writes_nothing_and_does_not_register_its_command(data_dir):
    system, _adapter, run_id = _engineering_unavailable_system(data_dir)
    system.run_until_stop(run_id)
    [decision] = _open(system)
    end = system.store.end_position()
    command_id = str(uuid.uuid4())
    with pytest.raises(DecisionNotFound):
        _answer(system, "evt_missing", command_id=command_id)
    with pytest.raises(StaleDecision) as stale:
        _answer(system, decision.decision_id, base_version=2, command_id=command_id)
    assert stale.value.version == 1
    with pytest.raises(InvalidOption) as invalid:
        _answer(system, decision.decision_id, "retry", command_id=command_id)
    assert invalid.value.options == ["continue", "stop"]
    assert system.store.end_position() == end and system.store.command(command_id) is None

    # 同一命令身份再次提交时不再判断；另一个身份回答已经回答的请求时拒绝
    assert _answer(system, decision.decision_id, command_id=command_id) == run_id
    with pytest.raises(DuplicateCommand):
        _answer(system, decision.decision_id, command_id=command_id)
    with pytest.raises(DecisionClosed):
        _answer(system, decision.decision_id)
    assert len(system.store.command_events(command_id)) == 1

def test_a_decision_request_blocking_the_run_stops_a_running_activation_at_its_next_safe_node(data_dir):
    # 激活进行中出现阻塞 run 的决定请求（这里由测试经写入口写入）：模型回答以后的安全节点得到停止，
    # 回答中的提交不执行，run 等待回答；回答以后从产品部门接着进行
    requested = threading.Event()

    def reply_after_the_request(_call):
        system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
            EventType.DECISION_REQUESTED, actor="system", department="product",
            state_before=transaction.projection.status, state_after=transaction.projection.status, payload={
                "kind": "model_unavailable", "blocks": "run",
                "options": [{"id": "continue", "label": "继续执行"}, {"id": "stop", "label": "停止事项"}],
                "description": "部门 product 的模型无法使用", "facts": [], "department": "product",
                "target": None, "reason": "provider_unavailable", "message": UNAVAILABLE})))
        requested.set()
        return product_spec()

    adapter = FakeAdapter([reply_after_the_request, product_spec()])
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build an echo CLI")
    blocked = system.activate_once(run_id)
    assert requested.is_set()
    assert (blocked.active_department, blocked.product_spec) == ("product", None)
    events = system.store.list_events(run_id)
    skipped = [event for event in events if event.type == EventType.TOOL_SKIPPED]
    assert [event.payload["name"] for event in skipped] == ["submit_product_spec"]
    assert events[-1].type == EventType.ACTIVATION_FINISHED
    assert has_new_work(system.run_until_stop(run_id), "product")

    [decision] = _open(system)
    _answer(system, decision.decision_id)
    assert system.activate_once(run_id).product_spec is not None
    assert len(adapter.invocations) == 2

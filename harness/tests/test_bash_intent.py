# 运行命令的一句话只被记录，不交给执行环境（工作过程的任务与动作标题设计说明「接口」「动作标题」，
# 工单 #1659）：正常执行与恢复后重新执行两条路径上，交给执行环境的动作输入里都没有这一项，命令照常运行；
# 工具调用的记录里留着这一项。数据目录是真实的 SQLite 事件日志与工作区，模型回答由 FakeAdapter 给出，
# 中断由「关闭系统、重新以新的系统打开同一数据目录」表示（与 test_issue_17_action_recovery.py 同一个做法）。
#
# 层：模块层（一个工作区、一次部门激活、一条真实命令）。守 R2（动作的缝不变：交给执行环境的输入只有
# 可执行的那几项）与 R3（角色写的一句话留在记录里，页面读得到）。

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from harness.adapters.fake import FakeAdapter
from harness.environment import LocalEnvironment
from harness.event_store import run_stream
from harness.failure_list import tool_result
from harness.models import EventType, json_dumps
from harness.proposals import product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn
from harness.watched_outputs import has_new_work
from harness.write_path import NewEvent

# 角色写的那一句话：只说这条命令要做什么
SENTENCE = "先跑一次 echo，看看工作区里能不能执行命令"
COMMAND = "echo ready"


def _action_inputs(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    # 执行环境真正收到的动作与输入：在执行之前记下，再交给原来的实现执行
    recorded: list[tuple[str, dict[str, Any]]] = []
    original = LocalEnvironment.perform

    async def perform(self, action):
        recorded.append((action.tool, dict(action.input)))
        return await original(self, action)

    monkeypatch.setattr(LocalEnvironment, "perform", perform)
    return recorded



def _bash_call(identity: str = "cmd-1") -> dict[str, Any]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "bash",
            "arguments": json_dumps({"command": COMMAND, "intent": SENTENCE})}


def _bash_events(system, run_id, type_):
    return [event for event in system.store.list_events(run_id)
            if event.type == type_ and (event.payload or {}).get("name") == "bash"]


def test_the_one_sentence_is_recorded_but_not_handed_to_the_environment(data_dir, monkeypatch):
    # 正常路径：工具调用记录里有这一项，交给执行环境的输入里没有，命令照常运行。
    # 质检照常做它的一轮（脚本空着时它先失败，会让运行结束并取消还在跑的命令，见下面的恢复用例）
    recorded = _action_inputs(monkeypatch)
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [lambda request: ModelResponse(output=[_bash_call()])],
        "quality": [explore_turn()],
    }))
    run_id = system.create_run("build echo")
    try:
        system.run_until_stop(run_id)
        # 只被记录：执行环境按可执行的那几项执行，命令照常运行
        assert [item for item in recorded if item[0] == "bash"] == [("bash", {"command": COMMAND})]
        [started] = _bash_events(system, run_id, EventType.TOOL_STARTED)
        assert started.payload["args"] == {"command": COMMAND, "intent": SENTENCE}
        [called] = _bash_events(system, run_id, EventType.TOOL_CALLED)
        assert called.payload["args"] == {"command": COMMAND, "intent": SENTENCE}
        assert called.payload["ok"] is True and not called.payload.get("error")
        assert tool_result(called)["output"]["exit_code"] == 0
    finally:
        system.close()


def test_the_one_sentence_is_not_handed_to_the_environment_after_recovery(data_dir, monkeypatch):
    # 恢复路径：响应里没有处置的工具调用在恢复时补执行，动作的输入同样去掉这一项
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()], "engineering": [], "quality": []}))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")
    _append_unexecuted_response(system, run_id, _bash_call(identity="cmd-recovered"))
    system.close()

    recorded = _action_inputs(monkeypatch)
    # 脚本为空：一旦重新调用模型就以脚本用尽失败，恢复只补执行没有处置的调用
    restarted = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [], "engineering": [], "quality": [explore_turn()]}))
    try:
        assert [item for item in recorded if item[0] == "bash"] == [("bash", {"command": COMMAND})]
        [called] = _bash_events(restarted, run_id, EventType.TOOL_CALLED)
        assert called.payload["id"] == "cmd-recovered"
        assert called.payload["args"] == {"command": COMMAND, "intent": SENTENCE}
        assert called.payload["ok"] is True and not called.payload.get("error")
        assert tool_result(called)["output"]["exit_code"] == 0
    finally:
        restarted.close()


def _append_unexecuted_response(system, run_id, item: dict[str, Any]) -> None:
    # 保存一条完整模型响应（一个输出条目一条 model_message 事件），这个调用既没有 tool_started 也没有
    # tool_called：与进程在把响应执行之前退出留下的状态一致（工单 #17、#473）
    session_id = system.project(run_id).sessions["engineering"].session_id
    ref = system.artifacts.put(run_id, "model_message", json.dumps(item, ensure_ascii=False),
                               media_type="application/json")
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.MODEL_MESSAGE, actor="department:planning", department="engineering",
        state_before="running", state_after="running", session_id=session_id,
        payload={"message_ref": asdict(ref), "message_index": 1,
                 "activation_id": "act_recovered", "step_id": 1, "purpose": "work"}))

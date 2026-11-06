# 动作核实与一致边界（工单 #17，恢复契约 docs/design/recovery-contract-and-fault-matrix.md「执行权与一致边界」、「动作分类与处置」）。数据目录是真实的 SQLite 事件日志，服务启动经真实的
# LoopSystem，模型回答由 FakeAdapter 给出；中断由「进程关闭、重新以新的系统打开同一数据目录」表示，
# 需要在中断前落盘的中间状态由测试直接追加事件构造，与前面用例改写事件库的做法一致。

import json
from dataclasses import asdict
from typing import Any

from harness.watched_outputs import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.event_store import run_stream
from harness.models import EventType
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.write_path import NewEvent

def _write_events(run_id):
    return [EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED]

def _product_only_script() -> dict[str, list[Any]]:
    # 这一轮只有产品回答：PRD 被接纳以后工程与质检同时工作，
    # 两个部门各自的脚本是空的（模型再被调用就以脚本用尽失败）
    return {"product": [product_spec()], "engineering": [], "quality": []}


def _empty_script() -> dict[str, list[Any]]:
    # 恢复时不再调用模型：每个部门的脚本都是空的
    return {"product": [], "engineering": [], "quality": []}


def _engineering_run(data_dir, script):
    # 一个已完成产品规格、停在 ENGINEERING 的 run：可以直接继续工程部门的模型步骤
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")
    return system, run_id

def _tool_events(system, run_id, tool):
    return [event for event in system.store.list_events(run_id)
            if event.type in _write_events(run_id) and (event.payload or {}).get("name") == tool]


def test_a_partial_model_response_only_executes_the_remaining_calls(data_dir):
    # 部分执行的模型响应只补剩余合法动作，不整批重发、不重新调用模型
    system, run_id = _engineering_run(data_dir, _product_only_script())
    _append_partial_response(system, run_id, executed=("c1",), remaining=("c2",))
    system.close()

    # 脚本为空：一旦重新调用模型就会以脚本用尽失败；恢复只补执行剩余动作
    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()))
    calls = [event.payload.get("id") for event in _tool_events(restarted, run_id, "write_file")]
    assert calls == ["c1", "c1", "c2", "c2"], calls
    assert restarted.workspace(run_id).list_files() == ["src/c2.py"]
    restarted.close()

def _engineering_session(system, run_id):
    # 工程主线会话的标识：恢复时补执行的动作按会话找（工单 #473），
    # 真实记录里的事件都带着会话标识
    return system.project(run_id).sessions["engineering"].session_id

def _append_partial_response(system, run_id, *, executed, remaining):
    # 保存一条完整模型响应（每个输出条目一条 model_message 事件，与真实记录一致），executed 已经有
    # tool_started 与 tool_called，remaining 没有任何事件：与进程在把响应执行到一半时退出留下的状态一致
    from harness.models import json_dumps

    def call(identity, path):
        return {"id": identity, "call_id": identity, "type": "function_call", "name": "write_file",
                "arguments": json_dumps({"path": path, "content": identity.upper()})}

    session_id = _engineering_session(system, run_id)
    for index, identity in enumerate((*executed, *remaining)):
        item = call(identity, f"src/{identity}.py")
        ref = system.artifacts.put(run_id, "model_message", json.dumps(item, ensure_ascii=False),
                                   media_type="application/json")
        system.writes.append(run_stream(run_id), NewEvent(
            EventType.MODEL_MESSAGE, actor="department:planning", department="engineering",
            state_before="running", state_after="running", session_id=session_id,
            payload={"message_ref": asdict(ref), "message_index": index + 1,
                     "activation_id": "act_partial", "step_id": 1, "purpose": "work"}))
    for identity in executed:
        for event_type in (EventType.TOOL_STARTED, EventType.TOOL_CALLED):
            system.writes.append(run_stream(run_id), NewEvent(
                event_type, actor="department:planning", department="engineering",
                state_before="running", state_after="running", session_id=session_id,
                payload={"id": identity, "name": "write_file",
                         "args": {"path": f"src/{identity}.py", "content": identity.upper()},
                         "step_id": 1, "activation_id": "act_partial", "attempt": 1, "purpose": "work",
                         "ok": True,
                         "input_item": {"type": "function_call_output", "call_id": identity,
                                        "output": json.dumps({"ok": True})}}))

def test_a_partial_model_response_executes_remaining_host_tool(data_dir):
    # 恢复路径覆盖主机工具：未处置的主机调用（如 submit_delivery）在恢复时正常执行并记录 tool_called
    system, run_id = _engineering_run(data_dir, _product_only_script())
    product_spec_hash = system.project(run_id).product_spec.content_hash
    from harness.models import json_dumps

    item_write = {
        "id": "hw1", "call_id": "hw1", "type": "function_call", "name": "write_file",
        "arguments": json_dumps({"path": "src/echo.py", "content": "print('ok')"})
    }
    item_submit = {
        "id": "hs1", "call_id": "hs1", "type": "function_call", "name": "submit_delivery",
        "arguments": json_dumps({
            "summary": "deliver echo", "check_names": [],
            "basis_product_spec_hash": product_spec_hash,
        })
    }
    session_id = _engineering_session(system, run_id)
    for index, item in enumerate((item_write, item_submit)):
        ref = system.artifacts.put(run_id, "model_message", json.dumps(item, ensure_ascii=False),
                                   media_type="application/json")
        system.writes.append(run_stream(run_id), NewEvent(
            EventType.MODEL_MESSAGE, actor="department:planning", department="engineering",
            state_before="running", state_after="running", session_id=session_id,
            payload={"message_ref": asdict(ref), "message_index": index + 1,
                     "activation_id": "act_partial_host", "step_id": 1, "purpose": "work"}))
    for event_type in (EventType.TOOL_STARTED, EventType.TOOL_CALLED):
        system.writes.append(run_stream(run_id), NewEvent(
            event_type, actor="department:planning", department="engineering",
            state_before="running", state_after="running", session_id=session_id,
            payload={"id": "hw1", "name": "write_file",
                     "args": {"path": "src/echo.py", "content": "print('ok')"},
                     "step_id": 1, "activation_id": "act_partial_host", "attempt": 1, "purpose": "work",
                     "ok": True,
                     "input_item": {"type": "function_call_output", "call_id": "hw1",
                                    "output": json.dumps({"ok": True})}}))
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()))
    tool_called_events = [
        event for event in restarted.store.list_events(run_id)
        if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == "hs1"
    ]
    assert len(tool_called_events) == 1
    assert tool_called_events[0].payload["name"] == "submit_delivery"
    assert tool_called_events[0].payload["ok"] is True
    restarted.close()

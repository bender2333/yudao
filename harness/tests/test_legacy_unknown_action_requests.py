# 旧版本 unknown_action 决定请求与旧核实记录的读取与恢复（工单 #582，ADR-0038，恢复契约第 4 节）：
# 1. 旧数据目录中未回答的 unknown_action 请求：启动时被撤回（decision_withdrawn，reason: superseded_by_hand_back），
#    动作被交还模型（action_verified，resolution: handed_back），事项不阻塞，下一次模型请求包含此工具结果；
# 2. 对已撤回请求调用 decision.answer 返回 decision_closed，decisions.list 不再列出 open 状态；
# 3. 事件流与 run.export 能正常读取旧的 unknown_action 决定请求与 resolution: continue 的核实记录。

import asyncio
import json
import uuid
from dataclasses import asdict

import pytest

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.decision_commands import DecisionAnswer
from harness.app.event_stream import EventScope
from harness.app.decision_queries import DecisionsList
from harness.app.project_queries import RunExport
from harness.event_store import run_stream
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec
from harness.runtime import LoopSystem
from harness.write_path import NewEvent


def _engineering_run(data_dir, script):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")
    return system, run_id


def _append_lost_write(system, run_id, *, tool="write_file", action_id="lost-write", before=None):
    before = {"digest": "sha256:" + action_id, "files": []} if before is None else before
    snap_ref = system.artifacts.put(run_id, "snapshot/before", json.dumps(before, ensure_ascii=False),
                                    media_type="application/json")
    args = {"path": "src/a.py", "content": "A"}
    msg_item = {"type": "function_call", "call_id": action_id, "id": action_id, "name": tool,
                "arguments": json.dumps(args)}
    msg_ref = system.artifacts.put(run_id, "message", json.dumps(msg_item, ensure_ascii=False),
                                   media_type="application/json")
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.MODEL_MESSAGE, actor="model:fake", department="engineering",
        state_before="running", state_after="running",
        payload={
            "activation_id": "act_eng_1", "step_id": 1, "purpose": "work",
            "message_ref": asdict(msg_ref),
        }))
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.TOOL_STARTED, actor="department:engineering", department="engineering",
        state_before="running", state_after="running",
        payload={"id": action_id, "name": tool, "args": args,
                 "step_id": 1, "activation_id": "act_eng_1", "attempt": 1,
                 "purpose": "work", "before_snapshot_ref": asdict(snap_ref)}))
    return snap_ref


def _answer(system, decision_id, option, base_version=1):
    application = Application(system)
    return asyncio.run(application.command("decision.answer", DecisionAnswer(
        command_id=str(uuid.uuid4()), decision_id=decision_id, option=option, base_version=base_version,
        note=None), actor="user"))


def _collect(stream, limit: int, timeout: float = 5.0):
    async def run():
        messages = []
        async for message in stream.messages():
            messages.append(message)
            if len(messages) >= limit:
                break
        return messages

    return asyncio.run(asyncio.wait_for(run(), timeout))


def test_unanswered_legacy_unknown_action_is_withdrawn_handed_back_and_resumes(tmp_path):
    data_dir = tmp_path / "data"
    system, run_id = _engineering_run(data_dir, [product_spec()])
    _append_lost_write(system, run_id, tool="write_file", action_id="lost-write")
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.DECISION_REQUESTED, actor="system", department="engineering",
        state_before="running", state_after="running",
        payload={
            "kind": "unknown_action",
            "blocks": "action",
            "options": [{"id": "continue", "label": "按当前实际状态继续"}, {"id": "stop", "label": "停止事项"}],
            "description": "动作 lost-write（write_file）已经发出，结果没有得到确认。",
            "facts": [],
            "department": "engineering",
            "action_id": "lost-write",
            "tool": "write_file",
            "action_kind": "write",
            "repeatable": False,
            "repeat_attempted": False,
        },
    ))
    [legacy_decision] = [e for e in system.store.list_events(run_id) if e.type == EventType.DECISION_REQUESTED]
    system.close()

    adapter = FakeAdapter([delivery_turn()])
    restarted = LoopSystem.for_testing(data_dir, adapter, resume_on_startup=True)

    # 1. 请求被撤回
    withdrawn = [e for e in restarted.store.list_events(run_id) if e.type == EventType.DECISION_WITHDRAWN]
    assert len(withdrawn) == 1
    assert withdrawn[0].payload["decision_id"] == legacy_decision.event_id
    assert withdrawn[0].payload["reason"] == "superseded_by_hand_back"

    # 2. 动作被交还
    verified = [e for e in restarted.store.list_events(run_id) if e.type == EventType.ACTION_VERIFIED]
    assert len(verified) == 1
    assert verified[0].payload["id"] == "lost-write"
    assert verified[0].payload["resolution"] == "handed_back"

    # 3. 事项不阻塞：模型被成功调用，事项继续运行
    assert len(adapter.invocations) >= 1

    # 4. 下一次模型请求里有这条工具结果
    first_call = adapter.invocations[0]
    output_item = next(
        item for item in first_call.input_items
        if isinstance(item, dict) and item.get("type") == "function_call_output" and item.get("call_id") == "lost-write"
    )
    output_data = json.loads(output_item["output"])
    assert output_data["ok"] is False
    assert "核实确认没有发生" in output_data["error"] or "执行被中断" in output_data["error"]

    # 6. decisions.list 不再列出它（不是 open）；对已撤回请求调用 decision.answer 返回 decision_closed
    app = Application(restarted)
    decisions = app.query("decisions.list", DecisionsList()).data.decisions
    assert not any(d.decision_id == legacy_decision.event_id and d.status == "open" for d in decisions)

    answer_result = _answer(restarted, legacy_decision.event_id, "continue")
    assert answer_result.reason == "decision_closed"

    restarted.close()


def test_event_stream_and_run_export_read_legacy_decision_and_continue_records(tmp_path):
    data_dir = tmp_path / "data"
    system, run_id = _engineering_run(data_dir, [product_spec()])
    activated = [event for event in system.store.list_events(run_id)
                 if event.type == EventType.DEPARTMENT_ACTIVATED]
    activation_id = activated[-1].payload["activation_id"]

    # 写入旧的 unknown_action 决定请求事件
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.DECISION_REQUESTED, actor="system", department="engineering",
        state_before="running", state_after="running",
        payload={
            "kind": "unknown_action",
            "blocks": "action",
            "options": [{"id": "continue", "label": "按当前实际状态继续"}, {"id": "stop", "label": "停止事项"}],
            "description": "动作 legacy-act（write_file）已经发出，结果没有得到确认。",
            "facts": [],
            "department": "engineering",
            "action_id": "legacy-act",
            "tool": "write_file",
            "action_kind": "write",
            "repeatable": False,
            "repeat_attempted": False,
        },
    ))
    # 写入旧的 resolution: continue 核实记录事件
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.ACTION_VERIFIED, actor="system", department="engineering",
        state_before="running", state_after="running",
        payload={
            "id": "legacy-act",
            "name": "write_file",
            "step_id": 1,
            "activation_id": activation_id,
            "purpose": "work",
            "input_item": {
                "type": "function_call_output",
                "call_id": "legacy-act",
                "output": json.dumps({"ok": True, "output": {"resolved": "continue"}}),
            },
            "ok": True,
            "resolution": "continue",
            "note": "按实际状态继续",
        },
    ))
    system.close()

    opened = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    app = Application(opened)

    # 验证 run.export 读出旧事件与核实记录
    exported = app.query("run.export", RunExport(run_id=run_id))
    exported_types = [e["type"] for e in exported.data.events]
    assert EventType.DECISION_REQUESTED in exported_types
    assert EventType.ACTION_VERIFIED in exported_types
    legacy_verified = next(e for e in exported.data.events if e["type"] == EventType.ACTION_VERIFIED)
    assert legacy_verified["payload"]["resolution"] == "continue"

    # 验证 event_stream 能正常校验并读出旧事件
    stream = app.open_event_stream(EventScope(), after=0, live=False)
    messages = _collect(stream, len(exported.data.events))
    assert any(m.event.type == EventType.DECISION_REQUESTED and getattr(m.event.payload, "kind", None) == "unknown_action"
               for m in messages)
    assert any(m.event.type == EventType.ACTION_VERIFIED and getattr(m.event.payload, "resolution", None) == "continue"
               for m in messages)

    opened.close()

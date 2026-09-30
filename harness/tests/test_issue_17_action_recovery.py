"""工单 #17：动作核实与一致边界的三个窄场景测试"""
from harness.models import Event, EventType
from harness.recovery import classify_actions, build_unknown_action_request


def _make_event(event_id, event_type, payload, run_id="run-1"):
    """创建最小化的 Event 对象用于测试"""
    return Event(
        event_id=event_id,
        run_id=run_id,
        type=event_type,
        role="engineering",
        parent_event_id=None,
        state_before="ENGINEERING",
        state_after="ENGINEERING",
        payload=payload,
        artifact_hashes=[],
        session_id=None,
        provider=None,
        model=None,
        context_digest=None,
        stop_reason=None,
        error=None,
        created_at="2026-09-30T00:00:00Z",
        position=1,
        stream=f"run:{run_id}",
        stream_version=1,
        project_id=None,
        work_item_id=None,
        department="engineering",
    )


def test_classify_actions_identifies_unknown_action():
    """场景1：classify_actions 正确识别 status='unknown' 的动作（有 tool_started 但无 tool_called）"""
    events = [
        _make_event(
            event_id="evt-1",
            event_type=EventType.TOOL_STARTED,
            payload={"action_id": "action-1", "tool": "write_file", "arguments": {"path": "test.py"}},
        ),
    ]
    actions = classify_actions(events)
    assert "action-1" in actions
    assert actions["action-1"]["status"] == "unknown"
    assert actions["action-1"]["tool"] == "write_file"


def test_build_unknown_action_request_includes_repeatable_option():
    """场景2：build_unknown_action_request 为 repeatable 工具包含 reexecute 选项"""
    request = build_unknown_action_request(
        decision_id="decision-1",
        action_id="action-1",
        tool_name="read_file",  # repeatable=True
        run_id="run-1",
        version=1,
    )
    assert request["kind"] == "unknown_action"
    assert request["blocks"] == "action"
    option_ids = [opt["id"] for opt in request["request"]["options"]]
    assert "reexecute" in option_ids
    assert "continue" in option_ids
    assert "stop" in option_ids


def test_build_unknown_action_request_excludes_reexecute_for_non_repeatable():
    """场景3：build_unknown_action_request 为非 repeatable 工具排除 reexecute 选项"""
    request = build_unknown_action_request(
        decision_id="decision-2",
        action_id="action-2",
        tool_name="write_file",  # repeatable=False
        run_id="run-1",
        version=1,
    )
    assert request["kind"] == "unknown_action"
    assert request["blocks"] == "action"
    option_ids = [opt["id"] for opt in request["request"]["options"]]
    assert "reexecute" not in option_ids
    assert "continue" in option_ids
    assert "stop" in option_ids

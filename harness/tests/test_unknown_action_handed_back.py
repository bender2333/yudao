# 工单 #581（从 #545 拆出，对应 #483 验收第 1、2、3、4 条）：
# 恢复时结果未知的动作交还发出它的会话，删除自动重新执行与 repeatable 声明。
# (a) bash 运行中停掉再启动：下一次模型请求的部门历史里有这次调用的工具结果，
#     写明执行被中断、结果未知；没有 decision_requested，事项不进入等待用户；
# (b) run_check 同样；
# (c) 一个每运行一次就向文件追加一行的 bash 命令，运行中停掉再启动：文件只有一行（命令没有被再运行）；
# (d) 写入文件的动作结果未知，自动核实确认已完成，模型收到确定的结果；没有发生时模型收到「核实确认没有发生」。
# 都用真实子进程运行系统并终止，重启后在同一个数据目录上验证。不使用 mock。

import json
import sys
from harness.proposals import product_spec
from harness.tests import process_kill as killed
from harness.tests.helpers import run_wait_command


def _call(identity: str, name: str, arguments: dict) -> dict:
    return {
        "id": identity,
        "call_id": identity,
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(arguments),
    }


def _write(identity: str, path: str, content: str) -> dict:
    return {
        "id": identity,
        "call_id": identity,
        "type": "function_call",
        "name": "write_file",
        "arguments": json.dumps({"path": path, "content": content}),
    }


def _settle() -> dict:
    # 交付以后的检查：模型按核实结果继续往下走
    return {
        "writes": {"src/done.txt": "done"},
        "checks": {
            "smoke": {
                "command": f'"{sys.executable.replace(chr(92), chr(47))}" -c "print(\'smoke ok\')"'
            }
        },
    }


def _tool_output_item(invocation, call_id: str) -> dict:
    for item in invocation.input_items:
        if (
            isinstance(item, dict)
            and item.get("type") == "function_call_output"
            and item.get("call_id") == call_id
        ):
            return item
    raise AssertionError(
        f"call_id {call_id} not found in input_items: {invocation.input_items}"
    )


def _check_action(system, run_id: str) -> str:
    started = [
        event.payload
        for event in killed.events(system, run_id, "tool_started")
        if event.payload.get("name") == "run_check"
    ]
    assert started, "run_check 没有被执行"
    return str(started[0]["id"])


def test_a_killed_bash_is_handed_back_to_model(tmp_path):
    # (a) bash 运行中停掉再启动：下一次模型请求的部门历史里有这次调用的工具结果，
    # 写明执行被中断、结果未知；没有 decision_requested，事项不进入等待用户
    data_dir = tmp_path / "data"
    signals = tmp_path / "signals"
    signals.mkdir(exist_ok=True)

    # 脚本按会话给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [
            {"output": [_call("call-bash", "bash", {"command": run_wait_command(signals)})]},
        ],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
    }

    with killed.interrupted(data_dir, script, tail={"engineering": [_settle()],
                                                     "quality": [{"proposal": {"kind": "quality_auto"}}]},
                            started=signals / "started") as run:
        assert killed.unknown_action_requests(run.after, run.run_id) == []

        started_events = [
            e
            for e in killed.events(run.after, run.run_id, "tool_started")
            if (e.payload or {}).get("id") == "call-bash"
        ]
        assert len(started_events) == 1
        started = [event.payload for event in started_events]

        verified_events = [
            e
            for e in killed.events(run.after, run.run_id, "action_verified")
            if (e.payload or {}).get("id") == "call-bash"
        ]
        assert len(verified_events) == 1
        verified = [event.payload for event in verified_events]
        assert verified[0]["resolution"] == "handed_back"
        assert verified[0]["ok"] is False
        # 交还的是发出这个动作的那个会话（工单 #475）：核实记录带着这个会话的编号
        session = started_events[0].session_id
        assert session, "动作没有记下发出它的会话"
        assert verified_events[0].session_id == session
        assert verified[0]["activation_id"] == started[0]["activation_id"]
        assert verified[0]["step_id"] == started[0]["step_id"]
        assert verified[0]["activation_id"] is not None
        assert verified[0]["step_id"] is not None
        assert len(run.after.test_adapter.invocations) >= 1
        first_call = run.after.test_adapter.invocations[0]
        output_item = _tool_output_item(first_call, "call-bash")
        output_data = json.loads(output_item["output"])
        assert output_data["ok"] is False
        assert "执行被中断" in output_data["error"] and "结果未知" in output_data["error"]

        # 交还以后仍在结果未知的动作里（工单 #181，设计说明第 4.3 节）：处理方式是交还会话，
        # 交还给模型的内容与模型读到的那条工具结果相同，发出的会话与执行前快照都在，处理时间也有。
        # 没有决定卡片：事项不因这个动作等待用户
        handed = [entry for entry in killed.run_recovery(run.after, run.run_id).unknown_actions
                  if entry.action_id == "call-bash"]
        assert len(handed) == 1
        assert handed[0].handling == "returned"
        assert handed[0].session_id == session
        assert handed[0].department == "engineering"
        assert handed[0].before is not None
        assert handed[0].returned is not None
        assert json.loads(handed[0].returned) == output_data
        assert handed[0].at


def test_b_killed_check_is_handed_back_to_model(tmp_path):
    # (b) run_check 同样：检查运行中停掉再启动，结果交还模型
    data_dir = tmp_path / "data"
    signals = tmp_path / "signals"
    signals.mkdir(exist_ok=True)

    # 脚本按会话给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [
            {"checks": {"smoke": {"command": run_wait_command(signals)}}},
        ],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
    }

    with killed.interrupted(data_dir, script, tail={"engineering": [_settle()],
                                                     "quality": [{"proposal": {"kind": "quality_auto"}}]},
                            started=signals / "started") as run:
        action_id = _check_action(run.before, run.run_id)
        assert killed.unknown_action_requests(run.after, run.run_id) == []

        started = [
            e.payload
            for e in killed.events(run.after, run.run_id, "tool_started")
            if (e.payload or {}).get("id") == action_id
        ]
        assert len(started) == 1

        verified = [
            e.payload
            for e in killed.events(run.after, run.run_id, "action_verified")
            if (e.payload or {}).get("id") == action_id
        ]
        assert len(verified) == 1
        assert verified[0]["resolution"] == "handed_back"
        assert verified[0]["ok"] is False
        assert verified[0]["activation_id"] == started[0]["activation_id"]
        assert verified[0]["step_id"] == started[0]["step_id"]
        assert verified[0]["activation_id"] is not None
        assert verified[0]["step_id"] is not None
        assert len(run.after.test_adapter.invocations) >= 1
        first_call = run.after.test_adapter.invocations[0]
        output_item = _tool_output_item(first_call, action_id)
        output_data = json.loads(output_item["output"])
        assert output_data["ok"] is False
        assert "执行被中断" in output_data["error"] and "结果未知" in output_data["error"]


def test_c_killed_append_bash_is_not_reexecuted(tmp_path):
    # (c) 一个每运行一次就向文件追加一行的 bash 命令，运行中停掉再启动：文件只有一行（命令没有被再运行）
    data_dir = tmp_path / "data"
    signals = tmp_path / "signals"
    append_file = tmp_path / "appended.txt"
    signals.mkdir(exist_ok=True)
    append_script = (
        "import os, pathlib, sys, time; "
        "p = pathlib.Path(sys.argv[1]); "
        "signals = pathlib.Path(sys.argv[2]); "
        "content = (p.read_text('utf-8') if p.exists() else '') + 'line' + chr(10); "
        "p.write_text(content, 'utf-8'); "
        "(signals / 'started').write_text('running'); "
        "(signals / 'child.pid').write_text(str(os.getpid())); "
        "[time.sleep(0.05) for _ in range(600) if not (signals / 'release').exists()]"
    )
    cmd = f'"{sys.executable.replace(chr(92), "/")}" -c "{append_script}" "{append_file.as_posix()}" "{signals.as_posix()}"'

    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）：
    # 产品提交规格，命令执行是工程的活；重启以后父进程里接着跑的后半脚本同样按部门给出
    # 质检也要给脚本（工单 #935）：PRD 被接纳以后质检会话也发起模型请求，
    # 没有它的脚本时假模型报「脚本用尽」，运行以 provider_error 提前结束，
    # 用例在到达中断点以前就失败（运行机负载重的时候必现）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [{"output": [_call("call-append", "bash", {"command": cmd})]}],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
    }

    with killed.interrupted(data_dir, script, tail={"engineering": [_settle()],
                                                     "quality": [{"proposal": {"kind": "quality_auto"}}]},
                            started=signals / "started") as run:
        assert killed.unknown_action_requests(run.after, run.run_id) == []
        # 运行确实被中断过以后重启：这次调用的结果交还模型（工单 #935：
        # 运行因为提供方报错提前结束的时候，重启与交还都没有发生，
        # 「文件只有一行」就成了一句空话）
        verified = [
            e.payload
            for e in killed.events(run.after, run.run_id, "action_verified")
            if (e.payload or {}).get("id") == "call-append"
        ]
        assert len(verified) == 1
        assert verified[0]["resolution"] == "handed_back"
        # 命令没有被再运行：整个 run 里只有最初那一次调用
        started = [
            e.payload
            for e in killed.events(run.after, run.run_id, "tool_started")
            if (e.payload or {}).get("id") == "call-append"
        ]
        assert len(started) == 1
        assert append_file.exists()
        lines = append_file.read_text(encoding="utf-8").splitlines()
        assert lines == ["line"], f"文件应该只有一行，实际为 {lines}（命令被重新运行了）"


def test_d_file_action_completed_receives_confirmed_result(tmp_path):
    # (d1) 写入文件的动作结果未知，自动核实确认已完成，模型收到确定的结果
    data_dir = tmp_path / "data"
    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）：
    # 产品提交规格，写文件是工程的活；重启以后父进程里接着跑的后半脚本同样按部门给出
    # 质检也要给脚本（工单 #935）：PRD 被接纳以后质检会话也发起模型请求，
    # 没有它的脚本时假模型报「脚本用尽」，运行以 provider_error 提前结束，
    # 用例在到达中断点以前就失败（运行机负载重的时候必现）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [{"output": [_write("call-write", "src/note.txt", "hello\n")]}],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
    }

    with killed.interrupted(data_dir, script, tail={"engineering": [_settle()],
                                                     "quality": [{"proposal": {"kind": "quality_auto"}}]},
                            await_file=("src/note.txt", "hello\n")) as run:
        assert killed.unknown_action_requests(run.after, run.run_id) == []

        started = [
            e.payload
            for e in killed.events(run.after, run.run_id, "tool_started")
            if (e.payload or {}).get("id") == "call-write"
        ]
        assert len(started) == 1

        verified = [
            e.payload
            for e in killed.events(run.after, run.run_id, "action_verified")
            if (e.payload or {}).get("id") == "call-write"
        ]
        assert len(verified) == 1
        assert verified[0]["resolution"] == "auto_verify"
        assert verified[0]["ok"] is True
        assert verified[0]["verification"]["verdict"] == "completed"
        assert verified[0]["activation_id"] == started[0]["activation_id"]
        assert verified[0]["step_id"] == started[0]["step_id"]
        assert verified[0]["activation_id"] is not None
        assert verified[0]["step_id"] is not None
        assert len(run.after.test_adapter.invocations) >= 1
        first_call = run.after.test_adapter.invocations[0]
        output_item = _tool_output_item(first_call, "call-write")
        output_data = json.loads(output_item["output"])
        assert output_data["ok"] is True
        assert output_data["output"]["resolved"] == "auto_verify"
        # 自动核实确认完成以后同样列在结果未知的动作里（工单 #181）：处理方式是核实确认，
        # 交还给模型的内容与模型读到的工具结果相同
        handled = [entry for entry in killed.run_recovery(run.after, run.run_id).unknown_actions
                   if entry.action_id == "call-write"]
        assert len(handled) == 1
        assert handled[0].handling == "confirmed"
        assert handled[0].before is not None
        assert handled[0].returned is not None
        assert json.loads(handled[0].returned) == output_data
        # 核实记录与动作状态（工单 #308 的验收二：原来由 test_issue_308 的同结论用例断言）
        actions = [
            action
            for action in killed.run_actions(run.after, run.run_id)
            if action.action_id == "call-write"
        ]
        assert [action.status for action in actions] == ["completed"]

        records = [
            record
            for record in killed.run_recovery(run.after, run.run_id).verifications
            if record.action_id == "call-write"
        ]
        assert len(records) == 1
        assert records[0].basis == "自动核实（已完成）"
        assert records[0].decided_by == "system"


def test_d_file_action_not_happened_receives_handed_back(tmp_path):
    # (d2) 写入文件的动作结果未知，自动核实确认没有发生，模型收到「核实确认没有发生」
    data_dir = tmp_path / "data"
    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）：
    # 产品提交规格，写文件是工程的活；重启以后父进程里接着跑的后半脚本同样按部门给出
    # 质检也要给脚本（工单 #935）：PRD 被接纳以后质检会话也发起模型请求，
    # 没有它的脚本时假模型报「脚本用尽」，运行以 provider_error 提前结束，
    # 用例在到达中断点以前就失败（运行机负载重的时候必现）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [{"output": [_write("call-write", "src/note.txt", "hello\n")]}],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
    }

    with killed.interrupted(data_dir, script, tail={"engineering": [_settle()],
                                                     "quality": [{"proposal": {"kind": "quality_auto"}}]},
                            hold_after="tool_started", hold_action="call-write") as run:
        assert killed.unknown_action_requests(run.after, run.run_id) == []

        # 原来那一次尝试没有回执，恢复也没有补出第二次尝试（工单 #581：不再自动重新执行）
        attempts = killed.tool_attempts(run.after, run.run_id, "call-write")
        assert len(attempts) == 1, "没有发生时交还发出它的会话，不再自动重新执行"
        assert attempts[0]["result_type"] is None

        started = [
            e.payload
            for e in killed.events(run.after, run.run_id, "tool_started")
            if (e.payload or {}).get("id") == "call-write"
        ]
        assert len(started) == 1

        verified = [
            e.payload
            for e in killed.events(run.after, run.run_id, "action_verified")
            if (e.payload or {}).get("id") == "call-write"
        ]
        assert len(verified) == 1
        assert verified[0]["resolution"] == "handed_back"
        assert verified[0]["ok"] is False
        assert verified[0]["verification"]["verdict"] == "not_happened"
        assert verified[0]["activation_id"] == started[0]["activation_id"]
        assert verified[0]["step_id"] == started[0]["step_id"]
        assert verified[0]["activation_id"] is not None
        assert verified[0]["step_id"] is not None
        assert len(run.after.test_adapter.invocations) >= 1
        first_call = run.after.test_adapter.invocations[0]
        output_item = _tool_output_item(first_call, "call-write")
        output_data = json.loads(output_item["output"])
        assert output_data["ok"] is False
        assert "核实确认没有发生" in output_data["error"]

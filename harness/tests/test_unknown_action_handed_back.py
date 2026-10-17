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

    script = [
        {"proposal": product_spec()},
        {"output": [_call("call-bash", "bash", {"command": run_wait_command(signals)})]},
    ]

    with killed.interrupted(data_dir, script, tail=[_settle()], started=signals / "started") as run:
        assert killed.unknown_action_requests(run.after, run.run_id) == []

        started = [
            e.payload
            for e in killed.events(run.after, run.run_id, "tool_started")
            if (e.payload or {}).get("id") == "call-bash"
        ]
        assert len(started) == 1

        verified = [
            e.payload
            for e in killed.events(run.after, run.run_id, "action_verified")
            if (e.payload or {}).get("id") == "call-bash"
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
        output_item = _tool_output_item(first_call, "call-bash")
        output_data = json.loads(output_item["output"])
        assert output_data["ok"] is False
        assert "执行被中断" in output_data["error"] and "结果未知" in output_data["error"]


def test_b_killed_check_is_handed_back_to_model(tmp_path):
    # (b) run_check 同样：检查运行中停掉再启动，结果交还模型
    data_dir = tmp_path / "data"
    signals = tmp_path / "signals"
    signals.mkdir(exist_ok=True)

    script = [
        {"proposal": product_spec()},
        {"checks": {"smoke": {"command": run_wait_command(signals)}}},
    ]

    with killed.interrupted(data_dir, script, tail=[_settle()], started=signals / "started") as run:
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

    script = [
        {"proposal": product_spec()},
        {"output": [_call("call-append", "bash", {"command": cmd})]},
    ]

    with killed.interrupted(data_dir, script, tail=[_settle()], started=signals / "started") as run:
        assert killed.unknown_action_requests(run.after, run.run_id) == []
        assert append_file.exists()
        lines = append_file.read_text(encoding="utf-8").splitlines()
        assert lines == ["line"], f"文件应该只有一行，实际为 {lines}（命令被重新运行了）"


def test_d_file_action_completed_receives_confirmed_result(tmp_path):
    # (d1) 写入文件的动作结果未知，自动核实确认已完成，模型收到确定的结果
    data_dir = tmp_path / "data"
    script = [
        {"proposal": product_spec()},
        {"output": [_write("call-write", "src/note.txt", "hello\n")]},
    ]

    with killed.interrupted(data_dir, script, tail=[_settle()], await_file=("src/note.txt", "hello\n")) as run:
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


def test_d_file_action_not_happened_receives_handed_back(tmp_path):
    # (d2) 写入文件的动作结果未知，自动核实确认没有发生，模型收到「核实确认没有发生」
    data_dir = tmp_path / "data"
    script = [
        {"proposal": product_spec()},
        {"output": [_write("call-write", "src/note.txt", "hello\n")]},
    ]

    with killed.interrupted(data_dir, script, tail=[_settle()],
                            hold_after="tool_started", hold_action="call-write") as run:
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

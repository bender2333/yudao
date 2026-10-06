# 工单 #308：恢复契约第 4 节第 1 步。Yudao 自己的文件工具（write_file、edit_range、delete_file、
# move_file）结果未知时自动核实：按动作前的公开树快照、动作参数与当前公开树对比，
# 工作区与动作前相同就以新的尝试重新执行，只有目标路径变成目标内容就记一条自动核实记录，
# 其余情况交给用户决定。
# 四个场景都用真实的子进程运行系统，在工具执行中被终止。写入、编辑、删除、移动在执行环境里是
# 同步的、没有可等待的进程，「没有发生」用 tool_started 提交以后停住来制造（执行前终止），
# 「已经发生」用工作区文件变成目标内容以后子进程自己终止来制造（写入已落盘、回执未写）。
# 辅助代码在 harness/tests/process_kill.py（#307 已合并）。测试里不 mock。

import json
import sys

from harness.proposals import engineering_plan, product_spec
from harness.tests import process_kill as killed


def _call(identity: str, name: str, arguments: dict) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json.dumps(arguments)}


def _write(identity: str, path: str, content: str) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "write_file",
            "arguments": json.dumps({"path": path, "content": content})}


def _edit(identity: str, path: str, start: int, end: int, content: str) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "edit_range",
            "arguments": json.dumps({"path": path, "start_line": start, "end_line": end,
                                      "content": content})}


def _delete(identity: str, path: str) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "delete_file",
            "arguments": json.dumps({"path": path})}


def _move(identity: str, source: str, destination: str) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "move_file",
            "arguments": json.dumps({"source": source, "destination": destination})}


def _settle() -> dict:
    # 交付以后的检查：模型按核实结果继续往下走
    return {"writes": {"src/done.txt": "done"},
            "checks": {"smoke": {"argv": [sys.executable, "-c", "print('smoke ok')"]}}}


def test_a_write_that_never_happened_is_retried_once_without_asking_the_user(tmp_path):
    # 验收一（没有发生）：写入执行前终止进程，重启以后工作区与动作前快照相同，
    # 以新的尝试重新执行一次，没有决定请求
    data_dir = tmp_path / "data"
    script = [{"proposal": product_spec()}, {"proposal": engineering_plan()},
              {"output": [_write("call-write", "src/note.txt", "hello\n")]}]

    with killed.interrupted(data_dir, script, tail=[_settle()],
                            hold_after="tool_started", hold_action="call-write") as run:
        attempts = killed.tool_attempts(run.after, run.run_id, "call-write")

        assert len(attempts) == 2, "工作区与动作前相同，应当以新的尝试重新执行一次"
        assert attempts[0]["result_type"] is None, "终止前的第一次写入没有落盘结果"
        assert attempts[1]["auto_retry_of"] == attempts[0]["event_id"], "新的一次尝试指向被取代的那次"
        assert attempts[1]["verification_reason"] == "not_happened", "依据是自动核实确认没有发生"
        assert attempts[1]["result_type"] == "tool_called", "重新执行写入了文件"

        assert killed.unknown_action_requests(run.after, run.run_id) == [], "核实确认没有发生，不必问用户"

        records = [record for record in killed.run_recovery(run.after, run.run_id).verifications
                   if record.action_id == "call-write"]
        assert len(records) == 1
        assert records[0].basis == "自动核实（没有发生，重新执行）"
        assert records[0].decided_by == "system"


def test_a_write_that_happened_is_recorded_as_auto_verified(tmp_path):
    # 验收二（已完成）：写入已经落盘、回执还没写的时候进程终止。重启以后只有目标路径变成目标内容，
    # 记一条 action_verified（resolution=auto_verify），不补造原来的 tool_called，也不问用户
    data_dir = tmp_path / "data"
    script = [{"proposal": product_spec()}, {"proposal": engineering_plan()},
              {"output": [_write("call-write", "src/note.txt", "hello\n")]}]

    with killed.interrupted(data_dir, script, tail=[_settle()],
                            await_file=("src/note.txt", "hello\n")) as run:
        attempts = killed.tool_attempts(run.after, run.run_id, "call-write")

        assert len(attempts) == 1, "动作已经完成，不再重新执行"
        assert attempts[0]["result_type"] is None, "原来那一次尝试没有回执"

        verified = killed.events(run.after, run.run_id, "action_verified")
        assert len(verified) == 1, "记一条自动核实记录"
        payload = verified[0].payload
        assert payload["resolution"] == "auto_verify"
        assert payload["id"] == "call-write"
        assert payload["verification"]["verdict"] == "completed"
        assert "input_item" in payload, "结果进入部门历史，模型据此继续"

        assert killed.unknown_action_requests(run.after, run.run_id) == [], "已经完成，不必问用户"

        actions = [action for action in killed.run_actions(run.after, run.run_id)
                   if action.action_id == "call-write"]
        assert [action.status for action in actions] == ["completed"]

        records = [record for record in killed.run_recovery(run.after, run.run_id).verifications
                   if record.action_id == "call-write"]
        assert len(records) == 1
        assert records[0].basis == "自动核实（已完成）"
        assert records[0].decided_by == "system"


def test_other_changes_after_the_snapshot_ask_the_user(tmp_path):
    # 验收三（另有改动）：中断以后工作区里除了目标路径还有别的变化（这里直接改工作区，
    # 模拟动作发生以后模型之外的人改了同一个工作区），核实无法断定动作是否发生，
    # 恢复时发决定请求，材料里写明对比结果
    data_dir = tmp_path / "data"
    script = [{"proposal": product_spec()}, {"proposal": engineering_plan()},
              {"output": [_write("call-write", "src/note.txt", "hello\n")]}]
    with killed.interrupted(data_dir, script, tail=[_settle()], resume_after=False,
                            hold_after="tool_started", hold_action="call-write") as run:
        # 恢复之前先让工作区多出一个文件：目标路径没有变，但公开树已经不是动作前的样子
        # （模拟动作发生以后同一个工作区被别处改动）
        run.before.workspace(run.run_id).write_file("src/other.txt", "someone else\n")
        run.after.resume_startup_runs()

        requests = killed.unknown_action_requests(run.after, run.run_id)
        assert len(requests) == 1, "另有改动，核实不判断，交给用户决定"
        payload = requests[0]
        assert payload["action_id"] == "call-write"
        assert payload["tool"] == "write_file"
        assert payload["verification"]["verdict"] == "unclear", "材料写明对比结果"
        assert payload["verification"]["detail"], "对比材料给出判断的依据"

        attempts = killed.tool_attempts(run.after, run.run_id, "call-write")
        assert len(attempts) == 1, "没有结论就不重新执行"

        verified = killed.events(run.after, run.run_id, "action_verified")
        assert verified == [], "交给用户决定时不记自动核实记录"


def test_an_edit_delete_and_move_are_verified_the_same_way(tmp_path):
    # 验收三续：编辑、删除、移动与写入走同一条对比判断。
    # 这一条在单元层面直接驱动对比函数，覆盖三种目标形态各自的判据
    from harness.recovery import verify_file_action

    before = {"digest": "d1", "entries": [["src/note.txt", "hash-a"], ["src/other.txt", "hash-b"]]}

    # 编辑：目标哈希变了、其余路径没变
    edited = verify_file_action("edit_range", {"path": "src/note.txt", "start_line": 1, "end_line": 1,
                                                "content": "changed"},
                                before_snapshot=before,
                                current_entries=[["src/note.txt", "hash-c"], ["src/other.txt", "hash-b"]])
    assert edited["verdict"] == "completed"

    # 删除：目标路径消失、其余路径没变
    deleted = verify_file_action("delete_file", {"path": "src/note.txt"}, before_snapshot=before,
                                 current_entries=[["src/other.txt", "hash-b"]])
    assert deleted["verdict"] == "completed"

    # 移动：来源消失、目标出现且哈希等于动作前的来源哈希
    moved = verify_file_action("move_file", {"source": "src/note.txt", "destination": "src/moved.txt"},
                               before_snapshot=before,
                               current_entries=[["src/moved.txt", "hash-a"], ["src/other.txt", "hash-b"]])
    assert moved["verdict"] == "completed"

    # 工作区与动作前相同：三种动作都判为没有发生
    for tool, arguments in (("edit_range", {"path": "src/note.txt", "start_line": 1, "end_line": 1}),
                            ("delete_file", {"path": "src/note.txt"}),
                            ("move_file", {"source": "src/note.txt", "destination": "src/moved.txt"})):
        result = verify_file_action(tool, arguments, before_snapshot=before,
                                    current_entries=[["src/note.txt", "hash-a"],
                                                     ["src/other.txt", "hash-b"]])
        assert result["verdict"] == "not_happened", tool

    # 另有改动：判为 unclear，交给用户决定
    unclear = verify_file_action("delete_file", {"path": "src/note.txt"}, before_snapshot=before,
                                 current_entries=[["src/note.txt", "hash-a"], ["src/other.txt", "hash-z"]])
    assert unclear["verdict"] == "unclear", "只有目标路径变化才能确认，另有改动交给用户"



def test_a_retry_that_stays_unknown_after_the_chance_is_gone_asks_the_user(tmp_path):
    # 验收四：第一次写入执行前终止（没有发生）；第二次启动自动重新执行一次，这一次也在
    # tool_started 以后被终止（结果仍然未知）；第三次启动机会已经用掉，
    # 核实仍然判「没有发生」也不再重新执行，按 #307 第 3 步发决定请求，
    # 材料的对比结果写明工作区与动作前相同、连续两次结果未知
    data_dir = tmp_path / "data"
    script = [{"proposal": product_spec()}, {"proposal": engineering_plan()},
              {"output": [_write("call-write", "src/note.txt", "hello\n")]}]

    # 第一次：写入执行前终止，公开树仍然是动作前的样子
    first = killed.interrupted(data_dir, script, tail=[], hold_after="tool_started",
                               hold_action="call-write", resume_after=False)
    attempts = killed.tool_attempts(first.before, first.run_id, "call-write")
    assert len(attempts) == 1
    assert attempts[0]["result_type"] is None, "第一次尝试没有落盘结果"

    # 第二次启动：自动重新执行一次；这一次同样在 tool_started 以后被终止
    second = killed.restarted(data_dir, [_settle()], resume_after=False, hold_after="tool_started",
                              hold_action="call-write")
    attempts = killed.tool_attempts(second.before, second.run_id, "call-write")
    assert len(attempts) == 2, "自动重新执行一次，尝试次数是两次"
    assert attempts[1]["auto_retry_of"] == attempts[0]["event_id"]
    assert attempts[1]["result_type"] is None, "第二次尝试也是结果未知"

    # 第三次启动：机会已经用掉，出现决定请求，没有第三次尝试
    third = killed.restarted(data_dir, [], restart_round=3)
    assert len(killed.tool_attempts(third.after, third.run_id, "call-write")) == 2, \
        "上限只算一次，没有第三次尝试"
    requests = killed.unknown_action_requests(third.after, third.run_id)
    assert len(requests) == 1, "机会用掉以后新的尝试仍然结果未知，交给用户决定"
    assert requests[0]["repeat_attempted"] is True, "材料写明连续两次结果未知"
    assert requests[0]["verification"]["verdict"] == "not_happened", "材料写明对比结果"

    third.close()
    second.close()
    first.close()
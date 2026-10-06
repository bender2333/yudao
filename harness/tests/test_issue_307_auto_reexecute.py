# 工单 #307：恢复契约第 4 节。结果未知的动作自动重新执行一次（契约声明可以重复的动作）。
# 三个场景都用真实的子进程运行系统，在工具执行中被终止：读取是同步执行的，没有子进程可等，
# 在 tool_started 提交以后停住；检查与登记命令有真实进程，等它们写下 started 标记以后终止。
# 每次终止以后都用同一个数据目录重新打开系统，走启动恢复。辅助代码在 harness/tests/process_kill.py
# （#317、#308、#143 复用同一套）。

import json
import sys
from pathlib import Path

from harness.proposals import engineering_plan, product_spec
from harness.tests import process_kill as killed
from harness.tests.helpers import WAIT_FOR_RELEASE

# 读取的种子文件：重新执行读的是同一份内容，第二次尝试必须成功
NOTES = "re-execute reads the same bytes\n"


def _call(identity: str, name: str, arguments: dict) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json.dumps(arguments)}


def _check(name: str = "smoke") -> dict:
    # 交付以后的检查：写文件再运行检查，两项都在同一次回答里
    return {"writes": {"src/after.txt": "after"}, "checks": {name: {"argv": [sys.executable, "-c",
                                                                            "print('smoke ok')"]}}}


def _blocking_check(signals: Path) -> dict:
    # 等待放行的真实检查进程：写下 started 以后一直等，被终止时它正在运行
    return {"checks": {"smoke": {"argv": [sys.executable, "-c", WAIT_FOR_RELEASE, str(signals)]}}}


def _attempts(system, run_id: str, action_id: str) -> list[dict]:
    return killed.tool_attempts(system, run_id, action_id)


def _check_action(system, run_id: str) -> str:
    # 找到 run_check 那个逻辑动作的编号（工程部的检查动作）
    started = [event.payload for event in killed.events(system, run_id, "tool_started")
               if event.payload.get("name") == "run_check"]
    assert started, "run_check 没有被执行"
    return str(started[-1]["id"])


def test_a_killed_read_is_retried_once_without_asking_the_user(tmp_path):
    # 验收一：读取工具执行中终止 Yudao 进程，重启以后自动以新的一次尝试读取，没有决定请求，
    # run.actions 显示两次尝试与依据
    data_dir = tmp_path / "data"
    script = [{"proposal": product_spec()}, {"proposal": engineering_plan()},
              {"output": [_call("call-read", "read_file", {"path": "notes.txt"})]}]

    with killed.interrupted(data_dir, script, tail=[_check()],
                            workspace_files={"notes.txt": NOTES},
                            hold_after="tool_started", hold_action="call-read") as run:
        attempts = _attempts(run.after, run.run_id, "call-read")

        assert len(attempts) == 2, "第一次读取结果未知，重启以后应当自动再读一次"
        assert attempts[0]["result_type"] is None, "终止前的第一次读取没有落盘结果"
        assert attempts[1]["auto_retry_of"] == attempts[0]["event_id"], "新的一次尝试指向被取代的那次"
        assert attempts[1]["result_type"] == "tool_called", "重新执行读到了内容"

        assert killed.unknown_action_requests(run.after, run.run_id) == [], "契约声明可以重复的动作不需要问用户"

        actions = [action for action in killed.run_actions(run.after, run.run_id)
                   if action.action_id == "call-read"]
        assert [action.status for action in actions] == ["superseded", "completed"]
        assert actions[1].auto_retry_of == attempts[0]["event_id"]

        records = [record for record in killed.run_recovery(run.after, run.run_id).verifications
                   if record.action_id == "call-read"]
        assert len(records) == 1
        assert records[0].decided_by == "system"
        assert "自动重新执行" in records[0].basis, "核实记录写明依据：契约声明可以重复，自动重新执行"


def test_a_killed_check_is_retried_once_and_the_second_loss_asks_the_user(tmp_path):
    # 验收二：run_check 进行中终止进程，重启后自动重新检查一次；新的尝试中再次终止，
    # 重启后出现决定请求，材料写明连续两次结果未知并提供「重新执行」；
    # 再终止再重启，上限仍然只算一次（不出现第三次尝试）
    data_dir = tmp_path / "data"
    signals = tmp_path / "signals"
    signals.mkdir(exist_ok=True)
    # 重新执行用的是记录下来的 argv，标记一直落在同一个目录；每一轮终止以前删掉上一轮的标记，
    # 否则父进程会以为新一次执行已经开始运行

    # 第一次：检查的真实进程开始运行以后终止
    first = killed.interrupted(data_dir, [{"proposal": product_spec()},
                                          {"proposal": engineering_plan()},
                                          _blocking_check(signals)],
                               started=signals / "started", resume_after=False)
    action_id = _check_action(first.before, first.run_id)
    assert len(_attempts(first.before, first.run_id, action_id)) == 1, "第一次执行只留下一条 tool_started"
    assert _attempts(first.before, first.run_id, action_id)[0]["result_type"] is None

    # 重启：自动重新执行检查；这一次在检查进程中再次终止
    (signals / "started").unlink(missing_ok=True)
    second = killed.restarted(data_dir, [], started=signals / "started", resume_after=False)
    attempts = _attempts(second.before, second.run_id, action_id)
    assert len(attempts) == 2, "自动重新执行一次，尝试次数是两次"
    assert attempts[1]["auto_retry_of"] == attempts[0]["event_id"]
    assert attempts[1]["result_type"] is None, "第二次尝试也是结果未知"

    # 再重启：自动重新执行的机会已经用完，出现决定请求
    third = killed.restarted(data_dir, [], restart_round=3)
    assert len(_attempts(third.after, third.run_id, action_id)) == 2, "上限只算一次，没有第三次尝试"
    requests = killed.unknown_action_requests(third.after, third.run_id)
    assert len(requests) == 1, "连续两次结果未知需要问用户"
    request = requests[0]
    assert request["repeat_attempted"] is True, "材料写明已经重新执行过一次"
    assert [option["id"] for option in request["options"]] == ["reexecute", "continue", "stop"]
    assert "重新执行" in request["description"], "材料写明可以重新执行"

    third.close()
    second.close()
    first.close()


def test_a_registered_command_retry_follows_its_declaration(tmp_path):
    # 验收三：登记命令声明「可以重新执行」的，中途终止以后自动重新执行一次；
    # 没有声明（缺省为否）的，出现决定请求，选项里没有「重新执行」
    declared = _command_case(tmp_path / "declared", repeatable=True)
    undeclared = _command_case(tmp_path / "undeclared", repeatable=None)

    # 声明了「可以重新执行」：自动重新执行一次，没有决定请求
    second = killed.restarted(declared["data"], [], started=declared["signals"] / "started",
                              resume_after=False)
    attempts = _attempts(second.before, second.run_id, declared["action_id"])
    assert len(attempts) == 2, "声明可以重新执行的命令自动重新执行一次"
    assert attempts[1]["auto_retry_of"] == attempts[0]["event_id"]
    second.close()

    # 新的尝试里再次终止：机会已经用完，问用户，并且因为声明过可以重复，给出「重新执行」
    third = killed.restarted(declared["data"], [], restart_round=3)
    requests = killed.unknown_action_requests(third.after, third.run_id)
    assert len(requests) == 1
    assert requests[0]["repeatable"] is True
    assert "reexecute" in [option["id"] for option in requests[0]["options"]]
    third.close()
    declared["close"]()

    # 没有声明：重启以后出现决定请求，选项里没有「重新执行」
    fourth = killed.restarted(undeclared["data"], [])
    assert len(_attempts(fourth.after, fourth.run_id, undeclared["action_id"])) == 1, "没有声明就不自动重新执行"
    requests = killed.unknown_action_requests(fourth.after, fourth.run_id)
    assert len(requests) == 1
    assert [option["id"] for option in requests[0]["options"]] == ["continue", "stop"]
    assert requests[0]["repeatable"] is False
    fourth.close()
    undeclared["close"]()


def _command_case(root: Path, *, repeatable: bool | None) -> dict:
    # 一份登记命令的中断：命令执行到一半终止。repeatable 为空时注册表里不写这一项（缺省为否）。
    # 重新执行用的是记录下来的 argv，标记一直落在同一个目录；每一轮终止以前删掉上一轮的标记
    root.mkdir(exist_ok=True)
    signals = root / "signals"
    signals.mkdir(exist_ok=True)
    command = {"argv": [sys.executable, "-c", WAIT_FOR_RELEASE, str(signals)]}
    if repeatable is not None:
        command["repeatable"] = repeatable
    interrupted = killed.interrupted(
        root / "data",
        [{"proposal": product_spec()}, {"proposal": engineering_plan()},
         {"output": [_call("call-cmd", "run_command", {"name": "tooling"})]}],
        registered_commands={"tooling": command}, started=signals / "started", resume_after=False)
    (signals / "started").unlink(missing_ok=True)
    return {"data": root / "data", "signals": signals, "run_id": interrupted.run_id,
            "action_id": _command_action(interrupted.before, interrupted.run_id),
            "close": interrupted.close}


def _command_action(system, run_id: str) -> str:
    started = [event.payload for event in killed.events(system, run_id, "tool_started")
               if event.payload.get("name") == "run_command"]
    assert started, "登记命令没有被执行"
    return str(started[-1]["id"])
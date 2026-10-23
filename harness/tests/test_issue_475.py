# 工单 #475「重新启动以后同时运行的会话都继续」（三部门的循环结构第 9 节，ADR-0010）。
#
# 本文件覆盖当前结构下能到达的结论：
# (a) 询问分支会话进行中结束 Yudao 进程，重新启动以后分支会话继续（用掉的步数不清零），
#     回答交回提问方，事项运行到放行；
# (b) 工程提交交付以后、质检开始核验以前结束进程，重新启动以后质检开始核验这份交付；
# (c) 重新启动前后，各会话与事项的已用时间与次数连续累计；
# (d) 一个会话中结果未知的动作交还这个会话，模型收到「执行被中断、结果未知」以后接着工作。
#
# 都用真实子进程运行系统并终止，重启后在同一个数据目录上验证。不使用 mock。
# 一个事项里同时运行三个部门会话（工程的写入、质检的预测性探索、产品的询问分支）需要
# #474 的部门按关注的成果开始工作，本文件只覆盖当前结构下存在的会话。

import json
import sys
from typing import Any

from harness.models import EventType
from harness.proposals import delivery, product_spec, review
from harness.tests import process_kill as killed
from harness.tests.helpers import run_wait_command


def _call(identity: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": identity,
        "call_id": identity,
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args),
    }


def _smoke_check() -> dict[str, Any]:
    return {"smoke": {"command": f'"{sys.executable.replace(chr(92), "/")}" -c "print(\'smoke ok\')"'}}


def _session_of(event: Any) -> str | None:
    return event.session_id


def _branch_sessions(events: list[Any]) -> set[str]:
    return {str(event.session_id) for event in events
            if event.session_id and str(event.session_id).startswith("ses_ask_")}


def test_a_branch_session_continues_after_a_restart(tmp_path):
    # (a) 工程询问质检，质检的分支会话跑到一半时结束 Yudao 进程：
    # 重新启动以后分支会话继续（分支的步骤上限不清零），分支里结果未知的动作交还这个分支会话，
    # 回答照常交回提问方，事项运行到放行
    data_dir = tmp_path / "data"
    # 脚本按会话给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）：
    # 质检的分支会话另有一份（被询问的是质检）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [
            {"output": [_call("ask-1", "ask", {
                "recipient": "quality",
                "question": "Does the current snapshot match the requirements?",
                "background": "Engineering needs a second opinion before delivering.",
                "expected": "A verdict on the snapshot."})]},
        ],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
        # 质检的分支会话的第一步：在自己的检查工作区里跑一条命令
        "quality:ask": [
            {"output": [_call("branch-bash", "bash", {"command": "echo inspecting"})]},
        ],
    }
    tail = {
        "quality:ask": [
            {"output": [_call("ans-1", "answer", {"answer": "The snapshot matches the requirements."})]},
        ],
        "engineering": [
            {"proposal": delivery(check_names=["smoke"]),
             "writes": {"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
             "checks": _smoke_check()},
        ],
        "quality": [
            {"proposal": review("release", "checks passed on the current snapshot"),
             "checks": _smoke_check()},
        ],
    }

    with killed.interrupted(data_dir, script, tail=tail, hold_after="tool_started",
                            hold_session="ses_ask_") as run:
        # 终止前：分支会话已经开始，命令的结果还不知道
        before = run.before_events
        branches = _branch_sessions(before)
        assert branches, "没有开出询问分支"
        branch = next(iter(branches))
        started = [event for event in before
                   if event.type == EventType.TOOL_STARTED and event.session_id == branch]
        assert started, "分支会话没有开始执行动作"

        after = run.after.store.list_events(run.run_id)

        # 结果未知的动作交还发出它的会话：核实记录带着分支会话的编号
        handed_back = [event for event in after
                       if event.type == EventType.ACTION_VERIFIED
                       and event.session_id == branch
                       and (event.payload or {}).get("resolution") == "handed_back"]
        assert len(handed_back) == 1, [event.payload for event in after
                                       if event.type == EventType.ACTION_VERIFIED]
        assert (handed_back[0].payload or {}).get("ok") is False
        assert "执行被中断" in (handed_back[0].payload or {}).get("error", "")
        assert "结果未知" in (handed_back[0].payload or {}).get("error", "")

        # 回答交回提问方
        answered = [event for event in after
                    if event.type == EventType.ASK_ANSWERED and event.session_id == branch]
        assert len(answered) == 1, [event.payload for event in after
                                    if event.type == EventType.ASK_ANSWERED]
        assert (answered[0].payload or {}).get("status") == "answered"
        assert (answered[0].payload or {}).get("answer") == "The snapshot matches the requirements."

        # 事项运行到放行
        assert run.after.project(run.run_id).status == "done", run.after.project(run.run_id).status
        released = [event for event in after if event.type == EventType.QA_SUBMITTED]
        assert released, "质检没有提交结论"
        assert (released[0].payload or {}).get("verdict") == "release"


def test_the_delivery_is_verified_after_a_restart(tmp_path):
    # (b) 工程提交交付以后、质检开始核验以前结束进程：重新启动以后质检开始核验这份交付
    data_dir = tmp_path / "data"
    # 脚本按会话给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [
            {"proposal": delivery(check_names=["smoke"]),
             "writes": {"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
             "checks": _smoke_check()},
        ],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
    }
    tail = {
        "quality": [
            {"proposal": review("release", "checks passed on the current snapshot"),
             "checks": _smoke_check()},
        ],
    }

    with killed.interrupted(data_dir, script, tail=tail, hold_after="delivery_accepted") as run:
        # 终止前：交付已经接纳，质检还没有开始核验
        before = run.before_events
        assert [event for event in before if event.type == EventType.DELIVERY_ACCEPTED]
        assert not [event for event in before if event.type == EventType.QA_SUBMITTED]

        after = run.after.store.list_events(run.run_id)
        # 重新启动以后质检开始核验这份交付：质检的会话在交付到达以后才开始
        quality = [event for event in after
                   if event.type == EventType.DEPARTMENT_ACTIVATED and event.department == "quality"]
        assert quality, "质检没有开始核验"
        released = [event for event in after if event.type == EventType.QA_SUBMITTED]
        assert len(released) == 1
        assert (released[0].payload or {}).get("verdict") == "release"
        # 质检核验的是中断前接纳的那份交付
        accepted = [event for event in after if event.type == EventType.DELIVERY_ACCEPTED]
        assert len(accepted) == 1
        assert (released[0].payload or {}).get("delivery_spec_hash") == (
            accepted[0].payload or {}).get("content_hash")
        assert run.after.project(run.run_id).status == "done"


def test_session_and_item_usage_accumulate_across_a_restart(tmp_path):
    # (c) 重新启动前后，各会话与事项的已用时间与次数连续累计：
    # 事项的累计已用时间不倒退；分支会话的模型步数是累计值（中断前用掉的步数不清零）
    data_dir = tmp_path / "data"
    # 脚本按会话给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [
            {"output": [_call("ask-1", "ask", {
                "recipient": "quality",
                "question": "Does the current snapshot match the requirements?",
                "background": "Engineering needs a second opinion before delivering.",
                "expected": "A verdict on the snapshot."})]},
        ],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
        "quality:ask": [
            {"output": [_call("branch-bash", "bash", {"command": "echo inspecting"})]},
        ],
    }
    tail = {
        "quality:ask": [
            {"output": [_call("ans-1", "answer", {"answer": "The snapshot matches the requirements."})]},
        ],
        "engineering": [
            {"proposal": delivery(check_names=["smoke"]),
             "writes": {"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
             "checks": _smoke_check()},
        ],
        "quality": [
            {"proposal": review("release", "checks passed on the current snapshot"),
             "checks": _smoke_check()},
        ],
    }

    with killed.interrupted(data_dir, script, tail=tail, hold_after="tool_started",
                            hold_session="ses_ask_") as run:
        after = run.after.store.list_events(run.run_id)
        finished = [event for event in after if event.type == EventType.ACTIVATION_FINISHED]
        assert finished

        # 事项的累计已用时间不倒退
        elapsed = [int((event.payload or {}).get("elapsed_ms", 0)) for event in finished]
        assert all(x <= y for x, y in zip(elapsed, elapsed[1:])), elapsed

        # 分支会话的累计用量：模型步数是累计值，中断前用掉的那一步仍然算在里面
        branch = next(iter(_branch_sessions(after)))
        branch_finished = [event for event in finished if event.session_id == branch]
        assert branch_finished, "分支会话没有写激活结束事件"
        steps = int((branch_finished[-1].payload or {}).get("session_model_steps", 0))
        assert steps >= 2, steps
        branch_elapsed = int((branch_finished[-1].payload or {}).get("session_elapsed_ms", 0))
        assert branch_elapsed > 0, branch_elapsed
        # 分支会话的已用时间不超过事项的已用时间
        assert branch_elapsed <= elapsed[-1], (branch_elapsed, elapsed[-1])

        # 会话自己的累计步数与事件里数出来的步数一致
        requested = [event for event in after
                     if event.type == EventType.MODEL_REQUESTED and event.session_id == branch]
        assert steps == len(requested), (steps, len(requested))


def test_an_unknown_action_is_handed_back_to_the_session_that_issued_it(tmp_path):
    # (d) 一个会话中结果未知的动作交还这个会话：核实记录带着发出它的会话的编号，
    # 模型的下一个请求里是这个会话的这次工具结果
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
    tail = {
        "engineering": [
            {"proposal": delivery(check_names=["smoke"]),
             "writes": {"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
             "checks": _smoke_check()},
        ],
        "quality": [
            {"proposal": review("release", "checks passed on the current snapshot"),
             "checks": _smoke_check()},
        ],
    }

    with killed.interrupted(data_dir, script, tail=tail, started=signals / "started") as run:
        after = run.after.store.list_events(run.run_id)
        started = [event for event in after
                   if event.type == EventType.TOOL_STARTED
                   and (event.payload or {}).get("id") == "call-bash"]
        assert len(started) == 1
        session = started[0].session_id
        assert session, "动作没有记下发出它的会话"

        handed_back = [event for event in after
                       if event.type == EventType.ACTION_VERIFIED
                       and (event.payload or {}).get("id") == "call-bash"]
        assert len(handed_back) == 1
        assert handed_back[0].session_id == session
        assert (handed_back[0].payload or {}).get("resolution") == "handed_back"

        # 模型收到这次工具结果：执行被中断、结果未知
        outputs = [item for invocation in run.after.test_adapter.invocations
                   for item in invocation.input_items
                   if isinstance(item, dict) and item.get("type") == "function_call_output"
                   and item.get("call_id") == "call-bash"]
        assert outputs, "模型没有收到这次动作的结果"
        data = json.loads(outputs[0]["output"])
        assert data["ok"] is False
        assert "执行被中断" in data["error"] and "结果未知" in data["error"]

        # 这个会话接着工作，事项运行到放行
        assert run.after.project(run.run_id).status == "done", run.after.project(run.run_id).status
        released = [event for event in after if event.type == EventType.QA_SUBMITTED]
        assert len(released) == 1
        assert (released[0].payload or {}).get("verdict") == "release"

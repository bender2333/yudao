# 故障矩阵第 13 行：恢复与取消/撤销并发（恢复契约与故障矩阵 docs/design/recovery-contract-and-fault-matrix.md「故障矩阵」）。
# 真实的进程终止以后，恢复与取消按持久控制顺序处理：先已生效的取消不能被恢复越过。
# 两条顺序各一条用例：取消先写入事件库，再走启动恢复；以及恢复先取得执行权，取消随后写入。
# 两种顺序下都不再调用模型、不再执行工具，结果未知的动作也不会被恢复补做或补执行。
# 定义撤销的那一半按设计说明属于「对应能力存在时验收」（本机没有撤销定义的能力，这一条不写成通过）。
#
# 层：集成层（真实子进程被终止、真实事件库、真实工作区文件；中断与重启的辅助代码在 harness/tests/process_kill.py）。
# 守 R1（持久控制顺序与执行权：取消先生效就不会被恢复取得执行权或越过；结果未知的动作不再被补执行）
# 与 R3（重启后的接续与取消：恢复先开始也不能阻止随后生效的取消停掉后续分派）。
# 会让这些用例失败的反例：取消以后重启仍然写 run_resumed 或发起模型请求、重发工具（第 1 条），
# 或者恢复取得执行权以后取消，继续执行时仍然派发模型请求或工具（第 2 条）。

import json

from harness.models import EventType
from harness.proposals import product_spec
from harness.tests import process_kill as killed


def _write(identity: str, path: str, content: str) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "write_file",
            "arguments": json.dumps({"path": path, "content": content})}


def _script() -> dict:
    # 产品提交规格，工程写一个文件；写文件执行到结果落盘、回执未写时进程被终止。
    # 质检也要脚本：PRD 被接纳以后质检会话也发起模型请求
    return {
        "product": [{"proposal": product_spec()}],
        "engineering": [{"output": [_write("call-write", "src/note.txt", "hello\n")]}],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
    }


def _cancel_ending(run) -> int:
    # 取消写下的结束事件（run_failed，停止原因 cancelled）的位置
    ending = [event for event in run.after.store.list_events(run.run_id)
              if event.type == EventType.RUN_FAILED]
    assert ending, "取消没有写入结束事件"
    assert ending[-1].stop_reason == "cancelled", ending[-1].stop_reason
    return ending[-1].position


def test_a_cancel_recorded_before_the_restart_is_not_overtaken_by_recovery(tmp_path):
    data_dir = tmp_path / "data"
    with killed.interrupted(data_dir, _script(), await_file=("src/note.txt", "hello\n"),
                            resume_after=False) as run:
        # 故障矩阵第 13 行：中断以后、恢复以前：用户取消。取消经真实的命令写入事件库
        cancelled = run.after.cancel(run.run_id)
        assert cancelled.status == "failed"
        assert cancelled.stop_reason == "cancelled"
        cancel_position = _cancel_ending(run)

        # 启动恢复：已经生效的取消不可被越过，这个 run 不取得执行权、不继续运行
        assert run.after.resume_startup_runs() == {}
        assert run.after.test_adapter.invocations == []
        projection = run.after.project(run.run_id)
        assert (projection.status, projection.stop_reason) == ("failed", "cancelled")
        later = [event for event in run.after.store.list_events(run.run_id)
                 if event.position > cancel_position]
        assert later == [], [event.type for event in later]

        # 结果未知的动作留在原处：恢复没有核实、也没有补执行这一次写入；
        # 工作区里那次写入已经发生，工具没有被重新执行
        actions = [action for action in killed.run_actions(run.after, run.run_id)
                   if action.action_id == "call-write"]
        assert [action.status for action in actions] == ["running"]
        assert not [event for event in killed.events(run.after, run.run_id, "action_verified")
                   if (event.payload or {}).get("id") == "call-write"]
        started = [event for event in killed.events(run.after, run.run_id, "tool_started")
                   if (event.payload or {}).get("id") == "call-write"]
        assert len(started) == 1
        assert run.after.workspace(run.run_id).read_file("src/note.txt") == "hello\n"


def test_a_cancel_that_arrives_after_recovery_started_stops_further_dispatch(tmp_path):
    data_dir = tmp_path / "data"
    with killed.interrupted(data_dir, _script(), await_file=("src/note.txt", "hello\n"),
                            resume_after=False) as run:
        # 故障矩阵第 13 行：恢复先开始：取得执行权（写下继续的依据、核实结果未知的文件动作），还没有继续执行
        claimed = run.after.orchestrator.resume_incomplete_run(run.run_id)
        assert claimed is not None, "恢复没有取得执行权"
        resumed = [event for event in killed.events(run.after, run.run_id, "run_resumed")]
        assert len(resumed) == 1

        # 后来取消：取消持久生效，恢复不能越过它继续派发
        run.after.cancel(run.run_id)
        cancel_position = _cancel_ending(run)
        result = run.after.run_until_stop(run.run_id)
        assert result.status == "failed" and result.stop_reason == "cancelled"
        assert run.after.test_adapter.invocations == []
        later = [event for event in run.after.store.list_events(run.run_id)
                 if event.position > cancel_position]
        assert [event.type for event in later if event.type in {
            EventType.MODEL_REQUESTED, EventType.TOOL_STARTED, EventType.DEPARTMENT_ACTIVATED,
        }] == []
        # 这一次写入没有被重新执行
        started = [event for event in killed.events(run.after, run.run_id, "tool_started")
                   if (event.payload or {}).get("id") == "call-write"]
        assert len(started) == 1

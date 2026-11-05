# 工单 #308：恢复契约第 4 节第 1 步。Yudao 自己的文件工具（write_file、edit_range、delete_file、
# move_file）结果未知时自动核实：按动作前的公开树快照、动作参数与当前公开树对比，
# 只有目标路径变成目标内容才记一条自动核实记录，其余情况作为工具结果交还发出它的会话
# （工单 #581：不再以新的尝试重新执行这个动作，也不发决定请求）。
# 四个场景都用真实的子进程运行系统，在工具执行中被终止。写入、编辑、删除、移动在执行环境里是
# 同步的、没有可等待的进程，「没有发生」用 tool_started 提交以后停住来制造（执行前终止），
# 「已经发生」用工作区文件变成目标内容以后子进程自己终止来制造（写入已落盘、回执未写）。
# 辅助代码在 harness/tests/process_kill.py（#307 已合并）。测试里不 mock。

import json
import sys

from harness.proposals import product_spec
from harness.tests import process_kill as killed


def _write(identity: str, path: str, content: str) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "write_file",
            "arguments": json.dumps({"path": path, "content": content})}


def _settle() -> dict:
    # 交付以后的检查：模型按核实结果继续往下走
    return {"writes": {"src/done.txt": "done"},
            "checks": {"smoke": {"command": f"\"{sys.executable.replace(chr(92), chr(47))}\" -c \"print('smoke ok')\""}}}

def _tool_started(system, run_id: str, action_id: str) -> list[dict]:
    # 整个 run 里这一个调用编号的 tool_started（工单 #943）：恢复不再自动重新执行动作（工单 #581），
    # 动作被重新执行时这里会多出几条——结果没有交还、命令被再运行，用例要在它上面失败
    return [event.payload for event in killed.events(system, run_id, "tool_started")
            if (event.payload or {}).get("id") == action_id]


def test_other_changes_after_the_snapshot_ask_the_user(tmp_path):
    # 验收三（另有改动）：中断以后工作区里除了目标路径还有别的变化，核实无法断定动作是否发生（unclear），
    # 按非文件动作交还模型处理，没有决定请求
    data_dir = tmp_path / "data"
    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）：
    # 产品提交规格，写文件是工程的活；重启以后父进程里接着跑的后半脚本同样按部门给出
    # 质检也要给脚本（工单 #943：工单 #935 查出的同一处隐患。PRD 被接纳以后质检会话也发起模型请求，
    # 没有它的脚本时假模型报「脚本用尽」，整个 run 以 provider_error 提前结束，
    # 用例在到达中断点以前就失败；这里的日志是空的，风险窗口比 #935 窄，但成因相同）
    script = {
        "product": [{"proposal": product_spec()}],
        "engineering": [{"output": [_write("call-write", "src/note.txt", "hello\n")]}],
        "quality": [{"proposal": {"kind": "quality_auto"}}],
    }
    with killed.interrupted(data_dir, script, tail={"engineering": [_settle()], "quality": [{"proposal": {"kind": "quality_auto"}}]},
                            resume_after=False,
                            hold_after="tool_started", hold_action="call-write") as run:
        run.before.workspace(run.run_id).write_file("src/other.txt", "someone else\n")
        run.after.resume_startup_runs()

        attempts = killed.tool_attempts(run.after, run.run_id, "call-write")
        assert len(attempts) == 1

        verified = killed.events(run.after, run.run_id, "action_verified")
        assert len(verified) == 1
        assert verified[0].payload["resolution"] == "handed_back"
        assert verified[0].payload["ok"] is False
        assert verified[0].payload["verification"]["verdict"] == "unclear"
        # 结果确实交还了模型（工单 #943）：运行因为提供方报错提前结束的时候，
        # 重启与交还都没有发生，「没有重新执行」就成了一句空话
        assert verified[0].payload["id"] == "call-write"
        # 命令没有被再运行：整个 run 里只有最初那一次调用
        assert len(_tool_started(run.after, run.run_id, "call-write")) == 1

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

    # 另有改动：判为 unclear，作为工具结果交还发出它的会话
    unclear = verify_file_action("delete_file", {"path": "src/note.txt"}, before_snapshot=before,
                                 current_entries=[["src/note.txt", "hash-a"], ["src/other.txt", "hash-z"]])
    assert unclear["verdict"] == "unclear", "只有目标路径变化才能确认，另有改动交还发出它的会话"


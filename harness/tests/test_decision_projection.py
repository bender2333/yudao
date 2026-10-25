import pytest

from harness.adapters.fake import FakeAdapter
from harness.event_store import StreamVersionConflict, run_stream
from harness.models import EventType
from harness.projection import saved_decisions
from harness.runtime import LoopSystem
from harness.write_path import NewEvent

# 决定请求保存的投影：写入口在追加请求、回答与撤销事件的同一事务中更新它；按身份查找，按项目、事项、种类与状态
# 列出，并与日志末尾位置一起读取；删除保存的投影以后由重放补建。这里经写入口直接写入决定事件，检查保存的投影；
# 由流程编排发出请求、由命令回答的行为在 test_decisions.py。


def _requested(department: str = "product") -> NewEvent:
    return NewEvent(EventType.DECISION_REQUESTED, state_before="running", state_after="running",
                    actor="system", department=department, payload={
                        "kind": "model_unavailable", "blocks": "run",
                        "options": [{"id": "continue", "label": "继续执行"}, {"id": "stop", "label": "停止事项"}],
                        "description": f"{department} 部门的模型无法使用：Missing configuration: provider credential",
                        "facts": [], "department": department, "target": None,
                        "reason": "provider_unavailable", "message": "Missing configuration: provider credential",
                    })


def _runs(data_dir):
    # 两个项目各有事项与 run，另有一个不属于项目的 run
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    first = system.projects.register("项目一", "逐行文本处理工具")
    second = system.projects.register("项目二", "日志汇总工具")
    item_a, run_a = system.projects.start_work_item(first, "事项 A")
    item_b, run_b = system.projects.start_work_item(first, "事项 B")
    item_c, run_c = system.projects.start_work_item(second, "事项 C")
    bare = system.create_run("bare run")
    return system, {"first": first, "second": second, "item_a": item_a, "item_b": item_b, "item_c": item_c,
                    "run_a": run_a, "run_b": run_b, "run_c": run_c, "bare": bare}


def _append(system, run_id, *entries, command=None):
    return system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(*entries),
                                  command=command)


def test_a_transaction_that_does_not_commit_saves_no_decision_request(data_dir):
    system, ids = _runs(data_dir)
    stream = run_stream(ids["run_a"])
    version = system.writes.read(stream).version
    _append(system, ids["run_a"], _requested())
    end = system.store.end_position()

    # 期望版本已经过期：什么也不写，决定请求保存的投影不变
    with pytest.raises(StreamVersionConflict):
        system.writes.transact(stream, lambda transaction: transaction.append(_requested("engineering")),
                               expected_version=version)

    def fails(transaction):
        transaction.append(_requested("quality"))
        raise RuntimeError("judgment failed after appending")

    with pytest.raises(RuntimeError):
        system.writes.transact(stream, fails)
    assert system.store.end_position() == end
    _position, decisions = saved_decisions(system.store)
    assert [item.request["department"] for item in decisions] == ["product"]



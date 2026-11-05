# 成果失效写成一条事件（骨架事件 artifact_invalidated，工单 #858 的第一条与第二条验收）：
# 六种情形各有一条用例 —— 发生的那一刻记下一条成果失效事件，当前交付随之失效；
# 投影不再从工具调用与其他接纳事件推出失效，RunProjection 与最小投影都只折叠这一条。
# 守第 13 节的 R1（同样的事件重放出同样的状态）：两份投影从同一组事件得出同一个当前交付。
#
# 六种情形（骨架与应用设计说明第 4 节，清点第 4 节第 1 条）：
# 1. 非质检部门写文件的工具调用成功（workspace_changed）
# 2. PRD 被接纳（product_spec_changed）
# 3. 契约被接纳（effective_contract_changed）
# 4. 新交付被接纳（replaced）
# 5. 基线核验返工产品（baseline_rework_product）
# 6. 质检返工工程（qa_rework_engineering）
#
# 第 4、5 两种到不了写入口：工程提交交付之前必须先写文件，而写文件本身已经让上一版交付失效，
# 所以「接纳新的交付时上一版还是当前版本」在成果驱动的路由下不会发生；建档事项的工程部门没有
# 提交交付的工具，基线核验退回产品时也没有当前交付。这两条按「记事件的函数 → 写入口 → 投影」
# 验证：函数给出的事件与写文件、返工那几条走的是同一份载荷与同一个折叠。

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.event_store import run_stream
from harness.minimal_projection import fold_events
from harness.models import EventType
from harness.proposals import delivery_turn, product_decision, product_spec, product_spec_turn
from harness.runtime import LoopSystem
from harness.submissions import invalidation
from harness.tests.event_scenarios import SCENARIOS
from harness.tests.helpers import explore_turn
from harness.write_path import NewEvent

CHECKS = {"smoke": {"command": "python -c \"print('smoke ok')\""}}
ECHO = "import sys\nprint(sys.argv[1])\n"
TASK = "build an echo CLI"

# 失效事件的三种原因之外，六种情形各一种：这里是写进载荷的取值的全部
REASONS = ("workspace_changed", "product_spec_changed", "effective_contract_changed",
           "replaced", "baseline_rework_product", "qa_rework_engineering")


def _delivered(data_dir):
    # 一个有当前交付的事项：产品提交 PRD，工程交付。质检的脚本留着一轮探索，用例自己决定跑不跑它
    adapter = FakeAdapter({"product": [product_spec()],
                           "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
                           "quality": [explore_turn()]})
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run(TASK)
    system.activate_once(run_id)   # 产品提交 PRD
    system.activate_once(run_id)   # 工程交付
    assert system.project(run_id).delivery_spec is not None, "场景没有走到有当前交付的一步"
    return system, adapter, run_id


def _invalidations(system, run_id):
    # 这个事项里的全部成果失效事件：成果种类、版本与原因
    return [(event.payload.get("artifact_kind"), event.payload.get("artifact_version"), event.payload.get("reason"))
            for event in system.store.list_events(run_id) if event.type == EventType.ARTIFACT_INVALIDATED]


def _write_invalidation(system, run_id, kind, version, reason):
    # 经写入口追加一条成果失效事件（与成果驱动写它的路径相同）
    system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
        EventType.ARTIFACT_INVALIDATED, actor="system", state_before=transaction.projection.status,
        state_after=transaction.projection.status,
        payload={"artifact_kind": kind, "artifact_version": version, "reason": reason})))


def test_writing_a_file_by_a_non_quality_department_invalidates_the_current_delivery(data_dir):
    # 情形 1：工程按指导改文件（write_file 成功），当前交付失效，原因写工作区被改动
    system, adapter, run_id = _delivered(data_dir)
    system.add_guidance(run_id, "engineering", "顺手把输出改一下。")
    adapter.scripts["engineering"].append(FakeTurn(writes={"src/echo.py": "print('changed')\n"},
                                                   transcript="改好了。"))
    system.activate_once(run_id)   # 工程按指导改文件

    state = system.project(run_id)
    assert _invalidations(system, run_id) == [("delivery_spec", 1, "workspace_changed")]
    assert state.delivery_spec is None
    assert state.delivery_specs[-1].status == "superseded"
    assert state.delivery_specs[-1].invalidation_reason == "workspace_changed"


def test_a_new_product_spec_invalidates_the_current_delivery(data_dir):
    # 情形 2：用户在交付之后补一句要求，产品提交新的 PRD，当前交付失效
    system, adapter, run_id = _delivered(data_dir)
    system.add_input(run_id, "把输出改成大写。")
    adapter.scripts["product"].append(product_spec_turn(
        requirements=["print the given argument in uppercase to stdout"],
        change_record={"changed": ["print the given argument in uppercase to stdout"],
                       "retained": ["single file implementation"], "retired": [],
                       "rationale": "用户要求输出大写"}))
    system.activate_once(run_id)   # 产品提交 PRD 的新版本

    state = system.project(run_id)
    assert _invalidations(system, run_id) == [("delivery_spec", 1, "product_spec_changed")]
    assert state.delivery_spec is None
    assert state.delivery_specs[-1].invalidation_reason == "product_spec_changed"


def test_a_new_effective_contract_invalidates_the_current_delivery(data_dir):
    # 情形 3：产品补一条决定，有效合同重新签发（PRD 正文没改），当前交付失效
    system, adapter, run_id = _delivered(data_dir)
    system.add_input(run_id, "补一条决定：输出保留换行。")
    adapter.scripts["product"].append(product_decision("输出保留换行。", "交付的输出格式需要说清楚。"))
    system.activate_once(run_id)   # 产品提交产品决定，主机签发新的有效合同

    state = system.project(run_id)
    assert _invalidations(system, run_id) == [("delivery_spec", 1, "effective_contract_changed")]
    assert state.delivery_spec is None
    assert state.delivery_specs[-1].invalidation_reason == "effective_contract_changed"


def test_quality_rework_invalidates_the_current_delivery(data_dir):
    # 情形 6：质检以 rework_engineering 退回，当前交付失效；工程重新交付以后它又是当前版本
    scenario = SCENARIOS["quality_rework"]
    system, run_id, _replacements = scenario.run(data_dir)
    assert ("delivery_spec", 1, "qa_rework_engineering") in _invalidations(system, run_id)
    reworked = [delivery for delivery in system.project(run_id).delivery_specs if delivery.revision == 2]
    assert reworked and reworked[0].status == "active"


@pytest.mark.parametrize("reason", REASONS)
def test_each_situation_writes_one_event_that_ends_the_current_delivery(data_dir, reason):
    # 六种情形各一条：记事件的函数给出成果种类、版本与原因，写进写入口以后两份投影都不再有这一版。
    # 情形 4、5 到不了写入口（见文件开头），这一条按写入方与投影共用的同一个函数验证它们的载荷与折叠
    system, _adapter, run_id = _delivered(data_dir)
    event = invalidation(system.project(run_id), reason)
    assert event is not None, f"{reason}：有当前交付，应当记一条成果失效事件"
    event_type, payload = event
    assert event_type == EventType.ARTIFACT_INVALIDATED
    assert payload == {"artifact_kind": "delivery_spec", "artifact_version": 1, "reason": reason}

    system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
        event_type, actor="system", state_before=transaction.projection.status,
        state_after=transaction.projection.status, payload=payload)))

    state = system.project(run_id)
    assert state.delivery_spec is None
    assert state.delivery_specs[-1].status == "superseded"
    assert state.delivery_specs[-1].invalidation_reason == reason
    # 最小投影折同一组事件：这一种成果不再有当前版本（S1a 的对照在各份基准上逐项比较）
    projection = fold_events(system.store.list_events(run_id))
    assert projection.artifacts.get("delivery_spec") is None


def test_an_invalidation_of_another_kind_leaves_the_delivery_alone(data_dir):
    # 失效事件指名的是哪一种成果的哪一版：不是当前交付的那一种时，当前交付不变
    # （第二种路由可以带自己的成果种类，投影不为它猜）
    system, _adapter, run_id = _delivered(data_dir)
    _write_invalidation(system, run_id, "product_spec", 1, "replaced")
    assert system.project(run_id).delivery_spec is not None


def test_an_invalidation_of_another_version_leaves_the_current_delivery_alone(data_dir):
    # 指名的那一版不是当前版本时当前交付不变：迟到的失效事件不会让后来那一版失效
    system, _adapter, run_id = _delivered(data_dir)
    _write_invalidation(system, run_id, "delivery_spec", 2, "replaced")
    assert system.project(run_id).delivery_spec is not None


def test_no_invalidation_event_is_written_when_there_is_no_current_delivery(data_dir):
    # 没有当前交付时没有要失效的成果：不记事件（否则事件流里多出一条什么也没改变的事实）
    system = LoopSystem.for_testing(data_dir, FakeAdapter({"product": [product_spec()]}))
    run_id = system.create_run(TASK)
    system.activate_once(run_id)
    state = system.project(run_id)
    assert state.delivery_spec is None
    assert invalidation(state, "workspace_changed") is None
    assert _invalidations(system, run_id) == []


def test_the_projection_no_longer_infers_invalidation_from_a_tool_call(data_dir):
    # 第二条验收：补一条「非质检部门写了文件」的工具结果事件，投影不再自己让交付失效。
    # 失效只来自成果失效事件（上面各条），这条守着「删掉推断」没有被加回来
    system, _adapter, run_id = _delivered(data_dir)
    system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
        EventType.TOOL_CALLED, actor="department:engineering", department="engineering",
        state_before=transaction.projection.status, state_after=transaction.projection.status,
        payload={"name": "write_file", "ok": True, "id": "added-by-the-test"})))

    state = system.project(run_id)
    assert state.delivery_spec is not None, "投影不应从工具调用推出交付失效"
    assert _invalidations(system, run_id) == []

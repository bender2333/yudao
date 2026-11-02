import time

from harness.watched_outputs import has_new_work
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.engine import StepLimits
from harness.proposals import delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import list_files_turn, quality_turns

def _slow(turn):
    # 模型调用持续超过 1 秒的运行时间限制
    def respond(_call):
        time.sleep(1.2)
        return turn

    return respond

def test_time_limit_stops_run_with_failed_state(data_dir):
    # 运行时间限制为 1 秒，第一次模型调用期间运行时间用完
    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    script = {"product": [_slow(product_spec())], "engineering": [delivery_turn()],
              "quality": [FakeTurn(proposal=None, transcript="working") for _ in range(100)]}
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo", run_time_limit_sec=1, max_cycles=999)
    result = system.activate_once(run_id)
    assert result.status == "failed"
    assert result.stop_reason == "time_limit"
    assert result.human_action is not None
    assert "运行时间已达上限" in (result.waiting_reason or "")

def test_time_limit_checked_between_activations(data_dir):
    # #470 删除工程计划以后工程激活只有交付一步：第一次激活提交产品约定，
    # 第二次激活提交交付并转入质检
    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    script = {"product": [product_spec()], "engineering": [delivery_turn()],
              "quality": [judgement_turn(), review_turn("release", "ok")]}
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo", run_time_limit_sec=10)
    # 第一次激活正常完成；两次激活之间的等待不计入运行时间（工单 #350，按 #410 对齐短时限到 10 秒避免负载抖动），
    # 第二次激活开始时累计还没有达到上限，照常进行
    result = system.activate_once(run_id)
    assert has_new_work(result, "engineering")
    time.sleep(10.2)
    result = system.activate_once(run_id)
    assert result.stop_reason is None
    assert has_new_work(result, "quality")
    assert len(system.test_adapter.invocations) == 2


def test_loosened_step_limit_allows_more_than_32_steps(data_dir):
    # 最大模型步数的默认值是 999999（StepLimits），不再是 32
    # 用超过 32 个步骤后提交，验证不会暂停
    many_steps = [list_files_turn for _ in range(40)]
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [product_spec()],
        "engineering": [*many_steps, delivery_turn()],
        "quality": quality_turns("release", "ok"),
    }
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo")
    result = system.run_until_stop(run_id)
    assert result.status == "done"


def test_small_step_limit_still_pauses(data_dir):
    script = [
        FakeTurn(proposal=None, transcript="step1"),
        FakeTurn(proposal=None, transcript="step2"),
        FakeTurn(proposal=None, transcript="step3"),
        FakeTurn(proposal=None, transcript="step4"),
    ]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script), step_limits=StepLimits(max_model_steps=3))
    run_id = system.create_run("echo", run_time_limit_sec=7200)
    result = system.activate_once(run_id)
    assert result.status == "paused"
    assert result.stop_reason == "model_steps_exhausted"



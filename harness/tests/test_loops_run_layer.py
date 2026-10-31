# run 层的收敛判定（工单 #1194 的验收）：只按放行记录里算好的覆盖数判定，没有逐条结论的旧 run
# 写「缺少的事实」不判定；限额只由停止原因判定；震荡按同一条验收条件的结论翻转次数。
# 判定是纯函数（harness/loops.py 的 run_state 与 build_loop_tree），这些结论不写事件、不调用模型，登记为单元层。
# 守 R2（画面合同：投影两头的判定语义）。

from harness import loops
from harness.models import Event, EventType
from harness.parameters import FROZEN_PARAMETERS, initial_values


def frozen(**overrides):
    values = {name: initial_values()[name] for name in FROZEN_PARAMETERS}
    values.update(overrides)
    return {"values": values}


def event(kind: str, position: int, *, payload: dict | None = None, stop_reason: str | None = None) -> Event:
    return Event(
        event_id=f"evt-{position}", run_id="run-1", type=kind, role=None, parent_event_id=None,
        state_before="running", state_after="running", payload=payload or {}, artifact_hashes=[],
        session_id=None, provider=None, model=None, context_digest=None, stop_reason=stop_reason,
        error=None, created_at="2026-10-31T00:00:00+00:00", position=position, stream="run:run-1",
        stream_version=position, project_id="proj-1", work_item_id="wi-1", department=None,
    )


def created(**overrides) -> Event:
    return event(EventType.RUN_CREATED, 1, payload={
        "project_id": "proj-1", "work_item_id": "wi-1", "kind": "change",
        "max_cycles": 999999, "run_time_limit_sec": 7200,
        "sessions": {"product": "product", "engineering": "engineering", "quality": "quality"},
        "parameters": frozen(**overrides),
    })


def submitted(position: int, *, criteria: list[dict], executable: int, covered: int) -> Event:
    # 一份放行记录：逐条结论与 #151 在放行时算好的覆盖数（判定只读这里，不重新计算）
    return event(EventType.QA_SUBMITTED, position, payload={
        "criteria": criteria, "coverage": {"criteria_total": len(criteria), "executable": executable,
                                           "covered": covered, "coverage_ratio": 0.0,
                                           "model_reading": 0, "open": len(criteria) - executable},
    })


def _passed(criterion: str, result: str = "passed") -> dict:
    return {"criterion": criterion, "method": "check", "result": result}


def test_a_run_without_criterion_conclusions_is_not_judged_and_says_what_is_missing():
    # 旧 run：qa_submitted 没有逐条结论与覆盖数 → 不判定，写明缺少的事实
    tree = loops.build_loop_tree([created(), event(EventType.QA_SUBMITTED, 2, payload={"verdict": "release"})])
    run = next(layer for layer in tree.layers if layer.name == "run")
    assert run.state == loops.UNDETERMINED
    assert run.missing == loops.MISSING_RUN


def test_the_run_layer_reads_the_coverage_numbers_from_the_release_record():
    # 覆盖数是放行时算好的：criteria 全部 passed，但覆盖数说 5 条可执行里只覆盖了 1 条，
    # 判定按覆盖数得到未满足 4 条（不变的两轮 → 停滞），不重新数 criteria
    reviews = [{"criteria": [_passed("AC1")], "coverage": {"executable": 5, "covered": 1}},
               {"criteria": [_passed("AC1")], "coverage": {"executable": 5, "covered": 1}}]
    state, missing = loops.run_state(reviews, rounds=3, stop_reason=None)
    assert (state, missing) == (loops.STALLED, None)


def test_unsatisfied_strictly_decreasing_is_converging_and_zero_is_converging():
    reviews = [{"criteria": [], "coverage": {"executable": 3, "covered": 0}},
               {"criteria": [], "coverage": {"executable": 3, "covered": 2}},
               {"criteria": [], "coverage": {"executable": 3, "covered": 3}}]
    assert loops.run_state(reviews, rounds=3, stop_reason=None) == (loops.CONVERGING, None)
    assert loops.run_state(reviews[1:], rounds=3, stop_reason=None) == (loops.CONVERGING, None)


def test_unchanged_unsatisfied_is_stalled():
    reviews = [{"criteria": [], "coverage": {"executable": 4, "covered": 1}}] * 3
    assert loops.run_state(reviews, rounds=3, stop_reason=None) == (loops.STALLED, None)


def test_a_conclusion_flipping_twice_is_oscillating():
    # 同一条验收条件的结论翻转两次（passed → failed → passed）→ 震荡；翻转阈值是方法常量 2
    reviews = [
        {"criteria": [_passed("AC1", "passed")], "coverage": {"executable": 1, "covered": 0}},
        {"criteria": [_passed("AC1", "failed")], "coverage": {"executable": 1, "covered": 0}},
        {"criteria": [_passed("AC1", "passed")], "coverage": {"executable": 1, "covered": 0}},
    ]
    assert loops.run_state(reviews, rounds=3, stop_reason=None) == (loops.OSCILLATING, None)


def test_a_window_that_is_not_full_is_not_judged_and_says_how_many_rounds_it_needs():
    reviews = [{"criteria": [], "coverage": {"executable": 2, "covered": 0}}]
    state, missing = loops.run_state(reviews, rounds=3, stop_reason=None)
    assert state == loops.UNDETERMINED
    assert missing == loops.MISSING_RUN_WINDOW.format(rounds=3)


def test_eight_rounds_use_the_fixed_rank_trend():
    # 轮数达到 8：用秩相关（下降 → 收敛中；不变 → 停滞），方法常量不进可调参数
    decreasing = [{"criteria": [], "coverage": {"executable": 8, "covered": index}}
                  for index in range(8)]  # 未满足 8,7,…,1
    assert loops.run_state(decreasing, rounds=8, stop_reason=None) == (loops.CONVERGING, None)
    flat = [{"criteria": [], "coverage": {"executable": 8, "covered": 3}}] * 8
    assert loops.run_state(flat, rounds=8, stop_reason=None) == (loops.STALLED, None)


def test_the_limit_stop_reasons_reach_the_boundary_without_looking_at_numbers():
    assert loops.run_state([], rounds=3, stop_reason="time_limit") == (loops.BOUNDARY, None)
    assert loops.run_state([], rounds=3, stop_reason="max_cycles") == (loops.BOUNDARY, None)
    assert loops.run_state([], rounds=3, stop_reason="model_steps_exhausted") == (loops.BOUNDARY, None)
    # 不在限额清单里的停止原因不看数值，仍按缺少的事实判定
    assert loops.run_state([], rounds=3, stop_reason="release")[0] == loops.UNDETERMINED


def test_rising_unsatisfied_is_not_judged_and_says_why():
    reviews = [{"criteria": [], "coverage": {"executable": 3, "covered": 2}},
               {"criteria": [], "coverage": {"executable": 3, "covered": 0}}]
    assert loops.run_state(reviews, rounds=3, stop_reason=None) == (loops.UNDETERMINED, loops.MISSING_RUN_RISING)

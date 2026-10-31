# 工单 #1179：质检无法核验（cannot_verify）。
# 质检自己的条件不够（模型不支持图像输入而条目依赖外观、执行位置缺少试用或运行交付需要的程序）时，
# 不是放行也不是退回：提交 cannot_verify（没有 failed，至少一条 unverified，每条写明原因），
# 流程编排发出决定请求，阻塞整个 run；回答「重新核验」以后质检以新的激活重新检查同一份交付，
# 回答「停止事项」以后事项结束、交付不被采纳（浏览器与 computer use 设计说明第 8.3、8.4 节）。
# 模型回答由 FakeAdapter 的脚本给出，数据目录是真实的；冻结参数与运行时间上限用测试默认值。

from harness.adapters.fake import FakeAdapter
from harness.event_store import Command, run_stream
from harness.models import EventType, TERMINAL_STATUSES, new_id
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.recovery import observation_state
from harness.runtime import LoopSystem
from harness.watched_outputs import has_new_work

AC = ["prints the argument", "exits 0"]
# 逐条结论引用验收条件的写法：AC 加它在当前 PRD 里的位置
AC1, AC2 = "AC1", "AC2"


def _criteria(results: dict[str, str], notes: dict[str, str] | None = None,
              checks: list[str] | None = None) -> list[dict[str, object]]:
    # 逐条结论：验收条件、检验方式（外观依赖模型看图，判为不可执行的检验）、结果、证据与原因
    notes = notes or {}
    return [{"criterion": criterion, "method": "judgement", "result": results[criterion],
             "checks": list(checks or []), "trial_cases": [], "note": notes.get(criterion, "")}
            for criterion in (AC1, AC2)]


def _cannot_verify() -> list[dict[str, object]]:
    return _criteria({AC1: "unverified", AC2: "unverified"},
                     {AC1: "质检的模型不支持图像输入，看不到界面", AC2: "执行位置没有安装浏览器"})


def _answer_command() -> Command:
    # 回答决定请求经应用层的 decision.answer 命令；测试直接调用流程编排时造一个身份
    return Command(command_id=new_id("cmd"), name="decision.answer", digest="test", actor="user")


def _events(system: LoopSystem, run_id: str) -> list:
    return system.store.list_events(run_id)


def _open_decision(system: LoopSystem, run_id: str):
    return [decision for decision in system.writes.read(run_stream(run_id)).decisions.values()
            if decision.status == "open" and decision.request.get("kind") == "qa_cannot_verify"]


def _system(tmp_path, quality_turns):
    script = {"product": [product_spec(acceptance=AC)], "engineering": [delivery_turn()],
              "quality": quality_turns}
    return LoopSystem.for_testing(tmp_path, FakeAdapter(script))


def test_cannot_verify_asks_the_user_and_re_verify_reactivates_quality(tmp_path):
    # 质检提交「无法核验」：决定请求出现、阻塞整个 run、恢复观察状态是待恢复；回答「重新核验」以后
    # 质检以新的激活核对同一份交付，这次放行，事项以 released 结束
    system = _system(tmp_path, [review_turn("cannot_verify", "cannot see the interface", checks={"smoke": 0},
                                            criteria=_cannot_verify()),
                                review_turn("release", "verified after the settings changed", checks={"smoke": 0},
                                            criteria=_criteria({AC1: "passed", AC2: "passed"},
                                                               checks=["smoke"]))])
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # 产品
    system.activate_once(run_id)  # 工程交付
    projection = system.activate_once(run_id)  # 质检提交无法核验
    assert projection.status not in TERMINAL_STATUSES
    requests = _open_decision(system, run_id)
    assert len(requests) == 1
    request = requests[0]
    assert request.blocks == "run"
    assert [option["id"] for option in request.request["options"]] == ["re_verify", "stop"]
    # 说明列出每条无法核验的验收条件与原因
    assert [item["criterion"] for item in request.request["criteria"]] == [AC1, AC2]
    assert "不支持图像输入" in request.request["criteria"][0]["note"]
    assert AC1 in request.request["description"] and AC2 in request.request["description"]
    # 等待回答期间 run 显示待恢复
    state = observation_state(_events(system, run_id), system.writes.read(run_stream(run_id)).decisions.values(),
                              status=projection.status, stop_reason=projection.stop_reason)
    assert state == "waiting_resume", state
    # 交付还在、并且没有被当成核验过：回答「重新核验」以后质检能重新被激活
    assert has_new_work(system.project(run_id), "quality") is True
    activations_before = sum(1 for event in _events(system, run_id)
                             if event.type == EventType.DEPARTMENT_ACTIVATED and event.department == "quality")

    system.orchestrator.answer_decision(request.decision_id, "re_verify", None,
                                        base_version=request.version, command=_answer_command())
    projection = system.run_until_stop(run_id)
    assert (projection.status, projection.stop_reason) == ("done", "released"), (projection.status,
                                                                                  projection.stop_reason)
    activations_after = sum(1 for event in _events(system, run_id)
                            if event.type == EventType.DEPARTMENT_ACTIVATED and event.department == "quality")
    assert activations_after == activations_before + 1
    reviews = [event for event in _events(system, run_id) if event.type == EventType.QA_SUBMITTED]
    assert [review.payload["verdict"] for review in reviews] == ["cannot_verify", "release"]
    system.close()


def test_stop_ends_the_run_and_the_delivery_is_not_adopted(tmp_path):
    # 回答「停止事项」：事项结束，停止原因是 cannot_verify，交付不被采纳
    system = _system(tmp_path, [review_turn("cannot_verify", "cannot see the interface", checks={"smoke": 0},
                                            criteria=_cannot_verify())])
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    request = _open_decision(system, run_id)[0]
    system.orchestrator.answer_decision(request.decision_id, "stop", None,
                                        base_version=request.version, command=_answer_command())
    projection = system.project(run_id)
    assert projection.status in TERMINAL_STATUSES
    assert projection.stop_reason == "cannot_verify", projection.stop_reason
    # 交付不被采纳：只有那条无法核验的结论，没有放行
    verdicts = [event.payload["verdict"] for event in _events(system, run_id)
                if event.type == EventType.QA_SUBMITTED]
    assert verdicts == ["cannot_verify"]
    system.close()


def test_cannot_verify_with_a_failed_criterion_is_rejected(tmp_path):
    # 没有 failed、至少一条 unverified：含 failed 条目时按无法核验提交被拒绝，写明是哪一条
    criteria = _criteria({AC1: "failed", AC2: "unverified"}, {AC2: "执行位置没有安装浏览器"})
    system = _system(tmp_path, [review_turn("cannot_verify", "mixed", checks={"smoke": 0}, criteria=criteria),
                                review_turn("cannot_verify", "all unverified", checks={"smoke": 0},
                                            criteria=_cannot_verify())])
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    rejected = next(event for event in _events(system, run_id) if event.type == EventType.PROPOSAL_REJECTED)
    errors = rejected.payload.get("errors", [])
    assert any(error.get("field") == "criteria[0].result" and "failed" in error.get("message", "")
               for error in errors), errors
    # 改成交付与原因齐全的一条以后被接纳，决定请求出现
    system.activate_once(run_id)
    assert len(_open_decision(system, run_id)) == 1
    system.close()


def test_cannot_verify_without_an_unverified_criterion_is_rejected(tmp_path):
    # 全部 passed 的结论不能按无法核验提交
    criteria = _criteria({AC1: "passed", AC2: "passed"})
    system = _system(tmp_path, [review_turn("cannot_verify", "all passed", checks={"smoke": 0}, criteria=criteria)])
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    rejected = next(event for event in _events(system, run_id) if event.type == EventType.PROPOSAL_REJECTED)
    errors = rejected.payload.get("errors", [])
    assert any(error.get("field") == "criteria" and "unverified" in error.get("message", "") for error in errors), errors
    system.close()


def test_cannot_verify_without_a_reason_is_rejected(tmp_path):
    # 每条 unverified 都要写明原因
    criteria = _criteria({AC1: "unverified", AC2: "unverified"}, {AC1: "看不到界面"})
    system = _system(tmp_path, [review_turn("cannot_verify", "missing reason", checks={"smoke": 0},
                                            criteria=criteria)])
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    rejected = next(event for event in _events(system, run_id) if event.type == EventType.PROPOSAL_REJECTED)
    errors = rejected.payload.get("errors", [])
    assert any(error.get("field") == "criteria[1].note" and "reason" in error.get("message", "")
               for error in errors), errors
    system.close()

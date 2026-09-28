import sqlite3
import time
import uuid
from datetime import datetime

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.models import EventType, TERMINAL_PHASES, Usage
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api

# 用户决定在应用层与接口层的行为（设计说明第 3.3、4.3 节）：未回答的请求由查询 decisions.list 读取，回答经命令
# decision.answer 提交；回答「继续执行」时流程编排在服务的事件循环中把这个 run 继续运行到结束，「停止事项」时
# 事项以 cancelled 结束。服务是真实启动的 FastAPI 应用（uvicorn），事件日志是真实的 SQLite 文件，模型回答由
# FakeAdapter 脚本给出；新建事项与运行到阻塞经控制核心的公开接口，核对经 HTTP 与应用层。

UNAVAILABLE = "Missing configuration: provider credential"


class _Service:
    # 服务的生命周期中建立应用层；每次启动取一份模型回答脚本，脚本用尽时模型调用失败
    def __init__(self, data_dir, scripts) -> None:
        self.data_dir = data_dir
        self.scripts = list(scripts)
        self.applications: list[Application] = []
        self.adapters: list[FakeAdapter] = []

    def __call__(self) -> Application:
        adapter = FakeAdapter(self.scripts.pop(0))
        application = Application(LoopSystem.for_testing(self.data_dir, adapter))
        self.applications.append(application)
        self.adapters.append(adapter)
        return application

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system


def _unavailable_script() -> list[object]:
    # 产品提交规格（带用量）以后，工程部门的请求被提供方报告为不可用（缺少凭据）；修复配置以后从这次请求接着进行
    return [
        FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20)),
        ProviderError(UNAVAILABLE, reason="provider_unavailable"),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]


def _blocked_run(client, service):
    # 新建项目经命令，事项与运行经控制核心的公开接口；运行到模型不可用而停在这次请求之前
    created = client.post("/api/commands/project.create", json={
        "command_id": str(uuid.uuid4()), "name": "文本工具", "goal": "逐行处理文本"})
    assert created.status_code == 200, created.text
    project_id = created.json()["refs"]["project_id"]
    work_item_id, run_id = service.system.projects.start_work_item(project_id, "build an echo CLI")
    return project_id, work_item_id, run_id, service.system.run_until_stop(run_id)


def _list(client, **params):
    response = client.get("/api/queries/decisions.list", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _answer(client, command_id: str, **body):
    return client.post("/api/commands/decision.answer", json={"command_id": command_id, **body})


def _wait_for_completion(system: LoopSystem, run_id: str, timeout_sec: float = 30.0):
    # 回答以后 run 由服务的事件循环中的任务继续运行：等到任务结束并且 run 到了终态，再核对它的投影
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        projection = system.project(run_id)
        if projection.phase in TERMINAL_PHASES and system.orchestrator.execution(run_id) is None:
            return projection
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} was not finished by its task within {timeout_sec}s")


def _delete_saved_projections(data_dir):
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        connection.execute("DELETE FROM projections")
        connection.execute("DELETE FROM decisions")
        connection.commit()
    finally:
        connection.close()


def test_an_unavailable_model_blocks_the_run_until_the_answer_and_the_run_then_continues(data_dir):
    service = _Service(data_dir, [_unavailable_script()])
    with running_api(service) as client:
        project_id, work_item_id, run_id, blocked = _blocked_run(client, service)
        system = service.system
        assert (blocked.phase, blocked.stop_reason, blocked.outcome) == ("ENGINEERING", None, "running")
        assert blocked.cycle_count == 2 and blocked.token_used == 120 and blocked.product_spec is not None

        # 未回答的请求按项目与事项列出，内容完整：身份、种类、阻塞范围、选项与说明、涉及的事实引用、状态与回答
        listed = _list(client, project_id=project_id, work_item_id=work_item_id)
        assert listed["position"] == system.store.end_position()
        [decision] = listed["data"]["decisions"]
        assert (decision["kind"], decision["blocks"], decision["status"], decision["version"]) == (
            "model_unavailable", "run", "open", 1)
        assert decision["answer"] is None and decision["requested_at"]
        request = decision["request"]
        assert (request["department"], request["reason"], request["message"]) == (
            "engineering", "provider_unavailable", UNAVAILABLE)
        assert request["options"] == [{"id": "continue", "label": "继续执行"}, {"id": "stop", "label": "停止事项"}]
        assert request["description"] and request["target"]["requested_model"] == "fake-script"
        [failed] = [event for event in system.store.list_events(run_id)
                    if event.type == EventType.MODEL_ATTEMPT_FAILED]
        assert request["facts"] == [failed.event_id]

        # 筛选：同一个项目的另一个事项与另外的种类、已回答的请求都不被列出
        other_item, other_run = service.system.projects.start_work_item(project_id, "另一个事项")
        assert _list(client, project_id=project_id, work_item_id=work_item_id)["data"] == listed["data"]
        assert _list(client, work_item_id=other_item)["data"] == {"decisions": []}
        assert _list(client, kind="model_unavailable")["data"] == listed["data"]
        assert _list(client, answered=False)["data"] == listed["data"]
        assert _list(client, answered=True)["data"] == {"decisions": []}
        assert _list(client, kind="other")["data"] == {"decisions": []}
        assert _list(client, project_id="proj_missing")["data"] == {"decisions": []}

        # 查询不写入，也不推进运行：再次运行与激活都不写入，模型不再被调用
        end = system.store.end_position()
        assert _list(client, project_id=project_id)["position"] == end
        assert system.store.end_position() == end and len(service.adapters[0].invocations) == 2
        assert system.run_until_stop(run_id).phase == "ENGINEERING"
        assert system.store.end_position() == end and len(service.adapters[0].invocations) == 2

        # 回答「继续执行」：run 在服务的事件循环中继续到结束
        command_id = str(uuid.uuid4())
        accepted = _answer(client, command_id, decision_id=decision["decision_id"], option="continue",
                           base_version=1, note="凭据已经补上")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json() == {
            "command_id": command_id, "position": accepted.json()["position"], "duplicate": False,
            "refs": {"decision_id": decision["decision_id"], "run_id": run_id}}

        finished = _wait_for_completion(system, run_id)
        assert finished.phase == "DONE"
        assert [call.department for call in service.adapters[0].invocations] == [
            "product", "engineering", "engineering", "engineering", "quality"]
        # 已完成的工作、激活次数与已用限额保留：产品的成果不变，激活与用量从阻塞时接着增加
        assert finished.product_specs == blocked.product_specs
        assert finished.cycle_count == blocked.cycle_count + 3
        assert finished.token_used >= blocked.token_used
        assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()

        # 回答后的请求按状态列出，回答的内容与事件一致
        answered = _list(client, project_id=project_id, work_item_id=work_item_id, answered=True)
        assert answered["position"] == system.store.end_position()
        [answered_decision] = answered["data"]["decisions"]
        [answer_event] = [event for event in system.store.list_events(run_id)
                          if event.type == EventType.DECISION_ANSWERED]
        assert answered_decision["decision_id"] == decision["decision_id"]
        assert answered_decision["status"] == "answered"
        answer = answered_decision["answer"]
        assert {key: answer[key] for key in ("event_id", "option", "note", "base_version", "actor", "command_id")} == {
            "event_id": answer_event.event_id, "option": "continue", "note": "凭据已经补上", "base_version": 1,
            "actor": "user:local", "command_id": command_id}
        assert (datetime.fromisoformat(answer["answered_at"])
                == datetime.fromisoformat(answer_event.created_at))
        assert answered_decision["request"] == request


def test_answering_stop_ends_the_work_item_as_cancelled(data_dir):
    service = _Service(data_dir, [_unavailable_script()])
    with running_api(service) as client:
        project_id, work_item_id, run_id, _blocked = _blocked_run(client, service)
        system = service.system
        [decision] = _list(client, project_id=project_id)["data"]["decisions"]

        command_id = str(uuid.uuid4())
        accepted = _answer(client, command_id, decision_id=decision["decision_id"], option="stop", base_version=1)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["refs"] == {"decision_id": decision["decision_id"], "run_id": run_id}

        # 回答与结束运行在同一个事务中写入；事项以 cancelled 结束，模型不再被调用
        run = system.project(run_id)
        assert (run.phase, run.stop_reason) == ("FAILED", "cancelled")
        [item] = system.projects.projection(project_id).work_items
        assert (item.work_item_id, item.status, item.stop_reason) == (work_item_id, "stopped", "cancelled")
        assert len(service.adapters[0].invocations) == 2
        [answered_decision] = _list(client, project_id=project_id, answered=True)["data"]["decisions"]
        assert (answered_decision["status"], answered_decision["answer"]["option"],
                answered_decision["answer"]["note"]) == ("answered", "stop", None)


def test_a_repeated_command_identity_applies_once_and_every_rejection_explains_itself(data_dir):
    service = _Service(data_dir, [_unavailable_script()])
    with running_api(service) as client:
        project_id, _work_item_id, run_id, _blocked = _blocked_run(client, service)
        system = service.system
        [decision] = _list(client, project_id=project_id)["data"]["decisions"]
        decision_id = decision["decision_id"]
        end = system.store.end_position()

        # 基准版本过期、选项不存在、请求不存在各自被拒绝，原因与说明正确；被拒绝时什么也不写，命令不登记
        rejected_bodies = [
            ({"decision_id": decision_id, "option": "continue", "base_version": 2}, "stale_base", 1),
            ({"decision_id": decision_id, "option": "retry", "base_version": 1}, "option_invalid", None),
            ({"decision_id": "evt_missing", "option": "continue", "base_version": 1}, "not_found", None),
        ]
        for body, reason, current_version in rejected_bodies:
            command_id = str(uuid.uuid4())
            rejected = _answer(client, command_id, **body)
            assert rejected.status_code == 409, rejected.text
            payload = rejected.json()
            assert (payload["command_id"], payload["reason"], payload["current_version"]) == (
                command_id, reason, current_version)
            assert payload["message"] and system.store.command(command_id) is None
        assert system.store.end_position() == end
        assert _list(client, project_id=project_id)["data"]["decisions"][0]["status"] == "open"

        # 被拒绝的命令身份没有登记：同一个身份按当前版本重新提交时重新判断并被接受
        command_id = str(uuid.uuid4())
        assert _answer(client, command_id, decision_id=decision_id, option="continue",
                       base_version=2).json()["reason"] == "stale_base"
        accepted = _answer(client, command_id, decision_id=decision_id, option="stop", base_version=1)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["duplicate"] is False

        # 同一命令身份重复提交：返回原来的接受结果，回答只写入一次，也不再执行
        again = _answer(client, command_id, decision_id=decision_id, option="stop", base_version=1)
        assert again.status_code == 200 and again.json() == {**accepted.json(), "duplicate": True}
        answers = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.DECISION_ANSWERED]
        assert len(answers) == 1 and answers[0].command_id == command_id
        assert system.project(run_id).stop_reason == "cancelled"

        # 同一身份、内容不同：拒绝命令身份重复使用；内容指向不存在的请求时同样如此，与请求是否存在无关
        reused = _answer(client, command_id, decision_id=decision_id, option="continue", base_version=1)
        assert reused.status_code == 409 and reused.json()["reason"] == "command_id_reused"
        reused_missing = _answer(client, command_id, decision_id="evt_missing", option="continue", base_version=1)
        assert reused_missing.status_code == 409 and reused_missing.json()["reason"] == "command_id_reused"

        # 请求已回答：再次回答被拒绝，什么也不写
        end = system.store.end_position()
        closed = _answer(client, str(uuid.uuid4()), decision_id=decision_id, option="continue", base_version=1)
        assert closed.status_code == 409 and closed.json()["reason"] == "decision_closed"
        assert closed.json()["message"]
        assert system.store.end_position() == end
        assert len([event for event in system.store.list_events(run_id)
                    if event.type == EventType.DECISION_ANSWERED]) == 1


def test_a_withdrawn_request_is_still_unanswered_and_cannot_be_answered(data_dir):
    # 运行结束时撤销的请求没有回答：是否已回答为 false 时列出、为 true 时不列出，再次回答被拒绝
    service = _Service(data_dir, [_unavailable_script()])
    with running_api(service) as client:
        project_id, _work_item_id, run_id, _blocked = _blocked_run(client, service)
        system = service.system
        [decision] = _list(client, project_id=project_id)["data"]["decisions"]

        cancelled = system.cancel(run_id)
        assert (cancelled.phase, cancelled.stop_reason) == ("FAILED", "cancelled")
        [withdrawn] = _list(client, project_id=project_id, answered=False)["data"]["decisions"]
        assert (withdrawn["decision_id"], withdrawn["status"], withdrawn["answer"]) == (
            decision["decision_id"], "withdrawn", None)
        assert _list(client, project_id=project_id, answered=True)["data"] == {"decisions": []}
        assert [item["status"] for item in _list(client, project_id=project_id)["data"]["decisions"]] == ["withdrawn"]

        end = system.store.end_position()
        closed = _answer(client, str(uuid.uuid4()), decision_id=decision["decision_id"], option="continue",
                         base_version=1)
        assert closed.status_code == 409 and closed.json()["reason"] == "decision_closed"
        assert "已经撤销" in closed.json()["message"]
        assert system.store.end_position() == end and len(service.adapters[0].invocations) == 2


def test_a_decision_request_and_its_answer_survive_deleting_the_saved_projection(data_dir):
    service = _Service(data_dir, [_unavailable_script(), []])
    with running_api(service) as client:
        project_id, work_item_id, run_id, _blocked = _blocked_run(client, service)
        [decision] = _list(client, project_id=project_id)["data"]["decisions"]
        assert _answer(client, str(uuid.uuid4()), decision_id=decision["decision_id"], option="continue",
                       base_version=1, note="凭据已经补上").status_code == 200
        assert _wait_for_completion(service.system, run_id).phase == "DONE"
        before = _list(client, project_id=project_id, work_item_id=work_item_id)
        before_all = _list(client)

    # 删除保存的投影（运行状态投影与决定请求），由重放补建
    _delete_saved_projections(data_dir)
    with running_api(service) as client:
        system = service.system
        assert service.adapters[1].invocations == []
        assert _list(client, project_id=project_id, work_item_id=work_item_id) == before
        assert _list(client) == before_all
        # 重放核对：保存的投影与从事件重放的状态相同，其间不调用模型
        assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()
        assert service.adapters[1].invocations == []
        # 已经回答的请求再次回答时仍被拒绝
        closed = _answer(client, str(uuid.uuid4()), decision_id=decision["decision_id"], option="continue",
                         base_version=1)
        assert closed.status_code == 409 and closed.json()["reason"] == "decision_closed"
        assert service.adapters[1].invocations == []

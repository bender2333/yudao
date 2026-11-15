import sqlite3
import time
import uuid
from datetime import datetime

from harness.watched_outputs import has_new_work
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.decisions import ROLE_CHOICE
from harness.event_store import run_stream
from harness.models import EventType, TERMINAL_STATUSES, Usage
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.contract_checks import assert_payloads_follow_contract
from harness.tests.helpers import quality_turns
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
from harness.write_path import NewEvent

# 用户决定在应用层与接口层的行为（docs/design/app-and-interface.md「用户决定的回答」、「查询清单」）：未回答的请求由查询 decisions.list 读取，回答经命令
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

def _unavailable_script(runs: int = 1) -> dict[str, list[object]]:
    # 产品提交规格（带用量）以后，工程部门的请求被提供方报告为不可用（缺少凭据）；修复配置以后从这次请求接着进行
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）。
    # runs 给出连续几个事项的脚本：一个事项一份，各部门各自按顺序取用
    return {
        "product": [FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20))] * runs,
        "engineering": [ProviderError(UNAVAILABLE, reason="provider_unavailable"), delivery_turn()] * runs,
        "quality": quality_turns("release", "checks passed on the current snapshot", times=4 * runs),
    }

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

def _wait_for_completion(system: LoopSystem, run_id: str, timeout_sec: float = WAIT_FOR_HOST_WORK_SEC):
    # 回答以后 run 由服务的事件循环中的任务继续运行：等到任务结束并且 run 到了终态，再核对它的投影
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        projection = system.project(run_id)
        if projection.status in TERMINAL_STATUSES and system.orchestrator.execution(run_id) is None:
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
        # 同时运行的会话各自记下自己结束的时刻，最后激活的是哪个部门不再固定（工单 #557）：
        # 这里断言的是结果：run 停在这次请求之前，产品的成果与已用的用量都在
        assert (blocked.stop_reason, blocked.status) == (None, "running")
        assert blocked.token_used == 120 and blocked.product_spec is not None

        # 未回答的请求按项目与事项列出，内容完整：身份、所属的项目、事项与 run、种类、阻塞范围、选项与说明、
        # 涉及的事实引用、状态与回答
        listed = _list(client, project_id=project_id, work_item_id=work_item_id, status=["open"])
        assert listed["position"] == system.store.end_position()
        [decision] = listed["data"]["decisions"]
        assert (decision["project_id"], decision["work_item_id"], decision["run_id"]) == (
            project_id, work_item_id, run_id)
        assert (decision["kind"], decision["blocks"], decision["status"], decision["version"]) == (
            "model_unavailable", "run", "open", 1)
        assert decision["answer"] is None and decision["requested_at"]
        request = decision["request"]
        assert (request["department"], request["reason"], request["message"]) == (
            "engineering", "provider_unavailable", UNAVAILABLE)
        assert request["options"] == [{"id": "continue", "label": "继续执行", "note_required": False},
                                      {"id": "stop", "label": "停止事项", "note_required": False}]
        assert request["description"] and request["target"]["requested_model"] == "fake-script"
        [failed] = [event for event in system.store.list_events(run_id)
                    if event.type == EventType.MODEL_ATTEMPT_FAILED]
        assert request["facts"] == [failed.event_id]

        # 筛选：同一个项目的另一个事项与另外的种类、其他状态的请求都不被列出
        other_item, other_run = service.system.projects.start_work_item(project_id, "另一个事项")
        assert _list(client, project_id=project_id, work_item_id=work_item_id)["data"] == listed["data"]
        assert _list(client, work_item_id=other_item)["data"] == {"decisions": []}
        assert _list(client, kind="model_unavailable")["data"] == listed["data"]
        assert _list(client, status=["open"])["data"] == listed["data"]
        assert _list(client, status=["answered", "withdrawn"])["data"] == {"decisions": []}
        assert _list(client, kind="other")["data"] == {"decisions": []}
        assert _list(client, project_id="proj_missing")["data"] == {"decisions": []}

        # 查询不写入，也不推进运行：再次运行与激活都不写入，模型不再被调用
        end = system.store.end_position()
        calls = len(service.adapters[0].invocations)
        assert _list(client, project_id=project_id)["position"] == end
        assert system.store.end_position() == end and len(service.adapters[0].invocations) == calls
        assert has_new_work(system.run_until_stop(run_id), "engineering")
        assert system.store.end_position() == end and len(service.adapters[0].invocations) == calls

        # 回答「继续执行」：run 在服务的事件循环中继续到结束
        command_id = str(uuid.uuid4())
        accepted = _answer(client, command_id, decision_id=decision["decision_id"], option="continue",
                           base_version=1, note="凭据已经补上")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json() == {
            "command_id": command_id, "position": accepted.json()["position"], "duplicate": False,
            "refs": {"decision_id": decision["decision_id"], "run_id": run_id}}

        finished = _wait_for_completion(system, run_id)
        assert finished.status == "done"
        # 产品只提交过一次 PRD；工程在阻塞以后接着做完了交付，质检核验并放行。
        # 质检在交付到达以前还有一轮预测性探索（工单 #557），因此这里不数模型调用的次数
        departments = [call.department for call in service.adapters[0].invocations]
        assert departments.count("product") == 1
        assert departments.count("engineering") >= 2
        assert "quality" in departments
        # 已完成的工作、激活次数与已用限额保留：产品的成果不变，激活与用量从阻塞时接着增加
        assert finished.product_specs == blocked.product_specs
        assert finished.cycle_count > blocked.cycle_count
        assert finished.token_used >= blocked.token_used
        assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()

        # 回答后的请求按状态列出，回答的内容与事件一致
        answered = _list(client, project_id=project_id, work_item_id=work_item_id, status=["answered"])
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
        calls = len(service.adapters[0].invocations)

        command_id = str(uuid.uuid4())
        accepted = _answer(client, command_id, decision_id=decision["decision_id"], option="stop", base_version=1)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["refs"] == {"decision_id": decision["decision_id"], "run_id": run_id}

        # 回答与结束运行在同一个事务中写入；事项以 cancelled 结束，模型不再被调用
        run = system.project(run_id)
        assert (run.status, run.stop_reason) == ("failed", "cancelled")
        [item] = system.projects.projection(project_id).work_items
        assert (item.work_item_id, item.status, item.stop_reason) == (work_item_id, "stopped", "cancelled")
        assert len(service.adapters[0].invocations) == calls
        [answered_decision] = _list(client, project_id=project_id, status=["answered"])["data"]["decisions"]
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

def test_a_withdrawn_request_is_not_in_the_waiting_list_and_cannot_be_answered(data_dir):
    # 运行结束时撤销的请求不在等待回答的列表里（状态为 withdrawn）；按已撤销或省略状态时列出，再次回答被拒绝
    service = _Service(data_dir, [_unavailable_script()])
    with running_api(service) as client:
        project_id, work_item_id, run_id, _blocked = _blocked_run(client, service)
        system = service.system
        [decision] = _list(client, project_id=project_id, status=["open"])["data"]["decisions"]

        cancelled = system.cancel(run_id)
        assert (cancelled.status, cancelled.stop_reason) == ("failed", "cancelled")
        assert _list(client, project_id=project_id, status=["open"])["data"] == {"decisions": []}
        [withdrawn] = _list(client, project_id=project_id, status=["withdrawn"])["data"]["decisions"]
        assert (withdrawn["decision_id"], withdrawn["status"], withdrawn["answer"]) == (
            decision["decision_id"], "withdrawn", None)
        assert [item["status"] for item in
                _list(client, project_id=project_id, work_item_id=work_item_id)["data"]["decisions"]] == ["withdrawn"]

        end = system.store.end_position()
        calls = len(service.adapters[0].invocations)
        closed = _answer(client, str(uuid.uuid4()), decision_id=decision["decision_id"], option="continue",
                         base_version=1)
        assert closed.status_code == 409 and closed.json()["reason"] == "decision_closed"
        assert "已经撤销" in closed.json()["message"]
        assert system.store.end_position() == end and len(service.adapters[0].invocations) == calls

def test_the_listing_filters_by_several_states_and_reports_the_owning_identities(data_dir):
    # 状态筛选可以重复给出多个状态（?status=open&status=answered），也可以一次给出多个；省略状态时不限制。
    # 每一项都带所属的项目、事项与 run；不在清单里的状态被拒绝（422），查询不写入
    service = _Service(data_dir, [_unavailable_script(2)])
    with running_api(service) as client:
        project_id, work_item_id, run_id, _blocked = _blocked_run(client, service)
        system = service.system
        [first] = _list(client, project_id=project_id, status=["open"])["data"]["decisions"]
        assert (first["project_id"], first["work_item_id"], first["run_id"]) == (project_id, work_item_id, run_id)
        # 单值筛选：等待回答的列表只取 open，其他状态各自为空
        assert _list(client, project_id=project_id, status=["answered"])["data"] == {"decisions": []}
        assert _list(client, project_id=project_id, status=["withdrawn"])["data"] == {"decisions": []}

        # 回答以后它只在 answered 下出现
        assert _answer(client, str(uuid.uuid4()), decision_id=first["decision_id"], option="continue",
                       base_version=1).status_code == 200
        assert _wait_for_completion(system, run_id).status == "done"
        assert _list(client, project_id=project_id, status=["open"])["data"] == {"decisions": []}
        assert [(item["decision_id"], item["status"]) for item in
                _list(client, project_id=project_id, status=["open", "answered"])["data"]["decisions"]] == [
            (first["decision_id"], "answered")]

        # 第二个事项的请求在运行取消时撤销
        second_item, second_run = system.projects.start_work_item(project_id, "另一个事项")
        blocked_again = system.run_until_stop(second_run)
        assert (blocked_again.stop_reason, blocked_again.status) == (None, "running")
        [second] = _list(client, work_item_id=second_item)["data"]["decisions"]
        assert (second["project_id"], second["work_item_id"], second["run_id"]) == (project_id, second_item,
                                                                                    second_run)
        assert system.cancel(second_run).stop_reason == "cancelled"

        # 多选：两个状态一起筛选，按请求的先后排列；省略状态时不限制
        assert [(item["decision_id"], item["status"]) for item in
                _list(client, project_id=project_id, status=["answered", "withdrawn"])["data"]["decisions"]] == [
            (first["decision_id"], "answered"), (second["decision_id"], "withdrawn")]
        assert [item["decision_id"] for item in
                _list(client, project_id=project_id)["data"]["decisions"]] == [
            first["decision_id"], second["decision_id"]]
        # 事项范围与状态一起使用
        assert [item["decision_id"] for item in
                _list(client, work_item_id=second_item, status=["withdrawn"])["data"]["decisions"]] == [
            second["decision_id"]]

        # 不在清单里的状态被拒绝，查询不写入
        end = system.store.end_position()
        invalid = client.get("/api/queries/decisions.list", params=[("status", "open"), ("status", "bogus")])
        assert invalid.status_code == 422
        assert system.store.end_position() == end

def test_a_decision_request_and_its_answer_survive_deleting_the_saved_projection(data_dir):
    service = _Service(data_dir, [_unavailable_script(), []])
    with running_api(service) as client:
        project_id, work_item_id, run_id, _blocked = _blocked_run(client, service)
        [decision] = _list(client, project_id=project_id)["data"]["decisions"]
        assert _answer(client, str(uuid.uuid4()), decision_id=decision["decision_id"], option="continue",
                       base_version=1, note="凭据已经补上").status_code == 200
        assert _wait_for_completion(service.system, run_id).status == "done"
        # run 结束时由流程编排结算（采纳）；这里显式结算一次，作为重启以后补结算的对照
        service.system.projects.settle(run_id)
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


def _role_choice_questions() -> list[dict[str, object]]:
    return [
        {
            "id": "q1",
            "question": "配置格式采用哪一种？",
            "options": [
                {"id": "json", "label": "JSON 文件", "description": "零额外依赖"},
                {"id": "toml", "label": "TOML 文件"},
            ],
            "recommended": "json",
            "rationale": "标准库可直接读写",
        },
        {
            "id": "q2",
            "question": "默认端口选哪个？",
            "options": [
                {"id": "8080", "label": "8080 端口"},
                {"id": "9000", "label": "9000 端口"},
            ],
            "recommended": "8080",
            "rationale": "本地调试常用端口",
        },
    ]


def _completed_script(runs: int = 1) -> dict[str, list[object]]:
    return {
        "product": [FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=60, output_tokens=15))] * runs,
        "engineering": [delivery_turn()] * runs,
        "quality": quality_turns("release", "checks passed on the current snapshot", times=4 * runs),
    }


def _emit_role_choice(system: LoopSystem, run_id: str) -> str:
    questions = _role_choice_questions()
    system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
        EventType.DECISION_REQUESTED, actor="system", department="product",
        state_before=transaction.projection.status, state_after=transaction.projection.status,
        payload={
            "kind": "role_choice",
            "blocks": "round",
            "options": [{"id": opt.id, "label": opt.label} for opt in ROLE_CHOICE.options],
            "description": "请确认两项前置配置选择",
            "facts": [],
            "department": "product",
            "questions": questions,
            "input_version": 1,
            "round": 1,
            "note": "默认采用推荐项即可直接运行",
        },
    )))
    [requested] = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.DECISION_REQUESTED]
    return requested.event_id


def test_role_choice_decisions_list_and_three_answer_modes_survive_replay(data_dir):
    # 守护 R1 与 R2：decisions.list 完整返回 role_choice 的题目清单，decision.answer 支持完整 answers、
    # 部分 answers 自动补齐及 option="recommended" 无 answers 全推荐补齐；未知题号与未知选项拒绝为 option_invalid；
    # 删掉保存的投影以后重放与原先查询结果一致
    service = _Service(data_dir, [_completed_script(3), []])
    expected_questions = _role_choice_questions()
    submissions = [
        ("submit", {"q1": "toml", "q2": "9000"}, "按项目需求选择", {"q1": "toml", "q2": "9000"}),
        ("submit", {"q1": "toml"}, None, {"q1": "toml", "q2": "8080"}),
        ("recommended", None, "全部采纳建议", {"q1": "json", "q2": "8080"}),
    ]
    with running_api(service) as client:
        created = client.post("/api/commands/project.create", json={
            "command_id": str(uuid.uuid4()), "name": "多题选择项目", "goal": "验证 role_choice 接口"})
        assert created.status_code == 200, created.text
        project_id = created.json()["refs"]["project_id"]
        system = service.system

        decision_ids: list[str] = []
        for idx, (option, submitted_answers, note, expected_answers) in enumerate(submissions):
            _item_id, run_id = system.projects.start_work_item(project_id, f"事项 {idx + 1}")
            decision_id = _emit_role_choice(system, run_id)
            decision_ids.append(decision_id)

            [listed] = _list(client, project_id=project_id, status=["open"])["data"]["decisions"]
            assert (listed["decision_id"], listed["kind"], listed["blocks"]) == (
                decision_id, "role_choice", "round")
            assert listed["request"]["questions"] == [
                {
                    **q,
                    "options": [{"description": None, **opt} for opt in q["options"]],
                }
                for q in expected_questions
            ]
            assert (listed["request"]["input_version"], listed["request"]["round"]) == (1, 1)

            if idx == 0:
                end = system.store.end_position()
                for bad_answers in ({"q_missing": "json"}, {"q1": "yaml"}):
                    bad_cmd = str(uuid.uuid4())
                    rejected = _answer(client, bad_cmd, decision_id=decision_id, option="submit",
                                       base_version=1, answers=bad_answers)
                    assert rejected.status_code == 409, rejected.text
                    assert rejected.json()["reason"] == "option_invalid"
                    assert system.store.command(bad_cmd) is None
                assert system.store.end_position() == end

            body: dict[str, object] = {"decision_id": decision_id, "option": option, "base_version": 1}
            if submitted_answers is not None:
                body["answers"] = submitted_answers
            if note is not None:
                body["note"] = note
            accepted = _answer(client, str(uuid.uuid4()), **body)
            assert accepted.status_code == 200, accepted.text
            assert _wait_for_completion(system, run_id).status == "done"
            system.projects.settle(run_id)
            assert_payloads_follow_contract(system.store.list_events(run_id))

            [answered] = [item for item in _list(client, project_id=project_id, status=["answered"])["data"]["decisions"]
                          if item["decision_id"] == decision_id]
            assert answered["answer"]["answers"] == expected_answers
            assert answered["answer"]["note"] == note

        before_replay = _list(client, project_id=project_id, kind="role_choice")

    _delete_saved_projections(data_dir)
    with running_api(service) as client:
        assert service.adapters[1].invocations == []
        after_replay = _list(client, project_id=project_id, kind="role_choice")
        assert after_replay == before_replay
        assert [item["answer"]["answers"] for item in after_replay["data"]["decisions"]] == [
            entry[3] for entry in submissions]


def test_non_role_choice_decision_rejects_non_empty_answers_with_option_invalid(data_dir):
    # 守护 R1：非 role_choice 决定若传入非空 answers，返回 option_invalid 且不写入事件或登记命令
    service = _Service(data_dir, [_unavailable_script()])
    with running_api(service) as client:
        project_id, _work_item_id, _run_id, _blocked = _blocked_run(client, service)
        system = service.system
        [decision] = _list(client, project_id=project_id)["data"]["decisions"]
        end = system.store.end_position()
        command_id = str(uuid.uuid4())
        rejected = _answer(client, command_id, decision_id=decision["decision_id"], option="continue",
                           base_version=1, answers={"q1": "a"})
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["reason"] == "option_invalid"
        assert system.store.command(command_id) is None
        assert system.store.end_position() == end
        assert _list(client, project_id=project_id)["data"]["decisions"][0]["status"] == "open"

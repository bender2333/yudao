import base64
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
import pytest
from filelock import FileLock

from harness.__main__ import main
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.decision_queries import DecisionsList
from harness.app.home import AwayReportRequest
from harness.app.project_queries import (
    DeliveryFile,
    DepartmentWorkspace,
    EventDetail,
    NotFound,
    ProjectAttempts,
    ProjectFlow,
    ProjectLoop,
    ProjectOverview,
    ProjectSettings,
    ProjectUsage,
    ProjectsList,
    ReplayCheck,
    RunActions,
    RunAsks,
    RunAttempt,
    RunExport,
    RunRecovery,
    WorkItemInputs,
    WorkItemMaterials,
)
from harness.app.registry import QueryDefinition, Registry
from harness.app.rules_queries import RulesRegistryRequest
from harness.app.system_queries import SYSTEM_STATUS, SystemStatusRequest
from harness.event_store import run_stream
from harness.models import EventType
from harness.proposals import (
    product_spec, delivery_turn, review_turn,
    ask_turn, answer_turn,
    baseline_review_turn, structure_turn,
)
from harness.providers.selection import ModelSelection
from harness.providers.call import ModelCall, ModelResponse
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import (
    after_event, explore_turn, from_another_thread, happy_script, merge_scripts, quality_turns,
)
from harness.tests.onboarding_project import onboarding_source
from harness.write_path import NewEvent

GOAL = "把文本按行处理清楚"

def _release_script(summary="v1", files=None):
    # 按部门给出（工单 #557：同时运行的会话各自取用自己的脚本）
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(summary=summary, files=files)],
        "quality": [explore_turn(), review_turn("release", f"ok {summary}")],
    }


def _system(data_dir, script):
    return LoopSystem.for_testing(data_dir, FakeAdapter(script))

def _application(system: LoopSystem) -> Application:
    return Application(system)

def _projection_rows(store) -> list[tuple]:
    with store._reading() as connection:
        rows = connection.execute(
            "SELECT stream, version, position, state FROM projections ORDER BY stream"
        ).fetchall()
    return [(row["stream"], row["version"], row["position"], row["state"]) for row in rows]

def test_overlays_list_only_when_every_dependent_query_is_registered(data_dir):
    application = _application(_system(data_dir, []))
    capabilities = application.capabilities("sha256:test", access="local")
    overlays = {item.name: item.queries for item in capabilities.overlays}
    assert overlays["flow"] == ["project.flow"]
    assert overlays["waiting"] == ["project.loop", "decisions.list"]
    assert overlays["recovery"] == ["run.recovery"]
    assert "context_usage" not in overlays
    assert "semantic_records" not in overlays

    partial = Registry(commands=[], queries=[SYSTEM_STATUS], decisions=())
    listed = {item.name for item in partial.capabilities(capabilities.deployment).overlays}
    assert listed == set()

def test_each_query_returns_a_snapshot_and_later_events_have_greater_positions(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("查询", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    for name, request in _all_requests(system, project_id, work_item_id, run_id):
        snapshot = application.query(name, request)
        assert snapshot.position >= 1
        before = system.store.end_position()
        assert snapshot.position <= before
        system.writes.append(run_stream(run_id), NewEvent(
            "marker", state_before="done", state_after="done", actor="system", payload={"marker": name},
        ))
        assert system.store.end_position() > snapshot.position

def test_queries_do_not_write_events_or_saved_projections(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("只读", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    before_position = system.store.end_position()
    before_rows = _projection_rows(system.store)
    for name, request in _all_requests(system, project_id, work_item_id, run_id):
        application.query(name, request)
    assert system.store.end_position() == before_position
    assert _projection_rows(system.store) == before_rows

def _all_requests(system, project_id, work_item_id, run_id):
    # 全部已登记的查询各一个请求：位置与只读的断言都用它
    attempt_id = next(
        event.payload["attempt_id"] for event in system.store.list_events(run_id)
        if event.type == EventType.MODEL_ATTEMPT_FINISHED
    )
    event_id = next(event.event_id for event in system.store.list_events(run_id)
                    if event.type == EventType.CONTEXT_ASSEMBLED)
    delivery_event_id = system.project(run_id).delivery_spec.created_event_id
    return [
        ("system.status", SystemStatusRequest()),
        ("decisions.list", DecisionsList()),
        ("projects.list", ProjectsList()),
        ("home.away_report", AwayReportRequest()),
        ("project.overview", ProjectOverview(project_id=project_id)),
        ("project.loop", ProjectLoop(project_id=project_id)),
        ("project.flow", ProjectFlow(project_id=project_id)),
        ("work_item.inputs", WorkItemInputs(project_id=project_id, work_item=work_item_id)),
        ("event.detail", EventDetail(event_id=event_id)),
        ("department.workspace", DepartmentWorkspace(project_id=project_id, department="product",
                                                     work_item=work_item_id)),
        ("run.actions", RunActions(run_id=run_id)),
        ("run.asks", RunAsks(run_id=run_id)),
        ("work_item.materials", WorkItemMaterials(project_id=project_id, work_item=work_item_id)),
        ("delivery.file", DeliveryFile(event_id=delivery_event_id, path="src/echo.py")),
        ("project.attempts", ProjectAttempts(project_id=project_id)),
        ("project.usage", ProjectUsage(project_id=project_id)),
        ("run.attempt", RunAttempt(run_id=run_id, attempt_id=attempt_id)),
        ("project.settings", ProjectSettings(project_id=project_id)),
        ("run.export", RunExport(run_id=run_id)),
        ("replay.check", ReplayCheck(run_id=run_id)),
        ("rules.registry", RulesRegistryRequest()),
    ]


def test_deleting_read_models_and_rebuilding_returns_the_same_queries_without_calling_a_model(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("重建", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    attempt_id = application.query(
        "project.attempts", ProjectAttempts(project_id=project_id)).data.attempts[0].attempt_id
    # 读取模型相关的全部查询：两张表、用量、请求详情与导出
    requests = (
        ("project.attempts", ProjectAttempts(project_id=project_id)),
        ("project.flow", ProjectFlow(project_id=project_id)),
        ("project.usage", ProjectUsage(project_id=project_id)),
        ("run.attempt", RunAttempt(run_id=run_id, attempt_id=attempt_id)),
        ("run.export", RunExport(run_id=run_id)),
    )
    before = {name: application.query(name, request).data.model_dump(mode="json") for name, request in requests}
    calls = len(system.test_adapter.invocations)
    end_position = system.store.end_position()
    application.rebuild_read_models()
    # 重建只读取事件：不调用模型、不写入事件日志（工具调用同样要写入事件，所以位置不变即没有调用工具）
    assert len(system.test_adapter.invocations) == calls
    assert system.store.end_position() == end_position
    for name, request in requests:
        assert application.query(name, request).data.model_dump(mode="json") == before[name], name

def test_attempt_pages_stay_inside_the_first_page_position(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("翻页", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    first = application.query("project.attempts", ProjectAttempts(project_id=project_id, limit=1))
    assert first.data.attempts
    assert first.data.cursor
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.MODEL_ATTEMPT_FINISHED, state_before="done", state_after="done", actor="system",
        department="product",
        payload={
            "attempt_id": "late-attempt", "logical_call_id": "late",
            "context_event_id": "ctx", "activation_id": "late", "step_id": 1, "root_step_id": 1,
            "retry_of_step_id": None, "attempt": 1, "purpose": "work", "started_at": "2026-09-29T00:00:00+00:00",
            "finished_at": "2026-09-29T00:00:01+00:00", "duration_ms": 1, "duration_source": "monotonic",
            "provider_response_id": None, "actual_provider": "late", "actual_model": "late-model",
            "response_ref": None, "stream_events_ref": None, "stream_event_count": 0,
            "stream_first_observed_at": None, "stream_first_output_at": None, "stream_last_stage": None,
            "collection_scope": "observable_main_dialogue", "usage": None, "raw_usage_ref": None,
            "input_version": 1, "prompt_version": 0, "definitions_version": "0",
            "requested_provider": "late", "requested_model": "late-model", "requested_protocol": "responses",
            "credential_ref": None, "credential_version": None, "snapshot_id": None,
        },
    ))
    rest = application.query("project.attempts", ProjectAttempts(
        project_id=project_id, limit=50, cursor=first.data.cursor,
    ))
    seen = [item.attempt_id for item in first.data.attempts + rest.data.attempts]
    assert "late-attempt" not in seen
    assert len(seen) == len(set(seen))
    complete = application.query("project.attempts", ProjectAttempts(project_id=project_id, limit=50))
    assert "late-attempt" in [item.attempt_id for item in complete.data.attempts]
    bounded = {item.attempt_id for item in complete.data.attempts if item.position <= first.position}
    assert set(seen) == bounded


def test_the_action_receipt_shows_the_command_text(data_dir):
    # 工单 #658：动作回执里显示动作实际执行的命令原文，界面按它列出命令
    def bash(request):
        identity = "bash-1"
        return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call", "name": "bash",
                                      "arguments": json.dumps({"command": "python -m pytest"})}])
    system = _system(data_dir, [bash])
    run_id = system.create_run("跑一条命令")
    system.run_until_stop(run_id)
    application = _application(system)
    actions = application.query("run.actions", RunActions(run_id=run_id))
    commands = [action.receipt.args.get("command") for action in actions.data.actions
                if action.receipt is not None]
    assert "python -m pytest" in commands


def test_current_queries_cover_the_old_read_scenarios(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("对照", GOAL)
    system.projects.configure_department_settings(
        project_id, "product", ModelSelection(department_prompt="产品提示"), 0)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    projection = system.run_until_stop(run_id)
    application = _application(system)

    listed = application.query("projects.list", ProjectsList())
    assert listed.data.projects[0].name == "对照"
    assert listed.data.projects[0].version == system.projects.projection(project_id).stream_version

    overview = application.query("project.overview", ProjectOverview(project_id=project_id))
    assert overview.data.goal == GOAL
    item = overview.data.work_items[0]
    assert item.work_item_id == work_item_id
    assert item.department is None
    assert item.round == projection.cycle_count
    scoped = application.query("project.overview", ProjectOverview(project_id=project_id, work_item=work_item_id))
    assert [entry.work_item_id for entry in scoped.data.work_items] == [work_item_id]
    assert scoped.data.stats.total == 1
    with pytest.raises(NotFound):
        application.query("project.overview", ProjectOverview(project_id=project_id, work_item="wi_missing"))

    loop = application.query("project.loop", ProjectLoop(project_id=project_id, work_item=work_item_id))
    assert loop.data.work_items[0].color_index == 1
    assert loop.data.adoptions == []

    flow = application.query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))
    assert any(record.kind == "版本交付" for record in flow.data.records)

    inputs = application.query("work_item.inputs", WorkItemInputs(project_id=project_id, work_item=work_item_id))
    assert inputs.data.inputs[0].text == "做一件事"
    assert inputs.data.inputs[0].version == 1

    assembled = next(event for event in system.store.list_events(run_id) if event.type == EventType.CONTEXT_ASSEMBLED)
    detail = application.query("event.detail", EventDetail(event_id=assembled.event_id))
    assert detail.position == assembled.position
    assert detail.data.artifacts["request"]["input"][0]["role"] == "developer"

    workspace = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="product", work_item=work_item_id,
    ))
    # 部门消息的文字：正文在工件里时按引用取出来（工单 #670）
    messages = workspace.data.messages
    assert messages, "部门消息为空"
    by_type = {message["type"]: message for message in messages}
    assert EventType.MODEL_MESSAGE in by_type, [message["type"] for message in messages]
    assert by_type[EventType.MODEL_MESSAGE]["text"] != "", by_type[EventType.MODEL_MESSAGE]
    assert all(message["text"] != "" for message in messages), [message["text"] for message in messages]
    assert workspace.data.department_setting.configured_version == 1
    assert workspace.data.department_setting.department_setting_configured is True
    # 实际采用的版本来自该部门最近一次模型请求事件（run 内没有 Prompt 副本）
    assert workspace.data.department_setting.used_version == 1
    assert workspace.data.setting.model_id is None and workspace.data.setting.requested_tier is None
    # 部门房间的画面数据：这个 run 走完以后产品房间为已完成，卷轴数是它写出的 PRD 版本数
    room = workspace.data.room
    assert room.department == "product"
    assert room.status == "done"
    assert room.crt.target == "做一件事"
    assert room.crt.status == "已完成"
    assert room.crt.cycle == projection.cycle_count
    assert room.roles[0].id == "product-agent" and room.roles[0].kind == "agent"
    assert room.scrolls == len(projection.product_specs)
    assert room.pipes.out == "idle"
    # 门口立牌只在暂停、中断与因升级停止时出现
    assert room.door is None

    actions = application.query("run.actions", RunActions(run_id=run_id))
    assert any(action.tool == "write_file" and action.receipt.ok for action in actions.data.actions)

    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id,
    ))
    assert materials.data.contracts
    # PRD 各版带一段摘要（工单 #668）：目标是哪件事、要求与边界各有几条
    assert materials.data.contracts[0].summary is not None
    assert "目标" in materials.data.contracts[0].summary
    assert "要求" in materials.data.contracts[0].summary
    assert materials.data.deliveries[0].summary == "implemented echo CLI"

    delivery_event = projection.delivery_spec.created_event_id
    delivered = application.query("delivery.file", DeliveryFile(event_id=delivery_event, path="src/echo.py"))
    assert delivered.position == system.store.get_event(delivery_event).position
    assert delivered.data.content.splitlines() == ["import sys", "print(sys.argv[1])"]
    with pytest.raises(NotFound):
        application.query("delivery.file", DeliveryFile(event_id=delivery_event, path="missing.py"))
    delivery_detail = application.query("event.detail", EventDetail(event_id=delivery_event))
    assert delivery_detail.data.artifacts["tree_archive"]["tree_digest"] == projection.delivery_spec.code_tree_digest
    assert {item["path"] for item in delivery_detail.data.artifacts["tree_files"]} >= {"src/echo.py"}

    attempts = application.query("project.attempts", ProjectAttempts(project_id=project_id, work_item=work_item_id))
    assert attempts.data.attempts
    usage = application.query("project.usage", ProjectUsage(project_id=project_id, work_item=work_item_id))
    assert usage.data.totals.attempts >= 1
    assert usage.data.departments
    one = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=attempts.data.attempts[0].attempt_id))
    assert one.data.attempt["id"] == attempts.data.attempts[0].attempt_id
    assert set(one.data.artifact_refs) == {"request", "response", "events", "usage"}

    settings = application.query("project.settings", ProjectSettings(project_id=project_id))
    assert settings.data.version == system.projects.projection(project_id).stream_version
    assert settings.data.departments["product"].version == 1
    assert settings.data.departments["product"].text == "产品提示"

    exported = application.query("run.export", RunExport(run_id=run_id))
    assert any(event["type"] == EventType.RUN_CREATED for event in exported.data.events)

def test_run_asks_returns_in_progress_answered_and_unable(data_dir):
    # run.asks 查询返回进行中、已回答、没能回答三种状态的询问：
    # 包含提问方、被询问部门、问题、状态、回答或原因、开始与结束位置
    from harness.definitions import DEFINITIONS

    limit = DEFINITIONS.rule_value("tool_call_required_limit")
    captured: dict[str, Any] = {}

    def branch_turn_in_progress(call: ModelCall) -> Any:
        app = Application(system)
        in_prog = app.query("run.asks", RunAsks(run_id=call.run_id))
        captured["in_progress_asks"] = in_prog.data.asks
        return answer_turn("已回答问题二")(call)

    system = _system(data_dir, {
        "product": [
            ask_turn(recipient="engineering", question="Python 单文件 CLI 是否可行？",
                     background="准备初始规格", expected="确认可行性", call_id="ask-1"),
            product_spec(),
        ],
        "engineering": [
            ask_turn(recipient="product", question="参数错误如何处理？",
                     background="实现中需要明确", expected="规格澄清", call_id="ask-2"),
            delivery_turn(),
        ],
        "quality": [
            ask_turn(recipient="engineering", question="执行入口在哪里？",
                     background="质检核对", expected="指出入口", call_id="ask-3"),
            review_turn("release", "验收通过"),
        ],
        "engineering:ask": [
            answer_turn("标准库支持该实现，无需外部依赖。"),
            *(ModelResponse(output=[{"id": f"plain-{i}", "type": "message", "role": "assistant",
                                     "content": [{"type": "output_text", "text": "普通文本，未调用工具。"}]}])
              for i in range(limit + 1)),
        ],
        "product:ask": [
            branch_turn_in_progress,
        ],
    })
    project_id = system.projects.register("询问查询", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "验证 run.asks")
    system.run_until_stop(run_id)

    app = Application(system)

    in_prog_asks = captured["in_progress_asks"]
    # 同时运行以后质检也可能在这期间发起询问（工单 #557），捕获到的条数不再固定：
    # 断言的是每一条询问的内容与状态
    captured_by_question = {ask.question: ask for ask in in_prog_asks}
    assert {"Python 单文件 CLI 是否可行？", "参数错误如何处理？"} <= set(captured_by_question)
    first = captured_by_question["Python 单文件 CLI 是否可行？"]
    assert first.status == "已回答"
    assert first.requester == "product"
    assert first.recipient == "engineering"
    assert first.answer == "标准库支持该实现，无需外部依赖。"
    assert first.reason is None
    assert first.start_position > 0
    assert first.end_position is not None
    assert first.end_position > first.start_position

    second = captured_by_question["参数错误如何处理？"]
    assert second.status == "进行中"
    assert second.requester == "engineering"
    assert second.recipient == "product"
    assert second.answer is None
    assert second.reason is None
    assert second.start_position > first.start_position
    assert second.end_position is None

    final_query = app.query("run.asks", RunAsks(run_id=run_id))
    asks = final_query.data.asks
    assert len(asks) == 3
    # 同时运行以后几次询问的先后不再固定（工单 #557），断言的是每一条询问的内容与状态
    by_question = {ask.question: ask for ask in asks}

    answered = by_question["Python 单文件 CLI 是否可行？"]
    assert answered.status == "已回答"
    assert answered.requester == "product"
    assert answered.recipient == "engineering"
    assert answered.answer == "标准库支持该实现，无需外部依赖。"
    assert answered.reason is None
    assert answered.start_position > 0
    assert answered.end_position > answered.start_position

    answered_to_product = by_question["参数错误如何处理？"]
    assert answered_to_product.status == "已回答"
    assert answered_to_product.requester == "engineering"
    assert answered_to_product.recipient == "product"
    assert answered_to_product.answer == "已回答问题二"
    assert answered_to_product.reason is None
    assert answered_to_product.start_position > 0
    assert answered_to_product.end_position > answered_to_product.start_position

    unable = by_question["执行入口在哪里？"]
    assert unable.status == "没能回答"
    assert unable.requester == "quality"
    assert unable.recipient == "engineering"
    assert unable.answer is None
    assert unable.reason is not None
    assert "without calling a tool" in unable.reason
    assert unable.start_position > 0
    assert unable.end_position > unable.start_position
def test_flow_records_cover_delivery_problem_and_rework(data_dir):
    # 工单 #556：阶段迁移事件没有了，交接与返工的记录由正式成果给出（版本交付、质检退回）
    system = _system(data_dir, _rework_script())
    project_id = system.projects.register("流转", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    flow = application.query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))
    kinds = [record.kind for record in flow.data.records]
    assert {"版本交付", "问题反馈"} <= set(kinds)
    assert "需求交接" not in set(kinds)
    # 工单 #882：种类按成果命名，不用「交接」；流转记录里不出现这两个字样
    assert all("交接" not in record.kind and "交接" not in record.content
               for record in flow.data.records)
    problem = next(record for record in flow.data.records if record.kind == "问题反馈")
    assert problem.status == "已退回" and problem.direction_to == "engineering"
    assert problem.content == "质检退回" and problem.direction_from == "quality"
    assert all(record.work_item_id == work_item_id for record in flow.data.records)
    positions = [record.position for record in flow.data.records]
    assert positions == sorted(positions)
    assert flow.position >= positions[-1]

def test_flow_records_give_one_department_pair_two_plain_kinds_and_one_rework(data_dir):
    # 工单 #415 的场景：质检在工程退回事项的结论之前向工程提出询问并得到回答，
    # engineering 一侧与 quality 一侧因此在 quality→engineering 上留下「咨询」「问题反馈」与「返工」。
    # 期望直接写出应有的记录条数与种类，不复用画面侧的分组公式：分组若改变，这段断言照样成立
    system = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [
            delivery_turn(),
            delivery_turn(summary="处理空输入"),
        ],
        "quality": [
            ask_turn(
                recipient="engineering",
                question="Which acceptance line governs the rework?",
                background="Quality is preparing its verdict.",
                expected="Name the acceptance line to follow.",
            ),
            # 预测性探索那一轮没有交付可以核验，提交的结论被拒绝（工单 #557）
            explore_turn(),
            review_turn(
                "rework_engineering", "质检退回",
                defects=[{"severity": "minor", "summary": "空输入需要处理"}],
            ),
            review_turn("release", "revised delivery checked"),
        ],
        "engineering:ask": [
            answer_turn("Follow the acceptance line recorded in the requirement."),
        ],
    })
    project_id = system.projects.register("同对部门", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    flow = application.query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))

    rows = [record for record in flow.data.records
            if record.direction_from == "quality" and record.direction_to == "engineering"]
    assert len(rows) == 2
    assert sorted(record.kind for record in rows) == ["询问", "问题反馈"]
    by_kind = {record.kind: record for record in rows}
    assert by_kind["询问"].status == "已回答"
    assert by_kind["问题反馈"].status == "已退回"


def _prd_revision_script():
    # 工单 #882：产品先提交一版 PRD；工程询问产品，产品在回答里修订 PRD（第二版）
    return {
        "product": [product_spec()],
        "engineering": [
            ask_turn(recipient="product", question="空输入应该打印什么？"),
            delivery_turn(),
        ],
        "product:ask": [answer_turn(
            answer="空输入打印空行。",
            requirements=["print the given argument to stdout"],
            acceptance=["running the program with a word prints that word",
                        "empty input prints a blank line"],
            change_record={"changed": ["empty input prints a blank line"],
                           "retained": ["running the program with a word prints that word"],
                           "retired": [], "rationale": "验收标准漏了空输入。"})],
        "quality": quality_turns("release", "checks passed"),
    }


def test_flow_records_give_two_prd_new_versions_for_each_accepted_prd(data_dir):
    # 工单 #882 验收标准 1：每接纳一版 PRD，产品→工程与产品→质检各一条「PRD 新版本」。
    # 这个事项接纳了两版（第二版来自产品回答询问时的修订），因此有四条，内容分别写第 1 版与第 2 版
    system = _system(data_dir, _prd_revision_script())
    project_id = system.projects.register("PRD 版本", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    flow = application.query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))
    rows = [record for record in flow.data.records if record.kind == "PRD 新版本"]
    assert len(rows) == 4
    assert sorted((record.direction_from, record.direction_to) for record in rows) == [
        ("product", "engineering"), ("product", "engineering"),
        ("product", "quality"), ("product", "quality"),
    ]
    assert all(record.status == "已完成" for record in rows)
    assert all(record.work_item_id == work_item_id for record in rows)
    # 内容写第几版：第一版两条、第二版两条；第二版附上改动的要点
    assert sum("第 1 版" in record.content for record in rows) == 2
    second = [record for record in rows if "第 2 版" in record.content]
    assert len(second) == 2
    assert all("empty input prints a blank line" in record.content for record in second)
    # 两条的编号不同（否则后一条会盖掉前一条）
    assert len({record.flow_id for record in rows}) == 4


def test_flow_records_give_two_prd_new_versions_for_the_onboarding_initial_prd(data_dir, tmp_path):
    # 工单 #882 验收标准 2：建档事项的初始 PRD 被接纳时同样有两条（产品→工程、产品→质检）
    requirement = "print the given argument to stdout"
    source = onboarding_source(tmp_path / "source")
    system = _system(data_dir, {
        "product": [product_spec(requirements=[requirement], acceptance=["running the program with a word prints that word"])],
        "engineering": [structure_turn(requirement_locations=[
            {"requirement": requirement, "locations": ["src/echo.py"]}])],
        "quality": [baseline_review_turn(conclusions=[
            {"requirement": requirement, "status": "verified", "evidence": "smoke"}])],
    })
    project_id, work_item_id, run_id = system.projects.onboard("已有项目", GOAL, "src", str(source))
    system.run_until_stop(run_id)
    application = _application(system)
    flow = application.query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))
    rows = [record for record in flow.data.records if record.kind == "PRD 新版本"]
    assert len(rows) == 2
    assert sorted((record.direction_from, record.direction_to) for record in rows) == [
        ("product", "engineering"), ("product", "quality"),
    ]
    assert all(record.status == "已完成" for record in rows)
    assert all("第 1 版" in record.content for record in rows)


def test_event_detail_returns_git_version_and_accepted_materials(data_dir):
    system = _system(data_dir, _release_script())
    project_id = system.projects.register("工件", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    event = next(item for item in system.store.list_events(run_id)
                 if item.type == EventType.CONTRACT_ACCEPTED)
    detail = application.query("event.detail", EventDetail(event_id=event.event_id))
    assert detail.position == event.position
    assert detail.data.event["event_id"] == event.event_id
    assert {"commit", "tree", "files", "diff"} <= set(detail.data.artifacts["git_version"])
    assert detail.data.artifacts["prd"]
    assembled = next(item for item in system.store.list_events(run_id)
                     if item.type == EventType.CONTEXT_ASSEMBLED)
    context = application.query("event.detail", EventDetail(event_id=assembled.event_id))
    assert context.data.artifacts["request"]["input"][0]["role"] == "developer"


def test_event_detail_rejects_an_artifact_of_another_run(data_dir, monkeypatch):
    system = _system(data_dir, merge_scripts(_release_script(), _release_script()))
    first_project = system.projects.register("第一个", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(first_project, "第一件事")
    system.run_until_stop(run_id)
    second_project = system.projects.register("第二个", GOAL)
    _other_work_item_id, other_run_id = system.projects.start_work_item(second_project, "第二件事")
    system.run_until_stop(other_run_id)
    application = _application(system)
    event = next(item for item in system.store.list_events(run_id) if item.type == EventType.CONTRACT_ACCEPTED)
    foreign = next(item for item in system.store.list_events(other_run_id)
                   if item.type == EventType.CONTRACT_ACCEPTED).payload["prd_ref"]
    changed = replace(event, payload={**event.payload, "prd_ref": foreign})
    original = system.store.get_event
    monkeypatch.setattr(system.store, "get_event",
                        lambda event_id: changed if event_id == event.event_id else original(event_id))
    with pytest.raises(ValueError):
        application.query("event.detail", EventDetail(event_id=event.event_id))
    with pytest.raises(NotFound):
        application.query("delivery.file", DeliveryFile(event_id=event.event_id, path="src/echo.py"))

def test_event_detail_includes_compaction_summary_and_its_sources(tmp_path):
    from harness.tests.helpers import compacted_runner as _runner

    system, _, run_id, _ = _runner(tmp_path)
    system.activate_once(run_id)
    application = _application(system)
    event = next(item for item in system.store.list_events(run_id)
                 if item.type == EventType.COMPACTION_RECORDED)
    detail = application.query("event.detail", EventDetail(event_id=event.event_id))
    assert detail.data.artifacts["compaction_summary"]
    assert detail.data.artifacts["compaction_sources"]

def test_delivery_detail_and_file_use_the_archived_bytes(data_dir):
    # 封存的清单与文件原文取自交付封存，不取自当前工作区
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("封存", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    workspace = system.workspace(run_id)
    workspace.write_file(".settings", "hidden configuration\n")
    (workspace.root / "assets").mkdir()
    (workspace.root / "assets" / "data.bin").write_bytes(b"\x00\xff\x01")
    (workspace.root / "empty").mkdir()
    projection = system.run_until_stop(run_id)
    workspace.write_file("src/echo.py", "changed after delivery\n")
    (workspace.root / "assets" / "data.bin").unlink()
    application = _application(system)
    delivery_event = projection.delivery_spec.created_event_id

    detail = application.query("event.detail", EventDetail(event_id=delivery_event))
    archive = detail.data.artifacts["tree_archive"]
    assert archive["tree_digest"] == projection.delivery_spec.code_tree_digest
    assert [item["path"] for item in archive["tree"]["files"]] == [".settings", "assets/data.bin", "src/echo.py"]
    assert [item["path"] for item in detail.data.artifacts["tree_files"]] == [".settings", "assets/data.bin", "src/echo.py"]
    for blob in archive["blobs"]:
        assert (system.artifacts.root / blob["artifact"]["path"]).is_file()

    text = application.query("delivery.file", DeliveryFile(event_id=delivery_event, path="src/echo.py"))
    assert text.data.content.splitlines() == ["import sys", "print(sys.argv[1])"]
    assert text.data.base64 is None
    binary = application.query("delivery.file", DeliveryFile(event_id=delivery_event, path="assets/data.bin"))
    assert binary.data.content is None
    assert base64.b64decode(binary.data.base64) == b"\x00\xff\x01"

def test_delivery_file_is_limited_to_the_archived_paths_of_a_delivery(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("路径", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    projection = system.run_until_stop(run_id)
    application = _application(system)
    delivery_event = projection.delivery_spec.created_event_id
    for path in (".checks/receipts.jsonl", "../outside", "unarchived.py", "empty"):
        with pytest.raises(NotFound):
            application.query("delivery.file", DeliveryFile(event_id=delivery_event, path=path))
    assembled = next(item for item in system.store.list_events(run_id)
                     if item.type == EventType.CONTEXT_ASSEMBLED)
    with pytest.raises(NotFound):
        application.query("delivery.file", DeliveryFile(event_id=assembled.event_id, path="src/echo.py"))
    with pytest.raises(NotFound):
        application.query("delivery.file", DeliveryFile(event_id="event_missing", path="src/echo.py"))

@pytest.mark.parametrize("damage", ["missing_blob", "modified_blob"])
def test_queries_reject_a_corrupted_delivery_archive(data_dir, damage):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("损坏", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    projection = system.run_until_stop(run_id)
    delivery = projection.delivery_spec
    archive = json.loads(system.artifacts.get_for_run(run_id, delivery.tree_ref))
    blob = system.artifacts.root / archive["blobs"][0]["artifact"]["path"]
    if damage == "missing_blob":
        blob.unlink()
        detail_error = file_error = FileNotFoundError
    else:
        blob.write_bytes(b"corrupt archive")
        detail_error = file_error = ValueError
    application = _application(system)
    with pytest.raises(detail_error):
        application.query("event.detail", EventDetail(event_id=delivery.created_event_id))
    with pytest.raises(file_error):
        application.query("delivery.file", DeliveryFile(event_id=delivery.created_event_id, path="src/echo.py"))


def test_work_item_scope_is_checked_in_every_project_query(data_dir):
    # 事项范围参数指向别的事项时，项目内的查询都以目标不存在拒绝（旧路由的跨项目场景）
    system = _system(data_dir, happy_script())
    first = system.projects.register("第一个", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(first, "做一件事")
    system.run_until_stop(run_id)
    second = system.projects.register("第二个", GOAL)
    foreign_item, _foreign_run = system.projects.start_work_item(second, "第二件事")
    application = _application(system)
    for name, request in (
        ("project.overview", ProjectOverview(project_id=first, work_item=foreign_item)),
        ("project.loop", ProjectLoop(project_id=first, work_item=foreign_item)),
        ("project.flow", ProjectFlow(project_id=first, work_item=foreign_item)),
        ("work_item.inputs", WorkItemInputs(project_id=first, work_item=foreign_item)),
        ("work_item.materials", WorkItemMaterials(project_id=first, work_item=foreign_item)),
        ("department.workspace", DepartmentWorkspace(project_id=first, department="product",
                                                    work_item=foreign_item)),
        ("project.attempts", ProjectAttempts(project_id=first, work_item=foreign_item)),
        ("project.usage", ProjectUsage(project_id=first, work_item=foreign_item)),
    ):
        with pytest.raises(NotFound):
            application.query(name, request)
        with pytest.raises(NotFound):
            application.query(name, request.model_copy(update={"work_item": "wi_missing"}))

def _rework_script(verdict="rework_engineering"):
    # 按部门给出（工单 #557：同时运行的会话各自取用自己的脚本）
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [explore_turn(),
                    review_turn(verdict, "质检退回", defects=[{"severity": "minor", "summary": "空输入需要处理"}]),
                    review_turn("release", "revised delivery checked")],
    }


def test_cli_output_matches_the_queries_and_does_not_write_or_lock(data_dir, capsys):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("命令行", GOAL)
    archived_id = system.projects.register("已归档", GOAL)
    system.projects.archive(archived_id)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    system.close()
    before = _files(data_dir)

    readonly = Application.open_readonly(data_dir)
    listed = readonly.query("projects.list", ProjectsList())
    assert main(["project", "list", "--data-dir", str(data_dir)]) == 0
    assert json.loads(capsys.readouterr().out) == listed.model_dump(mode="json")
    archived = readonly.query("projects.list", ProjectsList(include_archived=True))
    assert main(["project", "list", "--archived", "--data-dir", str(data_dir)]) == 0
    assert json.loads(capsys.readouterr().out) == archived.model_dump(mode="json")
    shown = readonly.query("project.overview", ProjectOverview(project_id=project_id))
    assert main(["project", "show", project_id, "--data-dir", str(data_dir)]) == 0
    assert json.loads(capsys.readouterr().out) == shown.model_dump(mode="json")
    checked = readonly.query("replay.check", ReplayCheck(project_id=project_id))
    assert main(["replay", "--project", project_id, "--data-dir", str(data_dir)]) == 0
    assert json.loads(capsys.readouterr().out) == checked.model_dump(mode="json")
    run_checked = readonly.query("replay.check", ReplayCheck(run_id=run_id))
    assert run_checked.data.consistent is True
    assert main(["replay", run_id, "--data-dir", str(data_dir)]) == 0
    assert json.loads(capsys.readouterr().out) == run_checked.model_dump(mode="json")
    readonly.close()

    assert _files(data_dir) == before
    assert not (data_dir / "service.lock").exists()

def test_demo_and_smoke_take_the_data_directory_lock_and_refuse_when_it_is_held(data_dir, capsys):
    data_dir.mkdir()
    held = FileLock(data_dir / "service.lock")
    held.acquire(timeout=0)
    try:
        assert main(["demo", "--data-dir", str(data_dir)]) == 1
        assert "data directory is in use by another service process" in capsys.readouterr().err
        assert main(["smoke", "--data-dir", str(data_dir), "--scenario", "happy"]) == 1
        assert "data directory is in use by another service process" in capsys.readouterr().err
    finally:
        held.release()

def _files(data_dir: Path) -> dict[str, bytes]:
    # SQLite 的只读连接会建立空的边车文件（-wal/-shm），它们不改变保存的数据
    return {
        path.relative_to(data_dir).as_posix(): path.read_bytes()
        for path in data_dir.rglob("*")
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }


def test_run_actions_background_commands_running_and_ended(data_dir: Path):
    interpreter = sys.executable.replace("\\", "/")
    server_cmd = f'"{interpreter}" -c "import time; time.sleep(60)"'
    captured: dict[str, Any] = {}

    def _extract_job_id(call: ModelCall) -> str:
        for item in reversed(call.input_items):
            if item.get("type") == "function_call_output":
                try:
                    data = json.loads(item["output"])
                    if isinstance(data, dict) and data.get("ok"):
                        out = data.get("output")
                        if isinstance(out, dict) and "job_id" in out:
                            return out["job_id"]
                except Exception:
                    pass
        raise ValueError(f"job_id not found in input_items: {call.input_items}")

    def eng_step1(call: ModelCall) -> ModelResponse:
        identity = f"call-bg-start-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "bash", "arguments": json.dumps({"command": server_cmd, "background": True}),
        }])

    def eng_step2(call: ModelCall) -> ModelResponse:
        job_id = _extract_job_id(call)
        captured["job_id"] = job_id
        app = Application(system)
        res = app.query("run.actions", RunActions(run_id=call.run_id))
        captured["running_actions"] = res.data

        identity = f"call-stop-job-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "stop_job", "arguments": json.dumps({"job_id": job_id}),
        }])

    def eng_step3(call: ModelCall) -> ModelResponse:
        app = Application(system)
        res = app.query("run.actions", RunActions(run_id=call.run_id))
        captured["stopped_actions"] = res.data
        return ModelResponse(output=[])

    script = {
        # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
        # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
        "product": [product_spec()],
        "engineering": [eng_step1, eng_step2, eng_step3, delivery_turn()],
        "quality": quality_turns("release", "ok"),
    }

    system = _system(data_dir, script)
    run_id = system.create_run("bg action test")
    system.run_until_stop(run_id)

    running_data = captured["running_actions"]
    assert hasattr(running_data, "background_commands")
    assert len(running_data.background_commands) == 1
    bg_cmd = running_data.background_commands[0]
    assert bg_cmd.command == server_cmd
    assert bg_cmd.started_at
    assert bg_cmd.status == "running"

    stopped_data = captured["stopped_actions"]
    assert len(stopped_data.background_commands) == 1
    assert stopped_data.background_commands[0].command == server_cmd
    assert stopped_data.background_commands[0].status == "ended"

    system.close()


def test_run_actions_background_commands_cancelled_and_restarted(tmp_path: Path):
    interpreter = sys.executable.replace("\\", "/")
    server_cmd = f'"{interpreter}" -c "import time; time.sleep(60)"'

    # A. 取消事项后状态为已结束
    data_cancel = tmp_path / "cancel"
    def eng_cancel_step1(call: ModelCall) -> ModelResponse:
        identity = f"call-bg-start-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "bash", "arguments": json.dumps({"command": server_cmd, "background": True}),
        }])

    def eng_cancel_step2(call: ModelCall) -> ModelResponse:
        sys_cancel.cancel(call.run_id)
        return ModelResponse(output=[])

    sys_cancel = _system(data_cancel, {
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [eng_cancel_step1, eng_cancel_step2],
        "quality": quality_turns("release", "ok"),
    })
    run_cancel = sys_cancel.create_run("cancel test")
    sys_cancel.run_until_stop(run_cancel)
    app_cancel = Application(sys_cancel)
    res_cancel = app_cancel.query("run.actions", RunActions(run_id=run_cancel))
    assert res_cancel.data.background_commands[0].status == "ended"
    sys_cancel.close()

    # B. 重建 LoopSystem（服务重启）后状态为已结束
    data_restart = tmp_path / "restart"
    captured: dict[str, Any] = {}
    def eng_restart_step1(call: ModelCall) -> ModelResponse:
        identity = f"call-bg-start-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "bash", "arguments": json.dumps({"command": server_cmd, "background": True}),
        }])

    def eng_restart_step2(call: ModelCall) -> ModelResponse:
        app1 = Application(sys_restart1)
        captured["running"] = app1.query("run.actions", RunActions(run_id=call.run_id)).data.background_commands[0].status
        raise ProviderError("service stopped for restart", reason="provider_error")

    sys_restart1 = _system(data_restart, {
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [eng_restart_step1, eng_restart_step2],
        "quality": quality_turns("release", "ok"),
    })
    run_restart = sys_restart1.create_run("restart test")
    sys_restart1.run_until_stop(run_restart)
    assert captured["running"] == "running"
    sys_restart1.close()
    sys_restart2 = LoopSystem.for_testing(data_restart, FakeAdapter([]), resume_on_startup=False)
    app2 = Application(sys_restart2)
    res_restart = app2.query("run.actions", RunActions(run_id=run_restart))
    assert res_restart.data.background_commands[0].status == "ended"
    sys_restart2.close()


def test_background_job_status_query_does_not_affect_read_output(data_dir: Path):
    interpreter = sys.executable.replace("\\", "/")
    code = "import time; print('LINE_ONE', flush=True); time.sleep(0.1); print('LINE_TWO', flush=True); time.sleep(60)"
    server_cmd = f'"{interpreter}" -c "{code}"'
    captured: dict[str, Any] = {}

    def _extract_job_id(call: ModelCall) -> str:
        for item in reversed(call.input_items):
            if item.get("type") == "function_call_output":
                try:
                    data = json.loads(item["output"])
                    if isinstance(data, dict) and data.get("ok"):
                        out = data.get("output")
                        if isinstance(out, dict) and "job_id" in out:
                            return out["job_id"]
                except Exception:
                    pass
        raise ValueError(f"job_id not found in input_items: {call.input_items}")

    def eng_step1(call: ModelCall) -> ModelResponse:
        identity = f"call-bg-start-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "bash", "arguments": json.dumps({"command": server_cmd, "background": True}),
        }])

    def eng_step2(call: ModelCall) -> ModelResponse:
        job_id = _extract_job_id(call)
        captured["job_id"] = job_id
        time.sleep(0.3)
        app = Application(system)
        actions = app.query("run.actions", RunActions(run_id=call.run_id))
        assert actions.data.background_commands[0].status == "running"
        identity = f"call-read-output-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "read_output", "arguments": json.dumps({"job_id": job_id}),
        }])

    def eng_step3(call: ModelCall) -> ModelResponse:
        for item in reversed(call.input_items):
            if item.get("type") == "function_call_output":
                data = json.loads(item["output"])
                if isinstance(data, dict) and data.get("ok"):
                    captured["read_output"] = data["output"]["output"]
                    break

        job_id = captured["job_id"]
        identity = f"call-stop-job-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "stop_job", "arguments": json.dumps({"job_id": job_id}),
        }])

    script = {
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [eng_step1, eng_step2, eng_step3, delivery_turn()],
        "quality": quality_turns("release", "ok"),
    }

    system = _system(data_dir, script)
    run_id = system.create_run("read_output query test")
    system.run_until_stop(run_id)

    assert "LINE_ONE" in captured["read_output"]
    assert "LINE_TWO" in captured["read_output"]
    system.close()


def test_recovery_reports_the_position_of_this_items_last_event(data_dir):
    # 验收二（工单 #895）：两个事项先后写了事件，前一个事项的最后已确认位置是它自己最后一条事件的位置，
    # 不是整个事件库的末尾
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("恢复位置", GOAL)
    first_item, first_run = system.projects.start_work_item(project_id, "先做这件事")
    second_item, second_run = system.projects.start_work_item(project_id, "再做这件事")
    own_last = system.store.list_events(first_run)[-1]
    assert system.store.list_events(second_run)[-1].position > own_last.position
    recovery = _application(system).query("run.recovery", RunRecovery(run_id=first_run))
    assert recovery.data.last_confirmed_event_id == own_last.event_id
    assert recovery.data.last_confirmed_position == own_last.position
    assert recovery.data.last_confirmed_position < system.store.end_position()


# 询问分支没能回答的原因与让事项停下的那条错误很容易看混：分支的原因是旁支自己的失败，
# 停止说明只取事项结束的那条事件（工单 #1162，试用 Tf61ac6a6-09 的截图上正是这两句挨在一起）
BRANCH_FAILURE = "分支没能回答的原因 A：模型服务返回 HTTP 400（回答的请求被拒绝）"
STOP_FAILURE = "主干停下的原因 B：模型服务返回 HTTP 400（输入超过上下文长度）"


def _stop_note_system(data_dir):
    # 工程先问产品一次，产品的回答分支失败（A）；拿到结果以后工程的下一次请求失败（B），事项因此停下。
    # 质检的脚本按 PRD 被接纳以后同时开始的那一轮准备（工单 #557）：没有它，先失败的是质检
    system = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [
            ask_turn(recipient="product", question="输出要不要改成大写？", background="实现中需要明确",
                     expected="确认输出形式", call_id="ask-stop-note"),
            ProviderError(STOP_FAILURE),
        ],
        "quality": [explore_turn(), review_turn("release", "ok")],
        "product:ask": [ProviderError(BRANCH_FAILURE)],
    })
    project_id = system.projects.register("停止说明", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "验证停止说明")
    system.run_until_stop(run_id)
    return system, project_id, work_item_id, run_id


def test_the_stop_note_is_the_error_that_stopped_the_item_not_the_asking_branch(data_dir):
    # 验收一（工单 #1162）：先有一次询问分支没能回答（失败原因 A），然后主干以 provider_error 停止（错误 B）；
    # project.overview 里这张卡片的停止说明是 B，不是 A
    system, project_id, work_item_id, run_id = _stop_note_system(data_dir)
    application = _application(system)
    overview = application.query("project.overview", ProjectOverview(project_id=project_id)).data
    card = next(entry for entry in overview.work_items if entry.work_item_id == work_item_id)
    assert card.status == "stopped"
    assert card.stop_reason == "provider_error"
    assert card.stop_note == STOP_FAILURE
    assert BRANCH_FAILURE not in card.stop_note
    # 询问记录照旧留着分支自己的原因：不改询问列表与流转记录
    asks = application.query("run.asks", RunAsks(run_id=run_id)).data.asks
    assert [ask.reason for ask in asks if ask.status == "没能回答"] == [BRANCH_FAILURE]


def test_a_released_item_has_no_stop_note(data_dir):
    # 验收二（工单 #1162）：放行完成的事项没有停止说明
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("没有停止说明", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    overview = _application(system).query("project.overview", ProjectOverview(project_id=project_id)).data
    card = next(entry for entry in overview.work_items if entry.work_item_id == work_item_id)
    assert card.status == "released_unsettled"
    assert card.stop_note is None
    # 验收三（工单 #1239）：放行完成的事项不写停止说明，kept_delivery 也为空——它走的是正常的进度
    assert card.kept_delivery is None


def test_a_cancelled_item_has_no_stop_note(data_dir):
    # 用户自己让事项停下不是错误：结束事件里写的是这次决定，不写进停止说明（工单 #1162）
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("用户取消", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.activate_once(run_id)
    system.cancel(run_id)
    overview = _application(system).query("project.overview", ProjectOverview(project_id=project_id)).data
    card = next(entry for entry in overview.work_items if entry.work_item_id == work_item_id)
    assert card.status == "stopped"
    assert card.stop_reason == "cancelled"
    assert card.stop_note is None


# 已收下的交付（工单 #1239，试用 Te28ea596-03）：交付收下之后事项因为别的原因停下时，
# 停止说明旁边要写出这件事。页面上只有一句失败原因，用户看不出这件事已经有一份可用的交付
KEPT_DELIVERY_FAILURE = "整理失败：模型服务返回 HTTP 500（工作区整理没能完成）"


def _kept_delivery_system(data_dir):
    # 工程交出一版交付，质检核验那一轮的请求失败：交付已经收下，事项仍以 provider_error 停下。
    # 质检的预测性探索（PRD 被接纳以后同时开始的那一轮）照常给上，先失败的是后面核验那一轮
    system = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [explore_turn(), ProviderError(KEPT_DELIVERY_FAILURE)],
    })
    project_id = system.projects.register("已收下的交付", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "验证已收下的交付")
    system.run_until_stop(run_id)
    return system, project_id, work_item_id, run_id


def test_a_stopped_item_reports_the_delivery_it_already_kept(data_dir):
    # 验收一（工单 #1239）：交付收下之后以 provider_error 停下 → 卡片的 kept_delivery 有版本与收下的时间，
    # 停止说明照旧是让事项停下的那条错误
    system, project_id, work_item_id, run_id = _kept_delivery_system(data_dir)
    accepted = [event for event in system.store.list_events(run_id)
                if event.type == EventType.DELIVERY_ACCEPTED]
    assert accepted, "这份脚本应当先收下一版交付"
    overview = _application(system).query("project.overview", ProjectOverview(project_id=project_id)).data
    card = next(entry for entry in overview.work_items if entry.work_item_id == work_item_id)
    assert card.status == "stopped"
    assert card.stop_reason == "provider_error"
    assert card.stop_note == KEPT_DELIVERY_FAILURE
    assert card.kept_delivery is not None
    assert card.kept_delivery.version == accepted[-1].payload["revision"]
    assert card.kept_delivery.accepted_at == accepted[-1].created_at


def test_a_stopped_item_without_a_delivery_keeps_nothing(data_dir):
    # 验收二（工单 #1239）：没有交付就停下的事项，kept_delivery 为空
    system, project_id, work_item_id, run_id = _stop_note_system(data_dir)
    overview = _application(system).query("project.overview", ProjectOverview(project_id=project_id)).data
    card = next(entry for entry in overview.work_items if entry.work_item_id == work_item_id)
    assert card.status == "stopped"
    assert card.kept_delivery is None


def test_a_cancelled_item_still_reports_the_delivery_it_kept(data_dir):
    # 用户自己取消时也写这一行（工单 #1239）：交付仍然在，取消说的是这次决定，不是交付没了
    system = _system(data_dir, {"product": [product_spec()], "engineering": [delivery_turn()],
                                "quality": quality_turns()})
    project_id = system.projects.register("取消前已收下", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    after_event(system, EventType.DELIVERY_ACCEPTED,
                lambda event: from_another_thread(lambda: system.cancel(run_id)))
    system.run_until_stop(run_id)
    overview = _application(system).query("project.overview", ProjectOverview(project_id=project_id)).data
    card = next(entry for entry in overview.work_items if entry.work_item_id == work_item_id)
    assert card.status == "stopped"
    assert card.stop_reason == "cancelled"
    assert card.stop_note is None
    assert card.kept_delivery is not None
    assert card.kept_delivery.version == 1


# ---------------------------------------------------------------------------
# 工单 #1218：replay.check 的参数组合不对时按输入问题回 422，说明只能给 run_id 或 project_id
# 其中一个。查询只有一个参数组合是对的（图里两种目标只有一种能问），所以这里核对的是
# 拒绝按输入问题回答（设计说明第 4.1 节「按位置读取」与第 4.3 节 replay.check 一行），
# 而不是未登记的异常冒到框架成为 500。


def _serving(data_dir, *, registry: Registry | None = None):
    # 真 HTTP 服务用的打开方式：应用层在服务的事件循环里按数据目录打开，事件日志是先前写好的那一份
    def open_application() -> Application:
        return Application(LoopSystem.for_testing(data_dir, FakeAdapter(happy_script())),
                           registry=registry or DEFAULT_REGISTRY)
    return open_application


def _unregistered_failure(application, request):
    # 探针查询：抛一个没有登记的应用层异常。接口层不该把它收成 422
    raise RuntimeError("a failure nobody registered")


UNREGISTERED_FAILURE = QueryDefinition(name="test.unregistered_failure", request=None, result=int,
                                       handle=_unregistered_failure, changed_by=())


def test_replay_check_answers_422_when_it_gets_neither_or_both_parameters(data_dir):
    # 验收一（工单 #1218）：不带参数、两个都带都回 422，error 写明只能给其中一个；只给其中一个照旧 200
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("回放的参数", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    system.close()

    with running_api(_serving(data_dir)) as client:
        for params in ({}, {"run_id": run_id, "project_id": project_id}):
            response = client.get("/api/queries/replay.check", params=params)
            assert response.status_code == 422, response.text
            error = response.json()["error"]
            assert "run_id" in error and "project_id" in error, error
        for params in ({"run_id": run_id}, {"project_id": project_id}):
            response = client.get("/api/queries/replay.check", params=params)
            assert response.status_code == 200, response.text
            assert response.json()["data"] == {"target": "run" if "run_id" in params else "project",
                                              "consistent": True, "differences": []}


def test_an_unregistered_application_failure_is_still_a_500(data_dir):
    # 验收四（工单 #1218）：只有登记过的输入问题变成 422。别的异常照旧冒到框架，回 500 纯文本，
    # 响应体不写原因与路径（与 #740 的字段错误不同：那不是输入问题）
    registry = Registry(commands=list(DEFAULT_REGISTRY.commands.values()),
                        queries=[*DEFAULT_REGISTRY.queries.values(), UNREGISTERED_FAILURE],
                        decisions=DEFAULT_REGISTRY.decisions)
    with running_api(_serving(data_dir, registry=registry), registry=registry) as client:
        response = client.get("/api/queries/test.unregistered_failure")
        assert response.status_code == 500, response.text
        assert response.text.strip() == "Internal Server Error"


def test_cli_replay_refuses_neither_or_both_parameters_without_a_traceback(data_dir, capsys):
    # 验收三（工单 #1218）：命令行走同一个查询。参数组合不对时打印原因、非零退出，不打印栈
    for argv in (["replay"], ["replay", "run_x", "--project", "project_x"]):
        with pytest.raises(SystemExit) as stopped:
            main([*argv, "--data-dir", str(data_dir)])
        assert stopped.value.code not in (0, None)
        err = capsys.readouterr().err
        assert "run_id" in err and "project_id" in err, err
        assert "Traceback" not in err and "ValueError" not in err, err

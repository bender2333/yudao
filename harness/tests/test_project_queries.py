import base64
import json
import sqlite3
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from filelock import FileLock

from harness.__main__ import main
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.decision_queries import DecisionsList
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
    RunAttempt,
    RunExport,
    WorkItemInputs,
    WorkItemMaterials,
)
from harness.app.registry import Registry
from harness.app.system_queries import SYSTEM_STATUS
from harness.event_store import run_stream
from harness.models import EventType, ProjectEventType
from harness.proposals import product_spec, plan_turn, delivery_turn, review_turn
from harness.providers.selection import ModelSelection
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script
from harness.tests.saved_rewrite import rewrite_saved_event
from harness.write_path import NewEvent

GOAL = "把文本按行处理清楚"


def _release_script(summary="v1", files=None):
    return [
        product_spec(), plan_turn(), delivery_turn(summary=summary, files=files),
        review_turn("release", f"ok {summary}"),
    ]


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
            "marker", state_before="DONE", state_after="DONE", actor="system", payload={"marker": name},
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
        ("system.status", None),
        ("decisions.list", DecisionsList()),
        ("projects.list", ProjectsList()),
        ("project.overview", ProjectOverview(project_id=project_id)),
        ("project.loop", ProjectLoop(project_id=project_id)),
        ("project.flow", ProjectFlow(project_id=project_id)),
        ("work_item.inputs", WorkItemInputs(project_id=project_id, work_item=work_item_id)),
        ("event.detail", EventDetail(event_id=event_id)),
        ("department.workspace", DepartmentWorkspace(project_id=project_id, department="product",
                                                     work_item=work_item_id)),
        ("run.actions", RunActions(run_id=run_id)),
        ("work_item.materials", WorkItemMaterials(project_id=project_id, work_item=work_item_id)),
        ("delivery.file", DeliveryFile(event_id=delivery_event_id, path="src/echo.py")),
        ("project.attempts", ProjectAttempts(project_id=project_id)),
        ("project.usage", ProjectUsage(project_id=project_id)),
        ("run.attempt", RunAttempt(run_id=run_id, attempt_id=attempt_id)),
        ("project.settings", ProjectSettings(project_id=project_id)),
        ("run.export", RunExport(run_id=run_id)),
        ("replay.check", ReplayCheck(run_id=run_id)),
    ]


def test_overview_does_not_settle_a_released_run(data_dir):
    system = _system(data_dir, _release_script())
    project_id = system.projects.register("未结算", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "第一步")
    system.run_until_stop(run_id)
    application = _application(system)
    before = [event.type for event in system.store.list_project_events(project_id)]
    snapshot = application.query("project.overview", ProjectOverview(project_id=project_id))
    item = next(item for item in snapshot.data.work_items if item.work_item_id == work_item_id)
    assert item.status == "released_unsettled"
    assert [event.type for event in system.store.list_project_events(project_id)] == before
    assert ProjectEventType.DELIVERABLE_ADOPTED not in before


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
        EventType.MODEL_ATTEMPT_FINISHED, state_before="DONE", state_after="DONE", actor="system",
        department="product",
        payload={
            "attempt_id": "late-attempt", "logical_call_id": "late", "collaboration_request_id": None,
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


def test_query_time_does_not_grow_with_unrelated_history(data_dir):
    # 同一场景把历史事件数量增加十倍：已登记的查询耗时不变。
    # replay.check 按设计要重放整份日志，与历史长度有关，不在其列
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("耗时", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    projection = system.run_until_stop(run_id)
    application = _application(system)
    attempts = application.query("project.attempts", ProjectAttempts(project_id=project_id)).data.attempts
    assembled = next(item for item in system.store.list_events(run_id)
                     if item.type == EventType.CONTEXT_ASSEMBLED)
    requests = (
        ("projects.list", ProjectsList()),
        ("project.overview", ProjectOverview(project_id=project_id)),
        ("project.loop", ProjectLoop(project_id=project_id)),
        ("project.flow", ProjectFlow(project_id=project_id)),
        ("work_item.inputs", WorkItemInputs(project_id=project_id, work_item=work_item_id)),
        ("event.detail", EventDetail(event_id=assembled.event_id)),
        ("department.workspace", DepartmentWorkspace(project_id=project_id, department="product",
                                                     work_item=work_item_id)),
        ("run.actions", RunActions(run_id=run_id)),
        ("work_item.materials", WorkItemMaterials(project_id=project_id, work_item=work_item_id)),
        ("delivery.file", DeliveryFile(event_id=projection.delivery_spec.created_event_id, path="src/echo.py")),
        ("project.attempts", ProjectAttempts(project_id=project_id, limit=5)),
        ("project.usage", ProjectUsage(project_id=project_id)),
        ("run.attempt", RunAttempt(run_id=run_id, attempt_id=attempts[0].attempt_id)),
        ("project.settings", ProjectSettings(project_id=project_id)),
        ("run.export", RunExport(run_id=run_id)),
    )

    def measure() -> float:
        started = time.perf_counter()
        for _ in range(10):
            for name, request in requests:
                application.query(name, request)
        return time.perf_counter() - started

    measure()  # 预热：第一次查询建立读取模型
    baseline = min(measure(), measure(), measure())
    noise = [NewEvent("noise", state_before="CREATED", state_after="CREATED", actor="system",
                      payload={"n": index})
             for index in range(system.store.end_position() * 9)]
    system.writes.append(run_stream("run_noise"), *noise)
    measure()  # 订阅把新事件吸收进读取模型；之后的查询不再处理它们
    again = min(measure(), measure(), measure())
    assert again < baseline * 4, f"baseline={baseline:.4f}s again={again:.4f}s"


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
    assert workspace.data.prompt.configured_version == 1
    assert workspace.data.prompt.prompt_configured is True
    # 实际采用的版本来自该部门最近一次模型请求事件（run 内没有 Prompt 副本）
    assert workspace.data.prompt.used_version == 1
    assert workspace.data.setting.model_id is None and workspace.data.setting.requested_tier is None

    actions = application.query("run.actions", RunActions(run_id=run_id))
    assert any(action.tool == "write_file" and action.receipt.ok for action in actions.data.actions)

    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id,
    ))
    assert materials.data.contracts
    assert materials.data.plans
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
    checked = application.query("replay.check", ReplayCheck(run_id=run_id))
    assert checked.data.consistent is True
    assert checked.data.differences == []
    project_checked = application.query("replay.check", ReplayCheck(project_id=project_id))
    assert project_checked.data.consistent is True


def test_flow_records_cover_handoff_delivery_problem_and_rework(data_dir):
    system = _system(data_dir, _rework_script())
    project_id = system.projects.register("流转", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    flow = application.query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))
    kinds = [record.kind for record in flow.data.records]
    assert {"需求交接", "版本交付", "返工", "问题反馈"} <= set(kinds)
    rework = next(record for record in flow.data.records if record.kind == "返工")
    assert rework.status == "已退回" and rework.direction_to == "engineering"
    problem = next(record for record in flow.data.records if record.kind == "问题反馈")
    assert problem.content == "质检退回" and problem.direction_from == "quality"
    assert all(record.work_item_id == work_item_id for record in flow.data.records)
    positions = [record.position for record in flow.data.records]
    assert positions == sorted(positions)
    assert flow.position >= positions[-1]


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
    system = _system(data_dir, [*_release_script(), *_release_script()])
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
    from harness.tests.test_compaction_engine import _runner

    system, _, run_id, _ = _runner(tmp_path)
    system.activate_once(run_id)
    application = _application(system)
    event = next(item for item in system.store.list_events(run_id)
                 if item.type == EventType.COMPACTION_RECORDED)
    detail = application.query("event.detail", EventDetail(event_id=event.event_id))
    assert detail.data.artifacts["compaction_summary"]
    assert detail.data.artifacts["compaction_sources"]


def test_delivery_detail_and_file_use_the_archived_bytes(data_dir):
    # 封存的清单与文件原文取自交付封存，不取自当前工作区（旧路由 test_web.py 的对应场景）
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
        # 事件详情的 Git 版本核对先读到缺失的对象（GitBindingError），交付文件按缺失的工件拒绝
        detail_error, file_error = ValueError, FileNotFoundError
    else:
        blob.write_bytes(b"corrupt archive")
        detail_error = file_error = ValueError
    application = _application(system)
    with pytest.raises(detail_error):
        application.query("event.detail", EventDetail(event_id=delivery.created_event_id))
    with pytest.raises(file_error):
        application.query("delivery.file", DeliveryFile(event_id=delivery.created_event_id, path="src/echo.py"))


@pytest.mark.parametrize("mismatch", ["other_commit", "fake_tree", "forged_material"])
def test_event_detail_rejects_a_git_version_not_bound_to_its_materials(data_dir, mismatch):
    # 改写保存的事件行以后核对绑定：另一个事件的版本、伪造的树、伪造的正式材料
    system = _system(data_dir, _release_script())
    project_id = system.projects.register("绑定", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    events = system.store.list_events(run_id)
    delivery = next(item for item in events if item.type == EventType.DELIVERY_ACCEPTED)
    payload = dict(delivery.payload)
    if mismatch == "other_commit":
        payload["git_version"] = next(item.payload["git_version"] for item in events
                                      if item.type == EventType.SPEC_ACCEPTED)
    elif mismatch == "fake_tree":
        payload["git_version"] = {**payload["git_version"], "tree": "0" * 40}
    else:
        payload["prd_ref"] = asdict(system.artifacts.put(
            run_id, "prd", "FORGED_ACCEPTED_MATERIAL", media_type="text/markdown"))
    rewrite_saved_event(system.store, replace(delivery, payload=payload))
    application = _application(system)
    with pytest.raises(ValueError):
        application.query("event.detail", EventDetail(event_id=delivery.event_id))


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
    return [
        product_spec(), plan_turn(), delivery_turn(),
        review_turn(verdict, "质检退回", defects=[{"severity": "minor", "summary": "空输入需要处理"}]),
        plan_turn(reason="处理质检退回"),
        delivery_turn(summary="处理空输入"),
        review_turn("release", "revised delivery checked"),
    ]


def test_read_models_write_only_their_own_database(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("读取模型", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    before = _log_tables(data_dir / "events.sqlite")
    application.query("project.attempts", ProjectAttempts(project_id=project_id))
    application.query("project.flow", ProjectFlow(project_id=project_id))
    application.rebuild_read_models()
    assert _log_tables(data_dir / "events.sqlite") == before
    assert (data_dir / "read-models.sqlite").is_file()
    assert _table_names(data_dir / "read-models.sqlite") >= {
        "app_attempt_state", "app_attempts", "app_flows", "app_read_positions",
    }
    assert not (data_dir / "read-models.sqlite").samefile(data_dir / "events.sqlite")


def _log_tables(path: Path) -> dict[str, list[tuple]]:
    # 事件日志的三张表：读取模型与查询都不写它们
    with sqlite3.connect(path) as connection:
        return {
            name: connection.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
            for name in ("events", "projections", "commands")
        }


def _table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


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

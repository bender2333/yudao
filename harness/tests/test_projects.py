"""B1 项目与事项内核：§13 反例（内核 / 服务 / 投影部分）。"""

import json

import pytest

from harness.__main__ import main
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.context import ContextAssembler
from harness.definitions import DEFINITIONS
from harness.engine import StepLimits
from harness.event_store import Command, project_stream, run_stream
from harness.department_prompts import save_department_prompt
from harness.models import DEPARTMENTS, ArtifactRef, DepartmentPrompt, EventType, ProjectEventType, json_dumps
from harness.write_path import NewProjectEvent
from harness.providers.selection import ModelSelection
from harness.projects import (
    DepartmentSettingConflict,
    ProjectArchivedError,
    ProjectNotFoundError,
    WorkItemInProgressError,
    project_context_text,
    project_projection,
)
from harness.proposals import (
    delivery_turn, product_spec,
    review_turn,
)
from harness.projection import RunNotFoundError, saved_decision, saved_decisions
from harness.providers.call import ModelResponse
from harness.public_tree import TreeError, capture_public_tree
from harness.runtime import LoopSystem
from harness.smoke import isolation_fields, summarize_run
from harness.tests.helpers import happy_script, recorded_context
from harness.tree_archive import load_tree

GOAL = "做一个可以长期演进的逐行文本处理工具。"

def _system(data_dir, script):
    return LoopSystem.for_testing(data_dir, FakeAdapter(script))

def _release_script(summary="v1", files=None):
    return [product_spec(),delivery_turn(summary=summary, files=files), review_turn("release", f"ok {summary}")]

def _v2_files():
    return {"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n", "src/extra.py": "EXTRA = True\n"}

def _kernel_release_script(summary="v1", files=None):
    # 内核清单路径的写操作需要用户决定授权，工具才会允许写这个文件
    return [product_spec(),delivery_turn(summary=summary, files=files),
            review_turn("release", f"ok {summary}")]

def _pinned_sources(system, request):
    return [part.source for part in recorded_context(system, request).parts]

def _project_events(system, project_id, event_type):
    return [event for event in system.store.list_project_events(project_id) if event.type == event_type]

# ---------------------------------------------------------------------------

# §3 项目流

def _open_decisions(system):
    return [decision for decision in saved_decisions(system.store, kinds=("kernel_modification",))[1]
            if decision.status == "open"]

@pytest.mark.parametrize("query", ["project_list", "drain"])
def test_status_queries_keep_work_item_states_without_reading_run_histories(data_dir, query):
    system = _system(data_dir, [*happy_script(), product_spec()])
    try:
        adopted_project = system.projects.register("已有成果", GOAL)
        _adopted_item, adopted_run = system.projects.start_work_item(adopted_project, "完成一个事项")
        assert system.run_until_stop(adopted_run).phase == "DONE"
        system.projects.settle(adopted_run)
        running_project = system.projects.register("正在运行", GOAL)
        _running_item, running_run = system.projects.start_work_item(running_project, "继续工作")
        system.activate_once(running_run)
        system.start_drain()
        queued_project = system.projects.register("等待执行", GOAL)
        system.projects.queue_work_item(queued_project, "排队的事项")
        queries = []
        connections = list(system.store._opened)
        for connection in connections:
            connection.set_trace_callback(queries.append)
        try:
            if query == "project_list":
                projects = system.projects.list_projects()
                assert {project.name: project.work_items[0].status for project in projects} == {
                    "已有成果": "adopted", "正在运行": "in_progress", "等待执行": "not_started",
                }
            else:
                state = system.drain
                assert (state.state, state.running_runs, state.queued_work_items) == ("draining", 1, 1)
        finally:
            for connection in connections:
                connection.set_trace_callback(None)
        run_queries = [statement for statement in queries
                       if "SELECT * FROM events WHERE stream = '" in statement
                       and any(run_stream(run_id) in statement for run_id in (adopted_run, running_run))]
        assert run_queries == []
    finally:
        system.close()


def _answer(system, decision_id, option):
    command = Command(decision_id, "decision.answer", f"sha256:{option}", "user:local")
    return system.orchestrator.answer_decision(decision_id, option, None, base_version=1, command=command)

def test_project_events_have_their_own_stream_in_the_one_log(data_dir):
    system = _system(data_dir, happy_script())
    project_a = system.projects.register("A", GOAL)
    system.projects.rename(project_a, "A2")
    project_b = system.projects.register("B", GOAL)
    first, second = system.store.list_project_events(project_a)
    [other] = system.store.list_project_events(project_b)
    # 流内版本按项目各自递增，全局位置跨项目递增
    assert (first.stream_version, second.stream_version, other.stream_version) == (1, 2, 1)
    assert first.position < second.position < other.position
    assert (first.stream, other.stream) == (f"project:{project_a}", f"project:{project_b}")
    assert [first.type, second.type] == ["project_registered", "project_renamed"]
    assert [event.stream_version for event in system.store.list_project_events(project_a, after_version=1)] == [2]
    assert system.store.get_project_event(second.event_id).payload == {"name": "A2"}
    assert system.store.get_project_event("missing") is None
    assert system.store.get_event(second.event_id) is None
    assert system.store.list_project_ids() == [project_b, project_a]
    # 项目事件不进入 run 流。
    assert system.store.list_run_ids() == []
    assert system.store.list_events(project_a) == []

# ---------------------------------------------------------------------------
# §13.1 同一项目两事项：继承与新版本

def test_second_work_item_inherits_adopted_tree_byte_for_byte(data_dir):
    system = _system(data_dir, [*_release_script("v1"), *_release_script("v2", files=_v2_files())])
    project_id = system.projects.register("Echo", GOAL)
    work_item_1, run_1 = system.projects.start_work_item(project_id, "第一步：echo CLI")
    run = system.project(run_1)
    assert (run.project_id, run.work_item_id, run.baseline) == (project_id, work_item_1, None)
    assert run.workspace_digest == capture_public_tree(system.workspace(run_1).root).digest
    assert run.prompt_config_versions == {"product": 0, "engineering": 0, "quality": 0}
    assert system.run_until_stop(run_1).phase == "DONE"
    adopted = system.projects.settle(run_1)
    assert adopted.type == ProjectEventType.DELIVERABLE_ADOPTED
    assert system.projects.settle(run_1) is None
    project = system.projects.projection(project_id)
    first_adoption = project.current_adoption
    assert first_adoption.run_id == run_1 and first_adoption.summary == "v1"
    assert first_adoption.previous_adoption_id is None
    assert project.work_items[0].status == "adopted"
    assert project.work_items[0].adoption_id == first_adoption.adoption_id

    work_item_2, run_2 = system.projects.start_work_item(project_id, "第二步：增加大写与 extra")
    inherited = capture_public_tree(system.workspace(run_2).root)
    archived = load_tree(system.artifacts, run_1, ArtifactRef(**first_adoption.tree_ref))
    assert inherited.digest == first_adoption.code_tree_digest == archived.digest
    assert inherited == archived
    run = system.project(run_2)
    assert run.baseline == {
        "adoption_id": first_adoption.adoption_id, "source_run_id": run_1,
        "delivery_event_id": first_adoption.delivery_event_id, "tree_ref": first_adoption.tree_ref,
        "code_tree_digest": first_adoption.code_tree_digest,
    }
    assert run.workspace_digest == first_adoption.code_tree_digest
    assert system.run_until_stop(run_2).phase == "DONE"
    assert system.projects.settle(run_2).type == ProjectEventType.DELIVERABLE_ADOPTED
    project = system.projects.projection(project_id)
    assert project.current_adoption.run_id == run_2 and project.current_adoption.summary == "v2"
    assert project.current_adoption.previous_adoption_id == first_adoption.adoption_id
    assert [item.summary for item in project.adoptions] == ["v1", "v2"]
    assert [item.status for item in project.work_items] == ["adopted", "adopted"]
    old_tree = load_tree(system.artifacts, project.adoptions[0].run_id, ArtifactRef(**project.adoptions[0].tree_ref))
    assert old_tree == archived
    new_tree = load_tree(system.artifacts, run_2, ArtifactRef(**project.current_adoption.tree_ref))
    assert {item.path for item in new_tree.files} == {"src/echo.py", "src/extra.py"}
    assert new_tree.digest != old_tree.digest

# ---------------------------------------------------------------------------
# §13.2 基线在放行前已变：保留为未采纳候选

def test_release_after_baseline_change_is_held_not_adopted(data_dir):
    system = _system(data_dir, [*_release_script("A"), *_release_script("B", files=_v2_files())])
    project_id = system.projects.register("Held", GOAL)
    work_item_a, run_a = system.projects.start_work_item(project_id, "事项 A")
    work_item_b, run_b = system.projects.start_work_item(project_id, "事项 B（在 A 采纳前创建）")
    assert system.project(run_b).baseline is None
    assert system.run_until_stop(run_a).phase == "DONE"
    assert system.projects.settle(run_a).type == ProjectEventType.DELIVERABLE_ADOPTED
    assert system.run_until_stop(run_b).phase == "DONE"
    held = system.projects.settle(run_b)
    assert held.type == ProjectEventType.ADOPTION_HELD
    project = system.projects.projection(project_id)
    assert project.current_adoption.run_id == run_a
    assert len(project.adoptions) == 1
    assert project.held[0].reason == "baseline_changed"
    assert project.held[0].work_item_id == work_item_b
    assert project.held[0].expected_adoption_id is None
    assert project.held[0].current_adoption_id == project.current_adoption.adoption_id
    assert {item.work_item_id: item.status for item in project.work_items} == {work_item_a: "adopted", work_item_b: "held"}
    assert system.projects.settle(run_b) is None
    assert system.projects.settle_pending(project_id) == []
    # 下一个事项仍从 A 的成果继承，而不是 B。
    _work_item_c, run_c = system.projects.start_work_item(project_id, "事项 C")
    assert system.project(run_c).baseline["adoption_id"] == project.current_adoption.adoption_id
    assert system.project(run_c).workspace_digest == project.current_adoption.code_tree_digest

# ---------------------------------------------------------------------------
# §13.3 取消 / max_cycles 暂停 / provider 失败：stopped，不采纳

@pytest.mark.parametrize("scenario,expected", [
    ("cancelled", ("FAILED", "cancelled")),
    ("max_cycles", ("PAUSED", "max_cycles")),
    ("provider_error", ("FAILED", "provider_error")),
])
def test_stopped_runs_keep_stop_reason_and_are_not_adopted(data_dir, scenario, expected):
    script = [product_spec(), FakeTurn(raise_error=ProviderError("upstream 500"))] if scenario == "provider_error" else happy_script()
    system = _system(data_dir, script)
    project_id = system.projects.register("Stops", GOAL)
    options = {"max_cycles": 1} if scenario == "max_cycles" else {}
    work_item_id, run_id = system.projects.start_work_item(project_id, f"事项：{scenario}", **options)
    if scenario == "cancelled":
        run = system.cancel(run_id)
    else:
        run = system.run_until_stop(run_id)
    assert (run.phase, run.stop_reason) == expected
    assert system.projects.settle(run_id) is None
    assert system.projects.settle_pending(project_id) == []
    project = system.projects.projection(project_id)
    item = project.work_item(work_item_id)
    assert item.status == "stopped"
    assert item.stop_reason == run.stop_reason
    assert item.human_action == run.human_action
    assert item.department is None and item.phase == run.phase
    assert project.current_adoption is None and project.adoptions == [] and project.held == []
    assert project.active_work_item_id is None
    types = {event.type for event in system.store.list_project_events(project_id)}
    assert ProjectEventType.DELIVERABLE_ADOPTED not in types and ProjectEventType.ADOPTION_HELD not in types

# ---------------------------------------------------------------------------
# §13.4 两个项目互不可见

def test_projects_do_not_see_each_other(data_dir):
    system = _system(data_dir, [*_release_script("A"), *_release_script("B")])
    project_a = system.projects.register("A", "目标 A")
    project_b = system.projects.register("B", "目标 B")
    work_item_a, run_a = system.projects.start_work_item(project_a, "A 的事项")
    work_item_b, run_b = system.projects.start_work_item(project_b, "B 的事项")
    system.run_until_stop(run_a)
    system.run_until_stop(run_b)
    system.projects.settle(run_a)
    system.projects.settle(run_b)
    system.projects.configure_department_settings(
        project_b, "quality", ModelSelection(department_prompt="只属于 B 的质检 Prompt"), 0)
    system.projects.record_material(project_b, "只属于 B 的材料", department="product")
    view_a = json_dumps(system.projects.projection(project_a).to_dict())
    view_b = json_dumps(system.projects.projection(project_b).to_dict())
    for foreign in (project_b, work_item_b, run_b, "只属于 B"):
        assert foreign not in view_a
    for foreign in (project_a, work_item_a, run_a):
        assert foreign not in view_b
    assert system.projects.projection(project_a).department_settings["quality"].source == "default"
    assert system.projects.projection(project_a).materials == []
    assert [item.name for item in system.projects.list_projects()] == ["B", "A"]
    system.projects.pin(project_a, True)
    assert [item.name for item in system.projects.list_projects()] == ["A", "B"]
    assert system.project(run_a).project_id == project_a and system.project(run_b).project_id == project_b

# ---------------------------------------------------------------------------
# §13.5 事件重放：两表重建 == 在线

def test_project_projection_rebuilds_from_two_tables_and_cli_replay(data_dir, capsys):
    system = _system(data_dir, [*_release_script("v1"), *_release_script("v2", files=_v2_files())])
    project_id = system.projects.register("Replay", GOAL)
    system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt="工程 Prompt v1"), 0)
    system.projects.record_material(project_id, "一条原文材料", department=None)
    _work_item_1, run_1 = system.projects.start_work_item(project_id, "第一步")
    system.run_until_stop(run_1)
    system.projects.settle(run_1)
    _work_item_2, run_2 = system.projects.start_work_item(project_id, "第二步")
    system.run_until_stop(run_2)
    system.projects.settle(run_2)
    system.projects.rename(project_id, "Replay 2")
    system.projects.pin(project_id, True)
    online = system.projects.projection(project_id)
    assert online.name == "Replay 2" and online.pinned and len(online.adoptions) == 2
    fresh = LoopSystem(data_dir)
    rebuilt = project_projection(fresh.store, fresh.artifacts, project_id)
    assert rebuilt.canonical_state() == online.canonical_state()
    assert rebuilt.to_dict() == online.to_dict()
    with pytest.raises(ProjectNotFoundError):
        project_projection(fresh.store, fresh.artifacts, "proj_missing")
    fresh.store.close()
    assert main(["replay", "--project", project_id, "--data-dir", str(data_dir)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["data"]["target"] == "project"
    assert printed["data"]["consistent"] is True
    assert printed["data"]["differences"] == []
    with pytest.raises(SystemExit):
        main(["replay", "--data-dir", str(data_dir)])

# ---------------------------------------------------------------------------
# §13.6 create_run 归属参数

def _ownership(project_id="proj_x", work_item_id="wi_x"):
    return {
        "project_id": project_id, "work_item_id": work_item_id, "project_context": "项目：X",
        "prompt_config_versions": {department: 0 for department in DEPARTMENTS},
    }

def test_create_run_rejects_mixed_ownership_parameters(data_dir, tmp_path):
    system = _system(data_dir, happy_script())
    for missing in ("project_id", "work_item_id", "project_context", "prompt_config_versions"):
        kwargs = _ownership()
        kwargs.pop(missing)
        with pytest.raises(ValueError, match="given together"):
            system.create_run("mixed", **kwargs)
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="require project ownership"):
        system.create_run("bare with baseline", baseline={"adoption_id": "a"}, initial_tree=capture_public_tree(tmp_path / "empty"))
    with pytest.raises(ValueError, match="cover exactly"):
        system.create_run("bad versions", **{**_ownership(), "prompt_config_versions": {"product": 0}})
    assert system.store.list_run_ids() == []
    # bare run 仍然允许：空目录 digest，没有 project 部件。
    run_id = system.create_run("bare")
    run = system.project(run_id)
    assert run.project_id is None and run.work_item_id is None and run.baseline is None
    assert run.project_context_ref is None and run.prompt_config_versions == {}
    assert run.workspace_digest == capture_public_tree(system.workspace(run_id).root).digest
    prompt = DepartmentPrompt("product", 0, DEFINITIONS.role("product").prompt,
                              save_department_prompt(system.artifacts, run_id, "product",
                                                     DEFINITIONS.role("product").prompt), "")
    assembled = ContextAssembler(system.artifacts).assemble(
        run, department="product", session_id="s", activation_id="a", prompt=prompt)
    assert "project" not in [part.source for part in assembled.parts]

def test_create_run_rejects_baseline_digest_mismatch_and_existing_workspace(data_dir, tmp_path):
    system = _system(data_dir, happy_script())
    seed = tmp_path / "seed"
    (seed / "src").mkdir(parents=True)
    (seed / "src" / "echo.py").write_text("print('seed')\n", encoding="utf-8")
    tree = capture_public_tree(seed)
    baseline = {"adoption_id": "adopt_x", "source_run_id": "run_src", "delivery_event_id": "evt_d",
                "tree_ref": {"kind": "tree_manifest"}, "code_tree_digest": "sha256:" + "0" * 64}
    with pytest.raises(ValueError, match="code_tree_digest does not match"):
        system.create_run("mismatch", baseline=baseline, initial_tree=tree, **_ownership())
    with pytest.raises(ValueError, match="given together"):
        system.create_run("tree without baseline", initial_tree=tree, **_ownership())
    assert system.store.list_run_ids() == []
    good = {**baseline, "code_tree_digest": tree.digest}
    run_id = system.create_run("restored", baseline=good, initial_tree=tree, **_ownership())
    assert system.project(run_id).workspace_digest == tree.digest
    assert system.workspace(run_id).read_file("src/echo.py") == "print('seed')\n"
    # 目标目录已存在：抛错且不覆盖。
    existing = system.orchestrator.workspace_root / "run_existing"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(TreeError, match="already exists"):
        system.create_run("clash", run_id="run_existing", baseline=good, initial_tree=tree, **_ownership())
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (existing / "src").exists()
    with pytest.raises(RunNotFoundError):
        system.project("run_existing")

# ---------------------------------------------------------------------------
# §13.7 项目上下文部件

def test_project_context_part_is_pinned_between_current_work_and_department_rules(data_dir):
    adapter = FakeAdapter(happy_script())
    system = LoopSystem.for_testing(data_dir, adapter)
    project_id = system.projects.register("Ctx", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "第一步：echo")
    run = system.project(run_id)
    text = system.artifacts.get_for_run(run_id, ArtifactRef(**run.project_context_ref)).decode("utf-8")
    assert text == project_context_text(system.projects.projection(project_id), "第一步：echo")
    assert "仍有效的决定：无" in text
    assert run.project_context_ref["media_type"] == "text/markdown"
    created = next(event for event in system.store.list_events(run_id) if event.type == EventType.RUN_CREATED)
    assert created.payload["project_context_ref"] == run.project_context_ref
    assert "project_context" not in created.payload
    assert "project_context" not in run.to_dict()
    assert system.run_until_stop(run_id).phase == "DONE"
    first_requests = {}
    for request in adapter.invocations:
        first_requests.setdefault(request.department, request)
    assert set(first_requests) == {"product", "engineering", "quality"}
    for request in adapter.invocations:
        context = recorded_context(system, request)
        sources = [part.source for part in context.parts]
        assert sources.index("current_work") < sources.index("project") < sources.index("department_rules")
        content = request.input_items[0]["content"]
        assert content.index("[current_work]") < content.index(f"[project]\n{text}") < content.index("[department_rules]")
        assert content.startswith(f"[intend]\n{run.task}\n\n[current_work]\n")
        project_part = next(part for part in context.parts if part.source == "project")
        assert project_part.version == run.project_context_ref["content_hash"].split(":", 1)[1][:12]
        injected = [item.source for item in context.manifest.injected]
        assert injected.index("current_work") < injected.index("project") < injected.index("department_rules")
    # 部门工作消息不重复项目材料（它属于钉住材料）。
    department_inputs = [event for event in system.store.list_events(run_id) if event.type == EventType.DEPARTMENT_INPUT]
    for event in department_inputs:
        item = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["input_ref"])))
        assert "[project]" not in item["content"]
    # smoke 审计把 project 视为合法钉住材料。
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "verified", audit["notes"]
    summary = summarize_run(system, run_id, scenario="happy")
    assert summary["model_input_audit"]["status"] == "verified"
    assert summary["context_isolated"] is True, summary["context_isolation_notes"]
    assert summary["delivery_archive"]["status"] == "verified"

def test_project_context_guidance_stays_before_department_rules(data_dir):
    adapter = FakeAdapter([lambda request: product_spec()])
    system = LoopSystem.for_testing(data_dir, adapter)
    project_id = system.projects.register("Guide", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "带指导的事项")
    system.add_guidance(run_id, "product", "先给出验收标准。")
    system.activate_once(run_id)
    sources = _pinned_sources(system, adapter.invocations[0])
    assert sources[:5] == ["intend", "current_work", "project", "department_guidance", "department_rules"]

def test_compaction_pinned_input_contains_project_part(data_dir):
    # 步数上限已放开为时间边界，本用例按旧步数上限验证单次激活内的压缩行为
    def respond(request):
        if request.purpose == "compaction":
            return ModelResponse(output=[{
                "id": f"summary-{request.activation_id}-{request.step_id}", "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "Product memory: prior evidence was read."}],
            }])
        if request.department != "product":
            return delivery_turn()
        if request.step_id == 1:
            identity = f"read-{request.activation_id}-{request.step_id}"
            return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                          "name": "read_file", "arguments": json_dumps({"path": "large.txt"})}])
        return product_spec()

    adapter = FakeAdapter([respond] * 100)
    system = LoopSystem.for_testing(data_dir, adapter, step_limits=StepLimits(max_model_steps=32))
    project_id = system.projects.register("Compact", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "小窗口事项", context_window=6000)
    system.workspace(run_id).write_file("large.txt", "FIRST_TOOL_ORIGINAL " * 2200)
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING", result.error
    compactions = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert compactions
    project_text = system.artifacts.get_for_run(
        run_id, ArtifactRef(**system.project(run_id).project_context_ref),
    ).decode("utf-8")
    for request in compactions:
        pinned = request.input_items[1]["content"]
        assert pinned.index("[current_work]") < pinned.index(f"[project]\n{project_text}") < pinned.index("[department_rules]")
        pinned_work = next(part for part in recorded_context(system, request).parts if part.source == "pinned_work")
        assert f"[project]\n{project_text}" in pinned_work.text
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "verified", audit["notes"]
    assert audit["compaction_count"] >= 1

# ---------------------------------------------------------------------------
# §13.8 部门 Prompt 项目配置

def test_department_setting_versions_conflicts_and_effect_timing(data_dir):
    # 部门 Prompt 保存在项目部门设置中，run 内没有副本：修改从该部门的下一次模型请求起生效
    adapter = FakeAdapter([*_release_script("A"), *_release_script("B", files=_v2_files())])
    system = LoopSystem.for_testing(data_dir, adapter)
    project_id = system.projects.register("Prompts", GOAL)
    default = system.projects.read_department_setting(project_id, "engineering")
    default_text = DEFINITIONS.role("engineering").prompt
    assert default == {"department": "engineering", "text": default_text,
                       "default_text": default_text, "department_setting_configured": False, "provider_id": None,
                       "model_id": None, "requested_tier": None, "version": 0, "updated_at": None,
                       "source": "default"}
    v1 = "工程 Prompt v1：直接写代码。"
    saved = system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt=v1), 0)
    assert (saved["version"], saved["source"], saved["unchanged"], saved["text"]) == (1, "configured", False, v1)
    assert saved["updated_at"] is not None and saved["default_text"] == default_text
    assert saved["department_setting_configured"] is True
    again = system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt=v1), 1)
    assert (again["version"], again["unchanged"]) == (1, True)
    with pytest.raises(ValueError):
        system.projects.configure_department_settings(
            project_id, "engineering", ModelSelection(department_prompt="   \n"), 1)
    with pytest.raises(DepartmentSettingConflict) as conflict:
        system.projects.configure_department_settings(
            project_id, "engineering", ModelSelection(department_prompt="过期编辑"), 0)
    assert conflict.value.current["version"] == 1 and conflict.value.current["text"] == v1
    with pytest.raises(ValueError):
        system.projects.configure_department_settings(
            project_id, "finance", ModelSelection(department_prompt=v1), 1)
    assert len(_project_events(system, project_id, ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED)) == 1

    _work_item_a, run_a = system.projects.start_work_item(project_id, "v1 期间的事项")
    run = system.project(run_a)
    # run 内没有部门 Prompt 的副本，只记项目部门设置的版本
    assert not hasattr(run, "department_prompts")
    assert run.prompt_config_versions == {"product": 0, "engineering": 1, "quality": 0}
    assert system.run_until_stop(run_a).phase == "DONE"
    system.projects.settle(run_a)
    requests_a = [json.loads(system.artifacts.get_for_run(run_a, ArtifactRef(**manifest.request_ref)))
                  for manifest in system.project(run_a).manifests if manifest.department == "engineering"]
    assert requests_a and all(v1 in request["input"][0]["content"] for request in requests_a)

    v2 = "工程 Prompt v2：保留重复行改为只保留首次出现。"
    saved = system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt=v2), 1)
    assert saved["version"] == 2
    project = system.projects.projection(project_id)
    assert [item.version for item in project.department_setting_history] == [1, 2]
    assert project.department_settings["engineering"].text == v2 and project.department_settings["product"].version == 0
    _work_item_b, run_b = system.projects.start_work_item(project_id, "v2 期间的事项")
    run = system.project(run_b)
    assert run.prompt_config_versions["engineering"] == 2
    assert system.run_until_stop(run_b).phase == "DONE"
    engineering_b = [request for request in adapter.invocations if request.department == "engineering"][-1]
    assert v2 in engineering_b.input_items[0]["content"] and v1 not in engineering_b.input_items[0]["content"]
    # 已经结束的 run 的请求正文不变；项目部门设置只随新请求生效
    later_a = [json.loads(system.artifacts.get_for_run(run_a, ArtifactRef(**manifest.request_ref)))
               for manifest in system.project(run_a).manifests if manifest.department == "engineering"]
    assert later_a == requests_a
    assert system.projects.read_department_setting(project_id, "engineering")["version"] == 2


def test_department_setting_without_prompt_returns_to_the_builtin_default(data_dir):
    # 不写入部门 Prompt（工单 #741：客户端的「使用内置默认 Prompt」走的就是这条）：
    # 这一段不再由本项目写入，文字回到内置默认 Prompt，设置记录的版本继续往下走
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("Prompts", GOAL)
    default_text = DEFINITIONS.role("engineering").prompt
    written = system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt="工程 Prompt v1：直接写代码。"), 0)
    assert written["department_setting_configured"] is True
    reset = system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(), 1)
    assert (reset["version"], reset["department_setting_configured"]) == (2, False)
    assert reset["text"] == default_text
    # 读到的设置与投影一致：这一段的内容是内置默认，且不再由本项目写入
    current = system.projects.read_department_setting(project_id, "engineering")
    assert current["text"] == default_text and current["department_setting_configured"] is False
    assert system.projects.projection(project_id).department_settings["engineering"].configured_prompt is False

# ---------------------------------------------------------------------------
# §13.9 归档项目只读

def test_archived_project_rejects_writes_until_restored(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("Archive", GOAL)
    system.projects.archive(project_id)
    system.projects.archive(project_id)
    assert len(_project_events(system, project_id, ProjectEventType.PROJECT_ARCHIVED)) == 1
    assert system.projects.projection(project_id).archived is True
    with pytest.raises(ProjectArchivedError):
        system.projects.start_work_item(project_id, "归档后的事项")
    with pytest.raises(ProjectArchivedError):
        system.projects.configure_department_settings(
            project_id, "product", ModelSelection(department_prompt="新 Prompt"), 0)
    with pytest.raises(ProjectArchivedError):
        system.projects.record_material(project_id, "归档后的材料")
    with pytest.raises(ProjectArchivedError):
        system.projects.rename(project_id, "改名")
    assert system.store.list_run_ids() == []
    assert system.projects.list_projects() == []
    assert [item.project_id for item in system.projects.list_projects(include_archived=True)] == [project_id]
    system.projects.restore(project_id)
    system.projects.restore(project_id)
    assert len(_project_events(system, project_id, ProjectEventType.PROJECT_RESTORED)) == 1
    assert system.projects.projection(project_id).archived is False
    material_id = system.projects.record_material(project_id, "恢复后的材料", department="engineering")
    assert system.projects.projection(project_id).materials[0].material_id == material_id
    _work_item_id, run_id = system.projects.start_work_item(project_id, "恢复后的事项")
    assert system.project(run_id).project_id == project_id

def test_in_progress_work_item_blocks_archive_and_materials(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("Busy", GOAL)
    system.projects.start_work_item(project_id, "进行中")
    before = [event.event_id for event in system.store.list_project_events(project_id)]
    with pytest.raises(WorkItemInProgressError):
        system.projects.archive(project_id)
    with pytest.raises(WorkItemInProgressError):
        system.projects.record_material(project_id, "不该写入")
    after = system.store.list_project_events(project_id)
    assert [event.event_id for event in after] == before
    project = system.projects.projection(project_id)
    assert project.archived is False and project.materials == []
    assert project.work_items[0].status == "in_progress"

# ---------------------------------------------------------------------------
# §13.10 D-H：记录原文不产生 run 事件

def test_material_recording_creates_no_run_events(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("Materials", GOAL)
    material_id = system.projects.record_material(project_id, "  用户口述的一段想法\r\n第二行  ", department="product")
    assert material_id.startswith("material_")
    project = system.projects.projection(project_id)
    assert project.active_work_item_id is None and project.work_items == []
    material = project.materials[0]
    assert material.text == "  用户口述的一段想法\r\n第二行  " and material.department == "product"
    assert system.artifacts.get_for_run(project_id, ArtifactRef(**material.material_ref)) == material.text.encode("utf-8")
    assert system.store.list_run_ids() == []
    assert [event.type for event in system.store.list_project_events(project_id)] == [
        ProjectEventType.PROJECT_REGISTERED, ProjectEventType.MATERIAL_RECORDED,
    ]
    with pytest.raises(ValueError):
        system.projects.record_material(project_id, "   ")
    with pytest.raises(ValueError):
        system.projects.record_material(project_id, "x", department="finance")

# ---------------------------------------------------------------------------
# §5 / §6 / §7 / §8 其他约定

def test_project_context_text_is_deterministic_and_ordered(data_dir):
    system = _system(data_dir, _release_script("交付摘要"))
    project_id = system.projects.register("文本", "长期目标\n第二行")
    project = system.projects.projection(project_id)
    first = project_context_text(project, "首个事项")
    assert first == project_context_text(project, "首个事项")
    assert first == (
        "项目：文本\n长期目标：长期目标\n第二行\n当前采用成果：无（这是项目的第一个事项）\n"
        "已采纳事项：无\n仍有效的决定：无\n本事项：首个事项"
    )
    work_item_id, run_id = system.projects.start_work_item(project_id, "首个事项\n更多说明")
    assert system.projects.projection(project_id).work_items[0].title == "首个事项"
    system.run_until_stop(run_id)
    system.projects.settle(run_id)
    project = system.projects.projection(project_id)
    adoption = project.current_adoption
    source = system.project(run_id)
    second = project_context_text(project, "第二个事项", source)
    assert second == project_context_text(project, "第二个事项", source)
    assert second == (
        "项目：文本\n长期目标：长期目标\n第二行\n"
        f"当前采用成果：来自事项「首个事项」（run {run_id}，采纳 {adoption.adoption_id}）：交付摘要；"
        f"文件：src/echo.py；检查：smoke；已知风险：无。本 run 工作区已从该成果的完整封存恢复，digest {adoption.code_tree_digest}。\n"
        '已采纳事项：\n1. "首个事项" — 交付摘要\n'
        "仍有效的决定：\n"
        f"产品合同 r1 hash {source.product_spec.content_hash}\n"
        "目标：build an echo CLI\n"
        "要求：print the given argument to stdout\n"
        "边界：do not read files\n"
        "约束：single file implementation\n"
        "验收：running the program with a word prints that word\n"
        "致命条件：non-zero exit on valid input\n"
        "非目标：network access\n"
        "有效决定：无\n"
        "本事项：第二个事项"
    )
    assert project.work_item(work_item_id).run_id == run_id

def test_second_work_item_project_part_includes_source_spec(data_dir):
    system = _system(data_dir, [*_release_script("v1"), *_release_script("v2", files=_v2_files())])
    project_id = system.projects.register("决定", GOAL)
    _work_1, run_1 = system.projects.start_work_item(project_id, "第一步")
    first = system.artifacts.get_for_run(run_1, ArtifactRef(**system.project(run_1).project_context_ref)).decode("utf-8")
    assert "仍有效的决定：无" in first
    system.run_until_stop(run_1)
    system.projects.settle(run_1)
    spec = system.project(run_1).product_spec
    _work_2, run_2 = system.projects.start_work_item(project_id, "第二步")
    second = system.artifacts.get_for_run(run_2, ArtifactRef(**system.project(run_2).project_context_ref)).decode("utf-8")
    assert "仍有效的决定：无" not in second
    assert spec.goal in second
    assert spec.requirements[0] in second

def test_work_item_title_defaults_to_first_line_truncated(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("Title", GOAL)
    long_line = "很长的标题" * 20
    work_item_id, _run_id = system.projects.start_work_item(project_id, f"\n\n  {long_line}\n第二行")
    item = system.projects.projection(project_id).work_item(work_item_id)
    assert item.title == long_line[:40] and len(item.title) == 40
    work_item_2, _ = system.projects.start_work_item(project_id, "正文", title="显式标题")
    assert system.projects.projection(project_id).work_item(work_item_2).title == "显式标题"

def test_work_item_derived_fields_follow_the_run(data_dir):
    script = [
        product_spec(),
        delivery_turn(summary="v1"),
        review_turn("rework_engineering", "命名不符", defects=[{"severity": "minor", "summary": "naming"}]),
        delivery_turn(summary="v2", files={"src/echo.py": "print('v2')\n"}),
        review_turn("release", "ok"),
    ]
    system = _system(data_dir, script)
    project_id = system.projects.register("Derived", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "带返工的事项", max_cycles=16)
    item = system.projects.projection(project_id).work_item(work_item_id)
    assert (item.status, item.department, item.phase, item.cycle_count) == ("in_progress", "product", "PRODUCT_SPEC", 0)
    assert item.last_handoff["from"] == "CREATED" and item.last_handoff["to"] == "PRODUCT_SPEC"
    assert item.pending_question == system.project(run_id).waiting_reason
    assert system.projects.projection(project_id).active_work_item_id == work_item_id
    system.activate_once(run_id)
    system.activate_once(run_id)
    item = system.projects.projection(project_id).work_item(work_item_id)
    assert item.status == "in_progress"
    assert system.run_until_stop(run_id).phase == "DONE"
    item = system.projects.projection(project_id).work_item(work_item_id)
    assert item.status == "released_unsettled" and item.department is None and item.phase == "DONE"
    assert item.last_handoff["to"] == "DONE" and item.last_handoff["seq"] > 0
    assert [entry["verdict"] for entry in item.rework] == ["rework_engineering"]
    assert item.rework[0]["summary"] == "命名不符" and item.rework[0]["seq"] > 0
    assert system.projects.settle_pending(project_id)[0].type == ProjectEventType.DELIVERABLE_ADOPTED
    item = system.projects.projection(project_id).work_item(work_item_id)
    assert item.status == "adopted" and item.pending_question is None
    recent = _overview(system, project_id)["recent"]
    assert recent[0]["kind"] == "project" and recent[0]["type"] == ProjectEventType.DELIVERABLE_ADOPTED
    assert any(entry["kind"] == "loop" and entry["type"] == EventType.RUN_DONE and entry["run_id"] == run_id for entry in recent)
    assert all(entry["position"] > later["position"] for entry, later in zip(recent, recent[1:]))

def _overview(system, project_id):
    from harness.projects import project_overview

    return project_overview(system.store, system.projects.projection(project_id))

def test_work_item_start_failure_is_recorded_and_project_stays_usable(data_dir):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("Failure", GOAL)
    with pytest.raises(ValueError, match="max_cycles"):
        system.projects.start_work_item(project_id, "会失败的事项", max_cycles=0)
    project = system.projects.projection(project_id)
    failed = project.work_items[0]
    assert failed.status == "not_started" and "max_cycles" in failed.start_error
    assert failed.department is None and failed.last_handoff is None
    assert [event.type for event in system.store.list_project_events(project_id)][1:] == [
        ProjectEventType.WORK_ITEM_CREATED, ProjectEventType.WORK_ITEM_START_FAILED,
    ]
    assert system.store.list_run_ids() == []
    assert system.projects.settle(failed.run_id) is None
    work_item_id, run_id = system.projects.start_work_item(project_id, "正常的事项")
    assert system.projects.projection(project_id).work_item(work_item_id).status == "in_progress"
    assert system.project(run_id).work_item_id == work_item_id

def test_settle_pending_recovers_release_left_unsettled(data_dir):
    system = _system(data_dir, [*_release_script("v1"), *_release_script("v2", files=_v2_files())])
    project_id = system.projects.register("Recover", GOAL)
    _work_item_1, run_1 = system.projects.start_work_item(project_id, "第一步")
    system.run_until_stop(run_1)
    assert system.projects.projection(project_id).work_items[0].status == "released_unsettled"
    # 进程在 RUN_DONE 与结算之间中断：下一次创建事项前补跑结算，基线即为最新成果。
    _work_item_2, run_2 = system.projects.start_work_item(project_id, "第二步")
    project = system.projects.projection(project_id)
    assert project.work_items[0].status == "adopted"
    assert system.project(run_2).baseline["adoption_id"] == project.current_adoption.adoption_id
    assert system.project(run_2).workspace_digest == project.current_adoption.code_tree_digest
    assert system.projects.settle_pending(project_id) == []

def test_archived_unsettled_release_settles_on_read_not_on_start(data_dir):
    system = _system(data_dir, _release_script("v1"))
    project_id = system.projects.register("SettleArchive", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "第一步")
    system.run_until_stop(run_id)
    assert system.projects.projection(project_id).work_items[0].status == "released_unsettled"
    system.projects.archive(project_id)
    before = [event.event_id for event in system.store.list_project_events(project_id)]
    with pytest.raises(ProjectArchivedError):
        system.projects.start_work_item(project_id, "归档后新事项")
    after_start = system.store.list_project_events(project_id)
    assert [event.event_id for event in after_start] == before
    project = system.projects.projection(project_id)
    assert [item.work_item_id for item in project.work_items] == [work_item_id]
    assert project.work_items[0].status == "released_unsettled" and project.current_adoption is None
    written = system.projects.settle_pending(project_id)
    assert len(written) == 1 and written[0].type == ProjectEventType.DELIVERABLE_ADOPTED
    project = system.projects.projection(project_id)
    assert project.archived is True and project.current_adoption.run_id == run_id
    assert project.work_items[0].status == "adopted"

def test_release_touching_kernel_paths_is_not_adopted_without_approval(data_dir):
    # 受控内核设计说明第 4.2 节：交付改动了内核清单里的路径时，结算不自动采纳，
    # 而是发出内核修改决定请求，材料附改动的路径与差异
    kernel_files = {"src/echo.py": "LOWER = True\n", "harness/bounds.py": "# 被交付改动的内核文件\n"}
    system = _system(data_dir, _kernel_release_script(files=kernel_files))
    project_id = system.projects.register("Kernel", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "改动了内核")
    system.run_until_stop(run_id)
    system.projects.settle(run_id)
    project = system.projects.projection(project_id)
    assert project.current_adoption is None
    assert project.work_item(work_item_id).status == "released_unsettled"
    assert _project_events(system, project_id, ProjectEventType.DELIVERABLE_ADOPTED) == []
    [decision] = _open_decisions(system)
    assert decision.kind == "kernel_modification" and decision.blocks == "run"
    assert decision.status == "open"
    assert decision.request["delivery_run_id"] == run_id
    assert decision.request["kernel_paths"] == ["harness/bounds.py"]
    assert "+# 被交付改动的内核文件" in decision.request["diff"]
    assert [option["id"] for option in decision.request["options"]] == ["approve", "reject"]
    # 幂等：重复结算不再发出第二个决定请求
    assert system.projects.settle(run_id) is None
    assert len(_open_decisions(system)) == 1

def test_release_outside_kernel_paths_is_adopted_as_before(data_dir):
    # 没有落在内核清单里的改动照常采纳，不产生决定请求
    system = _system(data_dir, _release_script("v1", files=_v2_files()))
    project_id = system.projects.register("Ordinary", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "常规改动")
    system.run_until_stop(run_id)
    system.projects.settle(run_id)
    project = system.projects.projection(project_id)
    assert project.current_adoption.run_id == run_id
    assert _open_decisions(system) == []

def test_kernel_modification_approved_adopts_the_delivery(data_dir):
    system = _system(data_dir, _kernel_release_script(files={"harness/bounds.py": "# 批准以后采纳\n"}))
    project_id = system.projects.register("Approve", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "批准内核改动")
    system.run_until_stop(run_id)
    system.projects.settle(run_id)
    [decision] = _open_decisions(system)
    assert _answer(system, decision.decision_id, "approve") is None
    project = system.projects.projection(project_id)
    assert project.current_adoption.run_id == run_id
    assert project.current_adoption.previous_adoption_id is None
    assert project.work_item(work_item_id).status == "adopted"
    assert _open_decisions(system) == []
    # 批准以后再结算：同一个 run 已有请求，不再发出第二个请求，也不重复采纳
    assert system.projects.settle(run_id) is None
    assert len(_project_events(system, project_id, ProjectEventType.DELIVERABLE_ADOPTED)) == 1

def test_kernel_modification_rejected_leaves_the_delivery_unadopted(data_dir):
    system = _system(data_dir, _kernel_release_script(files={"harness/bounds.py": "# 拒绝以后不采纳\n"}))
    project_id = system.projects.register("Reject", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "拒绝对内核的改动")
    system.run_until_stop(run_id)
    system.projects.settle(run_id)
    [decision] = _open_decisions(system)
    assert _answer(system, decision.decision_id, "reject") is None
    project = system.projects.projection(project_id)
    assert project.current_adoption is None
    assert project.work_item(work_item_id).status == "released_unsettled"
    assert _project_events(system, project_id, ProjectEventType.DELIVERABLE_ADOPTED) == []
    assert _open_decisions(system) == []
    assert system.projects.settle(run_id) is None

def test_source_run_from_another_project_cannot_be_baseline(data_dir):
    system = _system(data_dir, _release_script("v1"))
    project_a = system.projects.register("A", GOAL)
    _work_a, run_a = system.projects.start_work_item(project_a, "A的事项")
    system.run_until_stop(run_a)
    system.projects.settle(run_a)
    adoption = system.projects.projection(project_a).current_adoption
    project_b = system.projects.register("B", GOAL)
    system.writes.append(project_stream(project_b), NewProjectEvent(ProjectEventType.DELIVERABLE_ADOPTED, {
        "adoption_id": adoption.adoption_id, "work_item_id": adoption.work_item_id,
        "run_id": adoption.run_id, "delivery_event_id": adoption.delivery_event_id,
        "qa_event_id": adoption.qa_event_id, "tree_ref": adoption.tree_ref,
        "code_tree_digest": adoption.code_tree_digest, "summary": adoption.summary,
        "files": list(adoption.files), "check_names": list(adoption.check_names),
        "known_risks": list(adoption.known_risks), "previous_adoption_id": None,
    }, actor="system"))
    assert system.projects.projection(project_b).current_adoption.run_id == run_a
    with pytest.raises(ValueError):
        system.projects.start_work_item(project_b, "偷树")
    assert system.projects.projection(project_b).work_items == []

def test_mismatched_run_ownership_does_not_derive_work_item(data_dir):
    system = _system(data_dir, happy_script())
    project_a = system.projects.register("A", GOAL)
    work_a, run_a = system.projects.start_work_item(project_a, "A的事项")
    assert system.projects.projection(project_a).work_item(work_a).status == "in_progress"
    project_b = system.projects.register("B", GOAL)
    system.writes.append(project_stream(project_b), NewProjectEvent(ProjectEventType.WORK_ITEM_CREATED, {
        "work_item_id": "wi_forged", "title": "伪造", "text": "伪造", "run_id": run_a, "baseline": None,
        "project_context_ref": {"kind": "project_context"},
        "prompt_config_versions": {"product": 0, "engineering": 0, "quality": 0},
        "max_cycles": 8, "run_time_limit_sec": 600, "context_window": 32_000,
    }, actor="user:local"))
    forged = system.projects.projection(project_b).work_item("wi_forged")
    assert forged.status == "not_started"
    assert forged.phase is None and forged.department is None
    assert forged.last_handoff is None and forged.pending_question is None
    real = system.projects.projection(project_a).work_item(work_a)
    assert real.status == "in_progress" and real.phase is not None

def test_register_validates_and_stores_goal_artifact(data_dir):
    system = _system(data_dir, happy_script())
    with pytest.raises(ValueError):
        system.projects.register("", GOAL)
    with pytest.raises(ValueError):
        system.projects.register("名字", "  ")
    project_id = system.projects.register("名字", GOAL)
    assert project_id.startswith("proj_")
    project = system.projects.projection(project_id)
    assert (project.name, project.goal, project.source) == ("名字", GOAL, "idea")
    assert project.goal_ref["media_type"] == "text/markdown"
    assert system.artifacts.get_for_run(project_id, ArtifactRef(**project.goal_ref)).decode("utf-8") == GOAL
    assert project.created_at == project.updated_at and project.stream_version == 1
    assert {department: config.version for department, config in project.department_settings.items()} == {
        "product": 0, "engineering": 0, "quality": 0,
    }
    with pytest.raises(ProjectNotFoundError):
        system.projects.projection("proj_missing")

def test_cli_project_list_and_show(data_dir, capsys):
    system = _system(data_dir, happy_script())
    project_id = system.projects.register("CLI", GOAL)
    archived_id = system.projects.register("Archived", GOAL)
    system.projects.archive(archived_id)
    version = system.projects.projection(project_id).stream_version
    assert main(["project", "list", "--data-dir", str(data_dir)]) == 0
    listed = json.loads(capsys.readouterr().out)
    rows = listed["data"]["projects"]
    assert [row["project_id"] for row in rows] == [project_id]
    assert rows[0]["work_item_count"] == 0 and rows[0]["current_adoption"] is None
    assert listed["position"] >= 1
    assert main(["project", "list", "--archived", "--data-dir", str(data_dir)]) == 0
    archived_rows = json.loads(capsys.readouterr().out)["data"]["projects"]
    assert {row["project_id"] for row in archived_rows} == {project_id, archived_id}
    assert main(["project", "show", project_id, "--data-dir", str(data_dir)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["data"]["name"] == "CLI" and shown["data"]["goal"] == GOAL
    assert shown["data"]["version"] == version

# 建 run 时冻结参数（工单 #1189；规则登记与参数 docs/design/rules-and-parameters.md「参数怎样成为带版本的数据」；总图第二节「定义」、第四节「定义」缝）：
# 一组运行参数与 3 条可见范围在建 run 时取样，写进 run_created 的一个字典字段，这个 run 全程读那份取值。
# 这个文件查六件事：
# 1. run_created 里的冻结字典、全局参数版本、项目覆盖来源、事项已解析限额与定义版本对得上同一份快照；
# 2. 建 run 之后改参数只作用于之后创建的 run；已有 run 的事件重放与重新启动都读冻结值，不取现值；
# 3. 旧事件没有冻结字典时按定义初值解释，不取现值；
# 4. 每个冻结的运行参数各有一条行为用例：参数改了，新 run 的行为跟着变，旧 run 不变；
# 5. 每个角色一条可见范围在建 run 时冻结（工单 #1401：名字跟着角色编号走），词表以外的取值在参数校验处被拒绝；
#    三个部门都改名的定义下，每个角色的可见范围参数照常冻结、照常生效；
# 6. 中断（事项已提交、run 未创建）与定义版本差异两条恢复路径。
#
# 层：模块层（全部用例只用到工作区文件、单次 activate_once 与重新加载恢复，按 docs/design/test-pyramid.md「三层的定义」
# 登记为模块层；启动真实子进程等待时间限额到期的两条用例见 test_frozen_parameter_timeouts.py）。守 R1（边界与冻结）与 R2（run_created 的交换字段）。

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from harness import parameters
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.context import frozen_visibility
from harness.definitions import DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR, DefinitionError, load_definitions
from harness.direct import DIRECT_TIGHTENING, SINGLE_ROLE_DIRECT
from harness.event_store import run_stream
from harness.models import EventType, ProjectEventType, RunProjection
from harness.parameters import (
    FROZEN_PARAMETERS, NOT_WIRED_REASONS, ParameterNotWiredError, ParameterOutOfBoundsError, frozen_run_parameters,
)
from harness.projection import project_run
from harness.proposals import product_spec
from harness.tightening import WATCHED_OUTPUTS
from harness.providers.call import ModelResponse
from harness.runtime import SEVERAL_ROLES_DIRECT, LoopSystem
from harness.tests.helpers import pinned_input_tokens, summary_message
from harness.validation import TightenRequest
from harness.write_path import NewEvent

GOAL = "print the argument in uppercase"


def _call(identity: str, tool: str, /, **arguments: object) -> dict[str, object]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": tool,
            "arguments": json.dumps(arguments)}


def _respond(*calls: dict[str, object]):
    # 这一次模型回答给出这些工具调用（每次请求取一条脚本项）
    def respond(request):
        return ModelResponse(output=list(calls))
    return respond


def _system(tmp_path, script=None) -> LoopSystem:
    # 不给 step_limits：上限按 run 创建时冻结的参数构造（给了就整份照用，绕开冻结）
    return LoopSystem.for_testing(tmp_path, FakeAdapter(script or {"product": [product_spec()]}))


def _created(system: LoopSystem, run_id: str) -> dict:
    return next(event for event in system.store.list_events(run_id)
                if event.type == EventType.RUN_CREATED).payload


def _frozen(system: LoopSystem, run_id: str) -> dict:
    return _created(system, run_id)["parameters"]


def _tool_called(system: LoopSystem, run_id: str, identity: str) -> dict:
    # tool_called 的载荷把结果存成 output_ref，结果本身按 input_item 里的三项 JSON 取回
    event = next(event for event in system.store.list_events(run_id)
                 if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == identity)
    return json.loads(event.payload["input_item"]["output"])


def _set(system: LoopSystem, name: str, value: object) -> None:
    system.set_parameter(name, value, reason="核对冻结", modified_by="user:test")


def test_run_created_freezes_the_run_parameters_and_their_sources(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("冻结", GOAL)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)

    frozen = _frozen(system, run_id)
    created = _created(system, run_id)
    current = parameters.current_values(system.store)

    assert sorted(frozen["values"]) == sorted(FROZEN_PARAMETERS)
    assert frozen["values"] == {name: current[name] for name in FROZEN_PARAMETERS}
    assert frozen["global_version"] == parameters.current_version(system.store)
    assert frozen["project_overrides"] == {name: parameters.value_for_project(system.store, project_id, name)
                                           for name in parameters.PROJECT_PARAMETERS}
    assert frozen["item_limits"] == {
        "max_cycles": created["max_cycles"],
        "run_time_limit_sec": created["run_time_limit_sec"],
        "check_timeout_sec": created["check_timeout_sec"],
        "onboarding.round_time_limit_sec": parameters.value_for_project(
            system.store, project_id, "onboarding.round_time_limit_sec"),
    }
    assert frozen["definitions_version"] == created["definitions_version"] == DEFINITIONS.version
    system.close()


def test_a_parameter_change_after_creation_keeps_the_run_frozen_and_changes_the_next_one(tmp_path):
    # 整张单的核心：建 run 之后改一次全局参数，已有 run 的事件重放与重新启动都还是冻结的那个数
    system = _system(tmp_path)
    project_id = system.projects.register("冻结", GOAL)
    _item, first_run = system.projects.start_work_item(project_id, GOAL)
    frozen_before = _frozen(system, first_run)["values"]
    assert frozen_before["max_model_steps"] == DEFINITIONS.rule_value("max_model_steps")
    assert frozen_before["tool_output_limit"] == DEFINITIONS.rule_value("tool_output_limit")

    _set(system, "max_model_steps", 7)
    _set(system, "tool_output_limit", 900)
    _item, second_run = system.projects.start_work_item(project_id, "second item")
    system.close()

    reopened = LoopSystem.for_testing(system.data_dir, FakeAdapter({"product": [product_spec()]}))
    first = project_run(reopened.store, first_run)
    second = project_run(reopened.store, second_run)
    replayed = reopened.replay(first_run)
    assert frozen_run_parameters(first) == frozen_run_parameters(replayed)
    assert frozen_run_parameters(first)["max_model_steps"] == DEFINITIONS.rule_value("max_model_steps")
    assert frozen_run_parameters(first)["tool_output_limit"] == DEFINITIONS.rule_value("tool_output_limit")
    assert (frozen_run_parameters(second)["max_model_steps"],
            frozen_run_parameters(second)["tool_output_limit"]) == (7, 900)
    assert first.parameters["global_version"] != second.parameters["global_version"]
    assert first.parameters["global_version"] != parameters.current_version(reopened.store)
    reopened.close()


def test_old_events_without_the_frozen_dictionary_use_the_definition_initial_values(tmp_path):
    # 旧 run 的事件没有冻结字典：按定义初值解释，不取现值（改了参数以后也一样）
    system = _system(tmp_path)
    _set(system, "max_provider_attempts", 5)
    projection = RunProjection()
    initial = parameters.initial_values()

    assert frozen_run_parameters(projection) == {name: initial[name] for name in FROZEN_PARAMETERS}
    assert frozen_run_parameters(projection)["max_provider_attempts"] == DEFINITIONS.rule_value("max_provider_attempts")
    assert frozen_visibility(projection, "quality") == tuple(DEFINITIONS.role("quality").visibility)
    system.close()


def test_tool_output_limit_sizes_the_read_range_page_of_each_run_by_its_frozen_value(tmp_path):
    # read_range 的一页按输出上限收缩：上限小的一页装得少，上限大的装得多；两个 run 各按自己冻结的那个数
    many_lines = "\n".join(f"MATCH {index:03d} " + "y" * 80 for index in range(400))
    script = {"product": [_respond(_call("range-small", "read_range", path="many.txt",
                                                                     start_line=1, end_line=400)),
                          product_spec(),
                          _respond(_call("range-large", "read_range", path="many.txt",
                                                                     start_line=1, end_line=400)),
                          product_spec()]}
    system = _system(tmp_path, script)
    project_id = system.projects.register("输出上限", GOAL)
    _set(system, "tool_output_limit", 200)
    _item, first_run = system.projects.start_work_item(project_id, GOAL)
    system.workspace(first_run).write_file("many.txt", many_lines + "\n")
    system.activate_once(first_run)
    _set(system, "tool_output_limit", 4000)
    _item, second_run = system.projects.start_work_item(project_id, "second")
    system.workspace(second_run).write_file("many.txt", many_lines + "\n")
    system.activate_once(second_run)

    small = _tool_called(system, first_run, "range-small")["output"]
    large = _tool_called(system, second_run, "range-large")["output"]
    assert small["truncated"] is True and large["truncated"] is True
    assert len(small["lines"]) < len(large["lines"])
    system.close()


def test_max_model_steps_comes_from_the_frozen_value(tmp_path):
    script = {"product": [_respond(_call("read-1", "read_file", path="a.txt")),
                          _respond(_call("read-2", "read_file", path="a.txt")), product_spec()]}
    system = _system(tmp_path, script)
    project_id = system.projects.register("步数上限", GOAL)
    _set(system, "max_model_steps", 1)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    system.workspace(run_id).write_file("a.txt", "hello\n")
    result = system.activate_once(run_id)

    assert (result.status, result.stop_reason) == ("paused", "model_steps_exhausted")
    assert _tool_called(system, run_id, "read-1")["ok"] is True
    assert not any((event.payload or {}).get("id") == "read-2"
                   for event in system.store.list_events(run_id) if event.type == EventType.TOOL_CALLED)
    system.close()


def test_tool_call_required_limit_comes_from_the_frozen_value(tmp_path):
    script = {"product": [FakeTurn(transcript="只回复文字"), FakeTurn(transcript="再一次只回复文字")]}
    system = _system(tmp_path, script)
    project_id = system.projects.register("提醒上限", GOAL)
    _set(system, "tool_call_required_limit", 1)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    result = system.activate_once(run_id)

    assert (result.status, result.stop_reason) == ("paused", "no_tool_call")
    reminders = [event for event in system.store.list_events(run_id)
                 if event.type == EventType.TOOL_CALL_REQUIRED]
    assert len(reminders) == 1
    system.close()


def test_provider_attempts_and_retry_delays_come_from_the_frozen_values(tmp_path):
    script = {"product": [ProviderError("temporary", retryable=True), product_spec()]}
    system = _system(tmp_path, script)
    project_id = system.projects.register("重试", GOAL)
    _set(system, "max_provider_attempts", 2)
    _set(system, "retry_initial_delay_sec", 0.1)
    _set(system, "retry_max_delay_sec", 1.0)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    system.activate_once(run_id)

    [retry] = [event for event in system.store.list_events(run_id)
               if event.type == EventType.MODEL_RETRY_SCHEDULED]
    assert (retry.payload["max_attempts"], retry.payload["delay_sec"]) == (2, 0.1)
    system.close()


def test_compaction_stalled_limit_comes_from_the_frozen_value(tmp_path):
    # 整理一直不推进（摘要为空）：冻结算到的次数上限是 1，第一次不推进就进入待恢复，说明里写的是冻结的那个数
    def respond(request):
        if request.purpose == "compaction":
            return summary_message(request, "")
        return ModelResponse(output=[_call(f"read-{request.step_id}", "read_file", path="large.txt")])

    script = {department: [respond] * 50 for department in ("product", "engineering", "quality")}
    system = _system(tmp_path, script)
    project_id = system.projects.register("整理上限", GOAL)
    _set(system, "compaction.stalled_limit", 1)
    measure = system.create_run("Original intent", context_window=1_000_000)
    run_id = system.create_run("Original intent", context_window=pinned_input_tokens(system, measure) + 1600)
    system.workspace(run_id).write_file("large.txt", "TOOL_OUTPUT " * 340)
    system.activate_once(run_id)

    payloads = json.dumps([event.payload for event in system.store.list_events(run_id)], ensure_ascii=False)
    assert "compaction.stalled_limit=1" in payloads
    system.close()


def test_visibility_is_frozen_and_values_outside_the_vocabulary_are_rejected(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("可见范围", GOAL)
    _set(system, "roles.quality.visibility", ["current_delivery_spec", "qa_defects"])
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    projection = project_run(system.store, run_id)

    assert _frozen(system, run_id)["values"]["roles.quality.visibility"] == ["current_delivery_spec", "qa_defects"]
    assert frozen_visibility(projection, "quality") == ("current_delivery_spec", "qa_defects")
    assert frozen_visibility(projection, "engineering") == tuple(DEFINITIONS.role("engineering").visibility)
    with pytest.raises(ParameterOutOfBoundsError, match="词表"):
        _set(system, "roles.quality.visibility", ["not_a_declared_value"])
    system.close()


# 三个部门都改名的一份测试定义（与 test_department_names.py 同一做法：定义里表示部门的字符串与按部门分段的
# 规则条目名一起换）
RENAMED_DEPARTMENTS = {"product": "requirements", "engineering": "build", "quality": "inspection"}
DELIVERY_SUMMARY = "SECRET_DELIVERY_SUMMARY"


def _renamed(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {_renamed_key(key, old, new): _renamed(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed(item, old, new) for item in value]
    return new if value == old else value


def _renamed_key(key: Any, old: str, new: str) -> Any:
    if not isinstance(key, str):
        return key
    return ".".join(new if part == old else part for part in key.split("."))


def _renamed_definitions(tmp_path: Path, names: dict[str, str],
                         visibility: dict[str, list[str]] | None = None):
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))
        for old, new in names.items():
            content = _renamed(content, old, new)
        (directory / path.name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    for role, values in (visibility or {}).items():
        # 改名后的角色的可见范围写在两处：角色的取值与规则登记的同一项（加载时核对两处相同）
        roles = json.loads((directory / "roles.json").read_text(encoding="utf-8"))
        roles[role]["visibility"] = values
        (directory / "roles.json").write_text(json.dumps(roles, ensure_ascii=False, indent=2), encoding="utf-8")
        rules = json.loads((directory / "rules.json").read_text(encoding="utf-8"))
        rules[f"roles.{role}.visibility"]["value"] = values
        (directory / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def test_every_role_of_a_renamed_definition_freezes_its_own_visibility_parameter(tmp_path):
    # 验收第 3 条（工单 #1401）：三个部门都改名的定义下，每个角色的可见范围参数照常冻结、照常生效。
    # 冻结字典里每个角色各有一条，名字跟着角色编号走；装配读的就是这一份（frozen_visibility 按角色取），
    # 核验角色改成只给事实的取值时，冻结的与装配读到的都是它
    renamed = _renamed_definitions(tmp_path, RENAMED_DEPARTMENTS,
                                    visibility={"inspection": ["delivery_facts"]})
    system = LoopSystem.for_testing(tmp_path / "runs", FakeAdapter({}),
                                    forms={DEFAULT_FORM: (renamed, WATCHED_OUTPUTS)})
    project_id = system.projects.register("改名", GOAL)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)

    frozen = _frozen(system, run_id)["values"]
    projection = project_run(system.store, run_id)
    for role in renamed.departments:
        assert frozen[f"roles.{role}.visibility"] == list(renamed.role(role).visibility), role
        assert frozen_visibility(projection, role, renamed) == renamed.role(role).visibility, role
    assert frozen["roles.inspection.visibility"] == ["delivery_facts"]
    system.close()


def test_a_missing_run_is_rebuilt_with_recovery_time_values_only_for_unresolved_parameters(tmp_path):
    # 中断：事项已提交、run 未创建；期间改全局参数，重启补建以后事项的事实不变，
    # 未解析为事项实际限额的参数取恢复时现值
    system = _system(tmp_path)
    project_id = system.projects.register("补建", GOAL)
    real_create_run = system.orchestrator.create_run

    def crash_before_run(*args, **kwargs):
        raise RuntimeError("进程在 run 创建之前终止")

    system.orchestrator.create_run = crash_before_run
    with pytest.raises(RuntimeError, match="进程在 run 创建之前终止"):
        system.projects.start_work_item(project_id, GOAL)
    system.orchestrator.create_run = real_create_run
    item = system.projects.projection(project_id).work_items[0]
    run_id = item.run_id
    assert system.store.stream_events(run_stream(run_id), after_version=0) == []
    _set(system, "max_model_steps", 11)
    system.close()

    reopened = LoopSystem.for_testing(system.data_dir, FakeAdapter({"product": [product_spec()]}))
    assert reopened.recovered_work_item_runs == [run_id]
    created = _created(reopened, run_id)
    item_after = reopened.projects.projection(project_id).work_item(item.work_item_id)

    assert (item_after.work_item_id, item_after.text, item_after.title) == (item.work_item_id, item.text, item.title)
    assert item_after.baseline == item.baseline and item_after.snapshot == item.snapshot
    assert created["max_cycles"] == item_after.max_cycles == item.max_cycles
    assert created["run_time_limit_sec"] == item_after.run_time_limit_sec == item.run_time_limit_sec
    assert created["parameters"]["values"]["max_model_steps"] == 11
    assert created["parameters"]["values"]["tool_call_required_limit"] == DEFINITIONS.rule_value(
        "tool_call_required_limit")
    assert created["parameters"]["global_version"] == parameters.current_version(reopened.store)
    assert created["parameters"]["item_limits"]["max_cycles"] == item.max_cycles
    assert created["definitions_version"] == DEFINITIONS.version
    reopened.close()


def test_a_missing_run_is_rebuilt_from_the_frozen_organization_after_the_release_changes(tmp_path, monkeypatch):
    # 事项创建时冻结了整份合成结果（工单 #1517）：发布里这一份形态的内容后来变了，补建这个 run 时仍按事项
    # 冻结的那一份（版本与工件引用都记在这一版的定义里），不读发布里换过内容的那一份。
    # 补建与「定义版本不同」的决定请求是两件事：这条看的是补建
    from harness.projects import ProjectService

    system = _system(tmp_path)
    project_id = system.projects.register("补建升级", GOAL)
    real_create_run = system.orchestrator.create_run

    def crash_before_run(*args, **kwargs):
        raise RuntimeError("进程在 run 创建之前终止")

    system.orchestrator.create_run = crash_before_run
    with pytest.raises(RuntimeError, match="进程在 run 创建之前终止"):
        system.projects.start_work_item(project_id, GOAL)
    system.orchestrator.create_run = real_create_run
    item = system.projects.projection(project_id).work_items[0]
    # 事项创建时冻结的整份合成结果与它的版本（工单 #1517）：补建时按这一份，不按发布现在的内容
    [work_item_created] = [event for event in system.store.list_project_events(project_id)
                           if event.type == ProjectEventType.WORK_ITEM_CREATED]
    item_created_version = work_item_created.payload["definitions_version"]
    system.close()

    startup_rebuild = ProjectService.create_missing_work_item_runs_on_startup
    monkeypatch.setattr(ProjectService, "create_missing_work_item_runs_on_startup", lambda self: [])
    reopened = LoopSystem.for_testing(system.data_dir, FakeAdapter({"product": [product_spec()]}))
    assert reopened.store.stream_events(run_stream(item.run_id), after_version=0) == []

    class _OtherDefinitions:
        version = "sha256:other-definitions"

        def __getattr__(self, name: str):
            return getattr(DEFINITIONS, name)

    # 这一份形态在发布里换了内容（版本不同）：事项有它冻结的那一份，补建照常进行，run 记下的是冻结的版本
    monkeypatch.setitem(reopened.orchestrator._forms, DEFAULT_FORM,
                        replace(reopened.orchestrator._forms[DEFAULT_FORM], definitions=_OtherDefinitions()))
    assert startup_rebuild(reopened.projects) == [item.run_id]
    [created] = reopened.store.stream_events(run_stream(item.run_id), after_version=0)
    assert created.type == EventType.RUN_CREATED
    assert created.payload["definitions_version"] == item_created_version
    assert created.payload["definitions_version"] == DEFINITIONS.version != _OtherDefinitions.version
    assert created.payload["definitions_ref"]["kind"] == "item_definitions"
    assert reopened.projects.projection(project_id).work_item(item.work_item_id) is not None
    reopened.close()


def _copy_form_definitions(source: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    for path in source.glob("*.json"):
        (target / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_ask_user_tool_and_rules_load_and_validate_bounds_across_all_forms(tmp_path):
    # R1（测试按三环留）：ask_user 工具定义、规则默认值与范围边界在三份形态定义中保持有效
    forms = (
        (DEFAULT_FORM, DEFINITIONS_DIR),
        (SINGLE_ROLE_DIRECT, DEFINITIONS_DIR / "forms" / SINGLE_ROLE_DIRECT),
        (SEVERAL_ROLES_DIRECT, DEFINITIONS_DIR / "forms" / SEVERAL_ROLES_DIRECT),
    )
    for form_name, form_dir in forms:
        defs = load_definitions(form_dir)
        assert "ask_user" in defs.tools
        tool = defs.tools["ask_user"]
        assert tool.kind == "host"
        assert tool.proposal is None
        schema = tool.parameters
        assert schema["additionalProperties"] is False
        assert tuple(schema["required"]) == ("questions",)
        assert "note" in schema["properties"]
        question_schema = schema["properties"]["questions"]["items"]
        assert question_schema["additionalProperties"] is False
        assert set(question_schema["required"]) == {"id", "question", "options", "recommended", "rationale"}
        option_schema = question_schema["properties"]["options"]["items"]
        assert option_schema["additionalProperties"] is False
        assert set(option_schema["required"]) == {"id", "label"}
        assert "description" in option_schema["properties"]

        # R1：三份形态全部角色（change 与 onboarding）均已配备 ask_user 工具（工单 #1801）
        for role in defs.departments:
            assert "ask_user" in defs.tools_for(role, "change")
            assert "ask_user" in defs.tools_for(role, "onboarding")

        questions_rule = defs.rules["ask_user.max_questions_per_round"]
        rounds_rule = defs.rules["ask_user.max_rounds_per_input"]
        assert (questions_rule.value, questions_rule.bounds, questions_rule.kind, questions_rule.form) == (
            4, (1, 8), "parameter", "boundary")
        assert (rounds_rule.value, rounds_rule.bounds, rounds_rule.kind, rounds_rule.form) == (
            2, (0, 5), "parameter", "boundary")

        for rule_name, invalid_value in (
            ("ask_user.max_questions_per_round", 0),
            ("ask_user.max_questions_per_round", 9),
            ("ask_user.max_rounds_per_input", -1),
            ("ask_user.max_rounds_per_input", 6),
        ):
            copy_dir = _copy_form_definitions(form_dir, tmp_path / f"{form_name}-{rule_name}-{invalid_value}")
            rules_doc = json.loads((copy_dir / "rules.json").read_text(encoding="utf-8"))
            rules_doc[rule_name]["value"] = invalid_value
            (copy_dir / "rules.json").write_text(json.dumps(rules_doc, ensure_ascii=False, indent=2), encoding="utf-8")
            with pytest.raises(DefinitionError):
                load_definitions(copy_dir)

        boundary_dir = _copy_form_definitions(form_dir, tmp_path / f"{form_name}-bounds-ok")
        rules_doc = json.loads((boundary_dir / "rules.json").read_text(encoding="utf-8"))
        rules_doc["ask_user.max_questions_per_round"]["value"] = 8
        rules_doc["ask_user.max_rounds_per_input"]["value"] = 0
        (boundary_dir / "rules.json").write_text(json.dumps(rules_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        assert load_definitions(boundary_dir).rule_value("ask_user.max_questions_per_round") == 8
        assert load_definitions(boundary_dir).rule_value("ask_user.max_rounds_per_input") == 0

    for name, valid in (
        ("ask_user.max_questions_per_round", 1),
        ("ask_user.max_questions_per_round", 8),
        ("ask_user.max_rounds_per_input", 0),
        ("ask_user.max_rounds_per_input", 5),
    ):
        assert parameters.check_bounds(name, valid) == valid
    for name, bad in (
        ("ask_user.max_questions_per_round", 0),
        ("ask_user.max_questions_per_round", 9),
        ("ask_user.max_rounds_per_input", -1),
        ("ask_user.max_rounds_per_input", 6),
    ):
        with pytest.raises(ParameterOutOfBoundsError):
            parameters.check_bounds(name, bad)


def test_new_runs_freeze_ask_user_parameters_and_old_snapshots_preserve_values_with_defaults(tmp_path):
    # R2（测试按三环留）：新建 run 冻结 ask_user 参数、已接入参数可按界限改写且不改变已建 run 的冻结值，
    # 旧快照缺这两项时保留既有冻结值并从定义初值补齐
    for name in ("ask_user.max_questions_per_round", "ask_user.max_rounds_per_input"):
        assert name in FROZEN_PARAMETERS
        assert NOT_WIRED_REASONS.get(name) == ""
        assert parameters.wired(name)

    system = _system(tmp_path)
    _set(system, "max_model_steps", 7)
    first_run = system.create_run("冻结提问参数")

    _set(system, "ask_user.max_questions_per_round", 6)
    _set(system, "ask_user.max_rounds_per_input", 4)
    _set(system, "max_model_steps", 11)
    second_run = system.create_run("再次更改步数与提问参数后的 run")

    reopened = _system(tmp_path)
    first = frozen_run_parameters(project_run(reopened.store, first_run))
    second = frozen_run_parameters(project_run(reopened.store, second_run))
    assert (first["max_model_steps"], first["ask_user.max_questions_per_round"], first["ask_user.max_rounds_per_input"]) == (7, 4, 2)
    assert (second["max_model_steps"], second["ask_user.max_questions_per_round"], second["ask_user.max_rounds_per_input"]) == (11, 6, 4)

    created_payload = _created(reopened, first_run)
    assert created_payload["parameters"]["values"]["ask_user.max_questions_per_round"] == 4
    assert created_payload["parameters"]["values"]["ask_user.max_rounds_per_input"] == 2
    legacy_values = {
        key: value
        for key, value in created_payload["parameters"]["values"].items()
        if key not in ("ask_user.max_questions_per_round", "ask_user.max_rounds_per_input")
    }
    legacy_payload = {
        **created_payload,
        "parameters": {**created_payload["parameters"], "values": legacy_values},
    }
    legacy_run = "run-legacy-ask-user-snapshot"
    reopened.orchestrator._transact(
        run_stream(legacy_run),
        lambda tx: tx.append(NewEvent(
            EventType.RUN_CREATED,
            actor="system",
            department="product",
            state_before="running",
            state_after="running",
            payload=legacy_payload,
        )),
        expected_version=0,
        definitions=DEFINITIONS,
    )
    legacy_frozen = frozen_run_parameters(project_run(reopened.store, legacy_run))
    assert legacy_frozen["max_model_steps"] == 7
    assert legacy_frozen["ask_user.max_questions_per_round"] == DEFINITIONS.rule_value("ask_user.max_questions_per_round")
    assert legacy_frozen["ask_user.max_rounds_per_input"] == DEFINITIONS.rule_value("ask_user.max_rounds_per_input")

    custom = parameters.frozen_values({
        "values": {"max_model_steps": 5, "ask_user.max_questions_per_round": 6, "ask_user.max_rounds_per_input": 4},
    })
    assert (custom["max_model_steps"], custom["ask_user.max_questions_per_round"], custom["ask_user.max_rounds_per_input"]) == (5, 6, 4)
    assert parameters.frozen_values({"values": {"max_model_steps": 5}})["max_model_steps"] == 5
    assert parameters.frozen_values({"values": {"max_model_steps": 5}})["ask_user.max_questions_per_round"] == 4
    assert parameters.frozen_values(None)["ask_user.max_questions_per_round"] == 4
    assert parameters.frozen_values({"values": {}})["ask_user.max_rounds_per_input"] == 2

    reopened.close()
    system.close()


def _definitions_granting_ask_user(source: Path, target: Path, roles: tuple[str, ...]) -> Any:
    copied = _copy_form_definitions(source, target)
    roles_doc = json.loads((copied / "roles.json").read_text(encoding="utf-8"))
    for role in roles:
        if "ask_user" not in roles_doc[role]["tools"]:
            roles_doc[role]["tools"].append("ask_user")
    (copied / "roles.json").write_text(json.dumps(roles_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    work_items_doc = json.loads((copied / "work_items.json").read_text(encoding="utf-8"))
    departments = work_items_doc["kinds"]["change"]["departments"]
    for role in roles:
        dept_cfg = departments.get(role)
        if isinstance(dept_cfg, dict) and "tools" in dept_cfg and "ask_user" not in dept_cfg["tools"]:
            dept_cfg["tools"].append("ask_user")
    (copied / "work_items.json").write_text(json.dumps(work_items_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(copied)


def test_ask_branch_tightening_excludes_ask_user_for_watched_outputs_and_direct_routing(tmp_path):
    # R2（测试按三环留）：询问分支会话收紧剔除 ask_user 并拒绝直接向用户提问
    default_defs = _definitions_granting_ask_user(
        DEFINITIONS_DIR, tmp_path / "default-with-ask-user", ("product", "engineering", "quality"))
    direct_defs = _definitions_granting_ask_user(
        DEFINITIONS_DIR / "forms" / SEVERAL_ROLES_DIRECT,
        tmp_path / "direct-with-ask-user",
        ("product", "engineering"),
    )

    for tightening, defs, roles in (
        (WATCHED_OUTPUTS, default_defs, ("product", "engineering", "quality")),
        (DIRECT_TIGHTENING, direct_defs, ("product", "engineering")),
    ):
        main_projection = RunProjection(run_id="run-main", status="running", kind="change")
        for role in roles:
            assert "ask_user" in tightening.offered(TightenRequest(
                department=role, state=main_projection, session_id="main-session", definitions=defs,
            ))
            assert tightening.tool(TightenRequest(
                department=role,
                state=main_projection,
                session_id="main-session",
                definitions=defs,
                tool={"name": "ask_user", "args": {}},
            )).reason is None

            branch_projection = RunProjection(
                run_id="run-branch",
                status="running",
                kind="change",
                ask_stack=[{
                    "requester": "product" if role != "product" else "engineering",
                    "recipient": role,
                    "question": "clarify scope",
                    "origin_session_id": "origin-session",
                    "branch_session_id": "branch-session",
                }],
            )
            offered = tightening.offered(TightenRequest(
                department=role, state=branch_projection, session_id="branch-session", definitions=defs,
            ))
            assert "ask_user" not in offered
            assert "answer" in offered
            rejected = tightening.tool(TightenRequest(
                department=role,
                state=branch_projection,
                session_id="branch-session",
                definitions=defs,
                tool={"name": "ask_user", "args": {}},
            ))
            assert rejected.reason


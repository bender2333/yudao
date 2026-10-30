# 建 run 时冻结参数（工单 #1189；规则登记与参数设计说明第 3 节；总图第二节「定义」、第四节「定义」缝）：
# 10 个参数与 3 条可见范围在建 run 时取样，写进 run_created 的一个字典字段，这个 run 全程读那份取值。
# 这个文件查六件事：
# 1. run_created 里的冻结字典、全局参数版本、项目覆盖来源、事项已解析限额与定义版本对得上同一份快照；
# 2. 建 run 之后改参数只作用于之后创建的 run；已有 run 的事件重放与重新启动都读冻结值，不取现值；
# 3. 旧事件没有冻结字典时按定义初值解释，不取现值；
# 4. 10 个参数各自有一条行为用例：参数改了，新 run 的行为跟着变，旧 run 不变；
# 5. 3 条可见范围在建 run 时冻结，词表以外的取值在参数校验处被拒绝；
# 6. 中断（事项已提交、run 未创建）与定义版本差异两条恢复路径。
#
# 层：集成层（有两条用例要起真实进程验证命令与检查的时限上限；其余用例只用到工作区文件与一次激活，
# 整个文件按测试分层设计说明第 2 节登记为其中最高的一层）。守 R1（边界与冻结）与 R2（run_created 的交换字段）。

from __future__ import annotations

import json

import pytest

from harness import parameters
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.context import frozen_visibility
from harness.definitions import DEFINITIONS
from harness.event_store import run_stream
from harness.models import EventType, RunProjection
from harness.parameters import FROZEN_PARAMETERS, ParameterOutOfBoundsError, frozen_run_parameters
from harness.projection import project_run
from harness.proposals import product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import pinned_input_tokens, summary_message

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


def test_run_created_freezes_the_thirteen_values_and_their_sources(tmp_path):
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


def test_bash_timeouts_come_from_the_frozen_values(tmp_path):
    slow = "python -c \"import time; time.sleep(30)\""
    script = {"product": [_respond(_call("slow-default", "bash", command=slow)),
                          _respond(_call("slow-max", "bash", command=slow, timeout_sec=100)), product_spec()]}
    system = _system(tmp_path, script)
    project_id = system.projects.register("命令时限", GOAL)
    _set(system, "bash_timeout_default_sec", 1)
    _set(system, "bash_timeout_max_sec", 10)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    system.activate_once(run_id)

    assert _tool_called(system, run_id, "slow-default")["output"]["status"] == "timeout"
    # 请求里的 100 秒按冻结的上限压到 2 秒
    assert _tool_called(system, run_id, "slow-max")["output"]["status"] == "timeout"
    system.close()


def test_check_timeout_max_comes_from_the_frozen_value(tmp_path):
    script = {"product": [_respond(_call("slow-check", "run_check", name="slow", command="python sleep.py",
                                         timeout_sec=100)),
                          product_spec()]}
    system = _system(tmp_path, script)
    project_id = system.projects.register("检查时限", GOAL)
    _set(system, "check_timeout_max_sec", 10)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    system.workspace(run_id).write_file("sleep.py", "import time\ntime.sleep(30)\n")
    system.activate_once(run_id)

    assert "check timed out after 10s" in _tool_called(system, run_id, "slow-check")["output"]["summary"]
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


def test_a_missing_run_is_not_rebuilt_after_the_item_definition_version_changes(tmp_path, monkeypatch):
    # 升级以后事项记录的定义版本与当前不同：启动不写使用新定义的 run_created，事项记录与原始起点保留
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
    system.close()

    startup_rebuild = ProjectService.create_missing_work_item_runs_on_startup
    monkeypatch.setattr(ProjectService, "create_missing_work_item_runs_on_startup", lambda self: [])
    reopened = LoopSystem.for_testing(system.data_dir, FakeAdapter({"product": [product_spec()]}))
    assert reopened.store.stream_events(run_stream(item.run_id), after_version=0) == []

    class _OtherDefinitions:
        version = "sha256:other-definitions"

        def __getattr__(self, name: str):
            return getattr(DEFINITIONS, name)

    monkeypatch.setattr("harness.projects.DEFINITIONS", _OtherDefinitions())
    assert startup_rebuild(reopened.projects) == []
    assert reopened.store.stream_events(run_stream(item.run_id), after_version=0) == []
    assert reopened.projects.projection(project_id).work_item(item.work_item_id) is not None
    reopened.close()

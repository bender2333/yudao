import sqlite3
import time

import pytest

from harness.adapters.fake import FakeAdapter
from harness.event_store import run_stream
from harness.models import json_dumps
from harness.projection import replay_run, saved_project
from harness.proposals import product_spec
from harness.providers.call import ModelResponse
from harness.public_tree import capture_public_tree
from harness.replay_check import PROJECTION_REASON, ReplayIntegrityError
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, system_on_copy

# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次运行并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上改写与检查。数据来自真实运行，登记为集成层。


@pytest.fixture(scope="module")
def saved_project_and_bare_run(tmp_path_factory):
    directory = tmp_path_factory.mktemp("project-and-bare")
    system = LoopSystem.for_testing(directory / "data", FakeAdapter(happy_script() + happy_script()))
    project_id = system.projects.register("项目", "逐行文本处理工具")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "事项")
    system.run_until_stop(run_id)
    system.projects.settle(run_id)
    bare = system.create_run("bare run")
    system.run_until_stop(bare)
    system.close()
    return directory / "data", project_id, [run_id, bare]


@pytest.fixture
def project_and_bare_run(saved_project_and_bare_run, tmp_path):
    saved, project_id, runs = saved_project_and_bare_run
    return system_on_copy(saved, tmp_path / "data"), project_id, runs



def _delete_saved_projections(data_dir):
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        connection.execute("DELETE FROM projections")
        connection.commit()
    finally:
        connection.close()


def test_replaying_after_deleting_saved_projections_gives_the_same_projections(project_and_bare_run):
    system, project_id, runs = project_and_bare_run
    before = {run_id: system.project(run_id).to_dict() for run_id in runs}
    project = system.projects.projection(project_id).to_dict()
    saved = saved_project(system.store, project_id).to_dict()
    trees = {run_id: capture_public_tree(system.workspace(run_id).root).digest for run_id in runs}
    data_dir = system.data_dir
    end = system.store.end_position()
    system.close()
    _delete_saved_projections(data_dir)

    # 重启时补建缺失的投影；脚本为空的模型任何调用都会失败
    adapter = FakeAdapter([])
    restarted = LoopSystem.for_testing(data_dir, adapter)
    assert {run_id: restarted.project(run_id).to_dict() for run_id in runs} == before
    assert saved_project(restarted.store, project_id).to_dict() == saved
    assert restarted.projects.projection(project_id).to_dict() == project
    # 重放不调用模型，不执行工具，不写入事件
    assert adapter.invocations == []
    assert {run_id: capture_public_tree(restarted.workspace(run_id).root).digest for run_id in runs} == trees
    assert restarted.store.end_position() == end
    restarted.close()


def test_rebuild_replaces_one_saved_projection_with_the_replayed_projection(project_and_bare_run):
    system, _project_id, runs = project_and_bare_run
    run_id = runs[1]
    before = system.project(run_id).to_dict()
    rebuilt = system.writes.rebuild(run_stream(run_id))
    assert rebuilt.to_dict() == before == system.project(run_id).to_dict()
    assert system.store.projection(run_stream(run_id)).position == system.store.list_events(run_id)[-1].position


def test_replay_check_reports_a_saved_projection_that_differs_from_the_replay(project_and_bare_run):
    system, _project_id, runs = project_and_bare_run
    target, other = runs[1], runs[0]
    # 把另一个 run 的投影存成这个 run 的投影
    connection = sqlite3.connect(system.data_dir / "events.sqlite")
    try:
        connection.execute("UPDATE projections SET state = (SELECT state FROM projections WHERE stream = ?) "
                           "WHERE stream = ?", (run_stream(other), run_stream(target)))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ReplayIntegrityError) as failed:
        system.replay(target)
    assert failed.value.reason == PROJECTION_REASON
    assert system.replay(other).to_dict() == system.project(other).to_dict()


def _run_with_tool_calls(data_dir, count):
    # 一次激活：第一步的回答调用 count 次只读工具，第二步提交产品规格。事件随工具调用增加，投影的大小不变
    def reads(call):
        return ModelResponse(output=[{"id": f"list-{index}", "call_id": f"list-{index}", "type": "function_call",
                                      "name": "list_files", "arguments": json_dumps({})} for index in range(count)])

    system = LoopSystem.for_testing(data_dir, FakeAdapter([reads, product_spec()]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    return system, run_id


def _read_time(system, run_id):
    samples = []
    for _ in range(40):
        started = time.perf_counter()
        system.project(run_id)
        samples.append(time.perf_counter() - started)
    return min(samples)


def test_reading_the_run_state_does_not_slow_down_with_ten_times_the_history(tmp_path):
    small_system, small = _run_with_tool_calls(tmp_path / "small", 3)
    large_system, large = _run_with_tool_calls(tmp_path / "large", 110)
    small_events, large_events = small_system.store.list_events(small), large_system.store.list_events(large)
    assert len(large_events) >= 10 * len(small_events)
    # 工具次数另含提交产品规格的一次
    assert large_system.project(large).tool_count == 111 and small_system.project(small).tool_count == 4
    # 保存的投影与重放结果相同，读取的是保存的投影
    assert large_system.project(large).to_dict() == replay_run(large_system.store, large).to_dict()
    assert _read_time(large_system, large) < 3 * _read_time(small_system, small)

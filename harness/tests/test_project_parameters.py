# 项目级参数（迭代底座 B3，工单 #351）：从 HTTP 提交带项目的 parameter.set，经真实运行的服务核对：
# 一个项目设置了检查时限以后，之后创建的 run 按它检查，其他项目与没有设置过的项目仍按全局现值；
# 建档的单轮上限按项目设置以后，这个项目的建档事项用它；run 创建时冻结，之后改项目值不影响已创建的 run；
# 不能按项目设置的参数、超界取值、不存在的项目都被拒绝，不写事件。

from __future__ import annotations

import time
import uuid

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.event_store import catalog_stream, project_stream
from harness.definitions import DEFINITIONS
from harness.models import CatalogEventType, EventType, ProjectEventType
from harness.parameters import frozen_check_timeout as parameters_frozen
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import happy_script
from harness.tests.onboarding_project import ONBOARDING_GOAL, onboarding_source

class _Opened:
    # 服务生命周期中建立的应用层；测试经它直接读取事件日志核对结果
    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, FakeAdapter(happy_script())),
                                  registry=DEFAULT_REGISTRY)
        self.applications.append(application)
        return application

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system

    @property
    def store(self):
        return self.system.store

def _post(client, command: str, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})

def _project_parameter_events(opened: _Opened, project_id: str) -> list:
    return [event for event in opened.store.stream_events(project_stream(project_id))
            if event.type == ProjectEventType.PARAMETER_SET]

def _global_parameter_events(opened: _Opened) -> list:
    return [event for event in opened.store.stream_events(catalog_stream())
            if event.type == CatalogEventType.PARAMETER_SET]

def _settle(opened: _Opened, run_id: str) -> None:
    # 事项的执行在接口进程的事件循环中作为任务运行；等它结束（停在阻塞处或终止）
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        task = opened.system.orchestrator.work_item_execution(run_id)
        if task is None or task.done():
            return
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not stop")

def _run_created(opened: _Opened, run_id: str) -> dict:
    [event] = [event for event in opened.store.list_events(run_id)
               if event.type == EventType.RUN_CREATED]
    return event.payload

def _check_timeout_of(opened: _Opened, run_id: str) -> int:
    # run 冻结的检查时限：run_created 事件里的取值，与执行环境看到的是同一个值
    return parameters_frozen(opened.store, run_id)

def _environment_timeout_of(opened: _Opened, run_id: str) -> int:
    return opened.system.environment(run_id)._check_timeout_sec

def test_project_check_timeout_applies_to_runs_created_afterwards(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        left = _post(client, "project.create", name="左", goal="做一个命令行回显工具。")
        assert left.status_code == 200, left.text
        left_id = left.json()["refs"]["project_id"]
        right = _post(client, "project.create", name="右", goal="做另一个命令行工具。")
        assert right.status_code == 200, right.text
        right_id = right.json()["refs"]["project_id"]

        before = _post(client, "work_item.create", project_id=left_id, text="全局时限下的功能。")
        assert before.status_code == 200, before.text
        before_run = before.json()["refs"]["run_id"]
        assert _check_timeout_of(opened, before_run) == DEFINITIONS.rule_value("check_timeout_sec")
        _settle(opened, before_run)

        changed = _post(client, "parameter.set", name="check_timeout_sec", value=120,
                        reason="这个项目的检查跑得快", modified_by="user:test", project_id=left_id)
        assert changed.status_code == 200, changed.text

        [event] = _project_parameter_events(opened, left_id)
        payload = event.payload
        assert payload["name"] == "check_timeout_sec"
        assert (payload["old_value"], payload["new_value"]) == (600, 120)
        # 旧请求的 modified_by 仍被接受，事件里的提出者与历史以认证身份为准（工单 #1262）
        assert (payload["reason"], payload["modified_by"]) == ("这个项目的检查跑得快", "user:local")
        assert payload["bounds"] == [1, 86400]
        assert _global_parameter_events(opened) == []

        after = _post(client, "work_item.create", project_id=left_id, text="项目时限下的功能。")
        assert after.status_code == 200, after.text
        after_run = after.json()["refs"]["run_id"]
        # 之后创建的 run 用项目值，之前创建的 run 保持冻结的全局值
        assert _check_timeout_of(opened, after_run) == 120
        assert _run_created(opened, after_run)["check_timeout_sec"] == 120
        assert _environment_timeout_of(opened, after_run) == 120
        assert _check_timeout_of(opened, before_run) == 600
        assert _environment_timeout_of(opened, before_run) == 600
        _settle(opened, after_run)

        # 另一个项目没有设置过，仍按全局现值
        other = _post(client, "work_item.create", project_id=right_id, text="另一个项目的功能。")
        assert other.status_code == 200, other.text
        other_run = other.json()["refs"]["run_id"]
        assert _check_timeout_of(opened, other_run) == 600
        # 项目流的参数事件带 project_parameter_set 种类，与目录流的 parameter_set 是两个不同流的事件种类
        assert event.type == "project_parameter_set"


def test_global_value_stays_the_fallback_for_projects_without_a_value(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project = _post(client, "project.create", name="参数", goal="做一个命令行回显工具。")
        assert project.status_code == 200, project.text
        project_id = project.json()["refs"]["project_id"]

        changed = _post(client, "parameter.set", name="check_timeout_sec", value=60,
                        reason="全局给短一点", modified_by="user:test")
        assert changed.status_code == 200, changed.text

        run = _post(client, "work_item.create", project_id=project_id, text="项目没有设置过。")
        assert run.status_code == 200, run.text
        run_id = run.json()["refs"]["run_id"]
        assert _check_timeout_of(opened, run_id) == 60
        assert _project_parameter_events(opened, project_id) == []

def test_project_onboarding_round_limit_sets_the_work_item_limit(data_dir, tmp_path):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        source = onboarding_source(tmp_path / "source")
        accepted = _post(client, "project.onboard", name="已有项目", goal=ONBOARDING_GOAL,
                         source_name="src", source_path=str(source))
        assert accepted.status_code == 200, accepted.text
        project_id = accepted.json()["refs"]["project_id"]
        first_run = accepted.json()["refs"]["run_id"]
        # 第一轮在项目建立之前取值：没有项目值，按全局现值
        assert opened.system.project(first_run).run_time_limit_sec == 7200
        _settle(opened, first_run)

        changed = _post(client, "parameter.set", name="onboarding.round_time_limit_sec", value=1800,
                        reason="这个项目一轮读得快", modified_by="user:test", project_id=project_id)
        assert changed.status_code == 200, changed.text
        [event] = _project_parameter_events(opened, project_id)
        payload = event.payload
        assert payload["name"] == "onboarding.round_time_limit_sec"
        assert (payload["old_value"], payload["new_value"]) == (7200, 1800)
        assert payload["bounds"] == [600, 86400]
        # 这个项目重新开始建档以后，新一轮建档事项的单轮上限按项目值（工单 #351 验收第 2 条）
        restarted = _post(client, "onboarding.restart", project_id=project_id, source_name="src")
        assert restarted.status_code == 200, restarted.text
        restart_run = restarted.json()["refs"]["run_id"]
        assert opened.system.project(restart_run).kind == "onboarding"
        assert opened.system.project(restart_run).run_time_limit_sec == 1800
        # 其他项目没有设置过，仍按全局现值
        other_id = opened.system.projects.register("另一个项目", "做另一个命令行工具。")
        assert opened.system.projects.onboarding_round_limit(other_id) == 7200

def test_project_parameter_rejects_names_bounds_and_unknown_projects(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project = _post(client, "project.create", name="参数", goal="做一个命令行回显工具。")
        assert project.status_code == 200, project.text
        project_id = project.json()["refs"]["project_id"]
        end = opened.store.end_position()

        not_project_level = _post(client, "parameter.set", name="max_cycles", value=4,
                                  reason="试一个不能按项目设置的参数", modified_by="user:test",
                                  project_id=project_id)
        assert not_project_level.status_code == 409, not_project_level.text
        assert not_project_level.json()["reason"] == "not_found"

        out_of_bounds = _post(client, "parameter.set", name="check_timeout_sec", value=0,
                              reason="试一个超界的值", modified_by="user:test", project_id=project_id)
        assert out_of_bounds.status_code == 409, out_of_bounds.text
        assert out_of_bounds.json()["reason"] == "out_of_bounds"

        unknown = _post(client, "parameter.set", name="check_timeout_sec", value=120,
                        reason="试一个不存在的项目", modified_by="user:test", project_id="proj_missing")
        assert unknown.status_code == 409, unknown.text
        assert unknown.json()["reason"] == "not_found"

        assert _project_parameter_events(opened, project_id) == []
        assert _global_parameter_events(opened) == []
        assert opened.store.end_position() == end

# 参数命令与参数事件（工单 #349）：从 HTTP 提交 parameter.set，经真实运行的服务读规则登记；
# 限额冻结与停止行为直接用系统核对。覆盖六条验收：界内修改后新 run 用新限额、旧 run 保持冻结值、
# 超界拒绝不写事件、改回原值后历史列两次修改、停止的 run 不因调大而继续、事件载荷带双版本。
# 工单 #643 的接入标记与拒绝：登记每条带 wired 与未接入原因，未接入的条目在全局与项目两个入口
# 都以 not_wired 拒绝，说明与登记逐字相同，两条流都不写事件。

from __future__ import annotations

import time
import uuid

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.event_store import catalog_stream, project_stream
from harness.definitions import DEFINITIONS
from harness.models import CatalogEventType, EventType, ProjectEventType
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import happy_script


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


def _parameter_events(opened: _Opened) -> list:
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


def test_parameter_set_changes_limits_for_new_runs_and_keeps_old_runs_frozen(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project = _post(client, "project.create", name="参数", goal="做一个命令行回显工具。")
        assert project.status_code == 200, project.text
        project_id = project.json()["refs"]["project_id"]

        first = _post(client, "work_item.create", project_id=project_id, text="做第一个回显功能。")
        assert first.status_code == 200, first.text
        first_run = first.json()["refs"]["run_id"]
        _settle(opened, first_run)

        changed = _post(client, "parameter.set", name="run_time_limit_sec", value=3600,
                        reason="测试给短一点", modified_by="user:test")
        assert changed.status_code == 200, changed.text

        [event] = _parameter_events(opened)
        payload = event.payload
        assert payload["name"] == "run_time_limit_sec"
        assert (payload["old_value"], payload["new_value"]) == (7200, 3600)
        assert (payload["reason"], payload["modified_by"]) == ("测试给短一点", "user:test")
        assert payload["bounds"] == [600, 86400]
        version = payload["parameters_version"]
        assert version == opened.system.parameters_version()

        second = _post(client, "work_item.create", project_id=project_id, text="做第二个回显功能。")
        assert second.status_code == 200, second.text
        second_run = second.json()["refs"]["run_id"]
        _settle(opened, second_run)

        first_created = _run_created(opened, first_run)
        second_created = _run_created(opened, second_run)
        # 修改以前建立的 run 保持创建时的限额
        assert (first_created["run_time_limit_sec"], first_created["max_cycles"]) == (7200, 999999)
        assert first_created["parameters_version"] != version
        # 修改以后建立的 run 按新的参数限额建立，参数版本是修改以后的那一版
        assert second_created["run_time_limit_sec"] == 3600
        assert second_created["parameters_version"] == version
        # 两个版本独立：定义的版本不变，参数的版本按修改改变
        assert first_created["definitions_version"] == DEFINITIONS.version
        assert second_created["definitions_version"] == DEFINITIONS.version

        # 运行中的请求与裁决记录都带这两个版本
        for event in opened.store.list_events(second_run):
            if event.type in (EventType.MODEL_REQUESTED, EventType.PROPOSAL_SUBMITTED,
                              EventType.PROPOSAL_REJECTED):
                assert event.payload["definitions_version"] == DEFINITIONS.version, event.type
                assert event.payload["parameters_version"] == version, event.type

        # 参数修改前后两个 run 的重放都与保存的投影一致
        for run_id in (first_run, second_run):
            checked = client.get("/api/queries/replay.check", params={"run_id": run_id})
            assert checked.status_code == 200, checked.text
            assert checked.json()["data"]["consistent"] is True


def test_parameter_set_out_of_bounds_rejects_without_an_event(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project = _post(client, "project.create", name="参数", goal="做一个命令行回显工具。")
        assert project.status_code == 200, project.text
        end = opened.store.end_position()

        rejected = _post(client, "parameter.set", name="run_time_limit_sec", value=60,
                         reason="太小了", modified_by="user:test")
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["reason"] == "out_of_bounds"
        assert "600" in rejected.json()["message"] and "86400" in rejected.json()["message"]
        # 拒绝不写事件，事件日志末尾不动
        assert _parameter_events(opened) == [] and opened.store.end_position() == end

        missing = _post(client, "parameter.set", name="no_such_parameter", value=1,
                        reason="没有这个", modified_by="user:test")
        assert missing.status_code == 409 and missing.json()["reason"] == "not_found"

        # structure 类条目不是参数，不能用参数命令修改
        structure = _post(client, "parameter.set", name="loop.nesting_max", value=2,
                          reason="结构不能改", modified_by="user:test")
        assert structure.status_code == 409 and structure.json()["reason"] == "not_found"
        assert _parameter_events(opened) == [] and opened.store.end_position() == end


def test_setting_a_parameter_back_records_two_changes_and_restores_the_limit(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project = _post(client, "project.create", name="参数", goal="做一个命令行回显工具。")
        assert project.status_code == 200, project.text
        project_id = project.json()["refs"]["project_id"]

        assert _post(client, "parameter.set", name="run_time_limit_sec", value=3600,
                     reason="先改小", modified_by="user:alice").status_code == 200
        assert _post(client, "parameter.set", name="run_time_limit_sec", value=7200,
                     reason="改回原值", modified_by="user:bob").status_code == 200

        registry = client.get("/api/queries/rules.registry")
        assert registry.status_code == 200, registry.text
        entry = next(item for item in registry.json()["data"]["rules"]
                     if item["name"] == "run_time_limit_sec")
        # 改回原值：现值回到 7200，两次修改都在历史里，各带修改者、原值、新值与理由
        assert entry["value"] == 7200
        assert [(change["old_value"], change["new_value"]) for change in entry["changes"]] == [
            (7200, 3600), (3600, 7200)]
        assert [change["modified_by"] for change in entry["changes"]] == ["user:alice", "user:bob"]
        assert [change["reason"] for change in entry["changes"]] == ["先改小", "改回原值"]

        third = _post(client, "work_item.create", project_id=project_id, text="做第三个回显功能。")
        assert third.status_code == 200, third.text
        third_run = third.json()["refs"]["run_id"]
        _settle(opened, third_run)
        # 撤回以后建立的 run 按原限额建立
        assert _run_created(opened, third_run)["run_time_limit_sec"] == 7200


def test_rules_registry_reports_current_values_and_untouched_parameters_keep_their_definition(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        assert _post(client, "project.create", name="参数",
                     goal="做一个命令行回显工具。").status_code == 200
        assert _post(client, "parameter.set", name="max_cycles", value=12,
                     reason="轮数限制调小", modified_by="user:test").status_code == 200

        registry = client.get("/api/queries/rules.registry")
        assert registry.status_code == 200, registry.text
        entries = {item["name"]: item for item in registry.json()["data"]["rules"]}
        assert entries["max_cycles"]["value"] == 12
        assert len(entries["max_cycles"]["changes"]) == 1
        # 已经接入行为的条目改动生效，登记里原因为空（工单 #643）
        assert entries["max_cycles"]["wired"] is True
        assert entries["max_cycles"]["not_wired_reason"] == ""
        # 未接入的条目照常列出，原因写在登记里，参数命令拒绝修改
        assert entries["execution.slots"]["wired"] is False
        assert entries["execution.slots"]["not_wired_reason"]
        # 可见范围条目：现值是字符串列表，界限约束条目数，没有修改记录
        visibility = entries["roles.engineering.visibility"]
        assert visibility["value"] == DEFINITIONS.rule_value("roles.engineering.visibility")
        assert visibility["changes"] == []
        # 结构类条目取定义的默认值，没有修改记录
        assert entries["loop.nesting_max"]["changes"] == []


def test_unwired_parameters_are_rejected_in_both_scopes_with_the_registry_reason(data_dir):
    # 守 R2（对外合同：命令的拒绝原因与登记字段）与 R3 的阶段二要求：没有接入行为的参数不许改，
    # 拒绝说明与服务端的登记逐字一致，页面不另写文字（工单 #643、#726）
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project = _post(client, "project.create", name="参数", goal="做一个命令行回显工具。")
        assert project.status_code == 200, project.text
        project_id = project.json()["refs"]["project_id"]

        registry = client.get("/api/queries/rules.registry")
        assert registry.status_code == 200, registry.text
        entry = next(item for item in registry.json()["data"]["rules"] if item["name"] == "execution.slots")
        assert entry["wired"] is False and entry["not_wired_reason"]
        end = opened.store.end_position()

        # 全局入口与项目入口用同一条未接入的条目：两处都拒绝，说明逐字复用登记里的原因
        for body in ({"name": "execution.slots", "value": 8},
                     {"project_id": project_id, "name": "execution.slots", "value": 8}):
            rejected = _post(client, "parameter.set", reason="试试没有接入行为的条目",
                             modified_by="user:test", **body)
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["reason"] == "not_wired"
            assert rejected.json()["message"] == entry["not_wired_reason"]

        # 拒绝不写事件：目录流与项目流都没有新增参数事件，日志末尾不动
        assert _parameter_events(opened) == []
        assert [event for event in opened.store.stream_events(project_stream(project_id))
                if event.type == ProjectEventType.PARAMETER_SET] == []
        assert opened.store.end_position() == end


def test_a_paused_run_keeps_its_frozen_limit_after_the_parameter_is_raised(data_dir):
    # 直接用系统核对冻结行为：停止的 run 不因参数调大而继续
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    try:
        project_id = system.projects.register("参数", "做一个命令行回显工具。")
        system.set_parameter("max_cycles", 1, reason="先看一轮", modified_by="user:test")
        _work_item, run_id = system.projects.start_work_item(project_id, "做回显功能。")
        stopped = system.run_until_stop(run_id)
        assert stopped.status == "paused" and stopped.stop_reason == "max_cycles"
        assert stopped.cycle_count == 1 and stopped.max_cycles == 1

        system.set_parameter("max_cycles", 999999, reason="调回去", modified_by="user:test")
        assert system.parameters()["max_cycles"] == 999999
        # 已停止的 run 保持停止：限额与轮数都按创建时的值
        assert system.project(run_id).max_cycles == 1
        again = system.run_until_stop(run_id)
        assert again.status == "paused" and again.cycle_count == 1
    finally:
        system.close()
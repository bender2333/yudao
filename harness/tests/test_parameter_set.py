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
        # 旧请求的 modified_by 仍被接受，但事件里的提出者与历史以认证身份为准（工单 #1262）
        assert (payload["reason"], payload["modified_by"]) == ("测试给短一点", "user:local")
        assert event.actor == "user:local"
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
        # 改回原值：现值回到 7200，两次修改都在历史里，各带修改者、原值、新值与理由；
        # 修改者取认证身份，不是请求体里的旧字段（工单 #1262）
        assert entry["value"] == 7200
        assert [(change["old_value"], change["new_value"]) for change in entry["changes"]] == [
            (7200, 3600), (3600, 7200)]
        assert [change["modified_by"] for change in entry["changes"]] == ["user:local", "user:local"]
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

        # 全局入口与项目入口用同一条未接入的条目：两处都拒绝，说明逐字复用登记里的原因；
        # 旧请求省略新字段、带旧字段都能到达同一个拒绝（工单 #1262 的兼容行为）
        for body in ({"name": "execution.slots", "value": 8},
                     {"project_id": project_id, "name": "execution.slots", "value": 8},
                     {"name": "execution.slots", "value": 8, "base_version": "sha256:old"},
                     {"project_id": project_id, "name": "execution.slots", "value": 8,
                      "expected_change_id": "evt_x"}):
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


# ---------------------------------------------------------------------------
# 工单 #1262：默认值、认证身份、基准版本与撤回


def _registry_entry(client, name: str) -> dict:
    registry = client.get("/api/queries/rules.registry")
    assert registry.status_code == 200, registry.text
    return next(item for item in registry.json()["data"]["rules"] if item["name"] == name)


def test_rules_registry_reports_the_definition_default_alongside_the_current_value(data_dir):
    # 守 R2（对外合同：登记查询的字段）：默认值从定义的 Rule.value 来（工单 #1262），
    # 登记文件结构不变；被修改过的参数现值与默认值不同，从未修改的两者相同
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        assert _post(client, "project.create", name="参数",
                     goal="做一个命令行回显工具。").status_code == 200

        body = client.get("/api/queries/rules.registry").json()
        assert body["data"]["parameters_version"] == opened.system.parameters_version()
        entry = next(item for item in body["data"]["rules"] if item["name"] == "run_time_limit_sec")
        assert entry["default_value"] == DEFINITIONS.rule_value("run_time_limit_sec")
        assert entry["value"] == entry["default_value"]

        assert _post(client, "parameter.set", name="run_time_limit_sec", value=3600,
                     reason="调小一点").status_code == 200
        body = client.get("/api/queries/rules.registry").json()
        entry = next(item for item in body["data"]["rules"] if item["name"] == "run_time_limit_sec")
        assert (entry["value"], entry["default_value"]) == (
            3600, DEFINITIONS.rule_value("run_time_limit_sec"))
        assert body["data"]["parameters_version"] == opened.system.parameters_version()
        # structure 条目同样带定义里的默认值
        structure = next(item for item in body["data"]["rules"] if item["name"] == "loop.nesting_max")
        assert structure["default_value"] == DEFINITIONS.rule("loop.nesting_max").value
        assert structure["value"] == structure["default_value"]


def test_omitted_modified_by_defaults_to_the_authenticated_actor_and_old_requests_stay_accepted(data_dir):
    # 守 R2（对外合同：认证身份）：modified_by 可选（工单 #1262）；缺省时事件 actor 与历史都是认证身份；
    # 提供时也是认证身份——请求体不再决定提出者；旧请求省略新字段时兼容
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        assert _post(client, "project.create", name="参数",
                     goal="做一个命令行回显工具。").status_code == 200

        omitted = _post(client, "parameter.set", name="max_cycles", value=12, reason="省略修改者")
        assert omitted.status_code == 200, omitted.text
        legacy = _post(client, "parameter.set", name="max_cycles", value=13, reason="旧字段",
                       modified_by="user:someone-else")
        assert legacy.status_code == 200, legacy.text

        [first, second] = _parameter_events(opened)
        assert (first.payload["modified_by"], first.actor) == ("user:local", "user:local")
        assert (second.payload["modified_by"], second.actor) == ("user:local", "user:local")
        entry = _registry_entry(client, "max_cycles")
        assert [change["modified_by"] for change in entry["changes"]] == ["user:local", "user:local"]


def test_base_version_is_checked_against_the_parameter_version_and_rejections_carry_it(data_dir):
    # 守 R1（边界与基准版本）：base_version 按参数版本（内容摘要）核对，过期返回 stale_base 与当前版本，
    # 拒绝不写事件（工单 #1262）
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        assert _post(client, "project.create", name="参数",
                     goal="做一个命令行回显工具。").status_code == 200
        end = opened.store.end_position()

        stale = _post(client, "parameter.set", name="max_cycles", value=12, reason="版本过期",
                      base_version="sha256:not-the-current-one")
        assert stale.status_code == 409, stale.text
        assert stale.json()["reason"] == "stale_base"
        assert stale.json()["current_version"] == opened.system.parameters_version()
        assert _parameter_events(opened) == [] and opened.store.end_position() == end

        current = opened.system.parameters_version()
        accepted = _post(client, "parameter.set", name="max_cycles", value=12, reason="版本相符",
                         base_version=current)
        assert accepted.status_code == 200, accepted.text
        [event] = _parameter_events(opened)
        assert event.payload["parameters_version"] != current

        # 重复命令保持幂等：同一身份、同一内容再提交返回同一个接受结果，不写第二条事件
        again = client.post("/api/commands/parameter.set", json={
            "command_id": accepted.json()["command_id"], "name": "max_cycles", "value": 12,
            "reason": "版本相符", "base_version": current})
        assert again.status_code == 200 and again.json()["duplicate"] is True
        assert len(_parameter_events(opened)) == 1


def test_the_project_command_checks_the_project_effective_version(data_dir):
    # 守 R1（边界与基准版本）：项目级修改按项目有效参数的版本核对（全局现值加项目覆盖），
    # 项目的覆盖变化使全局版本不再相同；设置查询返回这个项目有效参数的版本（工单 #1262）
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project = _post(client, "project.create", name="参数", goal="做一个命令行回显工具。")
        assert project.status_code == 200, project.text
        project_id = project.json()["refs"]["project_id"]

        stale = _post(client, "parameter.set", name="check_timeout_sec", value=120, reason="过期",
                      project_id=project_id, base_version="sha256:stale")
        assert stale.status_code == 409 and stale.json()["reason"] == "stale_base"

        from harness.parameters import effective_parameter_version
        effective = effective_parameter_version(opened.store, project_id)
        assert effective == opened.system.parameters_version()
        settings = client.get("/api/queries/project.settings",
                              params={"project_id": project_id}).json()["data"]
        assert settings["effective_parameters_version"] == effective
        accepted = _post(client, "parameter.set", name="check_timeout_sec", value=120, reason="项目值",
                         project_id=project_id, base_version=effective)
        assert accepted.status_code == 200, accepted.text

        # 项目覆盖改变以后，同一项目按全局版本提交被拒绝；设置查询返回新的有效版本
        global_version = opened.system.parameters_version()
        effective = effective_parameter_version(opened.store, project_id)
        assert effective != global_version
        stale = _post(client, "parameter.set", name="check_timeout_sec", value=180, reason="按全局版本",
                      project_id=project_id, base_version=global_version)
        assert stale.status_code == 409 and stale.json()["reason"] == "stale_base"
        settings = client.get("/api/queries/project.settings",
                              params={"project_id": project_id}).json()["data"]
        assert settings["effective_parameters_version"] == effective


def test_withdraw_restores_the_previous_value_and_keeps_the_history(data_dir):
    # 守 R1（边界与撤回）与 R2（历史身份）：撤回用最近修改记录的身份，把值改回那一次的原值；
    # 撤回自己也是一次修改，历史不删除（工单 #1262）
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        assert _post(client, "project.create", name="参数",
                     goal="做一个命令行回显工具。").status_code == 200
        assert _post(client, "parameter.set", name="run_time_limit_sec", value=3600,
                     reason="先改小").status_code == 200

        entry = _registry_entry(client, "run_time_limit_sec")
        [change] = entry["changes"]
        assert change["event_id"] and change["parameters_version"]

        withdrawn = _post(client, "parameter.withdraw", name="run_time_limit_sec",
                          expected_change_id=change["event_id"],
                          reason=f"撤回：{change['reason']}")
        assert withdrawn.status_code == 200, withdrawn.text

        entry = _registry_entry(client, "run_time_limit_sec")
        assert entry["value"] == 7200
        assert [(item["old_value"], item["new_value"]) for item in entry["changes"]] == [
            (7200, 3600), (3600, 7200)]
        assert [item["reason"] for item in entry["changes"]] == ["先改小", "撤回：先改小"]
        assert [event.payload.get("expected_change_id") for event in _parameter_events(opened)] == [
            None, change["event_id"]]


def test_withdraw_rejects_when_the_latest_change_has_moved_on(data_dir):
    # 守 R1（ABA 边界）：现值经历修改后又变回相同数值时，记录身份改变，撤回被拒绝，不写事件（工单 #1262）
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        assert _post(client, "project.create", name="参数",
                     goal="做一个命令行回显工具。").status_code == 200
        assert _post(client, "parameter.set", name="run_time_limit_sec", value=3600,
                     reason="第一次改").status_code == 200
        [first] = _parameter_events(opened)

        # 另一方又改了一次（ABA 的 A）：现值与第一次的新值不再相同，历史多了一条
        assert _post(client, "parameter.set", name="run_time_limit_sec", value=5400,
                     reason="第二次改").status_code == 200

        end = opened.store.end_position()
        stale = _post(client, "parameter.withdraw", name="run_time_limit_sec",
                      expected_change_id=first.event_id, reason="撤回：第一次改")
        assert stale.status_code == 409, stale.text
        assert stale.json()["reason"] == "stale_base"
        assert _parameter_events(opened)[-1].event_id != first.event_id
        assert len(_parameter_events(opened)) == 2
        assert opened.store.end_position() == end

        # 改回第一次的取值也不能恢复撤回：最近的记录身份已经改变（同一数值，不同身份）
        assert _post(client, "parameter.set", name="run_time_limit_sec", value=3600,
                     reason="改回同一个值").status_code == 200
        [latest] = _registry_entry(client, "run_time_limit_sec")["changes"][-1:]
        assert latest["new_value"] == 3600
        end = opened.store.end_position()
        stale = _post(client, "parameter.withdraw", name="run_time_limit_sec",
                      expected_change_id=first.event_id, reason="撤回：第一次改")
        assert stale.status_code == 409 and stale.json()["reason"] == "stale_base"
        assert opened.store.end_position() == end

        # 未知的历史身份同样拒绝
        unknown = _post(client, "parameter.withdraw", name="run_time_limit_sec",
                        expected_change_id="evt_missing", reason="撤回：不存在的记录")
        assert unknown.status_code == 409 and unknown.json()["reason"] == "stale_base"
        assert opened.store.end_position() == end


def test_withdraw_in_the_same_transaction_checks_the_latest_identity_before_writing(data_dir):
    # 守 R1（同事务核对）：撤回的最近修改身份与基准版本在同一个写事务里核对；
    # 通过核对以后才追加事件，核对不过时什么也不写（工单 #1262，设计说明第 4.3 节）
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        assert _post(client, "project.create", name="参数",
                     goal="做一个命令行回显工具。").status_code == 200
        assert _post(client, "parameter.set", name="max_cycles", value=12, reason="先改").status_code == 200
        [first] = _parameter_events(opened)

        # 撤回时按最新的参数版本作为基准：接受并写事件
        end = opened.store.end_position()
        ok = _post(client, "parameter.withdraw", name="max_cycles",
                   expected_change_id=first.event_id, reason="撤回：先改",
                   base_version=opened.system.parameters_version())
        assert ok.status_code == 200, ok.text
        assert opened.store.end_position() == end + 1

        entry = _registry_entry(client, "max_cycles")
        assert entry["value"] == 999999
        # 事件里的提出者取认证身份，理由由页面按「撤回：」与原理由给出
        [withdraw_event] = _parameter_events(opened)[1:]
        assert withdraw_event.payload["modified_by"] == "user:local"


def test_withdraw_of_a_project_parameter_restores_the_project_value(data_dir):
    # 守 R1（项目级撤回）：项目级参数的撤回按项目流核对最近一次修改，恢复项目的覆盖值；
    # 没有设置过的参数没有可撤回的修改（工单 #1262）
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project = _post(client, "project.create", name="参数", goal="做一个命令行回显工具。")
        assert project.status_code == 200, project.text
        project_id = project.json()["refs"]["project_id"]

        missing = _post(client, "parameter.withdraw", name="check_timeout_sec",
                        expected_change_id="evt_none", reason="没有设置过", project_id=project_id)
        assert missing.status_code == 409 and missing.json()["reason"] == "not_found"

        assert _post(client, "parameter.set", name="check_timeout_sec", value=120, reason="项目值",
                     project_id=project_id).status_code == 200
        project_events = [event for event in opened.store.stream_events(project_stream(project_id))
                          if event.type == ProjectEventType.PARAMETER_SET]
        [change] = project_events

        withdrawn = _post(client, "parameter.withdraw", name="check_timeout_sec",
                          expected_change_id=change.event_id, reason="撤回：项目值",
                          project_id=project_id)
        assert withdrawn.status_code == 200, withdrawn.text

        project_events = [event for event in opened.store.stream_events(project_stream(project_id))
                          if event.type == ProjectEventType.PARAMETER_SET]
        assert [(event.payload["old_value"], event.payload["new_value"]) for event in project_events] == [
            (600, 120), (120, 600)]
        assert project_events[-1].payload["expected_change_id"] == change.event_id
        # 目录流没有新增事件：项目级参数的修改与撤回都写项目流
        assert _parameter_events(opened) == []
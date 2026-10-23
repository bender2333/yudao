# 命令登记删除以后的读取与写入合同（工单 #543，ADR-0038）：
# 旧版本写入的数据目录（项目流有 command_configured 事件、run_created 载荷带 registered_commands 与
# command_versions）能被新版本读取：项目流读得出、旧 run 读得出、能新建事项；新写入不再有这些字段与登记命令。
# 数据目录由事件库直接写入构造，不用 mock。

import json
import sqlite3
import uuid
from dataclasses import asdict

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.artifacts import ArtifactStore
from harness.event_store import EventStore, project_stream, run_stream
from harness.models import new_id
from harness.project_projection import handler_for, saved_project
from harness.projection import project_run
from harness.runtime import LoopSystem
from harness.write_path import NewEvent, NewProjectEvent, WritePath
from harness.tests.api_helpers import running_api
from harness.tests.helpers import happy_script

GOAL = "做一个可以长期演进的逐行文本处理工具。"


def _legacy_project(data_dir):
    # 一份旧版本写入的数据目录：项目登记了两条命令（其中一条没有 repeatable 字段），
    # 事项创建时冻结的登记与命令版本写进了 run_created 载荷
    store = EventStore(data_dir / "events.sqlite")
    artifacts = ArtifactStore(data_dir / "artifacts")
    writes = WritePath(store, handler_for)
    try:
        project_id = new_id("proj")
        goal_ref = artifacts.put(project_id, "project_goal", GOAL, media_type="text/markdown")
        context_ref = artifacts.put(project_id, "project_context", "项目：旧项目", media_type="text/markdown")
        run_id = new_id("run")
        work_item_id = new_id("item")

        def legacy(transaction):
            transaction.append(NewProjectEvent("project_registered", {
                "name": "旧项目", "goal": GOAL, "goal_ref": asdict(goal_ref), "source": "idea",
            }, actor="user:local"))
            transaction.append(NewProjectEvent("command_configured", {
                "name": "lint", "version": 1, "argv": ["python", "-m", "flake8"], "args": [],
                "timeout_sec": 600, "output_limit": 4096, "base_version": 0, "repeatable": True,
            }, actor="user:local"))
            # 更早的版本没有 repeatable 字段：读取时按否处理（ADR-0019）
            transaction.append(NewProjectEvent("command_configured", {
                "name": "build", "version": 1, "argv": ["python", "-m", "build"], "args": [],
                "timeout_sec": 600, "output_limit": 4096, "base_version": 0,
            }, actor="user:local"))
            transaction.append(NewProjectEvent("work_item_created", {
                "work_item_id": work_item_id, "title": "旧事项", "text": "旧事项", "run_id": run_id,
                "baseline": None, "snapshot": None, "project_context_ref": asdict(context_ref),
                "prompt_config_versions": {"product": 0, "engineering": 0, "quality": 0},
                "command_versions": {"lint": 1, "build": 1},
                "max_cycles": 2, "run_time_limit_sec": 7200, "context_window": 32000,
                "definitions_version": "sha256:legacy",
            }, actor="user:local"))

        writes.transact(project_stream(project_id), legacy, expected_version=0)

        # 旧版本的 run_created：没有 run 事件版本字段，载荷带着登记命令的冻结形态与命令版本
        git_version = {"commit": "0" * 40, "parent_commit": None, "tree": "0" * 40}
        writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
            "run_created", state_before="running", state_after="running", actor="user:local",
            payload={
                "task": "旧事项", "kind": "change",
                "initial_input": {"id": new_id("input"), "version": 1, "text": "旧事项", "kind": "text",
                                  "input_ref": asdict(context_ref), "intend_ref": asdict(context_ref),
                                  "byte_start": 0, "byte_end": 3, "git_version": git_version},
                "intend_ref": asdict(context_ref), "git_version": git_version,
                "intend_path": "materials/intend.md",
                "max_cycles": 2, "run_time_limit_sec": 7200, "context_window": 32000,
                "check_timeout_sec": 600, "provider": "directory", "adapter": "directory",
                "sessions": {}, "project_id": project_id, "work_item_id": work_item_id,
                "baseline": None, "snapshot": None, "workspace_digest": "sha256:legacy",
                "project_context_ref": asdict(context_ref),
                "prompt_config_versions": {"product": 0, "engineering": 0, "quality": 0},
                "registered_commands": {
                    "lint": {"argv": ["python", "-m", "flake8"], "args": [],
                             "timeout_sec": 600, "output_limit": 4096, "repeatable": True},
                    "build": {"argv": ["python", "-m", "build"], "args": [],
                              "timeout_sec": 600, "output_limit": 4096, "repeatable": False}},
                "command_versions": {"lint": 1, "build": 1},
                "definitions_version": "sha256:legacy",
                "parameters_version": "sha256:legacy"},
        )), expected_version=0)
    finally:
        store.close()

    # 旧版本的 run_created 载荷带着登记命令的冻结形态与命令版本，保存的投影一并删掉，启动时重放补建
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        row = connection.execute(
            "SELECT payload_json FROM events WHERE stream = ? AND type = ?",
            (run_stream(run_id), "run_created")).fetchone()
        assert row is not None, "no run_created event"
        document = json.loads(row[0])
        document["registered_commands"] = {
            "lint": {"argv": ["python", "-m", "flake8"], "args": [], "timeout_sec": 600,
                     "output_limit": 4096, "repeatable": True},
            "build": {"argv": ["python", "-m", "build"], "args": [], "timeout_sec": 600,
                      "output_limit": 4096, "repeatable": False},
        }
        document["command_versions"] = {"lint": 1, "build": 1}
        connection.execute("UPDATE events SET payload_json = ? WHERE stream = ? AND type = ?",
                           (json.dumps(document, ensure_ascii=False, sort_keys=True),
                            run_stream(run_id), "run_created"))
        connection.execute("DELETE FROM projections")
        connection.commit()
    finally:
        connection.close()
    return project_id, run_id


def test_old_data_with_command_registration_reads_and_starts_new_items(data_dir):
    # 验收三：含旧 command_configured 事件与旧 run_created 载荷的数据目录，新版本能读取项目流、
    # 读取旧 run 并新建事项；旧 run 的登记字段按缺省忽略
    project_id, legacy_run = _legacy_project(data_dir)

    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    try:
        state = saved_project(system.store, project_id)
        assert state.project_id == project_id
        # 旧 run 没有 run 事件版本字段：启动时按因升级停止并重新开始同一个事项，
        # 项目流的长期事实（登记命令的两条旧事件）完整重建
        assert [item["title"] for item in state.to_dict()["work_items"]] == ["旧事项", "旧事项"]
        # 登记命令的投影字段已经删除，投影里不再有命令清单与历史
        assert "commands" not in state.to_dict()
        assert "command_history" not in state.to_dict()

        run = project_run(system.store, legacy_run)
        assert run.status == "failed" and run.stop_reason == "run_event_version_changed"
        # 旧载荷里的登记字段按缺省忽略
        assert not hasattr(run, "registered_commands")
        assert not hasattr(run, "command_versions")

        _work_item_id, new_run = system.projects.start_work_item(project_id, "新事项")
        assert project_run(system.store, new_run).run_id == new_run
    finally:
        system.close()


def test_new_run_created_events_carry_no_registration_fields(data_dir):
    # 验收四：新建事项的 run_created 载荷没有 registered_commands 与 command_versions
    project_id, _legacy_run = _legacy_project(data_dir)
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    try:
        _work_item_id, run_id = system.projects.start_work_item(project_id, "新事项")
        [created] = [event for event in system.store.list_events(run_id) if event.type == "run_created"]
        assert "registered_commands" not in created.payload
        assert "command_versions" not in created.payload
        assert "command_versions" not in saved_project(system.store, project_id).work_items[-1].to_dict()
    finally:
        system.close()


def test_command_registration_is_gone_from_the_interface(data_dir):
    # 验收一、二：登记命令不再出现在能力清单与接口中，project.settings 不再返回登记命令
    project_id, _legacy_run = _legacy_project(data_dir)
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    try:
        application = Application(system)
        with running_api(lambda: application) as client:
            capabilities = client.get("/api/capabilities").json()
            assert "command_registration.save" not in capabilities["commands"]
            saved = client.post("/api/commands/command_registration.save", json={
                "command_id": str(uuid.uuid4()), "project_id": project_id, "name": "lint",
                "argv": ["python", "-m", "flake8"], "base_version": 0})
            assert saved.status_code == 404, saved.text
            settings = client.get("/api/queries/project.settings",
                                  params={"project_id": project_id}).json()["data"]
            assert "commands" not in settings
    finally:
        system.close()

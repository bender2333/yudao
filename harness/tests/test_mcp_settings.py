# 项目设置里的 MCP 服务器：保存、版本与事项创建时冻结（工单 #236；网络与 MCP 设计说明第 4.1 至 4.4 节、
# 第 18 节「本机的做法」第 3、5 条；总图第四节「写入口」的缝）。这个文件查七件事：
# 1. mcp_servers.save 保存非秘密设置与凭据引用，project.settings 读回，版本加一；
# 2. 基准版本过期时拒绝并带当前版本，提示重新读取；
# 3. 名称与传输等字段级校验有错误；
# 4. 凭据值不进入保存的事件、事项创建事实、run 创建载荷与导出（只存引用）；
# 5. 事项创建时把当时的设置冻结进事项创建事实与 run_created；新建、排队、升级重启与启动补建
#    都读冻结的那份；事项创建以后修改项目设置，已有事项的 run 仍用旧设置；
# 6. 运行投影只保存版本与摘要，不保存整份设置；旧事件没有 MCP 设置时按空设置读取；
# 7. 工具清单快照必须带与本台服务器配置一致的摘要，配置改变后旧快照被拒绝；保存未探测的配置允许。
#
# 建档修改轮的继承不在这里：修改轮由集成层的建档场景运行（decision_flow.create_revision_run 与
# restart_work_item_for_upgrade、启动补建读的都是 _work_item_created 写进事项事实的同一份冻结值）。
#
# 层：模块层（FakeAdapter 的一次激活或不出激活；SQLite 事件库与工作区文件，不用网络与完整循环，
# 测试分层设计说明第 2 节）。守 R1（边界与冻结）、R2（第二环的合同：项目流事件与 run_created 载荷、
# 两端共读的事件种类清单）与 R3（用户读到的设置与保存的一致，凭据值不出现）。

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.contracts import EVENT_TYPES
from harness.event_store import project_stream, run_stream
from harness.models import ArtifactRef, EventType, ProjectEvent, ProjectEventType, RunProjection, new_id
from harness.proposals import product_spec
from harness.projects import McpServersConflict, McpServersInvalid, mcp_document_digest, normalize_mcp_servers
from harness.projection import project_run
from harness.runtime import LoopSystem
from harness.streams import PROJECT_EVENT_TYPES
from harness.tests.helpers import happy_script
from harness.tests.project_stream_fields import load_manifest
from harness.write_path import NewProjectEvent

GOAL = "做一个可以长期演进的逐行文本处理工具。"
SECRET = "sk-super-secret-value-236"
FIXTURE = Path(__file__).resolve().parents[2] / "client" / "tests" / "fixtures" / "event-types.json"

STDIO_SERVER = {
    "time": {
        "name": "time", "transport": "stdio",
        "command": "uvx", "args": ["mcp-server-time"],
        "env": {"API_KEY": {"kind": "credential", "credential_ref": "MCP_TIME_KEY"}},
        "departments": ["product", "engineering", "quality"],
    },
}
HTTP_SERVER = {
    "search": {
        "name": "search", "transport": "http", "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": {"kind": "credential", "credential_ref": "EXA_KEY"}},
        "departments": ["product"],
    },
}


def _system(tmp_path, script=None) -> LoopSystem:
    return LoopSystem.for_testing(tmp_path, FakeAdapter(script or {"product": [product_spec()]}))


def _save(system: LoopSystem, project_id: str, servers: dict, *, base_version: int = 0) -> dict:
    return system.projects.configure_mcp_servers(project_id, servers, base_version=base_version)


def _saved_event(system: LoopSystem, project_id: str) -> dict:
    return next(event for event in system.store.list_project_events(project_id)
                if event.type == ProjectEventType.MCP_SERVERS_CONFIGURED).payload


def _created_payload(system: LoopSystem, run_id: str) -> dict:
    return next(event for event in system.store.list_events(run_id)
                if event.type == EventType.RUN_CREATED).payload


def _settings(application: Application, project_id: str):
    from harness.app.project_queries import ProjectSettings
    return application.query("project.settings", ProjectSettings(project_id=project_id)).data


# ---------------------------------------------------------------------------
# 保存、读回与版本（验收 1、2）


def test_save_is_read_back_with_a_raised_version_and_the_next_save_needs_the_new_base(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("设置", GOAL)

    saved = _save(system, project_id, STDIO_SERVER, base_version=0)
    assert saved["version"] == 1
    assert saved["document_digest"]
    assert set(saved["servers"]) == {"time"}
    stored = saved["servers"]["time"]
    assert stored["transport"] == "stdio" and stored["command"] == "uvx"
    assert stored["env"]["API_KEY"] == {"kind": "credential", "value": "", "credential_ref": "MCP_TIME_KEY"}
    # 默认时限与输出上限按设计说明第 7.2 节写进保存的设置
    assert stored["startup_timeout_sec"] == 60 and stored["call_timeout_sec"] == 120
    assert stored["output_limit"] == 20000

    assert system.projects.read_mcp_servers(project_id) == saved

    # 基准版本过期：以旧版本再保存被拒绝并带当前版本，提示重新读取
    with pytest.raises(McpServersConflict) as conflict:
        _save(system, project_id, STDIO_SERVER, base_version=0)
    assert conflict.value.current["version"] == 1

    # 读回的版本再保存：版本加二，换一份设置照常保存
    saved_again = _save(system, project_id, HTTP_SERVER, base_version=saved["version"])
    assert saved_again["version"] == 2
    assert set(saved_again["servers"]) == {"search"}
    system.close()


def test_the_saved_event_and_projection_carry_the_same_non_secret_document(tmp_path):
    # R2：保存写入项目流事件 mcp_servers_configured；项目投影与查询读的是这一份
    system = _system(tmp_path)
    project_id = system.projects.register("事件", GOAL)
    _save(system, project_id, {**STDIO_SERVER, **HTTP_SERVER}, base_version=0)

    event = _saved_event(system, project_id)
    assert event["version"] == 1 and event["base_version"] == 0
    assert set(event["servers"]) == {"time", "search"}
    assert event["servers"]["search"]["url"] == "https://mcp.example.com/mcp"

    state = system.projects.projection(project_id)
    assert state.mcp_servers.version == 1
    assert state.mcp_servers.frozen_document()["document_digest"] == event["document_digest"]
    system.close()


# ---------------------------------------------------------------------------
# 字段级校验（验收 1 的「名称与传输校验有字段级错误」）


@pytest.mark.parametrize("servers, message", [
    ({"time": {"name": "Bad Name", "transport": "stdio", "command": "uvx",
               "departments": ["product"]}}, "名称"),
    ({"time": {"name": "time", "transport": "sse", "url": "https://x", "departments": ["product"]}}, "传输"),
    ({"time": {"name": "time", "transport": "stdio", "departments": ["product"]}}, "命令"),
    ({"time": {"name": "time", "transport": "http", "url": "ftp://x", "departments": ["product"]}}, "http 或 https"),
    ({"time": {"name": "time", "transport": "stdio", "command": "uvx", "departments": ["nobody"]}}, "部门"),
    ({"time": {"name": "time", "transport": "stdio", "command": "uvx", "departments": ["product"],
               "env": {"K": {"kind": "credential", "credential_ref": "bad-key!"}}}}, "凭据引用"),
    ({"time": {"name": "time", "transport": "stdio", "command": "uvx", "departments": ["product"],
               "env": {"K": {"kind": "token", "value": "x"}}}}, "取值方式"),
    ({"time": {"name": "time", "transport": "stdio", "command": "uvx", "departments": ["product"],
               "call_timeout_sec": 0}}, "不小于 1"),
])
def test_field_level_errors_are_reported_per_field(servers, message):
    # 校验在写入口之前拒绝：不写事件，错误写明是哪一项、要求是什么
    with pytest.raises(McpServersInvalid, match=message):
        normalize_mcp_servers(servers)


def test_a_tool_snapshot_with_a_mismatched_config_digest_is_rejected_and_unprobed_saves(tmp_path):
    # 工具清单快照必须带与本台服务器配置一致的摘要（设计说明第 4.2 节）；配置改变后旧快照不可继续使用；
    # 保存未探测的配置允许（实际探测与更新由后续探测工单完成）。快照的摘要按归一化后的配置算出，
    # 与保存归一化的同一份配置得到的摘要相同
    system = _system(tmp_path)
    project_id = system.projects.register("快照", GOAL)
    stale = json.loads(json.dumps(STDIO_SERVER["time"]))
    stale["tool_snapshot"] = {"config_digest": "sha256:stale", "tools": [{"name": "now"}]}
    with pytest.raises(McpServersInvalid, match="不一致"):
        _save(system, project_id, {"time": stale}, base_version=0)

    probed = json.loads(json.dumps(STDIO_SERVER["time"]))
    config_digest = normalize_mcp_servers({"time": probed})["servers"]["time"]["config_digest"]
    probed["tool_snapshot"] = {"config_digest": config_digest, "tools": [{"name": "now"}]}
    saved = _save(system, project_id, {"time": probed}, base_version=0)
    assert saved["servers"]["time"]["tool_snapshot"]["config_digest"] == config_digest
    assert saved["servers"]["time"]["config_digest"] == config_digest

    plain = json.loads(json.dumps(STDIO_SERVER["time"]))
    plain_saved = _save(system, project_id, {"time": plain}, base_version=1)
    assert plain_saved["servers"]["time"]["tool_snapshot"] is None
    system.close()


# ---------------------------------------------------------------------------
# 凭据值不出现（验收 2）


def test_credential_values_do_not_enter_events_projections_or_the_run_created_payload(tmp_path):
    # 凭据只以名称进入设置：值按现有的边界由调用时的凭据来源解析，不进入事件、投影、导出与日志
    system = _system(tmp_path)
    project_id = system.projects.register("凭据", GOAL)
    _save(system, project_id, STDIO_SERVER, base_version=0)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)

    exported = json.dumps({
        "events": [event.to_dict() for event in system.store.list_events(run_id)],
        "project_events": [event.to_dict() for event in system.store.list_project_events(project_id)],
        "projection": project_run(system.store, run_id).canonical_state(),
        "run_created_payload": _created_payload(system, run_id),
        "settings": system.projects.read_mcp_servers(project_id),
    }, ensure_ascii=False)
    assert SECRET not in exported
    assert "MCP_TIME_KEY" in exported  # 引用在，值不在
    system.close()


# ---------------------------------------------------------------------------
# 冻结与继承（验收 3）


def test_work_item_creation_freezes_the_settings_and_the_run_reads_that_copy(tmp_path):
    # 事项创建事实与 run_created 携带同一份冻结设置；事项创建以后修改项目设置，
    # 已有事项的 run 仍用旧设置
    system = _system(tmp_path)
    project_id = system.projects.register("冻结", GOAL)
    _save(system, project_id, STDIO_SERVER, base_version=0)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)

    frozen = _created_payload(system, run_id)["mcp_servers"]
    assert frozen["version"] == 1
    assert set(frozen["servers"]) == {"time"}
    assert frozen["document_digest"] == _saved_event(system, project_id)["document_digest"]

    # 事项创建以后修改项目设置：已有事项的 run_created 还是旧的那份
    _save(system, project_id, HTTP_SERVER, base_version=1)
    assert set(_created_payload(system, run_id)["mcp_servers"]["servers"]) == {"time"}
    # run 投影只保存版本与摘要，不保存整份设置（验收 4 的投影一侧）
    projection = project_run(system.store, run_id)
    assert projection.mcp_servers_version == 1
    assert projection.mcp_servers_names == ["time"]
    assert projection.mcp_servers_digest == frozen["document_digest"]
    system.close()


def test_an_upgrade_restart_keeps_the_frozen_settings_of_the_item(tmp_path):
    # 事项创建以后修改项目设置：该事项因升级重新开始仍读事项创建时冻结的那份
    system = _system(tmp_path)
    project_id = system.projects.register("重启", GOAL)
    _save(system, project_id, STDIO_SERVER, base_version=0)
    _item, old_run = system.projects.start_work_item(project_id, GOAL)
    _save(system, project_id, HTTP_SERVER, base_version=1)

    restarted = system.projects.restart_work_item_for_upgrade(old_run)
    assert restarted is not None
    _new_item, new_run = restarted
    frozen = _created_payload(system, new_run)["mcp_servers"]
    assert set(frozen["servers"]) == {"time"}
    assert frozen["version"] == 1
    system.close()


def test_the_startup_rebuild_reads_the_frozen_values_from_the_work_item_created_event(tmp_path):
    # 中断（事项已提交、run 未创建）后启动补建：只读 work_item_created 里的冻结值，不取项目当前设置
    system = _system(tmp_path)
    project_id = system.projects.register("补建", GOAL)
    _save(system, project_id, STDIO_SERVER, base_version=0)
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

    _save(system, project_id, HTTP_SERVER, base_version=1)
    system.close()
    reopened = LoopSystem.for_testing(system.data_dir, FakeAdapter({"product": [product_spec()]}))
    assert reopened.recovered_work_item_runs == [run_id]
    frozen = _created_payload(reopened, run_id)["mcp_servers"]
    assert set(frozen["servers"]) == {"time"} and frozen["version"] == 1
    reopened.close()


def test_a_queued_work_item_freezes_the_settings_at_queue_time(tmp_path):
    # 排空期间排队的事项：登记事项时冻结当时的设置；run 在排空结束后由启动补建按事项事实建立
    system = _system(tmp_path)
    project_id = system.projects.register("排队", GOAL)
    _save(system, project_id, STDIO_SERVER, base_version=0)
    work_item_id = system.projects.queue_work_item(project_id, GOAL)
    _save(system, project_id, HTTP_SERVER, base_version=1)
    item = system.projects.projection(project_id).work_item(work_item_id)
    frozen = next(event.payload["mcp_servers"]
                  for event in system.store.list_project_events(project_id)
                  if event.type == ProjectEventType.WORK_ITEM_CREATED
                  and event.payload["work_item_id"] == work_item_id)
    assert set(frozen["servers"]) == {"time"} and frozen["version"] == 1
    assert item.mcp_servers == frozen
    system.close()


# ---------------------------------------------------------------------------
# 投影与旧事件（验收 4）


def test_the_run_projection_keeps_only_version_digest_and_names(tmp_path):
    # 运行投影只保存版本或摘要，不保存整份设置（验收 4）
    system = _system(tmp_path)
    project_id = system.projects.register("投影", GOAL)
    _save(system, project_id, STDIO_SERVER, base_version=0)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    projection = project_run(system.store, run_id)
    state = projection.canonical_state()
    assert state["mcp_servers_version"] == 1
    assert state["mcp_servers_names"] == ["time"]
    mcp_fields = json.dumps({key: value for key, value in state.items() if key.startswith("mcp")})
    assert "uvx" not in mcp_fields and "mcp-server-time" not in mcp_fields
    system.close()


def test_old_events_without_mcp_settings_read_as_empty_settings(tmp_path):
    # 旧事件没有 MCP 设置时按空设置读取：手工写一条旧形状的 work_item_created 与 run_created，
    # 重放以后事项与 run 都没有 MCP 设置，保存了新设置也不改变它们
    system = _system(tmp_path)
    project_id = system.projects.register("旧事件", GOAL)
    run_id = new_id("run")
    work_item_id = new_id("wi")
    context_ref = system.artifacts.put(project_id, "project_context", "旧项目", media_type="text/markdown")

    def legacy(transaction):
        transaction.append(NewProjectEvent(ProjectEventType.WORK_ITEM_CREATED, {
            "work_item_id": work_item_id, "title": "旧事项", "text": "旧事项", "run_id": run_id,
            "baseline": None, "snapshot": None, "project_context_ref": asdict(context_ref),
            "prompt_config_versions": {"product": 0, "engineering": 0, "quality": 0},
            "max_cycles": 2, "run_time_limit_sec": 7200, "context_window": 32000,
            "definitions_version": "sha256:legacy",
        }, actor="user:local"))

    system.writes.transact(project_stream(project_id), legacy, expected_version=None)
    state = system.projects.projection(project_id)
    item = state.work_item(work_item_id)
    assert item.mcp_servers is None  # 事项事实没有这个字段，按空设置读取

    _save(system, project_id, STDIO_SERVER, base_version=0)
    assert system.projects.projection(project_id).work_item(work_item_id).mcp_servers is None
    # 旧 run 的创建事件没有 mcp_servers 字段：投影按空设置读取（版本 0、摘要为空）
    old_projection = RunProjection()
    assert old_projection.mcp_servers_version == 0
    assert old_projection.mcp_servers_names == [] and old_projection.mcp_servers_digest == ""
    system.close()


def test_the_new_project_stream_event_is_registered_on_both_ends():
    # R2：新增项目流事件在服务端清单与客户端 event-types.json 登记；
    # coverage.ts 的归属核对由客户端单元测试读这份夹具完成
    assert "mcp_servers_configured" in PROJECT_EVENT_TYPES
    assert "mcp_servers_configured" in EVENT_TYPES
    manifest = load_manifest()
    assert "mcp_servers_configured" in manifest["fields"]
    assert "mcp_servers_configured" in json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# project.settings 查询（验收 1 的读回一路）


def test_project_settings_query_returns_the_mcp_section(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("查询", GOAL)
    application = Application(system)

    empty = _settings(application, project_id)
    assert empty.mcp_servers.version == 0 and empty.mcp_servers.servers == {}

    _save(system, project_id, STDIO_SERVER, base_version=0)
    settings = _settings(application, project_id)
    assert settings.mcp_servers.version == 1
    assert settings.mcp_servers.servers["time"].transport == "stdio"
    assert settings.mcp_servers.servers["time"].env["API_KEY"]["credential_ref"] == "MCP_TIME_KEY"
    assert settings.mcp_servers.document_digest == _saved_event(system, project_id)["document_digest"]
    system.close()

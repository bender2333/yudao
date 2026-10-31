# 部门调用 MCP 服务器的工具（工单 #1175；网络与 MCP 设计说明第 5、7.2、7.3、9、10 节；总图第四节「动作」缝）。
# 验收 4、5 与回执字段的集成层：事项创建时冻结的 MCP 设置叠加成定义副本，工程的一轮工作按这个事项的
# 别名调用本机启动的真实 MCP 进程（官方 SDK 写的测试服务器），调用按事项定义分派到执行环境的 MCP 分支；
# 同一个 run 的同一台服务器复用一个会话实例（两次调用拿到同一个服务器进程），run 结束时关闭；
# 回执带结果与外部来源工件，run.actions 的动作视图带 MCP 的回执字段。
#
# 层：集成层（完整循环、真实 MCP 子进程，测试分层设计说明第 2 节）。
# 守 R2（装配、许可、分派与回执按同一份事项定义工作；回执的交换字段与外部来源工件引用）
# 与 R3（MCP 工具经真实进程与真实凭据来源调用，结果保存为外部来源工件）。

from __future__ import annotations

import json
import sys
from pathlib import Path

import psutil

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.artifacts import ArtifactRef, ArtifactStore
from harness.models import EventType
from harness.proposals import product_spec_turn
from harness.projects import normalize_mcp_servers
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn

SERVERS = Path(__file__).resolve().parent / "mcp_servers"
STDIO_SERVER = SERVERS / "stdio_server.py"
GOAL = "做一个可以长期演进的逐行文本处理工具。"
ALIAS = "mcp__time__echo"
ENV_ALIAS = "mcp__time__environment"
SECRET = "mcp-integration-secret-1175"


def _settings_document() -> dict:
    # 一台 stdio 服务器：命令是本机解释器加测试服务器脚本，环境变量按凭据名称引用（调用时由
    # 控制主机的凭据来源解析）。工具清单快照的摘要与归一化配置算出的同一份；
    # 缺快照的服务器不提供工具由缝层与 #1174 的用例守
    server = {"name": "time", "transport": "stdio", "command": sys.executable,
              "args": [str(STDIO_SERVER)], "departments": ["engineering", "quality"],
              "env": {"API_KEY": {"kind": "credential", "credential_ref": "MCP_IT_KEY"}}}
    document = normalize_mcp_servers({"time": server})
    config_digest = document["servers"]["time"]["config_digest"]
    document["servers"]["time"]["tool_snapshot"] = {
        "config_digest": config_digest,
        "server_info": {"name": "yudao-test-stdio", "version": "0.0.1", "protocol_version": "2025-06-18"},
        "tools": [
            {"name": "echo", "description": "原样交回文本",
             "input_schema": {"type": "object",
                              "properties": {"text": {"type": "string"}}, "required": ["text"]}},
            {"name": "environment", "description": "回报自己的进程与环境变量",
             "input_schema": {"type": "object", "properties": {}}},
        ],
    }
    return document


def _mcp_turn(alias: str, arguments: dict, identity: str) -> ModelResponse:
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                  "name": alias, "arguments": json.dumps(arguments)}])


def _echo_turn(text: str) -> ModelResponse:
    return _mcp_turn(ALIAS, {"text": text}, f"mcp-{text}")


def _system(tmp_path: Path, script) -> LoopSystem:
    return LoopSystem.for_testing(tmp_path, FakeAdapter(script), resume_on_startup=False)


def _project_with_server(system: LoopSystem) -> str:
    project_id = system.projects.register("MCP", GOAL)
    system.projects.configure_mcp_servers(project_id, _settings_document()["servers"], base_version=0)
    # 控制主机的凭据来源：测试进程的内存覆盖（真实 CredentialChain，值不进入事件与工件）
    system.facade.credential_chain().set_override("MCP_IT_KEY", SECRET)
    return project_id


def _work_item_run(system: LoopSystem, project_id: str) -> str:
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    return run_id


def _tool_called(system: LoopSystem, run_id: str, identity: str):
    return next(event for event in system.store.list_events(run_id)
                if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == identity)


def _result_of(system: LoopSystem, run_id: str, event) -> dict:
    raw = system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["output_ref"]))
    return json.loads(raw)


def test_a_department_calls_the_mcp_tool_through_the_item_definitions(tmp_path):
    # 工程的一轮工作调用 mcp__time__echo：工具来自这个事项冻结的 MCP 设置（定义副本），
    # 调用经执行环境的 MCP 分支走到真实进程，结果按原样交回并保存为外部来源工件
    system = _system(tmp_path, {
        "product": [product_spec_turn()],
        "engineering": [_echo_turn("你好，MCP"), FakeTurn(transcript="调用完成")],
        "quality": [explore_turn(), explore_turn(), explore_turn()],
    })
    project_id = _project_with_server(system)
    run_id = _work_item_run(system, project_id)
    system.run_until_stop(run_id)

    called = _tool_called(system, run_id, "mcp-你好，MCP")
    assert called.payload["ok"] is True and called.payload["error"] is None
    output = _result_of(system, run_id, called)
    # 结果的第一页按 read_external_source 的同一套分页交回：文本与 structuredContent 连成的正文按行保存
    assert output["lines"][0]["text"] == "你好，MCP"
    # 回执字段：服务器、原名与别名、传输、结果与外部来源工件引用、耗时与外部内容标注
    assert output["server"] == "time" and output["tool"] == "echo" and output["alias"] == ALIAS
    assert output["transport"] == "stdio"
    assert output["ref"]["kind"] == "external_source" and output["content_hash"].startswith("sha256:")
    assert output["external_content"] is True and output["notice"]
    assert output["duration_ms"] >= 0
    # 结果工件是这个 run 的外部来源：来源写明服务器与工具，正文按行保存
    store = ArtifactStore(system.data_dir / "artifacts")
    entry = store.external_source(run_id, output["content_hash"])
    assert entry.source == "mcp:time:echo"
    assert "你好，MCP" in entry.text
    system.close()


def test_a_run_reuses_one_session_per_server_and_closes_it_at_run_end(tmp_path):
    # 同一个 run 的同一台服务器复用一个会话实例：两次 environment 调用拿到同一个服务器进程
    # （每次新启动的服务器进程是新的进程号）；run 结束时关闭，会话表清空，那个进程不再存活
    system = _system(tmp_path, {
        "product": [product_spec_turn()],
        "engineering": [
            _mcp_turn(ENV_ALIAS, {}, "mcp-env-1"),
            _mcp_turn(ENV_ALIAS, {}, "mcp-env-2"),
            FakeTurn(transcript="调用完成"),
        ],
        "quality": [explore_turn(), explore_turn(), explore_turn()],
    })
    project_id = _project_with_server(system)
    run_id = _work_item_run(system, project_id)
    system.run_until_stop(run_id)

    first = _result_of(system, run_id, _tool_called(system, run_id, "mcp-env-1"))
    second = _result_of(system, run_id, _tool_called(system, run_id, "mcp-env-2"))
    assert first["is_error"] is False and second["is_error"] is False

    def _pid(result):
        # environment 工具把进程号放在 structuredContent 里（结果工件的一行）
        return json.loads("".join(line["text"] for line in result["lines"]))["pid"]

    server_pid = _pid(first)
    assert _pid(second) == server_pid, "两次调用用了两个服务器进程：会话实例没有被复用"

    table = system.orchestrator.mcp_sessions(run_id)
    assert not table.open and table.sessions() == {}, "run 结束时会话表没有清空"
    assert not psutil.pid_exists(server_pid), "run 结束以后服务器进程还活着"
    system.close()


def test_an_alias_outside_the_item_definitions_is_refused(tmp_path):
    # 别名不在这个事项的定义副本里（例如别的工具名）：工具许可拒绝，回执带被拒绝标记与原因，
    # 执行环境没有被调用（没有 tool_started）
    stranger = "mcp__time__no_such_tool"
    identity = "stranger"
    call = {"id": identity, "call_id": identity, "type": "function_call", "name": stranger,
            "arguments": json.dumps({"text": "x"})}
    system = _system(tmp_path, {
        "product": [product_spec_turn()],
        "engineering": [ModelResponse(output=[call]), FakeTurn(transcript="调用完成")],
        "quality": [explore_turn(), explore_turn(), explore_turn()],
    })
    project_id = _project_with_server(system)
    run_id = _work_item_run(system, project_id)
    system.activate_once(run_id)
    system.activate_once(run_id)

    events = system.store.list_events(run_id)
    called = next(event for event in events
                  if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == identity)
    assert called.payload["ok"] is False and called.payload["refused"] is True
    assert "cannot use" in (called.payload["error"] or "")
    assert not any(event.type == EventType.TOOL_STARTED and (event.payload or {}).get("id") == identity
                   for event in events), "被拒绝的调用有工具开始事件"
    system.close()

def test_the_run_actions_query_carries_the_mcp_receipt(tmp_path):
    # run.actions 的动作视图（网络与 MCP 设计说明第 10 节）：MCP 调用带回执字段与外部来源工件引用
    from harness.app.application import Application
    from harness.app.project_queries import RunActions

    system = _system(tmp_path, {
        "product": [product_spec_turn()],
        "engineering": [_echo_turn("查询"), FakeTurn(transcript="调用完成")],
        "quality": [explore_turn(), explore_turn(), explore_turn()],
    })
    project_id = _project_with_server(system)
    run_id = _work_item_run(system, project_id)
    system.activate_once(run_id)
    system.activate_once(run_id)

    application = Application(system)
    try:
        snapshot = application.query("run.actions", RunActions(run_id=run_id))
    finally:
        application.close()
    actions = [action for action in snapshot.data.actions if action.tool == ALIAS]
    assert len(actions) == 1 and actions[0].status == "completed"
    receipt = actions[0].receipt
    assert receipt is not None and receipt.ok and receipt.refused is False
    output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**receipt.output_ref)))
    assert output["server"] == "time" and output["tool"] == "echo"
    assert output["ref"]["kind"] == "external_source"
    system.close()


def test_credential_values_do_not_appear_in_events_or_artifacts(tmp_path):
    # 凭据值不进入事件、工件与日志（设计说明第 4.4 节）：值只以名称与脱敏后的星号出现在保存的内容里
    system = _system(tmp_path, {
        "product": [product_spec_turn()],
        "engineering": [_echo_turn("凭据"), FakeTurn(transcript="调用完成")],
        "quality": [explore_turn(), explore_turn(), explore_turn()],
    })
    project_id = _project_with_server(system)
    run_id = _work_item_run(system, project_id)
    system.activate_once(run_id)
    system.activate_once(run_id)

    events = json.dumps([event.to_dict() for event in system.store.list_events(run_id)], ensure_ascii=False)
    assert SECRET not in events
    output = _result_of(system, run_id, _tool_called(system, run_id, "mcp-凭据"))
    artifact = system.artifacts.get_for_run(run_id, ArtifactRef(**output["ref"])).decode("utf-8")
    assert SECRET not in artifact
    system.close()



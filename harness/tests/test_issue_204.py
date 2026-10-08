# 工单 #204 的验收：run 因模型连续不调用工具（no_tool_call）或者工作区出现无法表示的条目
# （workspace_unrepresentable）而暂停时发出决定请求，用户回答以后从暂停位置继续，或者停止事项。
# 测试从 LoopSystem 整体驱动，使用真实的文件系统、真实的 Git 与真实的登记命令进程；FakeAdapter 只给出模型的回答。

from __future__ import annotations

import json
import os

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.decision_queries import DecisionsList
from harness.decisions import RESUMABLE_PAUSE_KINDS
from harness.definitions import DEFINITIONS
from harness.event_store import Command
from harness.models import EventType, new_id
from harness.projection import saved_decisions
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.contract_checks import assert_payloads_follow_contract
from harness.tests.helpers import TOOL_CALL_REQUIRED_LIMIT as LIMIT

REGISTRY = {"make-link": {"argv": ["python", "make_link.py"], "args": ["nested", "linked"],
                          "timeout_sec": 30, "output_limit": 4000}}

def _events(system, run_id, event_type):
    return [event for event in system.store.list_events(run_id) if event.type == event_type]

def _open_decisions(system, run_id):
    # 按保存的投影列出这个 run 未回答的决定请求
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    return [decision for decision in decisions if decision.run_id == run_id]

def _answer(system, decision, option):
    command = Command(new_id("cmd"), "decision.answer", f"sha256:{option}:{decision.version}", "user:local")
    return system.orchestrator.answer_decision(decision.decision_id, option, None,
                                               base_version=decision.version, command=command)

def _plain_reply():
    # 部门回复文字、没有调用工具；连续若干次以后主机要求调用工具，fake 回答仍不调用工具，run 以 no_tool_call 暂停
    return lambda _call: FakeTurn(transcript="先整理一下思路，稍后提交。")

def _completion_script():
    return [plan_turn(), delivery_turn(), review_turn("release", "checks passed on the current snapshot")]

def _no_tool_call_run(tmp_path, tail=None):
    script = [_plain_reply() for _ in range(LIMIT + 1)]
    if tail is not None:
        script.extend(tail)
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_id = system.create_run("build echo")
    result = system.run_until_stop(run_id)
    return system, run_id, result

def test_no_tool_call_pause_requests_a_decision(tmp_path):
    # 模型连续第 LIMIT+1 次没有调用工具：暂停并发出决定请求
    system, run_id, result = _no_tool_call_run(tmp_path)
    assert result.phase == "PAUSED" and result.stop_reason == "no_tool_call"
    [pause] = _events(system, run_id, EventType.RUN_PAUSED)
    assert pause.payload["paused_at_phase"] == "PRODUCT_SPEC"
    opened = _open_decisions(system, run_id)
    assert len(opened) == 1, [decision.decision_id for decision in opened]
    request = opened[0].request
    assert (request["kind"], request["blocks"]) == ("no_tool_call", "run")
    assert [option["id"] for option in request["options"]] == ["continue", "stop"]
    assert [option["label"] for option in request["options"]] == ["处理以后继续执行", "停止事项"]
    # 说明写明停止原因与人工处理说明
    assert "no_tool_call" in request["description"]
    assert DEFINITIONS.stop_reason("no_tool_call").human_action in request["description"]
    # 写入的事件符合应用层合同的载荷类型
    assert_payloads_follow_contract(system.store.list_events(run_id))
    system.close()

def test_pause_decision_is_listed_by_the_query_with_its_options(tmp_path):
    # 首页与项目页面的决定卡片据 decisions.list 显示选项：暂停请求经查询返回，选项与说明齐全
    system, run_id, _result = _no_tool_call_run(tmp_path)
    [decision] = _open_decisions(system, run_id)
    application = Application(system)
    listed = application.query("decisions.list", DecisionsList(status=["open"]))
    [view] = [item for item in listed.data.decisions if item.decision_id == decision.decision_id]
    assert (view.kind, view.blocks, view.run_id) == ("no_tool_call", "run", run_id)
    assert [option.id for option in view.request.options] == ["continue", "stop"]
    assert [option.label for option in view.request.options] == ["处理以后继续执行", "停止事项"]
    assert view.request.resumed_at_phase == "PRODUCT_SPEC"
    assert view.request.stop_reason == "no_tool_call"
    application.close()

def test_no_tool_call_continue_resumes_from_the_paused_phase(tmp_path):
    # 回答继续以后 run 从暂停位置（PRODUCT_SPEC）继续，接着走完三部门并完成
    system, run_id, result = _no_tool_call_run(tmp_path, tail=[product_spec(), *_completion_script()])
    paused_cycle = result.cycle_count
    paused_requests = len(_events(system, run_id, EventType.MODEL_REQUESTED))
    [decision] = _open_decisions(system, run_id)
    assert _answer(system, decision, "continue") == run_id
    finished = system.run_until_stop(run_id)

    assert finished.phase == "DONE", (finished.phase, finished.stop_reason)
    # 继续写成事件，恢复到暂停时的阶段
    [continued] = _events(system, run_id, EventType.RUN_CONTINUED)
    assert continued.payload["resumed_at_phase"] == "PRODUCT_SPEC"
    assert continued.payload["decision_id"] == decision.decision_id
    assert continued.payload["stop_reason"] == "no_tool_call"
    # 已用的激活次数与模型步数连续，不重新计算：继续之前的事件与计数都保留
    assert finished.cycle_count >= paused_cycle
    assert len(_events(system, run_id, EventType.MODEL_REQUESTED)) > paused_requests
    # 暂停的停止原因在继续以后不再出现在运行状态上：运行到达放行结束
    assert finished.stop_reason == "released"
    assert finished.phase == "DONE"
    system.close()

def test_no_tool_call_without_handling_pauses_again_with_a_new_request(tmp_path):
    # 没有处理（模型仍不调用工具）就回答继续：从原位置继续以后再次暂停，并发出新的决定请求
    script = [_plain_reply() for _ in range(2 * (LIMIT + 1))]
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_id = system.create_run("build echo")
    assert system.run_until_stop(run_id).stop_reason == "no_tool_call"
    [first] = _open_decisions(system, run_id)
    assert _answer(system, first, "continue") == run_id
    result = system.run_until_stop(run_id)

    assert result.phase == "PAUSED" and result.stop_reason == "no_tool_call"
    opened = _open_decisions(system, run_id)
    assert len(opened) == 1, [decision.decision_id for decision in opened]
    assert opened[0].decision_id != first.decision_id
    assert len(_events(system, run_id, EventType.DECISION_REQUESTED)) == 2
    system.close()

def test_no_tool_call_stop_keeps_the_run_paused_with_the_same_reason(tmp_path):
    # 回答停止：事项停止，停止原因保持暂停时的原因
    system, run_id, _result = _no_tool_call_run(tmp_path)
    [decision] = _open_decisions(system, run_id)
    assert _answer(system, decision, "stop") is None
    projection = system.project(run_id)
    assert projection.phase == "PAUSED" and projection.stop_reason == "no_tool_call"
    # 停止以后没有继续事件，也没有新的决定请求
    assert _events(system, run_id, EventType.RUN_CONTINUED) == []
    assert _open_decisions(system, run_id) == []
    system.close()

def test_second_no_tool_call_pause_after_the_first_continue_is_a_fresh_count(tmp_path):
    # 继续以后连续不调用工具的计数从零开始：继续之后再连续 LIMIT 次仍不调用工具也不暂停，
    # 第 LIMIT+1 次换成提交产品要求并走完三部门
    script = [*[_plain_reply() for _ in range(LIMIT + 1)],
              *[_plain_reply() for _ in range(LIMIT)], product_spec(), *_completion_script()]
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_id = system.create_run("build echo")
    assert system.run_until_stop(run_id).stop_reason == "no_tool_call"
    [first] = _open_decisions(system, run_id)
    assert _answer(system, first, "continue") == run_id
    finished = system.run_until_stop(run_id)

    # 继续以后的 LIMIT 次只回复文字没有触发暂停，第 LIMIT+1 次换成了提交产品要求
    assert finished.phase == "DONE", (finished.phase, finished.stop_reason)
    assert finished.stop_reason != "no_tool_call"
    system.close()

def _write_command_body(workspace, outside):
    workspace.write_file("make_link.py", (
        "import os, sys\n"
        "from pathlib import Path\n"
        f"outside = Path(r'{outside}')\n"
        "target = Path('node_modules') / sys.argv[1]\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        "os.symlink(outside, target)\n"
    ))

def _command_call(identity, name="make-link", args=None):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "run_command",
            "arguments": json.dumps({"name": name, "args": args or []})}

def _workspace_unrepresentable_run(tmp_path, tail):
    outside = tmp_path / "outside.txt"
    outside.write_text("VALUE = 9\n", encoding="utf-8")
    try:
        os.symlink(outside, tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")

    def link_then(request):
        return ModelResponse(output=[_command_call("cmd-link", "make-link", ["linked"])])

    # 产品先提交产品要求，工程提交计划，工步建立链接（node_modules/linked）导致公开树无法表示
    system = LoopSystem.for_testing(tmp_path / "data",
                                    FakeAdapter([product_spec(), plan_turn(), link_then, tail]))
    run_id = system.create_run("A link pauses the run", registered_commands=REGISTRY,
                               command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    _write_command_body(workspace, outside)
    result = system.run_until_stop(run_id)
    return system, run_id, workspace, result

def test_workspace_unrepresentable_pause_requests_a_decision_with_the_paths(tmp_path):
    system, run_id, workspace, result = _workspace_unrepresentable_run(tmp_path, delivery_turn())
    assert result.phase == "PAUSED" and result.stop_reason == "workspace_unrepresentable"
    [pause] = _events(system, run_id, EventType.RUN_PAUSED)
    assert pause.payload["paused_at_phase"] == "ENGINEERING"
    [decision] = _open_decisions(system, run_id)
    request = decision.request
    assert (request["kind"], request["blocks"]) == ("workspace_unrepresentable", "run")
    assert [option["id"] for option in request["options"]] == ["continue", "stop"]
    assert [option["label"] for option in request["options"]] == ["处理以后继续执行", "停止事项"]
    # 说明写明停止原因与人工处理说明，条目按工作区内的相对路径列出
    assert DEFINITIONS.stop_reason("workspace_unrepresentable").human_action in request["description"]
    assert "node_modules/linked" in request["facts"]
    assert all(not os.path.isabs(item) for item in request["facts"])
    system.close()

def test_workspace_unrepresentable_continue_after_ignoring_the_entry_completes(tmp_path):
    # 把条目加入忽略规则以后回答继续，run 从原位置（ENGINEERING）继续并完成
    system, run_id, workspace, result = _workspace_unrepresentable_run(tmp_path, delivery_turn())
    [decision] = _open_decisions(system, run_id)
    workspace.write_file(".gitignore", "node_modules/\n")
    assert _answer(system, decision, "continue") == run_id
    system.test_adapter.script.extend([review_turn("release", "checks passed on the current snapshot")])
    finished = system.run_until_stop(run_id)
    assert finished.phase == "DONE", (finished.phase, finished.stop_reason)
    [continued] = _events(system, run_id, EventType.RUN_CONTINUED)
    assert continued.payload["resumed_at_phase"] == "ENGINEERING"
    system.close()

def test_workspace_unrepresentable_continue_without_handling_pauses_again(tmp_path):
    # 没有处理就回答继续：再次暂停并发出新的请求
    system, run_id, workspace, result = _workspace_unrepresentable_run(tmp_path, delivery_turn())
    [first] = _open_decisions(system, run_id)
    assert _answer(system, first, "continue") == run_id
    # 继续以后的第一次请求装配仍然发现无法表示的条目：再次以同一原因暂停
    again = system.run_until_stop(run_id)
    assert again.phase == "PAUSED" and again.stop_reason == "workspace_unrepresentable"
    opened = _open_decisions(system, run_id)
    assert len(opened) == 1 and opened[0].decision_id != first.decision_id
    system.close()

def test_workspace_unrepresentable_stop_keeps_the_run_paused(tmp_path):
    system, run_id, workspace, _result = _workspace_unrepresentable_run(tmp_path, delivery_turn())
    [decision] = _open_decisions(system, run_id)
    assert _answer(system, decision, "stop") is None
    projection = system.project(run_id)
    assert projection.phase == "PAUSED" and projection.stop_reason == "workspace_unrepresentable"
    system.close()

def test_max_cycles_pause_does_not_request_a_decision(tmp_path):
    # max_cycles 暂停不发出这个请求
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter([product_spec(), *_completion_script()]))
    run_id = system.create_run("build echo", max_cycles=1)
    result = system.run_until_stop(run_id)
    assert result.phase == "PAUSED" and result.stop_reason == "max_cycles"
    assert _open_decisions(system, run_id) == []
    assert _events(system, run_id, EventType.DECISION_REQUESTED) == []
    system.close()

def test_model_steps_exhausted_pause_does_not_request_a_decision(tmp_path):
    # model_steps_exhausted 暂停不发出这个请求（模型步数上限设为 1，第一次回复文字即耗尽）
    from harness.engine import StepLimits
    limits = StepLimits(max_model_steps=1)
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter([_plain_reply(), product_spec()]),
                                    step_limits=limits)
    run_id = system.create_run("build echo")
    result = system.run_until_stop(run_id)
    assert result.phase == "PAUSED" and result.stop_reason == "model_steps_exhausted"
    assert _open_decisions(system, run_id) == []
    system.close()

def test_pause_decision_kinds_are_registered(tmp_path):
    # 两种决定种类登记在决定合同里，能力清单与查询都能看到
    assert set(RESUMABLE_PAUSE_KINDS) == {"no_tool_call", "workspace_unrepresentable"}

def _text_only_reply(text: str) -> bytes:
    # Responses 协议下只回复文字、没有工具调用的回复
    item = {"id": "message-1", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}
    response = {
        "id": "resp-text", "object": "response", "created_at": 1, "status": "completed", "model": "m",
        "output": [item], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "error": None, "incomplete_details": None,
    }
    frames = [
        f"event: response.created\ndata: {json.dumps({'type': 'response.created', 'response': {**response, 'status': 'in_progress', 'output': [], 'usage': None}})}\n\n",
        f"event: response.output_item.done\ndata: {json.dumps({'type': 'response.output_item.done', 'output_index': 0, 'item': item})}\n\n",
        f"event: response.completed\ndata: {json.dumps({'type': 'response.completed', 'response': response})}\n\n",
    ]
    return "".join(frames).encode("utf-8")

def _spec_reply() -> bytes:
    payload = product_spec()
    payload.pop("kind")
    item = {"id": "spec-1", "type": "function_call", "call_id": "spec-1",
            "name": "submit_product_spec", "arguments": json.dumps(payload, ensure_ascii=False)}
    response = {
        "id": "resp-spec", "object": "response", "created_at": 1, "status": "completed", "model": "scenario-model",
        "output": [item], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        "error": None, "incomplete_details": None,
    }
    frames = [
        f"event: response.created\ndata: {json.dumps({'type': 'response.created', 'response': {**response, 'status': 'in_progress', 'output': [], 'usage': None}})}\n\n",
        f"event: response.output_item.done\ndata: {json.dumps({'type': 'response.output_item.done', 'output_index': 0, 'item': item})}\n\n",
        f"event: response.completed\ndata: {json.dumps({'type': 'response.completed', 'response': response})}\n\n",
    ]
    return "".join(frames).encode("utf-8")

def test_no_tool_call_continue_uses_the_model_changed_before_answering(tmp_path):
    # no_tool_call：用户在回答继续之前在部门设置中更换模型，从下一次请求起生效
    from harness.models import DEPARTMENTS
    from harness.providers import CredentialChain, ProviderFacade
    from harness.tests.protocol_helpers import serve

    requests: list[dict] = []

    def responder(body):
        requests.append(body)
        # 产品部门在前 LIMIT+1 次只回复文字，触发 no_tool_call 暂停；换模型后由新的模型提交产品要求
        if len(requests) <= LIMIT + 1:
            return 200, "text/event-stream", [_text_only_reply("先整理一下思路，稍后提交。")]
        return 200, "text/event-stream", [_spec_reply()]

    server, _capture, base = serve(responder)
    try:
        facade = ProviderFacade(credentials=CredentialChain(overrides={"SCENARIO_KEY": "secret"}, use_env=False))
        facade.store_document({
            "providers": [{"id": "local", "name": "Local", "protocol": "responses", "base_url": base + "/v1",
                           "credential_ref": "SCENARIO_KEY", "timeout_sec": 20.0}],
            "models": [
                {"id": "m-a", "provider_id": "local", "model": "model-a", "context_window": 32000,
                 "max_output_tokens": 2048},
                {"id": "m-b", "provider_id": "local", "model": "model-b", "context_window": 32000,
                 "max_output_tokens": 2048},
            ],
            "bindings": {department: {"provider_id": "local", "model_id": "m-a"} for department in DEPARTMENTS},
        })
        facade.record_admission("local", "m-a", admitted_model="model-a")
        facade.record_admission("local", "m-b", admitted_model="model-b")
        system = LoopSystem(tmp_path / "data", facade=facade)
        run_id = system.create_run("build an echo CLI")
        result = system.run_until_stop(run_id)
        assert result.phase == "PAUSED" and result.stop_reason == "no_tool_call"
        [decision] = _open_decisions(system, run_id)

        # 在部门设置中把产品部门的模型换成 m-b
        bindings = facade.get_bindings()
        bindings["product"] = {"provider_id": "local", "model_id": "m-b"}
        facade.save_bindings(bindings)
        before = len(requests)

        assert _answer(system, decision, "continue") == run_id
        system.activate_once(run_id)
        assert len(requests) > before
        # 下一次请求使用新的调用目标（model-b）
        assert requests[-1]["model"] == "model-b"
        system.close()
    finally:
        server.shutdown()
        server.server_close()

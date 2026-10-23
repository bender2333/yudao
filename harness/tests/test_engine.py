import json
import time
from concurrent.futures import ThreadPoolExecutor

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.context import ContextAssembler
from harness.definitions import DEFINITIONS
from harness.models import ArtifactRef, DepartmentPrompt, EventType, canonical_hash, estimate_tokens, json_dumps
from harness.proposals import answer_turn, delivery_turn, product_spec, review_turn
from harness.providers.call import CallUsage, ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import (FAST_RETRIES, after_event, explore_turn, recorded_context,
                                   from_another_thread, run_wait_command, wait_for_file)
from harness.tests.protocol_helpers import complete, model_call

def _call(identity, name, **args):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(args)}

def _submit(identity="submit"):
    proposal = product_spec()
    proposal.pop("kind")
    return _call(identity, "submit_product_spec", **proposal)

def change_product_model(system: LoopSystem, upstream_model: str) -> None:
    # 运行中更换模型：确定性测试适配器登记的上游模型名取自编排器，在下一次解析时生效（#45 架构答复第 6 条）
    system.orchestrator.test_model = upstream_model

def test_fake_adapter_has_no_workspace_and_does_not_execute_tools(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("echo")
    # 部门 Prompt 来自项目部门设置，run 内没有副本；不属于项目的运行使用内置默认 Prompt
    context = ContextAssembler().assemble(
        system.project(run_id), department="engineering", session_id="session", activation_id="activation",
        prompt=DepartmentPrompt(department="engineering", version=0,
                                text=DEFINITIONS.role("engineering").prompt,
                                prompt_ref=ArtifactRef(kind="department_prompt", content_hash="", path=""),
                                created_event_id=""))
    call = model_call(context.input_items, context.tools)
    adapter = FakeAdapter([FakeTurn(writes={"owned.txt": "content"})])
    response = complete(adapter, call)
    assert not hasattr(call, "workspace")
    assert not hasattr(adapter, "invoke")
    assert response.output[0]["name"] == "write_file"
    assert json.loads(response.output[0]["arguments"]) == {"path": "owned.txt", "content": "content"}
    assert not (tmp_path / "owned.txt").exists()

def test_each_step_assembles_auditable_input_with_only_current_activation_history(tmp_path):
    reasoning = {"id": "reason-1", "type": "reasoning", "summary": [], "encrypted_content": "PRIVATE_CHAIN"}
    lookup = _call("read-1", "read_file", path="proof.txt")
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    adapter = FakeAdapter({
        "product": [
            ModelResponse(output=[lookup], reasoning={"provider_id": "fake", "protocol": "fake",
                                                      "model": "fake-script", "items": [reasoning]}),
            ModelResponse(output=[_submit(), _call("after-submit", "read_file", path="must-not-read.txt")]),
        ],
        # 工程先拿着过期依据提交被拒，再按当前版本重交（工单 #471、#499）：
        # 提交的历史留在本部门，工程的第二次请求看得到它，别的部门看不到
        "engineering": [delivery_turn(basis_product_spec_hash="stale"), delivery_turn()],
        # 质检在交付到达以前有一轮预测性探索（工单 #557），交付到达以后才核验
        "quality": [explore_turn(), review_turn("release", "valid host evidence")],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.workspace(run_id).write_file("proof.txt", "CAUSAL_TOOL_OUTPUT")
    result = system.run_until_stop(run_id)
    assert result.status == "done"
    # 步骤编号按各自的会话算：产品的两次请求在同一次激活里（1、2），别的部门各自是新激活的第一步
    steps = [(request.department, request.step_id) for request in adapter.invocations]
    assert steps[:2] == [("product", 1), ("product", 2)]
    assert sorted(steps[2:]) == [("engineering", 1), ("engineering", 1), ("quality", 1), ("quality", 1)]
    by_department: dict[str, list] = {}
    for request in adapter.invocations:
        by_department.setdefault(request.department, []).append(request)
    # 同一连接、同一协议、同一上游模型时推理内容原样回放，紧接它产生的那次输出（工单 #88）
    replayed = adapter.invocations[1].input_items[2]
    assert replayed["id"] == "reason-1" and replayed["encrypted_content"] == "PRIVATE_CHAIN"
    assert adapter.invocations[1].input_items[3] == lookup
    tool_input = adapter.invocations[1].input_items[4]
    assert tool_input["call_id"] == "read-1"
    assert json.loads(tool_input["output"])["output"] == "CAUSAL_TOOL_OUTPUT"
    for request in adapter.invocations[2:]:
        assert "PRIVATE_CHAIN" not in json_dumps(request.input_items)
        assert "CAUSAL_TOOL_OUTPUT" not in json_dumps(request.input_items)
        assert request.input_items[-1]["role"] == "user"
    # 每个部门第一次请求的输入只有当前状态与工作说明两段
    assert len(by_department["engineering"][0].input_items) == 2
    assert len(by_department["quality"][0].input_items) == 2
    assert any(item.get("name") == "submit_delivery" for item in by_department["engineering"][1].input_items)
    events = system.store.list_events(run_id)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "after-submit" for event in events)
    assert any(event.type == EventType.MODEL_REASONING and event.model == "fake-script"
               for event in events)
    contexts = [event for event in events if event.type == EventType.CONTEXT_ASSEMBLED]
    assert len(contexts) == len(adapter.invocations)
    # 同时运行的会话各自装配自己的上下文：按激活与步骤对上，不按先后（工单 #557）
    by_step = {(event.payload["activation_id"], event.payload["step_id"]): event for event in contexts}
    for request in adapter.invocations:
        event = by_step[(request.activation_id, request.step_id)]
        saved = json.loads(system.artifacts.get_text(event.payload["request_ref"]["content_hash"]))
        expected = {"input": request.input_items, "tools": request.tools}
        if request.max_output_tokens is not None:
            # 调用目标声明了输出上限时随请求发出，记录下来的工件与发出的请求一致
            expected["max_output_tokens"] = request.max_output_tokens
        assert saved == expected
        assert event.context_digest == canonical_hash(saved) == recorded_context(system, request).manifest.digest
        assert event.payload["token_estimate"] == estimate_tokens(json_dumps(saved))
        assert event.payload["admitted"]
        assert event.payload["request_ref"]["content_hash"] in event.artifact_hashes
    assert result.canonical_state() == system.replay(run_id).canonical_state()

def test_large_history_requests_compaction_and_rejects_submit_in_summary_response(tmp_path):
    # A tool call in a tool-less summary request is malformed provider output: it is retried
    # within the attempt limit and never executed, so three of them fail the compaction.
    adapter = FakeAdapter([ModelResponse(output=[_call("read-1", "read_file", path="proof.txt")],
                                         usage=CallUsage(total_tokens=100, reported=True)),
                           product_spec(), product_spec(), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo", context_window=6000)
    system.workspace(run_id).write_file("proof.txt", "x" * 40000)
    result = system.activate_once(run_id)
    assert len(adapter.invocations) == 4
    assert all(request.purpose == "compaction" and request.tools == [] for request in adapter.invocations[1:])
    assert [request.attempt for request in adapter.invocations[1:]] == [1, 2, 3]
    assert result.stop_reason == "compaction_failed"
    assert result.token_used == 100
    assert len(result.manifests) == 4
    assert result.manifests[-1].admitted
    events = system.store.list_events(run_id)
    assert sum(event.type == EventType.MODEL_REQUESTED for event in events) == 4
    assert not any(event.type == EventType.SPEC_ACCEPTED for event in events)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == "submit_product_spec"
                   for event in events)
    tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    assert tool.payload["input_item"]["call_id"] == "read-1"
    assert tool.payload["output_ref"]

def test_cancel_after_context_preparation_prevents_model_attempt(tmp_path):
    # 请求装配完成以后，另一个线程取消运行：取消在开始请求之前提交，这一步不开始模型调用
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    cancelled = []
    waiting = []
    after_event(system, EventType.CONTEXT_ASSEMBLED, lambda _event: waiting.append(
        from_another_thread(lambda: cancelled.append(system.cancel(run_id).stop_reason))))

    result = system.activate_once(run_id)

    [canceller] = waiting
    assert not canceller.errors
    assert cancelled == ["cancelled"]
    assert result.stop_reason == "cancelled"
    assert not adapter.invocations
    assert result.token_used == 0
    assert result.manifests[0].admitted
    assert not any(event.type == EventType.MODEL_REQUESTED for event in system.store.list_events(run_id))

def test_cancel_before_tool_start_rejects_new_side_effect(tmp_path):
    def cancel_during_request(_call):
        system.cancel(run_id)
        return ModelResponse(output=[_call("write-1", "write_file", path="new.txt", content="new")])

    adapter = FakeAdapter([product_spec(), cancel_during_request])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    result = system.activate_once(run_id)
    assert result.stop_reason == "cancelled"
    assert "new.txt" not in system.workspace(run_id).list_files()
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "write-1" for event in system.store.list_events(run_id))

def _command_run(tmp_path, script):
    # 工程部门的激活之前：产品规格已接纳
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), *script]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    return system, run_id

def _command_call(identity, command):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "bash",
            "arguments": json_dumps({"command": command})}

def _tool_output(system, run_id, identity):
    called = next(event for event in system.store.list_events(run_id)
                  if event.type == EventType.TOOL_CALLED and event.payload.get("id") == identity)
    output = None
    if "output_ref" in called.payload:
        output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**called.payload["output_ref"])))
    return called, output

def test_cancel_stops_the_running_command_and_does_not_start_following_tool(tmp_path):
    # bash 命令运行中另一个线程取消运行：进程树结束，回执记为已取消，之后的工具不开始
    signals = tmp_path / "signals"
    signals.mkdir()
    system, run_id = _command_run(tmp_path, [ModelResponse(output=[
        _command_call("command-1", run_wait_command(signals)), _call("write-2", "write_file", path="later.txt", content="later")])])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        wait_for_file(signals / "started")
        started = time.monotonic()
        assert system.cancel(run_id).stop_reason == "cancelled"
        result = future.result(timeout=20)
    assert time.monotonic() - started < 10
    assert not (signals / "release").exists()
    assert "later.txt" not in system.workspace(run_id).list_files()
    called, output = _tool_output(system, run_id, "command-1")
    assert called.payload["ok"] is True and called.state_before == "failed"
    assert output["status"] == "cancelled" and output["exit_code"] == 130
    assert output["output"].endswith("command cancelled; the process tree was stopped")
    events = system.store.list_events(run_id)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "write-2" for event in events)
    assert [event.payload["id"] for event in events if event.type == EventType.TOOL_SKIPPED] == ["write-2"]
    assert result.stop_reason == "cancelled"
    assert result.canonical_state() == system.replay(run_id).canonical_state()

def test_cancel_after_the_tool_permission_does_not_start_the_process(tmp_path):
    # 工具许可已经允许、动作还没有开始时取消到达（在 tool_started 提交的时点、写入方的线程中取消）：进程不启动
    signals = tmp_path / "signals"
    signals.mkdir()
    system, run_id = _command_run(tmp_path, [ModelResponse(output=[_command_call("command-1", run_wait_command(signals))])])
    after_event(system, EventType.TOOL_STARTED, lambda _event: system.cancel(run_id))
    result = system.activate_once(run_id)
    assert result.stop_reason == "cancelled"
    assert not (signals / "started").exists()
    called, output = _tool_output(system, run_id, "command-1")
    assert called.payload["ok"] is False and output is None
    assert called.payload["error"] == "The action was cancelled before it started."
    assert result.canonical_state() == system.replay(run_id).canonical_state()

def test_original_intend_is_preserved_verbatim_outside_the_delivery_tree(tmp_path):
    original = "  Original request\r\n\r\nKeep these spaces.  \n\t"
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run(original)
    result = system.activate_once(run_id)
    assert result.task == original
    assert (tmp_path / "materials" / run_id / "intend.md").read_bytes() == original.encode("utf-8")
    assert system.artifacts.get_text(result.intend_ref["content_hash"]) == original
    assert "intend.md" not in system.workspace(run_id).list_files()
    assert adapter.invocations[0].input_items[0]["content"].startswith(f"[intend]\n{original}\n\n[current_work]\n")
    assert result.canonical_state() == system.replay(run_id).canonical_state()

def test_reactivated_department_restores_its_received_work_outputs_and_complete_submit_pairs(tmp_path):
    private = {"id": "product-private", "type": "reasoning", "summary": [], "encrypted_content": "PRODUCT_PRIVATE"}
    skipped = _call("skip-read", "read_file", path="never-read.txt")
    scripts = {
        "product": [
            ModelResponse(output=[private, _submit(), skipped]),
        ],
        "engineering": [
            ModelResponse(output=[
                {"id": "eng-msg", "type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "ENGINEERING_PRIVATE"}]},
                _call("ask-1", "ask", recipient="product",
                      question="Need clarification?",
                      background="Clarification",
                      expected="The existing requirements define the current behavior."),
            ]),
            delivery_turn(),
        ],
        "product:ask": [
            answer_turn("The existing requirements define the current behavior."),
        ],
        "quality": [
            review_turn("release", "valid host evidence"),
        ],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("Original intent")
    system.activate_once(run_id)
    system.activate_once(run_id)
    # 运行中更换模型：再次激活前换一个上游模型，来源不同，推理内容不再回放（工单 #88）
    change_product_model(system, "other-model")
    # A fresh controller restores history from persisted events, not in-memory provider state.
    reloaded = LoopSystem.for_testing(tmp_path, adapter, resume_on_startup=False)
    result = reloaded.run_until_stop(run_id)
    assert result.status == "done", result.error
    resumed_product = adapter.invocations[2]
    history = resumed_product.input_items[1:]
    assert history[0]["role"] == "user"
    assert "current_work" in history[0]["content"]
    assert private not in history
    assert "PRODUCT_PRIVATE" not in json_dumps(history)
    assert "ENGINEERING_PRIVATE" not in json_dumps(history)
    assert history[-1]["role"] == "user"
    assert "[pending_ask]" in history[-1]["content"]
    assert "answer" in history[-1]["content"]
    assert history[-2]["type"] == "function_call_output"
    assert any(item.get("call_id") == "submit" and item["type"] == "function_call_output" for item in history)
    skipped_result = next(item for item in history if item.get("call_id") == "skip-read" and item["type"] == "function_call_output")
    assert json.loads(skipped_result["output"])["ok"] is False
    assert "Not executed" in skipped_result["output"]
    call_ids = [item["call_id"] for item in history if item.get("type") == "function_call"]
    output_ids = [item["call_id"] for item in history if item.get("type") == "function_call_output"]
    assert call_ids == output_ids
    engineering = adapter.invocations[3]
    assert "ENGINEERING_PRIVATE" in json_dumps(engineering.input_items)
    assert "PRODUCT_PRIVATE" not in json_dumps(engineering.input_items)
    assert engineering.input_items[-1]["type"] == "function_call_output"
    assert engineering.input_items[-1]["call_id"] == "ask-1"
    assert "The existing requirements define the current behavior." in engineering.input_items[-1]["output"]
    assert engineering.input_items[-2]["type"] == "function_call"
    assert engineering.input_items[-2]["name"] == "ask"
    events = reloaded.store.list_events(run_id)
    assert any(event.type == EventType.TOOL_SKIPPED and event.payload["id"] == "skip-read" for event in events)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "skip-read" for event in events)

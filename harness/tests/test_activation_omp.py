import json
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from harness.adapters.base import AdapterResult, InvokeRequest
from harness.adapters.omp import OmpConfig, OmpRpcAdapter, map_omp_frame
from harness.context import ContextAssembler
from harness.models import EventType, RunProjection
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tools import ToolRuntime
from harness.workspace import Workspace


def _request(tmp_path):
    context = ContextAssembler().assemble(RunProjection(task="echo"), department="product", session_id="ses", activation_id="act")
    return InvokeRequest("run", "product", "ses", "act", context, ["read_file"], Workspace(tmp_path / "ws"), Event())


def _rpc_script(tmp_path, *, timeout=False):
    messages = [
        {"role": "assistant", "timestamp": 1, "content": json.dumps(product_spec()),
         "usage": {"input": 10, "output": 20, "cacheRead": 80, "cacheWrite": 0, "totalTokens": 110,
                   "reasoning": 9, "cost": {"input": 9, "output": 9, "cacheRead": 9, "total": 0.11}}},
        {"role": "assistant", "timestamp": 1, "content": json.dumps(product_spec()),
         "usage": {"input": 11, "output": 22, "cacheRead": 100, "cacheWrite": 7, "totalTokens": 140,
                   "reasoning": 10, "cost": {"input": 8, "output": 8, "cacheRead": 8, "total": 0.14}}},
    ]
    path = tmp_path / "rpc.py"
    path.write_text(
        "import json, sys, time\n"
        f"messages = {messages!r}\n"
        "def emit(value): print(json.dumps(value), flush=True)\n"
        "emit({'type':'ready','supportedProtocolVersions':[1]})\n"
        "for line in sys.stdin:\n"
        "    frame = json.loads(line)\n"
        "    if frame['type'] == 'set_host_tools':\n"
        "        emit({'type':'response','id':frame['id'],'success':True})\n"
        "    elif frame['type'] == 'prompt':\n"
        "        emit({'type':'message_update','message':messages[0]})\n"
        "        emit({'type':'message_update','message':messages[0]})\n"
        "        emit({'type':'message_end','message':messages[0]})\n"
        "        emit({'type':'host_tool_call','id':'rpc-read','toolCallId':'model-read','toolName':'read_file','arguments':{'path':'proof.txt'}})\n"
        "    elif frame['type'] == 'host_tool_result':\n"
        "        emit({'type':'tool_execution_end','toolCallId':'model-read','toolName':'read_file','isError':False})\n"
        + ("        time.sleep(30)\n" if timeout else
           "        emit({'type':'agent_end','isTerminal':False,'messages':[messages[0]]})\n"
           "        emit({'type':'message_end','message':messages[1]})\n"
           "        emit({'type':'agent_end','isTerminal':True,'messages':messages})\n"
           "        break\n"),
        encoding="utf-8",
    )
    return path


def test_omp_counts_complete_messages_and_actual_tools_once(tmp_path):
    script = _rpc_script(tmp_path)
    system = LoopSystem(tmp_path / "data", OmpRpcAdapter(OmpConfig([sys.executable, str(script)], enabled=True, timeout_sec=5)))
    run_id = system.create_run("echo")
    system.workspace(run_id).write_file("proof.txt", "observable evidence")
    result = system.activate_once(run_id)
    events = system.store.list_events(run_id)
    assert result.phase == "ENGINEERING"
    assert result.token_used == 250 and result.cost == 0.25
    assert result.tool_count == 1
    assert sum(event.type == EventType.MODEL_MESSAGE for event in events) == 2
    reports = [event.payload for event in events if event.payload.get("name") == "provider_usage"]
    assert len(reports) == 2
    assert reports[-1]["input_tokens"] == 21
    assert reports[-1]["cache_read_tokens"] == 180
    assert reports[-1]["cache_write_tokens"] == 7
    assert reports[-1]["input_total_tokens"] == 208
    assert reports[-1]["output_tokens"] == 42
    assert reports[-1]["source"] == "reported"
    tool = next(event for event in events if event.payload.get("name") == "read_file")
    assert tool.payload["id"] == "rpc-read" and tool.payload["tool_call_id"] == "model-read"
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_omp_timeout_keeps_live_message_usage_and_tool_output(tmp_path):
    script = _rpc_script(tmp_path, timeout=True)
    adapter = OmpRpcAdapter(OmpConfig([sys.executable, str(script)], enabled=True, timeout_sec=2))
    observed = Event()
    invoke = adapter.invoke

    def watching(request):
        observer = request.on_observation

        def forward(observation):
            observer(observation)
            if observation.kind == "tool":
                observed.set()

        request.on_observation = forward
        return invoke(request)

    adapter.invoke = watching
    system = LoopSystem(tmp_path / "data", adapter)
    run_id = system.create_run("echo")
    system.workspace(run_id).write_file("proof.txt", "survives RPC timeout")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        assert observed.wait(5)
        live = system.project(run_id)
        assert live.phase == "PRODUCT_SPEC" and live.token_used == 110
        assert live.tool_count == 1 and not future.done()
        result = future.result(timeout=5)
    events = system.store.list_events(run_id)
    assert result.phase == "FAILED" and result.stop_reason == "provider_error"
    assert "timed out" in result.error
    assert result.token_used == 110 and result.cost == 0.11
    assert sum(event.type == EventType.MODEL_MESSAGE for event in events) == 1
    assert not any(event.type == EventType.SPEC_ACCEPTED for event in events)
    tool = next(event for event in events if event.payload.get("name") == "read_file")
    assert "survives RPC timeout" in system.artifacts.get_text(tool.payload["output_ref"]["content_hash"])


def test_omp_abort_only_targets_registered_session(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    flags = []
    adapter = OmpRpcAdapter(OmpConfig([sys.executable], enabled=True))

    def invoke_process(request, flag):
        flags.append(flag)
        entered.set()
        assert release.wait(5)
        return AdapterResult(None, finish_reason="aborted" if flag.is_set() else "completed")

    monkeypatch.setattr(adapter, "_invoke_process", invoke_process)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(adapter.invoke, _request(tmp_path))
        try:
            assert entered.wait(5)
            adapter.abort("other-session")
            assert not flags[0].is_set()
            adapter.abort("ses")
            assert flags[0].is_set()
        finally:
            release.set()
        assert future.result(timeout=5).finish_reason == "aborted"


def test_host_request_identity_does_not_merge_distinct_executions(tmp_path):
    request = _request(tmp_path)
    request.workspace.write_file("proof.txt", "first")
    observed, frames, executed = [], [], []
    request.on_observation = observed.append

    class Session:
        def send(self, frame):
            frames.append(frame)

    class Runtime(ToolRuntime):
        def execute(self, department, name, args=None):
            executed.append(name)
            return super().execute(department, name, args)

    adapter = OmpRpcAdapter(OmpConfig([sys.executable], enabled=True))
    runtime, calls, cache = Runtime(request.workspace), [], {}
    frame = {"id": "rpc-1", "toolCallId": "same-model-call", "toolName": "read_file", "arguments": {"path": "proof.txt"}}
    adapter._handle_host_tool(Session(), frame, runtime, request, calls, cache)
    request.workspace.write_file("proof.txt", "second")
    adapter._handle_host_tool(Session(), frame, runtime, request, calls, cache)
    adapter._handle_host_tool(Session(), {**frame, "id": "rpc-2"}, runtime, request, calls, cache)
    assert executed == ["read_file", "read_file"]
    assert len(observed) == len(calls) == 2
    assert [call["output"] for call in calls] == ["first", "second"]
    assert calls[0]["tool_call_id"] == calls[1]["tool_call_id"]
    assert calls[0]["id"] != calls[1]["id"]
    assert frames[0]["result"] == frames[1]["result"]
    assert frames[1]["result"] != frames[2]["result"]


def test_nonterminal_end_and_final_summary_do_not_produce_usage():
    message = {"role": "assistant", "content": "same", "usage": {"input": 1, "output": 2, "totalTokens": 3}}
    assert map_omp_frame({"type": "agent_end", "isTerminal": False, "messages": [message]}) == {}
    final = map_omp_frame({"type": "agent_end", "isTerminal": True, "messages": [message]})
    assert final["finish_reason"] == "completed"
    assert "usage" not in final and "text" not in final

import json
import sys
import time
from threading import Event

import pytest

from harness.adapters.base import InvokeRequest, ProviderError
from harness.adapters.omp import (
    UNAVAILABLE_MESSAGE,
    OmpConfig,
    OmpRpcAdapter,
    _launch_command,
    extract_json_proposal,
    map_omp_failure,
    map_omp_frame,
)
from harness.context import AssembledContext
from harness.models import ContextManifest
from harness.runtime import LoopSystem, build_adapter
from harness.workspace import Workspace


def _context():
    return AssembledContext(
        department="product",
        prompt_text="[department_rules]\n你是产品部门。",
        parts=[],
        manifest=ContextManifest(
            session_id="ses",
            department="product",
            activation_id="act",
            injected=[],
            excluded=[],
            token_estimate=10,
            budget=1000,
            digest="sha256:x",
        ),
    )


def _invoke(adapter, tmp_path, tools=None):
    workspace = Workspace(tmp_path / "ws")
    return adapter.invoke(
        InvokeRequest(
            run_id="run",
            department="product",
            session_id="ses",
            activation_id="act",
            context=_context(),
            tools=tools or ["read_file", "submit_product_spec"],
            workspace=workspace,
            abort_flag=Event(),
        )
    )


def test_omp_unconfigured_is_provider_unavailable(data_dir, monkeypatch):
    monkeypatch.delenv("YUDAO_OMP_ENABLED", raising=False)
    adapter = build_adapter("omp")
    availability = adapter.availability()
    assert availability.available is False
    assert availability.reason == "provider_unavailable"
    assert "不会" in availability.message or "fake" in availability.message.lower()

    system = LoopSystem(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.phase == "FAILED"
    assert projection.stop_reason == "provider_unavailable"
    assert projection.outcome == "failed"


def test_omp_does_not_fallback_to_fake(data_dir, monkeypatch):
    monkeypatch.delenv("YUDAO_OMP_ENABLED", raising=False)
    adapter = OmpRpcAdapter(OmpConfig.from_env())
    assert adapter.name == "omp"
    system = LoopSystem(data_dir, adapter)
    projection = system.run_until_stop(system.create_run("build echo"))
    assert projection.provider == "omp"
    assert projection.stop_reason == "provider_unavailable"
    events = system.store.list_events(projection.run_id)
    assert any(event.type == "run_failed" for event in events)
    assert not any(event.provider == "fake" for event in events if event.provider)


def test_missing_binary_is_unavailable(monkeypatch):
    monkeypatch.setenv("YUDAO_OMP_ENABLED", "1")
    monkeypatch.setenv("YUDAO_OMP_COMMAND", "omp-binary-that-does-not-exist")
    monkeypatch.delenv("YUDAO_OMP_ARGS", raising=False)
    config = OmpConfig.from_env()
    adapter = OmpRpcAdapter(config)
    availability = adapter.availability()
    assert availability.available is False
    assert availability.reason == "provider_unavailable"


def test_error_mapping():
    assert map_omp_failure(ProviderError("x", reason="provider_unavailable"))[0] == "provider_unavailable"
    assert map_omp_failure(FileNotFoundError("omp"))[0] == "provider_unavailable"
    assert map_omp_failure(RuntimeError("aborted by host"))[0] == "cancelled"
    assert map_omp_failure(RuntimeError("context window overflow"))[0] == "context_overflow"
    assert map_omp_failure(RuntimeError("500 from provider"))[0] == "provider_error"


def test_extract_json_proposal_and_frame_mapping():
    text = 'note\n{"kind": "product_spec", "goal": "x", "requirements": ["a"], "acceptance_criteria": ["b"]}\n'
    proposal = extract_json_proposal(text)
    assert proposal["kind"] == "product_spec"
    frame = map_omp_frame({"type": "message_update", "message": {"content": text}})
    assert frame["proposal"]["kind"] == "product_spec"
    ended = map_omp_frame({"type": "agent_end"})
    assert ended["finish_reason"] == "completed"
    failed = map_omp_frame({"type": "response", "success": False, "command": "prompt", "error": "nope"})
    assert failed["fatal"] is True


def test_launch_command_disables_builtins_and_keeps_yudao_host_tools():
    command = _launch_command(OmpConfig(command=["omp", "--mode", "rpc"], enabled=True, provider="blackrouter", model="gpt-5.6-terra"))
    assert "--no-tools" in command
    assert "--no-session" in command
    assert "--tools" not in command
    assert command[command.index("--provider") + 1] == "blackrouter"


def test_omp_message_end_maps_assistant_proposal_and_usage():
    frame = map_omp_frame(
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": '{"kind":"product_spec","goal":"x"}'}],
                "usage": {"input": 12, "output": 4, "totalTokens": 16, "cost": {"total": 0.25}},
                "stopReason": "stop",
            },
        }
    )
    assert frame["proposal"] == {"kind": "product_spec", "goal": "x"}
    assert frame["usage"].total_tokens == 16
    assert frame["usage"].cost == 0.25


def test_omp_agent_end_maps_final_assistant_message():
    frame = map_omp_frame(
        {
            "type": "agent_end",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "prompt"}]},
                {"role": "assistant", "content": [{"type": "text", "text": '{"kind":"delivery_spec"}'}]},
            ],
        }
    )
    assert frame["finish_reason"] == "completed"
    assert frame["proposal"] == {"kind": "delivery_spec"}


def _write_mock(path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


READY = (
    "print(json.dumps({'type':'ready','protocolVersion':1,'supportedProtocolVersions':[1,2],"
    "'maxFrameBytes':1048576,'maxReassembledFrameBytes':67108864}), flush=True)\n"
)


def test_omp_ndjson_mock_process(data_dir, tmp_path):
    mock = tmp_path / "omp_mock.py"
    _write_mock(
        mock,
        "import json, sys\n"
        + READY
        + "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('type') == 'negotiate_protocol':\n"
        "        print(json.dumps({'id': msg.get('id'), 'type':'response', 'command':'negotiate_protocol', 'success': True}), flush=True)\n"
        "    elif msg.get('type') == 'set_host_tools':\n"
        "        names = [item.get('name') for item in msg.get('tools', [])]\n"
        "        print(json.dumps({'id': msg.get('id'), 'type':'response', 'command':'set_host_tools', 'success': True, 'data': {'toolNames': names}}), flush=True)\n"
        "    elif msg.get('type') == 'prompt':\n"
        "        print(json.dumps({'id': msg.get('id'), 'type':'response', 'command':'prompt', 'success': True, 'data': {'agentInvoked': True}}), flush=True)\n"
        "        print(json.dumps({'type':'agent_start'}), flush=True)\n"
        "        body = {'kind':'product_spec','goal':'from omp mock','requirements':['r'],'acceptance_criteria':['a'],'boundaries':[],'constraints':[],'fatal_conditions':[],'non_goals':[]}\n"
        "        print(json.dumps({'type':'message_update','message': json.dumps(body)}), flush=True)\n"
        "        print(json.dumps({'type':'agent_end'}), flush=True)\n"
        "        break\n",
    )
    config = OmpConfig(command=[sys.executable, str(mock)], enabled=True, timeout_sec=8, model="mock")
    adapter = OmpRpcAdapter(config)
    assert adapter.availability().available is True
    result = _invoke(adapter, tmp_path)
    assert result.provider == "omp"
    assert result.proposal["kind"] == "product_spec"
    assert result.proposal["goal"] == "from omp mock"
    assert result.finish_reason == "completed"


def test_silent_stdout_times_out_and_includes_stderr(tmp_path):
    mock = tmp_path / "hang.py"
    _write_mock(
        mock,
        "import sys, time\n"
        "sys.stderr.write('invalid --tools: ls\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(30)\n",
    )
    adapter = OmpRpcAdapter(OmpConfig(command=[sys.executable, str(mock)], enabled=True, timeout_sec=1, model="mock"))
    started = time.monotonic()
    with pytest.raises(ProviderError) as caught:
        _invoke(adapter, tmp_path)
    assert time.monotonic() - started < 8
    assert caught.value.reason == "provider_error"
    assert "timed out" in str(caught.value).lower() or "ready" in str(caught.value).lower()
    assert "invalid --tools: ls" in str(caught.value)


def test_early_exit_is_provider_error_not_completed(tmp_path):
    mock = tmp_path / "exit.py"
    _write_mock(mock, "import json, sys\n" + READY)
    adapter = OmpRpcAdapter(OmpConfig(command=[sys.executable, str(mock)], enabled=True, timeout_sec=5, model="mock"))
    with pytest.raises(ProviderError) as caught:
        _invoke(adapter, tmp_path)
    assert caught.value.reason == "provider_error"
    assert "completed" not in str(caught.value).lower()


def test_host_tool_call_is_executed_by_yudao(tmp_path):
    mock = tmp_path / "host_tools.py"
    _write_mock(
        mock,
        "import json, sys\n"
        + READY
        + "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('type') == 'negotiate_protocol':\n"
        "        print(json.dumps({'id': msg.get('id'), 'type':'response', 'command':'negotiate_protocol', 'success': True}), flush=True)\n"
        "    elif msg.get('type') == 'set_host_tools':\n"
        "        print(json.dumps({'id': msg.get('id'), 'type':'response', 'command':'set_host_tools', 'success': True, 'data': {'toolNames': [t['name'] for t in msg.get('tools', [])]}}), flush=True)\n"
        "    elif msg.get('type') == 'prompt':\n"
        "        print(json.dumps({'id': msg.get('id'), 'type':'response', 'command':'prompt', 'success': True}), flush=True)\n"
        "        print(json.dumps({'type':'host_tool_call','id':'call-1','toolCallId':'tc-1','toolName':'read_file','arguments':{'path':'note.txt'}}), flush=True)\n"
        "    elif msg.get('type') == 'host_tool_result':\n"
        "        print(json.dumps({'type':'message_update','message': json.dumps({'kind':'product_spec','goal': msg['result']['content'][0]['text'],'requirements':['r'],'acceptance_criteria':['a']})}), flush=True)\n"
        "        print(json.dumps({'type':'agent_end'}), flush=True)\n"
        "        break\n",
    )
    adapter = OmpRpcAdapter(OmpConfig(command=[sys.executable, str(mock)], enabled=True, timeout_sec=8, model="mock"))
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("note.txt", "host-read-ok")
    result = adapter.invoke(
        InvokeRequest(
            run_id="run",
            department="product",
            session_id="ses",
            activation_id="act",
            context=_context(),
            tools=["read_file", "submit_product_spec"],
            workspace=workspace,
            abort_flag=Event(),
        )
    )
    assert result.finish_reason == "completed"
    assert result.proposal["goal"] == "host-read-ok"
    assert any(call["name"] == "read_file" and call["ok"] is True for call in result.tool_calls)


def test_diagnostics_redact_credentials(tmp_path, monkeypatch):
    secret = "super-secret-value-123456"
    monkeypatch.setenv("BLACKROUTER_API_KEY", secret)
    mock = tmp_path / "secret.py"
    _write_mock(
        mock,
        "import os, sys, time\n"
        "sys.stderr.write(os.environ['BLACKROUTER_API_KEY'] + '\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(30)\n",
    )
    adapter = OmpRpcAdapter(OmpConfig(command=[sys.executable, str(mock)], enabled=True, timeout_sec=1, model="mock"))
    with pytest.raises(ProviderError) as caught:
        _invoke(adapter, tmp_path)
    assert secret not in str(caught.value)
    assert "BLACKROUTER_API_KEY" in str(caught.value)

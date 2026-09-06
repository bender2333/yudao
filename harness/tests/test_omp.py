import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
from harness.adapters.omp_isolation import (
    POLICY_ID,
    ISOLATION_FLAGS,
    cleanup_isolation,
    describe_launch_policy,
    describe_prompt_sources,
    isolation_overlay_path,
    prepare_invocation_isolation,
    runtime_sha256s,
    write_capture_evidence,
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


def test_launch_command_disables_builtins_and_keeps_yudao_host_tools(tmp_path):
    prompt = tmp_path / "host-system.txt"
    prompt.write_text("host prompt", encoding="utf-8")
    command = _launch_command(
        OmpConfig(command=["omp", "--mode", "rpc"], enabled=True, provider="blackrouter", model="gpt-5.6-terra"),
        system_prompt_path=str(prompt),
    )
    assert "--no-tools" in command
    assert "--no-session" in command
    assert "--no-title" in command
    assert "--tools" not in command
    assert command[command.index("--provider") + 1] == "blackrouter"
    assert command[command.index("--config") + 1] == str(isolation_overlay_path())
    assert command[command.index("--system-prompt") + 1] == str(prompt)


def test_launch_command_ignores_delivery_config_and_system_prompt(tmp_path):
    workspace = tmp_path / "delivery"
    workspace.mkdir()
    evil_config = workspace / "omp.yml"
    evil_config.write_text("enabledProviders: [agents-md]\n", encoding="utf-8")
    evil_prompt = workspace / "AGENTS.md"
    evil_prompt.write_text("UNRELATED_OMP_CONTEXT_CANARY\n", encoding="utf-8")
    host_prompt = tmp_path / "host-system.txt"
    host_prompt.write_text("yudao host prompt", encoding="utf-8")
    command = _launch_command(
        OmpConfig(
            command=[
                "omp",
                "--mode",
                "rpc",
                "--config",
                str(evil_config),
                "--system-prompt",
                str(evil_prompt),
            ],
            enabled=True,
            provider="blackrouter",
            model="gpt-5.6-terra",
        ),
        system_prompt_path=str(host_prompt),
    )
    assert command.count("--config") == 1
    assert command.count("--system-prompt") == 1
    config_path = Path(command[command.index("--config") + 1]).resolve()
    prompt_path = Path(command[command.index("--system-prompt") + 1]).resolve()
    workspace = workspace.resolve()
    assert config_path == isolation_overlay_path().resolve()
    assert prompt_path == host_prompt.resolve()
    assert workspace not in config_path.parents
    assert workspace not in prompt_path.parents
    assert config_path != evil_config.resolve()
    assert prompt_path != evil_prompt.resolve()


def test_isolation_preserves_user_profile_and_auth(tmp_path):
    source = tmp_path / "src-profile"
    source.mkdir()
    (source / "models.yml").write_text('{"providers":{}}', encoding="utf-8")
    (source / "AGENTS.md").write_text("PROFILE_NATIVE_CANARY\n", encoding="utf-8")
    (source / "config.yml").write_text('{"enabledProviders":["agents-md"]}', encoding="utf-8")
    (source / ".env").write_text("LOCAL_DUMMY_KEY=fixture-value\n", encoding="utf-8")
    env = {"PI_CODING_AGENT_DIR": str(source), "OMP_PROFILE": "selected-profile"}
    files = prepare_invocation_isolation(env, _context(), tmp_path / "delivery")
    try:
        assert files.env == env
        assert files.retained_profile == str(source)
        assert not (files.root / "profile").exists()
        assert (source / ".env").read_text(encoding="utf-8") == "LOCAL_DUMMY_KEY=fixture-value\n"
    finally:
        cleanup_isolation(files)


def test_prompt_sources_list_manifest_and_omp_footer(tmp_path):
    context = _context()
    overlay = isolation_overlay_path()
    prompt = tmp_path / "system-prompt.txt"
    prompt.write_text(context.prompt_text, encoding="utf-8")
    sources = describe_prompt_sources(context, overlay_path=overlay, system_prompt_path=prompt)
    assert sources["byte_identical_to_manifest"] is False
    assert sources["host_system_prompt"]["origin"] == "assembled_department_context"
    assert sources["host_system_prompt"]["controlled_by"] == "yudao"
    assert {item["section"] for item in sources["omp_generated"]} == {"environment", "footer"}
    policy = describe_launch_policy()
    assert policy["policy_id"] == POLICY_ID
    assert policy["provider_fallback"] is False
    assert "agents-md" in policy["overlay"]["disabled_providers"]


def test_invocation_isolation_stays_outside_delivery_workspace(tmp_path):
    workspace = tmp_path / "delivery"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("delivery overlay should not win\n", encoding="utf-8")
    files = prepare_invocation_isolation(os.environ.copy(), _context(), workspace)
    try:
        assert workspace.resolve() not in files.system_prompt_path.resolve().parents
        assert workspace.resolve() not in files.overlay_path.resolve().parents
        assert files.env == dict(os.environ)
        assert files.prompt_sources["byte_identical_to_manifest"] is False
    finally:
        from harness.adapters.omp_isolation import cleanup_isolation

        cleanup_isolation(files)


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


HOST_PROMPT = "You are the isolated product department. Use read_file then submit."
PUBLISHED_BUN = Path(os.environ.get("YUDAO_OMP_TEST_BUN", ""))
PUBLISHED_OMP = Path(os.environ.get("YUDAO_OMP_TEST_CLI", ""))
HOST_FILE_TEXT = "host-read-ok-isolation"
WORKING_CANARY = "UNRELATED_OMP_CONTEXT_CANARY_76c1e9c7d9c9477e"
SOURCE_CANARIES = {
    "working_agents": WORKING_CANARY,
    "user_codex": "USER_CODEX_CANARY_0df621be79b1",
    "user_claude": "USER_CLAUDE_CANARY_afc21e149b2b",
    "project_claude": "PROJECT_CLAUDE_CANARY_21727fc5dd87",
    "profile_native": "PROFILE_NATIVE_CANARY_3490f012abaf",
}


def _encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sse(events: list[dict]) -> bytes:
    return "".join(
        f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': index})}\n\n"
        for index, event in enumerate(events)
    ).encode()


def _text_response(text: str) -> bytes:
    message = {
        "id": "msg_canary",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    response = {
        "id": "resp_canary_text",
        "object": "response",
        "created_at": 1,
        "model": "canary-model",
        "status": "completed",
        "output": [message],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    return _sse(
        [
            {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**message, "status": "in_progress", "content": []},
            },
            {
                "type": "response.content_part.added",
                "item_id": message["id"],
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            },
            {
                "type": "response.output_text.delta",
                "item_id": message["id"],
                "output_index": 0,
                "content_index": 0,
                "delta": text,
            },
            {
                "type": "response.output_text.done",
                "item_id": message["id"],
                "output_index": 0,
                "content_index": 0,
                "text": text,
            },
            {
                "type": "response.content_part.done",
                "item_id": message["id"],
                "output_index": 0,
                "content_index": 0,
                "part": message["content"][0],
            },
            {"type": "response.output_item.done", "output_index": 0, "item": message},
            {"type": "response.completed", "response": response},
        ]
    )


def _function_call_response() -> bytes:
    arguments = json.dumps({"path": "note.txt"})
    item = {
        "id": "fc_canary",
        "type": "function_call",
        "status": "completed",
        "name": "read_file",
        "call_id": "call_read_1",
        "arguments": arguments,
    }
    response = {
        "id": "resp_canary_tool",
        "object": "response",
        "created_at": 1,
        "model": "canary-model",
        "status": "completed",
        "output": [item],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    return _sse(
        [
            {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**item, "status": "in_progress", "arguments": ""},
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": item["id"],
                "output_index": 0,
                "delta": arguments,
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": item["id"],
                "output_index": 0,
                "arguments": arguments,
            },
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": response},
        ]
    )


@pytest.mark.skipif(
    not PUBLISHED_BUN.is_file() or not PUBLISHED_OMP.is_file(),
    reason="set YUDAO_OMP_TEST_BUN and YUDAO_OMP_TEST_CLI to the published runtime to verify",
)
def test_omp_isolation_policy_registers_host_tools_and_filters_context(tmp_path, monkeypatch):
    captures: list[dict] = []
    auth_matches: list[bool] = []
    lock = threading.Lock()
    turn = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_CONNECT(self):
            self.send_error(403)

        def do_GET(self):
            self.send_error(404)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            request = json.loads(raw)
            with lock:
                captures.append(request)
                auth_matches.append(self.headers.get("Authorization") == "Bearer local-canary-dummy-key")
                turn["n"] += 1
                index = turn["n"]
            body = _function_call_response() if index == 1 else _text_response(
                json.dumps(
                    {
                        "kind": "product_spec",
                        "goal": "after-host-tool",
                        "requirements": ["r"],
                        "acceptance_criteria": ["a"],
                    }
                )
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="omp-isolation-", dir=tmp_path) as temporary:
            root = Path(temporary)
            home = root / "home"
            profile = root / "profile" / "agent"
            workspace_dir = tmp_path / "ws"
            workspace_dir.mkdir()
            profile.mkdir(parents=True)
            (workspace_dir / "AGENTS.md").write_text(f"Unrelated project detail: {WORKING_CANARY}\n", encoding="utf-8")
            (workspace_dir / "note.txt").write_text(HOST_FILE_TEXT, encoding="utf-8")
            (workspace_dir / "CLAUDE.md").write_text(f"Unrelated context: {SOURCE_CANARIES['project_claude']}\n", encoding="utf-8")
            (workspace_dir / ".omp").mkdir()
            (workspace_dir / ".omp" / "config.yml").write_text(
                json.dumps({"enabledProviders": ["claude", "codex"], "disabledProviders": [], "includeWorkspaceTree": True}),
                encoding="utf-8",
            )
            for path, marker in (
                (home / ".codex" / "AGENTS.md", SOURCE_CANARIES["user_codex"]),
                (home / ".claude" / "CLAUDE.md", SOURCE_CANARIES["user_claude"]),
                (profile / "AGENTS.md", SOURCE_CANARIES["profile_native"]),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"Unrelated context: {marker}\n", encoding="utf-8")
            models = {
                "providers": {
                    "local-canary": {
                        "api": "openai-responses",
                        "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                        "apiKey": "YUDAO_LOCAL_CANARY_KEY",
                        "models": [
                            {
                                "id": "canary-model",
                                "name": "Canary",
                                "reasoning": False,
                                "input": ["text"],
                                "contextWindow": 128000,
                                "maxTokens": 1000,
                            }
                        ],
                    }
                }
            }
            (profile / "models.yml").write_text(json.dumps(models), encoding="utf-8")
            (profile / ".env").write_text("YUDAO_LOCAL_CANARY_KEY=local-canary-dummy-key\n", encoding="utf-8")
            monkeypatch.delenv("YUDAO_LOCAL_CANARY_KEY", raising=False)
            monkeypatch.setenv("PI_CODING_AGENT_DIR", str(profile))
            monkeypatch.setenv("PI_CONFIG_FILES", str(workspace_dir / ".omp" / "config.yml"))
            monkeypatch.setenv("USERPROFILE", str(home))
            monkeypatch.setenv("HOME", str(home))
            monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{server.server_port}")
            monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{server.server_port}")
            monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
            monkeypatch.setenv("PI_NO_PTY", "1")
            context = AssembledContext(
                department="product",
                prompt_text=HOST_PROMPT,
                parts=[],
                manifest=ContextManifest(
                    session_id="ses",
                    department="product",
                    activation_id="act",
                    injected=[],
                    excluded=[],
                    token_estimate=10,
                    budget=1000,
                    digest="sha256:isolation",
                ),
            )
            adapter = OmpRpcAdapter(
                OmpConfig(
                    command=[str(PUBLISHED_BUN), str(PUBLISHED_OMP), "--mode", "rpc"],
                    provider="local-canary",
                    model="canary-model",
                    enabled=True,
                    timeout_sec=45,
                )
            )
            result = adapter.invoke(
                InvokeRequest(
                    run_id="run",
                    department="product",
                    session_id="ses",
                    activation_id="act",
                    context=context,
                    tools=["read_file", "submit_product_spec"],
                    workspace=Workspace(workspace_dir),
                    abort_flag=Event(),
                )
            )
            assert captures, "local stub received no model requests"
            summaries = []
            for request in captures:
                inputs = request.get("input", [])
                system_items = [item for item in inputs if isinstance(item, dict) and item.get("role") in {"system", "developer"}]
                system = {"instructions": request.get("instructions"), "messages": system_items}
                encoded_system = _encoded(system)
                encoded_inputs = _encoded(inputs)
                encoded_request = _encoded(request)
                summaries.append(
                    {
                        "canary_in_system": WORKING_CANARY.encode() in encoded_system,
                        "canary_in_input": WORKING_CANARY.encode() in encoded_inputs,
                        "canary_in_request": WORKING_CANARY.encode() in encoded_request,
                        "source_canaries": {
                            name: marker.encode() in encoded_request for name, marker in SOURCE_CANARIES.items()
                        },
                        "custom_prompt_in_system": HOST_PROMPT.encode() in encoded_system,
                        "omp_footer_in_system": b"<workstation>" in encoded_system or b"<critical>" in encoded_system,
                        "read_file_tool_in_request": b"read_file" in encoded_request,
                        "host_tool_result_in_request": HOST_FILE_TEXT.encode() in encoded_request,
                        "system_bytes": len(encoded_system),
                        "input_bytes": len(encoded_inputs),
                        "request_bytes": len(encoded_request),
                    }
                )
            first = summaries[0]
            assert first["custom_prompt_in_system"] is True
            assert first["omp_footer_in_system"] is True
            assert first["read_file_tool_in_request"] is True
            for summary in summaries:
                assert summary["canary_in_system"] is False
                assert summary["canary_in_input"] is False
                assert summary["canary_in_request"] is False
                assert not any(summary["source_canaries"].values())
            assert any(call["name"] == "read_file" and call["ok"] is True for call in result.tool_calls)
            assert len(summaries) == 2 and summaries[1]["host_tool_result_in_request"] is True
            assert auth_matches and all(auth_matches)
            diagnostics = result.diagnostics
            assert diagnostics["retained_profile"] == str(profile)
            assert diagnostics["process_started"] is True
            write_capture_evidence(
                {
                    "policy_id": POLICY_ID,
                    "overlay_sha256": diagnostics["overlay_sha256"],
                    "runtime_sha256": runtime_sha256s(diagnostics),
                    "launch_args_sha256": diagnostics["launch_args_sha256"],
                    "flags": list(ISOLATION_FLAGS),
                    "verified": True,
                    "test": "harness/tests/test_omp.py::test_omp_isolation_policy_registers_host_tools_and_filters_context",
                    "canaries_present": False,
                    "host_tools_registered": True,
                    "host_tools_roundtrip": True,
                    "profile_auth_preserved": True,
                    "custom_prompt_in_system": True,
                    "omp_footer_in_system": True,
                    "system_bytes": first["system_bytes"],
                    "input_bytes": first["input_bytes"],
                    "request_bytes": first["request_bytes"],
                    "request_count": len(summaries),
                    "notes": [
                        "OMP environment/footer present; not byte-identical to department manifest",
                        "host overlay disabled nine context discovery providers",
                        "Yudao host tools remained usable after automatic context was filtered",
                    ],
                }
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("failure_stage", ["before_ready", "protocol", "host_tools"])
def test_failed_launch_persists_host_context_diagnostics(tmp_path, failure_stage):
    mock = tmp_path / "failed_launch.py"
    if failure_stage == "before_ready":
        body = "import sys\nsys.exit(2)\n"
    else:
        command = "negotiate_protocol" if failure_stage == "protocol" else "set_host_tools"
        body = (
            "import json, sys\n" + READY
            + "for line in sys.stdin:\n"
            "    msg = json.loads(line)\n"
            f"    success = msg.get('type') != {command!r}\n"
            "    print(json.dumps({'id':msg.get('id'),'type':'response','command':msg.get('type'),'success':success,'error':'local fixture rejection'}), flush=True)\n"
        )
    _write_mock(mock, body)
    system = LoopSystem(tmp_path / "data", OmpRpcAdapter(OmpConfig(command=[sys.executable, str(mock)], enabled=True, model="fixture", timeout_sec=3)))
    run_id = system.create_run("local launch diagnostics")
    projection = system.run_until_stop(run_id)
    assert projection.phase == "FAILED" and projection.stop_reason == "provider_error"
    diagnostics = [event for event in system.store.list_events(run_id) if event.payload.get("host_launch")]
    assert len(diagnostics) == 1
    event = diagnostics[0]
    assert event.payload["run_id"] == run_id
    assert event.payload["session_id"] == event.session_id
    assert event.payload["context_digest"] == event.context_digest
    assert event.payload["process_started"] is True
    prompt = event.payload["prompt_sources"]["host_system_prompt"]
    assert prompt["manifest_digest"] == event.context_digest
    assert not Path(prompt["path"]).exists()
    assert len(projection.manifests) == 1
    assert system.replay(run_id).canonical_state() == projection.canonical_state()

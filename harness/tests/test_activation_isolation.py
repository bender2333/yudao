"""Integration coverage for durable OMP launch observations."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from harness.adapters.omp import OmpConfig, OmpRpcAdapter
from harness.adapters.omp_isolation import capture_evidence_path
from harness.runtime import LoopSystem
from harness.smoke import isolation_fields
from harness.tests.test_omp import _text_response


def _launches(system, run_id):
    return [event for event in system.store.list_events(run_id) if event.payload.get("host_launch")]


def test_real_omp_launch_is_persisted_before_response_and_matches_capture(tmp_path, monkeypatch):
    bun = Path(os.environ.get("YUDAO_OMP_TEST_BUN", ""))
    cli = Path(os.environ.get("YUDAO_OMP_TEST_CLI", ""))
    if not bun.is_file() or not cli.is_file():
        pytest.skip("set YUDAO_OMP_TEST_BUN and YUDAO_OMP_TEST_CLI for the local OMP integration")
    evidence = capture_evidence_path()
    if not evidence.is_file():
        pytest.skip("run the OMP host-tools canary first to produce matching capture evidence")

    captures = []
    observed_live = []
    system = None
    run_id = None
    canary = "UNRELATED_ACTIVATION_ISOLATION_CONTEXT_435714"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_CONNECT(self):
            self.send_error(403)

        def do_GET(self):
            self.send_error(404)

        def do_POST(self):
            captures.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")))))
            launches = _launches(system, run_id)
            observed_live.append(len(launches) == 1 and launches[0].payload.get("process_started") is True)
            body = _text_response(json.dumps({
                "kind": "product_spec", "goal": "local activation observation",
                "requirements": ["print the first argument"],
                "acceptance_criteria": ["printing hello exits zero"],
            }))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        profile = tmp_path / "profile" / "agent"
        profile.mkdir(parents=True)
        (profile / "AGENTS.md").write_text(canary, encoding="utf-8")
        (profile / "models.yml").write_text(json.dumps({"providers": {"local-activation": {
            "api": "openai-responses", "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
            "apiKey": "local-dummy-key", "models": [{
                "id": "activation-model", "name": "Local activation", "reasoning": False,
                "input": ["text"], "contextWindow": 128000, "maxTokens": 1000,
            }],
        }}}), encoding="utf-8")
        preserved = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA"}
        for key in list(os.environ):
            if key.upper() not in preserved:
                monkeypatch.delenv(key, raising=False)
        for key, value in {
            "PI_CODING_AGENT_DIR": str(profile), "HOME": str(tmp_path / "home"),
            "USERPROFILE": str(tmp_path / "home"), "PI_NO_PTY": "1",
            "HTTP_PROXY": f"http://127.0.0.1:{server.server_port}",
            "HTTPS_PROXY": f"http://127.0.0.1:{server.server_port}", "NO_PROXY": "127.0.0.1,localhost",
        }.items():
            monkeypatch.setenv(key, value)
        system = LoopSystem(tmp_path / "data", OmpRpcAdapter(OmpConfig(
            command=[str(bun), str(cli), "--mode", "rpc"], enabled=True,
            provider="local-activation", model="activation-model", timeout_sec=45,
        )))
        run_id = system.create_run("Implement a local CLI printing its first argument")
        system.workspace(run_id).write_file("AGENTS.md", canary)
        projection = system.activate_once(run_id)
        assert projection.phase == "ENGINEERING"
        assert len(captures) == 1 and observed_live == [True]
        assert canary not in json.dumps(captures)
        events = _launches(system, run_id)
        assert len(events) == 1
        event = events[0]
        assert event.payload["process_started"] is True
        assert event.payload["activation_id"] == projection.last_activations["product"]
        assert event.payload["session_id"] == event.session_id
        assert event.payload["context_digest"] == event.context_digest
        report = isolation_fields(system.store, run_id)
        assert report["context_isolated"] is True, report["context_isolation_notes"]
        assert report["omp_policy_capture"]["semantic"] == "access_policy_verification"
        assert system.replay(run_id).canonical_state() == projection.canonical_state()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        if system is not None:
            system.store.close()


def test_failed_spawn_retains_unverified_launch_diagnostics(tmp_path, monkeypatch):
    def fail_spawn(*_args, **_kwargs):
        raise OSError("local fixture: process could not start")

    monkeypatch.setattr("harness.adapters.omp.RpcProcess.spawn", fail_spawn)
    system = LoopSystem(tmp_path / "data", OmpRpcAdapter(OmpConfig(
        command=[sys.executable], enabled=True, model="local-fixture",
    )))
    try:
        run_id = system.create_run("local launch failure")
        projection = system.activate_once(run_id)
        assert projection.phase == "FAILED"
        events = _launches(system, run_id)
        assert len(events) == 1
        assert events[0].payload["process_started"] is False
        assert events[0].payload["activation_id"] == projection.last_activations["product"]
        assert isolation_fields(system.store, run_id)["context_isolated"] is False
    finally:
        system.store.close()

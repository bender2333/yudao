import json
import subprocess
import threading
import time
from dataclasses import asdict, replace
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import quote

import pytest

from harness.__main__ import main
from harness.adapters.fake import FakeAdapter
from harness.adapters.responses import ResponsesAdapter, ResponsesConfig
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, run_scripted
from harness.web.server import serve


@contextmanager
def running_server(system):
    server = serve(system, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield server, host, port
    finally:
        server.shutdown()
        server.server_close()


def request(host, port, method, path, body=None, headers=None, timeout=5):
    conn = HTTPConnection(host, port, timeout=timeout)
    payload = b""
    hdrs = {}
    if body is not None:
        payload = json.dumps(body).encode("utf-8") if not isinstance(body, (bytes, bytearray)) else body
        hdrs["Content-Type"] = "application/json"
        hdrs["Content-Length"] = str(len(payload))
    if headers:
        hdrs.update(headers)
    conn.request(method, path, body=payload, headers=hdrs)
    response = conn.getresponse()
    data = response.read()
    status = response.status
    resp_headers = {key: value for key, value in response.getheaders()}
    conn.close()
    return status, data.decode("utf-8"), resp_headers


def get_json(host, port, path):
    status, body, _ = request(host, port, "GET", path)
    assert status == 200, body
    return json.loads(body)


def wait_until(predicate, timeout=8.0, interval=0.05):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timeout waiting, last={last!r}")


def wait_terminal(host, port, run_id, timeout=8.0):
    def check():
        status, body, _ = request(host, port, "GET", f"/api/runs/{run_id}")
        if status != 200:
            return False
        payload = json.loads(body)
        if payload["board"]["phase"] in {"DONE", "FAILED", "PAUSED"}:
            return payload
        return False

    return wait_until(check, timeout=timeout)


def first_loop_event(host, port, path, headers=None, timeout=5):
    conn = HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        assert response.status == 200, response.read().decode("utf-8", errors="ignore")
        assert "text/event-stream" in response.headers.get("Content-Type", "")
        buf = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = response.read(64)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="ignore")
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                if "event: loop" in block:
                    return block
        raise AssertionError(f"no loop event in {buf!r}")
    finally:
        conn.close()


def sse_id(block: str) -> int:
    for line in block.splitlines():
        if line.startswith("id:"):
            return int(line.split(":", 1)[1].strip())
    raise AssertionError(f"no id in {block!r}")


def gated_adapter():
    entered = threading.Event()
    release = threading.Event()

    def turn(_request):
        entered.set()
        if not release.wait(timeout=20):
            raise TimeoutError("worker gate was not released")
        return product_spec()

    return FakeAdapter([turn]), entered, release


def test_serve_binds_loop_system(data_dir):
    system = LoopSystem(data_dir, FakeAdapter(happy_script()))
    server = serve(system, host="127.0.0.1", port=0)
    try:
        assert server.system is system
        assert server.store is system.store
    finally:
        server.server_close()


def test_console_exposes_chinese_views_and_command_form(data_dir):
    system, _projection = run_scripted(data_dir, happy_script())
    with running_server(system) as (_server, host, port):
        html = request(host, port, "GET", "/")[1]
        assert "运行看板" in html
        assert "规格时间线" in html
        assert "证据视图" in html
        assert "上下文 / 追踪视图" in html
        assert 'id="provider-alert"' in html
        assert 'id="exec-alert"' in html
        assert 'aria-label="开始"' in html
        assert 'aria-label="取消"' in html
        assert 'aria-label="新任务"' in html
        assert 'title="新任务"' in html
        assert 'd="M5 12h14"' in html
        assert 'd="M12 5v14"' in html
        assert "python -m" not in html
        assert "Event Store" not in html
        assert 'class="panel"' not in html
        assert 'd="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"' in html
        assert 'rx="2"' in html
        assert request(host, port, "GET", "/static/play.svg")[0] == 404
        license_text = request(host, port, "GET", "/static/LUCIDE-LICENSE.txt")[1]
        assert "ISC License" in license_text
        css = request(host, port, "GET", "/static/styles.css")[1]
        assert "repeat(2, minmax(0, 1fr))" in css
        assert "repeat(auto-fit, minmax(0, 1fr))" not in css
        assert "overflow-wrap: anywhere" in css
        assert "letter-spacing: 0" in css
        assert "letter-spacing: 0.04" not in css
        js = request(host, port, "GET", "/static/app.js")[1]
        assert "产品" in js and "工程" in js and "质检" in js
        assert "适配器" in js
        assert '["Provider"' not in js
        assert "未上报" in js
        health = get_json(host, port, "/api/health")
        assert health["ok"] is True
        assert health["adapter"] == "fake"
        assert health.get("worker_error") is None
        assert "readonly" not in health or health["readonly"] is False


def test_create_run_goes_through_engine_and_replays(data_dir):
    system = LoopSystem(data_dir, FakeAdapter(happy_script()))
    calls = []
    original_create = system.create_run
    original_run = system.run_until_stop

    def create(task, **kwargs):
        calls.append(("create", task, dict(kwargs)))
        return original_create(task, **kwargs)

    def run(run_id):
        calls.append(("run", run_id))
        return original_run(run_id)

    system.create_run = create
    system.run_until_stop = run
    with running_server(system) as (_server, host, port):
        status, body, _ = request(
            host,
            port,
            "POST",
            "/api/runs",
            {"task": "build echo", "max_cycles": 6, "context_window": 16000},
        )
        assert status == 201, body
        created = json.loads(body)
        run_id = created["run_id"]
        payload = wait_terminal(host, port, run_id)
        assert payload["board"]["phase"] == "DONE"
        assert payload["board"]["task"] == "build echo"
        assert payload["evidence"]["reviews"][0]["verdict"] == "release"
        assert calls[0][0] == "create"
        assert calls[0][1] == "build echo"
        assert calls[0][2]["max_cycles"] == 6
        assert any(item[0] == "run" and item[1] == run_id for item in calls)
        listed = get_json(host, port, "/api/runs")
        assert listed["runs"][0]["run_id"] == run_id
        before = system.project(run_id)
        replay = json.loads(request(host, port, "POST", f"/api/runs/{run_id}/replay")[1])
        assert replay["ok"] is True
        assert replay["mutated"] is False
        after = system.project(run_id)
        assert after.last_seq == before.last_seq
        assert after.canonical_state() == before.canonical_state()
        assert after.canonical_state() == system.replay(run_id).canonical_state()


def test_second_start_returns_409_until_worker_exits(data_dir):
    adapter, entered, release = gated_adapter()
    system = LoopSystem(data_dir, adapter)
    with running_server(system) as (server, host, port):
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "first"})
        assert status == 201, body
        first_id = json.loads(body)["run_id"]
        assert entered.wait(timeout=5)
        assert server.busy() is True
        conflict, conflict_body, _ = request(host, port, "POST", "/api/runs", {"task": "second"})
        assert conflict == 409, conflict_body
        payload = json.loads(conflict_body)
        assert payload.get("reason") == "busy"
        assert get_json(host, port, "/api/health")["busy"] is True
        release.set()
        wait_until(lambda: not server.busy())
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "third"})
        assert status == 201, body
        assert json.loads(body)["run_id"] != first_id


def test_cancel_keeps_slot_until_worker_exits(data_dir):
    adapter, entered, release = gated_adapter()
    system = LoopSystem(data_dir, adapter)
    calls = []
    original_cancel = system.cancel

    def cancel(run_id):
        calls.append(run_id)
        return original_cancel(run_id)

    system.cancel = cancel
    with running_server(system) as (server, host, port):
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "hold"})
        assert status == 201, body
        run_id = json.loads(body)["run_id"]
        assert entered.wait(timeout=5)
        status, body, _ = request(host, port, "POST", f"/api/runs/{run_id}/cancel")
        assert status == 200, body
        cancelled = json.loads(body)
        assert cancelled["stop_reason"] == "cancelled"
        assert calls == [run_id]
        assert server.busy() is True
        conflict, conflict_body, _ = request(host, port, "POST", "/api/runs", {"task": "too-soon"})
        assert conflict == 409, conflict_body
        release.set()
        wait_until(lambda: not server.busy())
        payload = wait_terminal(host, port, run_id)
        assert payload["board"]["phase"] == "FAILED"
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "after-exit"})
        assert status == 201, body


def test_invalid_input_is_400_and_unknown_run_is_404(data_dir):
    system = LoopSystem(data_dir, FakeAdapter(happy_script()))
    with running_server(system) as (_server, host, port):
        before = system.list_run_ids()
        bad_bodies = [
            {"task": ""},
            {"task": "   "},
            {},
            {"task": "x", "max_cycles": 0},
            {"task": "x", "token_budget": 80000},
            {"task": "x", "context_window": True},
            {"task": "x", "max_cycles": 1.5},
            {"task": "x", "context_window": 8.0},
            {"task": "x", "max_cycles": "8"},
        ]
        for body in bad_bodies:
            status, response, _ = request(host, port, "POST", "/api/runs", body)
            assert status == 400, (body, status, response)
            assert system.list_run_ids() == before
        assert request(host, port, "POST", "/api/runs", b"{", headers={"Content-Type": "application/json", "Content-Length": "1"})[0] == 400
        assert system.list_run_ids() == before
        missing = request(host, port, "GET", "/api/runs/run_missing")
        assert missing[0] == 404
        cancel_missing = request(host, port, "POST", "/api/runs/run_missing/cancel")
        assert cancel_missing[0] == 404
        stream_missing = request(host, port, "GET", "/api/runs/run_missing/stream")
        assert stream_missing[0] == 404
        events_missing = request(host, port, "GET", "/api/runs/run_missing/events")
        assert events_missing[0] == 404
        assert json.loads(events_missing[1]).get("error")


def test_unconfigured_provider_is_clear_error_and_does_not_create(data_dir):
    adapter = ResponsesAdapter(ResponsesConfig(api_key="", model=""))
    system = LoopSystem(data_dir, adapter)
    before = system.list_run_ids()
    with running_server(system) as (_server, host, port):
        health = get_json(host, port, "/api/health")
        assert health["adapter"] == "responses"
        assert health["provider_available"] is False
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "build echo"})
        assert status == 503, body
        payload = json.loads(body)
        assert payload.get("reason") == "provider_unavailable"
        assert "YUDAO_MODEL_API_KEY" in payload["error"]
        assert system.list_run_ids() == before
        assert system.adapter.name == "responses"


def test_sse_resumes_from_after_seq_and_last_event_id(data_dir):
    system, projection = run_scripted(data_dir, happy_script())
    events = system.store.list_events(projection.run_id)
    mid = events[len(events) // 2].seq
    last = events[-1].seq
    with running_server(system) as (_server, host, port):
        after_block = first_loop_event(host, port, f"/api/runs/{projection.run_id}/stream?after_seq={mid}")
        assert sse_id(after_block) == mid + 1
        header_block = first_loop_event(
            host,
            port,
            f"/api/runs/{projection.run_id}/stream?after_seq=0",
            headers={"Last-Event-ID": str(mid)},
        )
        assert sse_id(header_block) == mid + 1
        last_block = first_loop_event(
            host,
            port,
            f"/api/runs/{projection.run_id}/stream?after_seq=0",
            headers={"Last-Event-ID": str(last - 1)},
        )
        assert sse_id(last_block) == last


def test_queries_do_not_mutate_existing_run(data_dir):
    system, projection = run_scripted(data_dir, happy_script())
    before = projection.canonical_state()
    with running_server(system) as (_server, host, port):
        payload = get_json(host, port, f"/api/runs/{projection.run_id}")
        assert payload["board"]["phase"] == "DONE"
        assert payload["timeline"]["requests"] == []
        assert payload["evidence"]["reviews"][0]["verdict"] == "release"
        assert payload["context"]["manifests"]
        manifests = payload["context"]["manifests"]
        assert all(item["step_id"] >= 1 and item["request_ref"] for item in manifests)
        assembled = next(event for event in system.store.list_events(projection.run_id)
                         if event.type == "context_assembled")
        detail = get_json(host, port, f"/api/runs/{projection.run_id}/events/{assembled.event_id}")
        assert manifests[0]["source_event_id"] == assembled.event_id
        assert detail["model_input"]["input"][0]["role"] == "developer"
        assert detail["model_input"]["tools"]
        events = get_json(host, port, f"/api/runs/{projection.run_id}/events")
        assert events["events"]
        replay = json.loads(request(host, port, "POST", f"/api/runs/{projection.run_id}/replay")[1])
        assert replay["ok"] is True
        assert replay["mutated"] is False
        after = system.project(projection.run_id)
        assert after.last_seq == projection.last_seq
        assert after.canonical_state() == before
        assert request(host, port, "POST", f"/api/runs/{projection.run_id}")[0] == 404


def test_effective_prd_and_plan_are_visible_from_their_accepted_materials(data_dir):
    system, projection = run_scripted(data_dir, happy_script())
    assert projection.phase == "DONE"
    with running_server(system) as (_server, host, port):
        payload = get_json(host, port, f"/api/runs/{projection.run_id}")
        contract = payload["timeline"]["effective_contract"]
        plan = payload["timeline"]["engineering_plan"]
        assert plan["effective_contract_hash"] == contract["content_hash"]
        assert payload["timeline"]["effective_contracts"] == [contract]
        assert payload["timeline"]["engineering_plans"] == [plan]
        for kind, item in (("prd", contract), ("plan", plan)):
            detail = get_json(host, port, f"/api/runs/{projection.run_id}/events/{item['created_event_id']}")
            ref = detail["payload"][f"{kind}_ref"]
            assert ref == item[f"{kind}_ref"]
            original = (system.artifacts.root / ref["path"]).read_bytes()
            material = data_dir / "materials" / projection.run_id / f"{kind.upper()}.md"
            assert detail[f"{kind}_markdown"].encode("utf-8") == original == material.read_bytes()
        assert system.project(projection.run_id).last_seq == projection.last_seq


@pytest.mark.parametrize("kind,event_type", [("prd", "contract_accepted"), ("plan", "plan_accepted")])
def test_document_detail_rejects_cross_run_material(data_dir, monkeypatch, kind, event_type):
    system, projection = run_scripted(data_dir, happy_script())
    event = next(item for item in system.store.list_events(projection.run_id) if item.type == event_type)
    ref = event.payload[f"{kind}_ref"]
    original = (system.artifacts.root / ref["path"]).read_bytes()
    foreign = system.artifacts.put("another-run", kind, original, media_type="text/markdown")
    event.payload[f"{kind}_ref"] = asdict(foreign)
    monkeypatch.setattr(system.store, "get_event", lambda _event_id: event)
    with running_server(system) as (_server, host, port):
        status, body, _ = request(host, port, "GET", f"/api/runs/{projection.run_id}/events/{event.event_id}")
        assert status in {400, 500}, body
        assert f"{kind}_markdown" not in json.loads(body)


@pytest.mark.parametrize("failure", ["missing_with_other_run_copy", "modified_bytes", "foreign_reference"])
def test_model_input_detail_rejects_invalid_or_cross_run_artifact(data_dir, monkeypatch, failure):
    system, projection = run_scripted(data_dir, happy_script())
    event = next(item for item in system.store.list_events(projection.run_id) if item.type == "context_assembled")
    ref = event.payload["request_ref"]
    original = system.artifacts.root / ref["path"]
    foreign = system.artifacts.put("another-run", "model_request", original.read_bytes(), media_type="application/json")
    if failure == "missing_with_other_run_copy":
        original.unlink()
    elif failure == "modified_bytes":
        original.write_text('{"input": "modified"}', encoding="utf-8")
    else:
        event.payload["request_ref"] = asdict(foreign)
        monkeypatch.setattr(system.store, "get_event", lambda _event_id: event)
    with running_server(system) as (_server, host, port):
        status, body, _ = request(host, port, "GET", f"/api/runs/{projection.run_id}/events/{event.event_id}")
        assert status in {400, 500}, body
        assert "model_input" not in json.loads(body)


def test_compaction_details_link_to_complete_original_tool_output(tmp_path):
    from harness.tests.test_compaction_engine import _runner

    system, _, run_id, _ = _runner(tmp_path)
    projection = system.activate_once(run_id)
    compaction = projection.compactions[-1]
    with running_server(system) as (_server, host, port):
        payload = get_json(host, port, f"/api/runs/{run_id}")
        assert payload["context"]["compactions"][-1]["source_event_id"] == compaction["source_event_id"]
        detail = get_json(host, port, f"/api/runs/{run_id}/events/{compaction['source_event_id']}")
        assert detail["compaction_summary"] == compaction["checkpoint"]["summary"]
        source = next(item for item in detail["source_events"] if item["type"] == "tool_called")
        original = get_json(host, port, f"/api/runs/{run_id}/events/{source['event_id']}")
        assert original["output"].count("FIRST_TOOL_ORIGINAL") == 2200
        assert original["role"] == detail["role"]


def test_serve_cli_defaults_to_responses_and_accepts_fake(monkeypatch, tmp_path):
    seen = {}

    def fake_serve(system, host, port):
        seen["name"] = system.adapter.name
        seen["host"] = host
        seen["port"] = port
        return 0

    monkeypatch.setattr("harness.__main__._serve", fake_serve)
    assert main(["serve", "--data-dir", str(tmp_path)]) == 0
    assert seen["name"] == "responses"
    assert main(["serve", "--adapter", "fake", "--data-dir", str(tmp_path), "--host", "127.0.0.1", "--port", "0"]) == 0
    assert seen["name"] == "fake"
    assert seen["port"] == 0


def test_serve_cli_unconfigured_responses_prints_error_but_starts(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("YUDAO_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("YUDAO_MODEL_NAME", raising=False)
    started = {}

    class Dummy:
        base_url = "http://127.0.0.1:0"

        def serve_forever(self):
            started["ok"] = True
            raise KeyboardInterrupt()

        def server_close(self):
            started["closed"] = True

    monkeypatch.setattr("harness.__main__.serve", lambda system, host, port: Dummy())
    code = main(["serve", "--data-dir", str(tmp_path), "--port", "0"])
    assert code == 0
    err = capsys.readouterr().err
    assert "YUDAO_MODEL_API_KEY" in err
    assert started["ok"] is True
    assert started["closed"] is True


def test_serve_cli_rejects_unknown_adapter(tmp_path):
    with pytest.raises(SystemExit):
        main(["serve", "--adapter", "openai", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        main(["serve", "--adapter", "omp", "--data-dir", str(tmp_path)])


def test_worker_exception_is_visible_and_does_not_complete(data_dir):
    system = LoopSystem(data_dir, FakeAdapter(happy_script()))

    def boom(_run_id):
        raise RuntimeError("boom-worker")

    system.run_until_stop = boom
    with running_server(system) as (server, host, port):
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "explode"})
        assert status == 201, body
        run_id = json.loads(body)["run_id"]
        wait_until(lambda: not server.busy())
        health = get_json(host, port, "/api/health")
        assert health["busy"] is False
        assert health["worker_error"]["run_id"] == run_id
        assert "boom-worker" in health["worker_error"]["message"]
        payload = get_json(host, port, f"/api/runs/{run_id}")
        assert payload["board"]["phase"] != "DONE"
        assert payload["board"]["outcome"] != "done"
        assert payload["execution_error"]
        assert "boom-worker" in payload["execution_error"]
        events = system.store.list_events(run_id)
        assert events
        assert not any(event.state_after == "DONE" for event in events)
        before = system.project(run_id)
        replay = json.loads(request(host, port, "POST", f"/api/runs/{run_id}/replay")[1])
        assert replay["ok"] is True
        assert replay["mutated"] is False
        after = system.project(run_id)
        assert after.last_seq == before.last_seq
        assert after.canonical_state() == before.canonical_state()


def test_unconfigured_provider_stays_on_health_after_listing_runs(data_dir):
    adapter = ResponsesAdapter(ResponsesConfig(api_key="", model=""))
    system, projection = run_scripted(data_dir, happy_script())
    system.adapter = adapter
    with running_server(system) as (_server, host, port):
        listed = get_json(host, port, "/api/runs")
        assert listed["runs"][0]["run_id"] == projection.run_id
        done = get_json(host, port, f"/api/runs/{projection.run_id}")
        assert done["board"]["phase"] == "DONE"
        health = get_json(host, port, "/api/health")
        assert health["provider_available"] is False
        assert health["provider_message"]
        html = request(host, port, "GET", "/")[1]
        assert 'id="provider-alert"' in html
        assert health["provider_message"] != done["board"]["phase"]


def test_health_stays_busy_after_cancel_until_worker_exits_without_new_events(data_dir):
    adapter, entered, release = gated_adapter()
    system = LoopSystem(data_dir, adapter)
    with running_server(system) as (server, host, port):
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "hold"})
        assert status == 201, body
        run_id = json.loads(body)["run_id"]
        assert entered.wait(timeout=5)
        status, body, _ = request(host, port, "POST", f"/api/runs/{run_id}/cancel")
        assert status == 200, body
        after_cancel = system.project(run_id)
        assert after_cancel.phase == "FAILED"
        last_seq = after_cancel.last_seq
        time.sleep(0.25)
        assert server.busy() is True
        health = get_json(host, port, "/api/health")
        assert health["busy"] is True
        assert health["active_run_id"] == run_id
        assert system.project(run_id).last_seq == last_seq
        release.set()
        wait_until(lambda: not server.busy())
        idle = get_json(host, port, "/api/health")
        assert idle["busy"] is False
        assert idle["active_run_id"] is None


def test_worker_error_after_last_event_is_on_that_run_only(data_dir):
    entered = threading.Event()
    release = threading.Event()

    def late(_run_id):
        entered.set()
        if not release.wait(timeout=20):
            raise TimeoutError("late worker was not released")
        raise RuntimeError("late-boom")

    system = LoopSystem(data_dir, FakeAdapter(happy_script()))
    original_run = system.run_until_stop
    system.run_until_stop = late
    with running_server(system) as (server, host, port):
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "late"})
        assert status == 201, body
        run_id = json.loads(body)["run_id"]
        assert entered.wait(timeout=5)
        before = get_json(host, port, f"/api/runs/{run_id}")
        assert before["execution_error"] is None
        seq = system.project(run_id).last_seq
        assert get_json(host, port, "/api/health")["busy"] is True
        release.set()
        wait_until(lambda: not server.busy())
        health = get_json(host, port, "/api/health")
        assert health["busy"] is False
        assert health["worker_error"]["run_id"] == run_id
        assert "late-boom" in health["worker_error"]["message"]
        crashed = get_json(host, port, f"/api/runs/{run_id}")
        assert "late-boom" in (crashed["execution_error"] or "")
        assert system.project(run_id).last_seq == seq
        system.run_until_stop = original_run
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "next"})
        assert status == 201, body
        other_id = json.loads(body)["run_id"]
        other = wait_terminal(host, port, other_id)
        assert other["execution_error"] is None
        still = get_json(host, port, f"/api/runs/{run_id}")
        assert "late-boom" in (still["execution_error"] or "")


def test_web_ui_node_behaviors():
    script = Path(__file__).with_name("test_web_ui.js")
    result = subprocess.run(
        ["node", "--test", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    print(output)
    if result.returncode != 0:
        raise AssertionError(output)
    assert "scheduleRefresh of B runs after in-flight A when switching gen" in output
    assert "pollWorkerHealth re-enables start after delayed busy=false without SSE" in output
    assert "late worker_error for selected run appears from health without new events" in output
    assert "worker_error of another run does not fill exec-alert" in output
    assert "cycle band shows" in output
    assert "new-task entry focuses existing input" in output
    assert "successful start leaves compose" in output
    assert "failed start stays on compose" in output
    assert "scrollBoardIntoView only moves the board on mobile" in output
    assert "desktop successful start does not force-scroll" in output
    assert "board distinguishes actual provider from adapter" in output
    assert "zero missing and invalid cost" in output
    assert "tiny positive cost is not rounded to zero" in output
    assert "missing event model is" in output
    assert "latest event model follows seq" in output


@pytest.fixture
def archived_run(data_dir):
    system = LoopSystem(data_dir, FakeAdapter(happy_script()))
    run_id = system.create_run("build echo")
    workspace = system.workspace(run_id)
    workspace.write_file(".settings", "hidden configuration\n")
    (workspace.root / "assets").mkdir()
    (workspace.root / "assets" / "data.bin").write_bytes(b"\x00\xff\x01")
    (workspace.root / "empty").mkdir()
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    return system, projection


def test_delivery_event_exposes_complete_persisted_manifest_and_original_blob(archived_run):
    system, projection = archived_run
    delivery = projection.delivery_spec
    workspace = system.workspace(projection.run_id)
    workspace.write_file("src/echo.py", "changed after delivery\n")
    (workspace.root / "assets" / "data.bin").unlink()
    endpoint = f"/api/runs/{projection.run_id}/events/{delivery.created_event_id}"
    with running_server(system) as (_server, host, port):
        detail = get_json(host, port, endpoint)
        archive = detail["tree_archive"]
        assert archive["tree_digest"] == delivery.code_tree_digest
        assert archive["tree"]["directories"] == ["assets", "empty", "src"]
        assert [file["path"] for file in archive["tree"]["files"]] == [".settings", "assets/data.bin", "src/echo.py"]
        assert delivery.files == ["src/echo.py"]
        for blob in archive["blobs"]:
            assert blob["artifact"]["path"].startswith(projection.run_id + "/")
            assert (system.artifacts.root / blob["artifact"]["path"]).is_file()
        conn = HTTPConnection(host, port)
        try:
            conn.request("GET", endpoint + "/files?path=" + quote("assets/data.bin", safe=""))
            response = conn.getresponse()
            assert response.status == 200
            assert response.read() == b"\x00\xff\x01"
            assert response.headers["Content-Type"] == "application/octet-stream"
            assert response.headers["Content-Disposition"] == "attachment; filename*=UTF-8''data.bin"
        finally:
            conn.close()
        status, body, _ = request(host, port, "GET", endpoint + "/files?path=src%2Fecho.py")
        assert status == 200
        assert "changed after delivery" not in body
        assert "print" in body


def test_delivery_download_is_limited_to_the_current_run_and_archived_paths(archived_run):
    system, projection = archived_run
    other_run = system.create_run("other task")
    event_id = projection.delivery_spec.created_event_id
    endpoint = f"/api/runs/{projection.run_id}/events/{event_id}/files"
    with running_server(system) as (_server, host, port):
        for path in (".checks/receipts.jsonl", "../outside", "unarchived.py", "empty"):
            assert request(host, port, "GET", endpoint + "?path=" + quote(path, safe=""))[0] == 404
        assert request(host, port, "GET", endpoint)[0] == 400
        assert request(host, port, "GET", endpoint + "?path=src/echo.py&path=.settings")[0] == 400
        foreign = f"/api/runs/{other_run}/events/{event_id}"
        assert request(host, port, "GET", foreign)[0] == 404
        assert request(host, port, "GET", foreign + "/files?path=.settings")[0] == 404


@pytest.mark.parametrize("damage", ["missing", "modified"])
def test_delivery_web_rejects_incomplete_or_corrupted_archive(archived_run, damage):
    system, projection = archived_run
    delivery = projection.delivery_spec
    archive = json.loads(system.artifacts.get_for_run(projection.run_id, delivery.tree_ref))
    blob = system.artifacts.root / archive["blobs"][0]["artifact"]["path"]
    if damage == "missing":
        blob.unlink()
    else:
        blob.write_bytes(b"corrupt archive")
    endpoint = f"/api/runs/{projection.run_id}/events/{delivery.created_event_id}"
    with running_server(system) as (_server, host, port):
        for url in (endpoint, endpoint + "/files?path=src%2Fecho.py"):
            status, body, _ = request(host, port, "GET", url)
            assert status in {400, 500}
            assert json.loads(body)["error"]


@pytest.mark.parametrize("mismatch", ["run", "tree_digest"])
def test_delivery_web_rejects_archive_not_bound_to_its_acceptance(archived_run, monkeypatch, mismatch):
    system, projection = archived_run
    delivery = projection.delivery_spec
    event = system.store.get_event(delivery.created_event_id)
    payload = dict(event.payload)
    if mismatch == "run":
        other_run = system.create_run("unrelated task")
        data = system.artifacts.get_for_run(projection.run_id, delivery.tree_ref)
        payload["tree_ref"] = asdict(system.artifacts.put(other_run, "tree_manifest", data, media_type="application/json"))
    else:
        payload["code_tree_digest"] = "sha256:" + "0" * 64
    changed = replace(event, payload=payload)
    get_event = system.store.get_event
    monkeypatch.setattr(system.store, "get_event", lambda event_id: changed if event_id == event.event_id else get_event(event_id))
    endpoint = f"/api/runs/{projection.run_id}/events/{delivery.created_event_id}"
    with running_server(system) as (_server, host, port):
        for url in (endpoint, endpoint + "/files?path=src%2Fecho.py"):
            status, body, _ = request(host, port, "GET", url)
            assert status == 400
            assert json.loads(body)["error"]

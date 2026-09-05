import json
import subprocess
import threading
import time
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path

import pytest

from harness.__main__ import main
from harness.adapters.fake import FakeAdapter
from harness.adapters.omp import UNAVAILABLE_MESSAGE, OmpConfig, OmpRpcAdapter
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
            {"task": "build echo", "max_cycles": 6, "token_budget": 80000, "context_window": 16000},
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
            {"task": "x", "token_budget": -1},
            {"task": "x", "context_window": True},
            {"task": "x", "max_cycles": 1.5},
            {"task": "x", "token_budget": 8.0},
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
    adapter = OmpRpcAdapter(OmpConfig(command=["omp"], enabled=False))
    system = LoopSystem(data_dir, adapter)
    before = system.list_run_ids()
    with running_server(system) as (_server, host, port):
        health = get_json(host, port, "/api/health")
        assert health["adapter"] == "omp"
        assert health["provider_available"] is False
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "build echo"})
        assert status == 503, body
        payload = json.loads(body)
        assert payload.get("reason") == "provider_unavailable"
        assert "fake" in payload["error"].lower() or "不会" in payload["error"]
        assert UNAVAILABLE_MESSAGE[:12] in payload["error"] or "OMP" in payload["error"]
        assert system.list_run_ids() == before
        assert system.adapter.name == "omp"


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
        assert payload["timeline"]["asks"] == []
        assert payload["evidence"]["reviews"][0]["verdict"] == "release"
        assert payload["context"]["manifests"]
        events = get_json(host, port, f"/api/runs/{projection.run_id}/events")
        assert events["events"]
        replay = json.loads(request(host, port, "POST", f"/api/runs/{projection.run_id}/replay")[1])
        assert replay["ok"] is True
        assert replay["mutated"] is False
        after = system.project(projection.run_id)
        assert after.last_seq == projection.last_seq
        assert after.canonical_state() == before
        assert request(host, port, "POST", f"/api/runs/{projection.run_id}")[0] == 404


def test_serve_cli_defaults_to_omp_and_accepts_fake(monkeypatch, tmp_path):
    seen = {}

    def fake_serve(system, host, port):
        seen["name"] = system.adapter.name
        seen["host"] = host
        seen["port"] = port
        return 0

    monkeypatch.setattr("harness.__main__._serve", fake_serve)
    assert main(["serve", "--data-dir", str(tmp_path)]) == 0
    assert seen["name"] == "omp"
    assert main(["serve", "--adapter", "fake", "--data-dir", str(tmp_path), "--host", "127.0.0.1", "--port", "0"]) == 0
    assert seen["name"] == "fake"
    assert seen["port"] == 0


def test_serve_cli_unconfigured_omp_prints_error_but_starts(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("YUDAO_OMP_ENABLED", raising=False)
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
    assert "OMP" in err
    assert "fake" in err.lower()
    assert started["ok"] is True
    assert started["closed"] is True


def test_serve_cli_rejects_unknown_adapter(tmp_path):
    with pytest.raises(SystemExit):
        main(["serve", "--adapter", "openai", "--data-dir", str(tmp_path)])


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
    adapter = OmpRpcAdapter(OmpConfig(command=["omp"], enabled=False))
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

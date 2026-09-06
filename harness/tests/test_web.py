import json
import subprocess
import threading
import time
from dataclasses import asdict, replace
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from harness.__main__ import main
from harness.adapters.fake import FakeAdapter
from harness.adapters.responses import ResponsesAdapter, ResponsesConfig
from harness.git_versions import GitVersionError
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, run_scripted
from harness.web.server import serve
from harness.views import retry_view
from harness.models import EventType


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


def request(host, port, method, path, body=None, headers=None, timeout=15):
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


def provider_config(tmp_path, *, credential_ref="MISSING_PROVIDER_KEY"):
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({
        "providers": [{"id": "provider", "name": "Provider", "protocol": "responses",
                       "base_url": "https://provider.example/v1", "credential_ref": credential_ref}],
        "models": [{"id": "model", "provider_id": "provider", "model": "model",
                     "context_window": 32000, "max_output_tokens": 4096}],
        "bindings": {department: {"provider_id": "provider", "model_id": "model"}
                     for department in ("product", "engineering", "quality")},
    }), encoding="utf-8")
    return config


def wait_until(predicate, timeout=45.0, interval=0.05):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timeout waiting, last={last!r}")


def wait_terminal(host, port, run_id, timeout=45.0):
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


def retry_event(seq, event_type, payload=None, *, role="engineering", error=None, stop_reason=None):
    return SimpleNamespace(
        event_id=f"event-{seq}", seq=seq, type=event_type, role=role,
        payload=payload or {}, error=error, stop_reason=stop_reason,
    )


def test_retry_view_tracks_waiting_attempt_and_clears_on_next_logical_request():
    activation = retry_event(1, EventType.DEPARTMENT_ACTIVATED, {"activation_id": "a1"})
    context = retry_event(2, EventType.CONTEXT_ASSEMBLED, {
        "activation_id": "a1", "step_id": 1, "attempt": 1, "root_step_id": 1,
        "retry_of_step_id": None, "purpose": "work",
    })
    requested = retry_event(3, EventType.MODEL_REQUESTED, {
        "activation_id": "a1", "step_id": 1, "attempt": 1,
    })
    failed = retry_event(4, EventType.MODEL_ATTEMPT_FAILED, {
        "activation_id": "a1", "step_id": 1, "attempt": 1, "max_attempts": 3,
        "root_step_id": 1, "retry_of_step_id": None, "reason": "provider_error",
        "error": "sanitized provider failure", "retryable": True,
    })
    scheduled = retry_event(5, EventType.MODEL_RETRY_SCHEDULED, {
        "activation_id": "a1", "step_id": 1, "attempt": 1, "max_attempts": 3,
        "root_step_id": 1, "retry_of_step_id": None, "next_step_id": 2,
        "next_attempt": 2, "delay_sec": 2,
    })
    waiting = retry_view([activation, context, requested, failed, scheduled])
    assert waiting["status"] == "waiting"
    assert waiting["attempt"] == 1
    assert waiting["next_attempt"] == 2
    assert waiting["delay_sec"] == 2
    assert waiting["last_error"] == "sanitized provider failure"

    next_context = retry_event(6, EventType.CONTEXT_ASSEMBLED, {
        "activation_id": "a1", "step_id": 2, "attempt": 2, "root_step_id": 1,
        "retry_of_step_id": 1, "purpose": "work",
    })
    next_request = retry_event(7, EventType.MODEL_REQUESTED, {
        "activation_id": "a1", "step_id": 2, "attempt": 2,
        "root_step_id": 1, "retry_of_step_id": 1,
    })
    recovered = retry_view([activation, context, requested, failed, scheduled, next_context, next_request])
    assert recovered["status"] == "requesting"
    assert recovered["attempt"] == 2

    ordinary_context = retry_event(8, EventType.CONTEXT_ASSEMBLED, {
        "activation_id": "a1", "step_id": 3, "attempt": 1, "root_step_id": 3,
        "retry_of_step_id": None, "purpose": "work",
    })
    ordinary_request = retry_event(9, EventType.MODEL_REQUESTED, {
        "activation_id": "a1", "step_id": 3, "attempt": 1,
    })
    ordinary_message = retry_event(10, EventType.MODEL_MESSAGE, {
        "activation_id": "a1", "step_id": 3, "attempt": 1,
    })
    cleared = retry_view([
        activation, context, requested, failed, scheduled, next_context, next_request,
        ordinary_context, ordinary_request, ordinary_message,
    ])
    assert cleared["status"] == "idle"
    assert cleared["last_error"] is None


def test_retry_view_clears_waiting_when_a_new_activation_supersedes_it():
    events = [
        retry_event(1, EventType.DEPARTMENT_ACTIVATED, {"activation_id": "old"}),
        retry_event(2, EventType.MODEL_REQUESTED, {"activation_id": "old", "step_id": 1, "attempt": 1}),
        retry_event(3, EventType.MODEL_ATTEMPT_FAILED, {
            "activation_id": "old", "step_id": 1, "attempt": 1, "max_attempts": 3,
            "root_step_id": 1, "retry_of_step_id": None, "reason": "provider_error",
            "error": "old failure", "retryable": True,
        }),
        retry_event(4, EventType.MODEL_RETRY_SCHEDULED, {
            "activation_id": "old", "step_id": 1, "attempt": 1, "max_attempts": 3,
            "root_step_id": 1, "retry_of_step_id": None, "next_step_id": 2,
            "next_attempt": 2, "delay_sec": 2,
        }),
        retry_event(5, EventType.DEPARTMENT_ACTIVATED, {"activation_id": "new"}),
    ]
    result = retry_view(events)
    assert result["status"] == "idle"
    assert result["last_error"] is None


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
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
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
        assert 'id="department-workspace-prototype"' in html
        assert 'class="dw-shell"' in html
        assert 'data-view="overview"' in html
        assert 'data-department="product"' in html
        assert 'data-department="engineering"' in html
        assert 'data-department="quality"' in html
        assert 'data-view="observability"' in html
        assert 'id="dw-task-dialog-form"' in html
        assert 'src="/static/lucide.min.js"' in html
        assert "python -m" not in html
        assert "Event Store" not in html
        assert 'class="panel"' not in html
        assert request(host, port, "GET", "/static/play.svg")[0] == 404
        lucide_status, lucide = request(host, port, "GET", "/static/lucide.min.js")[:2]
        assert lucide_status == 200 and "createIcons" in lucide
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
        assert 'data-action="new-task"' in js
        assert 'data-action="history"' in js
        assert "/departments/" in js and "/events/" in js
        assert "dw-panel-provider" in js
        assert "/model-attempts" in js and "/model-usage" in js
        health = get_json(host, port, "/api/health")
        assert health["ok"] is True
        assert health["adapter"] == "fake"
        assert health.get("worker_error") is None
        assert "readonly" not in health or health["readonly"] is False


def test_create_run_goes_through_engine_and_replays(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
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
    system = LoopSystem.for_testing(data_dir, adapter)
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


def test_live_input_and_prompt_keep_originals_and_activate_next_versions(data_dir):
    entered, release = threading.Event(), threading.Event()

    def held(_request):
        entered.set()
        assert release.wait(10)
        return product_spec()

    adapter = FakeAdapter([held, *happy_script()])
    system = LoopSystem.for_testing(data_dir, adapter)
    original, addition, prompt = "  echo\r\n", "继续\n  ", "  PRODUCT_PROMPT_V2\r\n按原文处理需求。  "
    with running_server(system) as (server, host, port):
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": original})
        assert status == 201, body
        run_id = json.loads(body)["run_id"]
        try:
            assert entered.wait(5)
            status, body, _ = request(host, port, "POST", f"/api/runs/{run_id}/inputs", {"text": addition})
            assert status == 201 and json.loads(body)["input_version"] == 2, body
            assert json.loads(body)["processed_input_version"] == 0
            status, body, _ = request(host, port, "POST", f"/api/runs/{run_id}/prompts/product", {"text": prompt})
            assert status == 201 and json.loads(body)["prompt_version"] == 2, body
            live = get_json(host, port, f"/api/runs/{run_id}")
            assert live["board"]["task"] == original + addition
            assert [item["text"] for item in live["inputs"]] == [original, addition]
            assert live["inputs"][1]["byte_start"] == len(original.encode("utf-8"))
            assert live["inputs"][1]["byte_end"] == len((original + addition).encode("utf-8"))
            item = live["inputs"][1]
            detail = get_json(host, port, f"/api/runs/{run_id}/events/{item['created_event_id']}")
            assert detail["input"] == addition and detail["intend"] == original + addition
            current = live["prompts"]["current"]["product"]
            assert current["text"] == prompt
            detail = get_json(host, port, f"/api/runs/{run_id}/events/{current['created_event_id']}")
            assert detail["prompt"] == prompt
            assert server.busy()
        finally:
            release.set()
        finished = wait_terminal(host, port, run_id)
        assert finished["board"]["phase"] == "DONE", finished["board"]
        assert finished["board"]["processed_input_version"] == 2
        assert [(item.input_version, item.prompt_version) for item in adapter.invocations[:2]] == [(1, 1), (2, 2)]
        assert "PRODUCT_PROMPT_V2" not in adapter.invocations[0].input_items[0]["content"]
        assert prompt in adapter.invocations[1].input_items[0]["content"]
        assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()


@pytest.mark.parametrize("text", [" /stop\r\n", "\n/cancel  "])
def test_text_cancel_records_raw_command_before_immediate_cancellation(data_dir, text):
    adapter, entered, release = gated_adapter()
    system = LoopSystem.for_testing(data_dir, adapter)
    with running_server(system) as (server, host, port):
        _, body, _ = request(host, port, "POST", "/api/runs", {"task": "echo"})
        run_id = json.loads(body)["run_id"]
        try:
            assert entered.wait(5)
            status, body, _ = request(host, port, "POST", f"/api/runs/{run_id}/inputs", {"text": text})
            assert status == 201 and json.loads(body)["phase"] == "FAILED", body
            current = system.project(run_id)
            assert current.stop_reason == "cancelled" and current.inputs[-1].text == text
            assert current.inputs[-1].kind == "command" and server.busy()
            events = system.store.list_events(run_id)
            received = next(event for event in events if event.type == "user_input_received")
            stopped = next(event for event in events if event.type == "run_failed")
            assert received.seq < stopped.seq
        finally:
            release.set()


@pytest.mark.parametrize("text", [" /stop\r\n", "\n/cancel  "])
@pytest.mark.parametrize("record_cancellation", [True, False])
def test_text_cancel_reports_stopped_when_git_input_save_fails(data_dir, monkeypatch, text, record_cancellation):
    adapter, entered, release = gated_adapter()
    system = LoopSystem.for_testing(data_dir, adapter)
    with running_server(system) as (server, host, port):
        _, body, _ = request(host, port, "POST", "/api/runs", {"task": "echo"})
        run_id = json.loads(body)["run_id"]
        try:
            assert entered.wait(5)
            before = system.project(run_id)
            insert = system.store._insert

            def fail_git(*args, **kwargs):
                raise GitVersionError("injected Git save failure")

            def fail_cancellation(event):
                if event.type == "run_failed":
                    raise OSError("injected cancellation event save failure")
                return insert(event)

            with monkeypatch.context() as patch:
                patch.setattr(system.git_versions, "prepare", fail_git)
                if not record_cancellation:
                    patch.setattr(system.store, "_insert", fail_cancellation)
                status, body, _ = request(host, port, "POST", f"/api/runs/{run_id}/inputs", {"text": text})
            result = json.loads(body)
            assert status == 503, result
            assert result["code"] == "cancelled_input_not_saved"
            assert result["cancelled"] is True and result["run_id"] == run_id
            assert result["cancellation_recorded"] is record_cancellation
            assert "执行已取消" in result["error"] and "未形成正式 Git 版本" in result["error"]
            assert system.orchestrator._abort[run_id].is_set()
            assert adapter._aborted == {before.sessions["product"].session_id}
            current = system.project(run_id)
            assert current.input_version == before.input_version and current.git_version == before.git_version
            assert [item.text for item in current.inputs] == ["echo"]
            events = system.store.list_events(run_id)
            assert not any(event.type == "user_input_received" for event in events)
            stopped = [event for event in events if event.type == "run_failed"]
            if record_cancellation:
                assert current.phase == "FAILED" and current.stop_reason == "cancelled"
                assert stopped[-1].payload["input_save_failure"]["text"] == text
                assert "git_version" not in stopped[-1].payload
                detail = get_json(host, port, f"/api/runs/{run_id}/events/{stopped[-1].event_id}")
                assert detail["payload"]["input_save_failure"]["text"] == text
                payload = get_json(host, port, f"/api/runs/{run_id}")
                card = next(item for item in payload["events"] if item["event_id"] == stopped[-1].event_id)
                assert card["input_save_failure"]["text"] == text
            else:
                assert stopped == []
                assert "取消事实也未能保存" in result["error"]
        finally:
            release.set()
        wait_until(lambda: not server.busy())
        assert system.project(run_id).product_spec is None


def test_cancel_button_needs_no_git_save_or_raw_command(data_dir, monkeypatch):
    adapter, entered, release = gated_adapter()
    system = LoopSystem.for_testing(data_dir, adapter)
    with running_server(system) as (server, host, port):
        _, body, _ = request(host, port, "POST", "/api/runs", {"task": "echo"})
        run_id = json.loads(body)["run_id"]
        try:
            assert entered.wait(5)
            before = system.project(run_id)

            def unexpected_git(*args, **kwargs):
                raise AssertionError("Button cancellation must not save a Git input version")

            monkeypatch.setattr(system.git_versions, "prepare", unexpected_git)
            status, body, _ = request(host, port, "POST", f"/api/runs/{run_id}/cancel")
            assert status == 200 and json.loads(body)["stop_reason"] == "cancelled", body
            current = system.project(run_id)
            assert current.input_version == before.input_version and current.git_version == before.git_version
            events = system.store.list_events(run_id)
            assert not any(event.type == "user_input_received" for event in events)
            stopped = next(event for event in events if event.type == "run_failed")
            assert "input_save_failure" not in stopped.payload
        finally:
            release.set()
        wait_until(lambda: not server.busy())


def test_input_and_prompt_api_reject_unknown_fields_and_terminal_runs(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    run_id = system.create_run("echo")
    with running_server(system) as (_server, host, port):
        for suffix in ("inputs", "prompts/product"):
            for body in ({"text": "x", "attachments": []}, {"text": "x", "extra": True}, {"text": []}, {"text": "  "}):
                status, raw, _ = request(host, port, "POST", f"/api/runs/{run_id}/{suffix}", body)
                assert status == 400, raw
        status, _, _ = request(host, port, "POST", f"/api/runs/{run_id}/prompts/unknown", {"text": "x"})
        assert status == 400
        system.cancel(run_id)
        before = system.project(run_id)
        assert len(before.inputs) == 1
        for suffix in ("inputs", "prompts/product"):
            status, raw, _ = request(host, port, "POST", f"/api/runs/{run_id}/{suffix}", {"text": "new"})
            assert status == 409 and json.loads(raw)["reason"] == "run_terminal", raw
        assert system.project(run_id).canonical_state() == before.canonical_state()


def test_cancel_keeps_slot_until_worker_exits(data_dir):
    adapter, entered, release = gated_adapter()
    system = LoopSystem.for_testing(data_dir, adapter)
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
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
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


def test_unconfigured_test_provider_is_clear_error_and_does_not_create(data_dir):
    adapter = ResponsesAdapter(ResponsesConfig(api_key="", model=""))
    system = LoopSystem.for_testing(data_dir, adapter)
    before = system.list_run_ids()
    with running_server(system) as (_server, host, port):
        health = get_json(host, port, "/api/health")
        assert health["adapter"] == "responses"
        assert health["provider_available"] is False
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "build echo"})
        assert status == 503, body
        payload = json.loads(body)
        assert payload.get("reason") == "provider_unavailable"
        assert "provider credential" in payload["error"]
        assert system.list_run_ids() == before
        assert system.test_adapter.name == "responses"


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


def test_serve_cli_requires_provider_config(monkeypatch, tmp_path):
    seen = {}

    def fake_serve(system, host, port):
        seen["catalog"] = system.provider_catalog
        seen["host"] = host
        seen["port"] = port
        return 0

    monkeypatch.setattr("harness.__main__._serve", fake_serve)
    config = provider_config(tmp_path)
    assert main(["serve", "--provider-config", str(config), "--data-dir", str(tmp_path), "--port", "0"]) == 0
    assert seen["catalog"] is not None
    assert seen["port"] == 0


def test_serve_cli_unconfigured_responses_prints_error_but_starts(monkeypatch, tmp_path, capsys):
    started = {}

    class Dummy:
        base_url = "http://127.0.0.1:0"

        def serve_forever(self):
            started["ok"] = True
            raise KeyboardInterrupt()

        def server_close(self):
            started["closed"] = True

    monkeypatch.setattr("harness.__main__.serve", lambda system, host, port: Dummy())
    config = provider_config(tmp_path)
    code = main(["serve", "--provider-config", str(config), "--data-dir", str(tmp_path), "--port", "0"])
    assert code == 0
    err = capsys.readouterr().err
    assert "credential reference cannot be resolved" in err
    assert started["ok"] is True
    assert started["closed"] is True


def test_serve_cli_rejects_missing_or_removed_adapter_flags(tmp_path):
    with pytest.raises(SystemExit):
        main(["serve", "--data-dir", str(tmp_path)])
    with pytest.raises(SystemExit):
        main(["serve", "--adapter", "fake", "--provider-config", str(provider_config(tmp_path)), "--data-dir", str(tmp_path)])


def test_worker_exception_is_visible_and_does_not_complete(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))

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
    system.test_adapter = adapter
    with running_server(system) as (_server, host, port):
        listed = get_json(host, port, "/api/runs")
        assert listed["runs"][0]["run_id"] == projection.run_id
        done = get_json(host, port, f"/api/runs/{projection.run_id}")
        assert done["board"]["phase"] == "DONE"
        health = get_json(host, port, "/api/health")
        assert health["provider_available"] is False
        assert health["provider_message"]
        html = request(host, port, "GET", "/")[1]
        assert 'id="dw-task-dialog-form"' in html
        status, body, _ = request(host, port, "POST", "/api/runs", {"task": "must be rejected"})
        assert status == 503
        assert health["provider_message"] in body
        assert health["provider_message"] != done["board"]["phase"]


def test_health_stays_busy_after_cancel_until_worker_exits_without_new_events(data_dir):
    adapter, entered, release = gated_adapter()
    system = LoopSystem.for_testing(data_dir, adapter)
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

    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
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
    assert "tests" in output
    assert "pass" in output
    assert "fail 0" in output


@pytest.fixture
def archived_run(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
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


@pytest.fixture
def revised_git_run(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([
        product_spec(goal="Echo the argument unchanged"),
        product_spec(goal="Echo the argument in uppercase", requirements=["Uppercase the given argument"],
                     acceptance=["hello prints HELLO"], change_record={
                         "changed": ["Uppercase the output"], "retained": ["Local single-file CLI"],
                         "retired": ["Output the argument unchanged"],
                         "rationale": "Apply the user's explicit new output direction",
                     }),
    ]))
    run_id = system.create_run("  Echo the argument unchanged.\r\n")
    system.activate_once(run_id)
    system.add_input(run_id, "  Uppercase the output instead.\n")
    system.activate_once(run_id)
    return system, system.project(run_id)


def test_web_git_versions_show_raw_input_and_real_requirement_changes(revised_git_run):
    system, projection = revised_git_run
    run_id = projection.run_id
    with running_server(system) as (_server, host, port):
        view = get_json(host, port, f"/api/runs/{run_id}")
        assert all(item["git_version"]["commit"] for item in view["inputs"])
        assert all(item["git_version"]["commit"] for item in view["timeline"]["effective_contracts"])
        for item in [*projection.inputs, *projection.product_specs, *projection.effective_contracts]:
            detail = get_json(host, port, f"/api/runs/{run_id}/events/{item.created_event_id}")
            version = detail["git_version_detail"]
            assert {key: version[key] for key in ("commit", "parent_commit", "tree")} == detail["payload"]["git_version"]
            assert all(not file["path"].startswith(("/", ".git/", ".checks/")) for file in version["files"])
            assert str(system.data_dir) not in version["diff"]
        initial = get_json(host, port, f"/api/runs/{run_id}/events/{projection.inputs[0].created_event_id}")
        assert initial["git_version_detail"]["parent_commit"] is None
        current = get_json(host, port, f"/api/runs/{run_id}/events/{projection.effective_contract.created_event_id}")
        assert "-Echo the argument unchanged" in current["git_version_detail"]["diff"]
        assert "+Echo the argument in uppercase" in current["git_version_detail"]["diff"]
        assert any(file["path"] == "PRD.md" and file["status"] == "M" for file in current["git_version_detail"]["files"])
        assert "Uppercase the output" in current["prd_markdown"]


def test_web_git_versions_include_plan_binary_delivery_and_no_current_tree_fallback(archived_run):
    system, projection = archived_run
    run_id = projection.run_id
    system.workspace(run_id).write_file("src/echo.py", "CURRENT_TREE_CHANGED")
    with running_server(system) as (_server, host, port):
        plan = get_json(host, port, f"/api/runs/{run_id}/events/{projection.engineering_plan.created_event_id}")
        assert any(file["path"] == "PLAN.md" for file in plan["git_version_detail"]["files"])
        delivery = get_json(host, port, f"/api/runs/{run_id}/events/{projection.delivery_spec.created_event_id}")
        version = delivery["git_version_detail"]
        assert {"path": "code/assets/data.bin", "status": "A", "binary": True} in version["files"]
        assert "Binary files" in version["diff"]
        assert "CURRENT_TREE_CHANGED" not in version["diff"]
        assert any(file["path"] == "assets/data.bin" for file in delivery["tree_archive"]["tree"]["files"])


@pytest.mark.parametrize("mismatch", ["same_run_commit", "tree", "material"])
def test_web_git_versions_reject_refs_or_materials_not_bound_to_the_event(revised_git_run, monkeypatch, mismatch):
    system, projection = revised_git_run
    run_id = projection.run_id
    event = system.store.get_event(projection.effective_contract.created_event_id)
    payload = dict(event.payload)
    if mismatch == "same_run_commit":
        payload["git_version"] = system.store.get_event(projection.inputs[-1].created_event_id).payload["git_version"]
    elif mismatch == "tree":
        payload["git_version"] = {**payload["git_version"], "tree": "0" * 40}
    else:
        payload["prd_ref"] = asdict(system.artifacts.put(run_id, "prd", "FORGED_ACCEPTED_MATERIAL", media_type="text/markdown"))
    changed = replace(event, payload=payload)
    original_get, original_list = system.store.get_event, system.store.list_events
    monkeypatch.setattr(system.store, "get_event", lambda event_id: changed if event_id == event.event_id else original_get(event_id))
    monkeypatch.setattr(system.store, "list_events", lambda *args, **kwargs: [
        changed if item.event_id == event.event_id else item for item in original_list(*args, **kwargs)
    ])
    with running_server(system) as (_server, host, port):
        status, body, _ = request(host, port, "GET", f"/api/runs/{run_id}/events/{event.event_id}")
        assert status == 400, body
        assert "Git" in json.loads(body)["error"]
        assert str(system.data_dir) not in body


def test_web_git_versions_reject_missing_objects_and_cross_run_event_queries(revised_git_run):
    system, projection = revised_git_run
    run_id = projection.run_id
    event = system.store.get_event(projection.effective_contract.created_event_id)
    other_run = system.create_run("Other task")
    commit = event.payload["git_version"]["commit"]
    obj = system.data_dir / "git" / f"{run_id}.git" / "objects" / commit[:2] / commit[2:]
    obj.chmod(0o600)
    obj.unlink()
    with running_server(system) as (_server, host, port):
        status, body, _ = request(host, port, "GET", f"/api/runs/{run_id}/events/{event.event_id}")
        assert status == 400 and "Git" in json.loads(body)["error"], body
        assert str(system.data_dir) not in body
        assert request(host, port, "GET", f"/api/runs/{other_run}/events/{event.event_id}")[0] == 404
        assert request(host, port, "GET", f"/api/runs/{run_id}/git/{commit}")[0] == 404

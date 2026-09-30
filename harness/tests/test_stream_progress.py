"""Bounded host-side progress facts for provider streams."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from harness.tests.protocol_helpers import ResponsesAdapter
from harness.models import ArtifactRef, EventType
from harness.tests.test_responses import KEY, _event, _server, _submit_stream
from harness.providers.responses import ResponsesConfig
from harness.runtime import LoopSystem


@contextmanager
def _chunked_stream(frames: list[bytes]):
    # 本机提供方：用分块传输逐帧发送流事件，帧之间停顿 0.4 秒，用来核对按时间的补充记录已经去掉
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for frame in frames:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(frame), frame))
                self.wfile.flush()
                time.sleep(0.4)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    config = ResponsesConfig(model="local-model", api_key=KEY, provider="local-stub",
                             base_url=f"http://127.0.0.1:{server.server_port}/v1", timeout_sec=30)
    try:
        yield config
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_stream_artifact_records_host_observed_time_and_progress_stages(tmp_path: Path):
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        run_id = system.create_run("stream progress")
        system.activate_once(run_id)

    events = system.store.list_events(run_id)
    progress = [event for event in events if event.type == EventType.MODEL_STREAM_PROGRESS]
    finished = next(event for event in events if event.type == EventType.MODEL_ATTEMPT_FINISHED)
    assert progress
    assert progress[0].payload["attempt_id"] == finished.payload["attempt_id"]
    assert progress[0].payload["first_observed_at"]
    assert any(event.payload["stage"] == "response_created" for event in progress)
    assert any(event.payload["stage"] == "output_item_done" for event in progress)
    for event in progress:
        datetime.fromisoformat(event.payload["observed_at"])
        assert event.payload["source"] == "sdk_decoded_stream"
        assert "event" not in event.payload

    ref = ArtifactRef(**finished.payload["stream_events_ref"])
    lines = [json.loads(line) for line in system.artifacts.get_for_run(run_id, ref).decode("utf-8").splitlines()]
    assert lines
    assert all(item["observed_at"] for item in lines)
    assert all("event" in item for item in lines)
    assert all("observed_at" not in item["event"] for item in lines)


def test_stream_progress_is_recorded_only_when_the_stage_changes(tmp_path: Path):
    # 输出片段加入以后（设计说明第 10 节第 5 项），同一次调用尝试中 model_stream_progress 只在阶段变化时写入：
    # 同一阶段的多条流事件只记录第一条，不再按时间间隔补充
    opening = _event("response.created", response={"id": "resp-one", "object": "response",
                    "status": "in_progress", "output": [], "usage": None}, sequence_number=0)

    def delta(text, sequence):
        return _event("response.output_text.delta", item_id="msg-1", output_index=0, content_index=0,
                      delta=text, sequence_number=sequence)

    # 帧之间停顿 0.4 秒：按时间的补充记录会为第二阶段再写一条，只在阶段变化时写入则只有一条。
    # 最后一条帧结束这次流（带提交调用），第一次调用尝试因此正常结束，不产生重试
    frames = [opening, delta("hello", 1), delta(" world", 2), delta(" again", 3),
              _event("response.completed", response={"id": "resp-one", "object": "response", "status": "completed",
                     "output": [], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}},
                     sequence_number=4),
              _submit_stream()]

    with _chunked_stream(frames) as config:
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        run_id = system.create_run("stream progress stage change")
        system.activate_once(run_id)

    events = system.store.list_events(run_id)
    first = next(event for event in events if event.type == EventType.MODEL_REQUESTED)
    attempt_id = first.payload["attempt_id"]
    progress = [event for event in events
                if event.type == EventType.MODEL_STREAM_PROGRESS and event.payload["attempt_id"] == attempt_id]
    stages = [event.payload["stage"] for event in progress]
    assert stages == ["response_created", "output", "completed"]

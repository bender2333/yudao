import json

from harness.adapters.fake import FakeAdapter
from harness.deltas import DeltaFragment
from harness.models import EventType
from harness.providers.call import CallUsage, ModelDelta, ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem

_USAGE = CallUsage(input_tokens=10, output_tokens=5, total_tokens=15, reported=True)

def _stream_event(text, offset, sequence, channel="output"):
    return ModelStreamEvent(
        kind="stream_event", id=f"stream-{sequence}", payload={"type": "response.output_text.delta"},
        source="sdk_decoded_stream", sequence=sequence, stage="output",
        deltas=(ModelDelta(channel=channel, offset=offset, text=text),),
    )

def _answer(text="done"):
    return ModelResponse(output=[{"type": "message", "content": [{"type": "output_text", "text": text}]}],
                         usage=_USAGE, provider="test", model="test-model")

def test_stream_deltas_are_published_with_offsets_and_kept_out_of_the_event_log(tmp_path):
    # 步骤驱动把调用合同里的片段发布到输出片段通道：订阅方按调用尝试收到片段与范围，
    # 片段不写入事件日志；调用尝试结束以后通道发出关闭通知
    def turn(call):
        yield _stream_event("hello", 0, 0)
        yield _stream_event(" world", 5, 1)
        yield _stream_event("again", 0, 2, channel="reasoning")
        return _answer()

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([turn]))
    fragments: list[DeltaFragment] = []
    closed_attempts: list[str] = []
    system.deltas.subscribe(lambda item: fragments.append(item) if isinstance(item, DeltaFragment)
                            else closed_attempts.append(item.attempt_id))

    run_id = system.create_run("deltas")
    system.activate_once(run_id)

    seen = [(item.channel, item.offset, item.text) for item in fragments]
    assert seen == [("output", 0, "hello"), ("output", 5, " world"), ("reasoning", 0, "again")]
    assert sorted(closed_attempts) == sorted({item.scope.attempt_id for item in fragments})
    assert all(item.scope.run_id == run_id for item in fragments)
    assert all(item.scope.project_id == system.project(run_id).project_id for item in fragments)

    events = system.store.list_events(run_id)
    assert not any(event.type == "delta" for event in events)
    serialized = json.dumps([event.payload for event in events], ensure_ascii=False)
    assert "hello" not in serialized
    assert "reasoning" not in json.dumps([event.payload.get("stage") for event in events])


def test_stream_progress_with_deltas_writes_one_event_per_stage(tmp_path):
    # 同一次调用尝试中同一阶段的多条带片段的流事件，model_stream_progress 仍只写一条
    def turn(call):
        for index in range(4):
            yield _stream_event(f"part{index}", index * 5, index)
        return _answer()

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([turn]))
    run_id = system.create_run("deltas progress")
    system.activate_once(run_id)

    events = system.store.list_events(run_id)
    progress = [event for event in events if event.type == EventType.MODEL_STREAM_PROGRESS]
    assert [event.payload["stage"] for event in progress] == ["output"]

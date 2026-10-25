import pytest

from harness.event_store import EventStore, run_stream
from harness.projection import run_handler
from harness.write_path import NewEvent, WritePath


RUN = run_stream("run")


def _note(name, **fields):
    return NewEvent(name, state_before="running", state_after="running", actor="system", **fields)


def test_event_batch_commits_in_order_with_contiguous_versions_and_positions(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    writes = WritePath(store, lambda _stream: run_handler())
    [first] = writes.append(RUN, _note("before"))
    batch = writes.append(RUN, _note("first", payload={"value": 1}), _note("second", payload={"value": 2}))
    assert [event.stream_version for event in batch] == [first.stream_version + 1, first.stream_version + 2]
    assert [event.position for event in batch] == [first.position + 1, first.position + 2]
    assert store.list_events("run") == [first, *batch]
    assert len({event.event_id for event in batch}) == 2
    saved = store.projection(run_stream("run"))
    assert (saved.version, saved.position) == (3, batch[-1].position)


def test_failed_later_insert_rolls_back_the_whole_batch_and_its_projection(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    writes = WritePath(store, lambda _stream: run_handler())
    [first] = writes.append(RUN, _note("before"))
    saved = store.projection(run_stream("run"))
    with pytest.raises(TypeError):
        writes.append(RUN, _note("first"), _note("second", payload={"invalid": object()}))
    assert store.list_events("run") == [first]
    assert store.projection(run_stream("run")) == saved
    [after] = writes.append(RUN, _note("after"))
    assert (after.stream_version, after.position) == (first.stream_version + 1, first.position + 1)



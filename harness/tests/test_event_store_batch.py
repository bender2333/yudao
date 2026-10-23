import sqlite3

import pytest

from harness.event_store import EventStore, StreamVersionConflict, run_stream
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


def test_invalid_batch_entry_cannot_begin_a_partial_commit(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    writes = WritePath(store, lambda _stream: run_handler())
    with pytest.raises(sqlite3.IntegrityError):
        writes.append(RUN, _note("valid"),
                      NewEvent("invalid", state_before="running", state_after=None, actor="system"))
    assert store.list_events("run") == []
    assert store.projection(run_stream("run")) is None


def test_commit_with_a_stale_expected_version_is_rejected_without_writing(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    writes = WritePath(store, lambda _stream: run_handler())
    [first] = writes.append(RUN, _note("before"))
    saved = store.projection(run_stream("run"))
    with pytest.raises(StreamVersionConflict) as rejected:
        store.commit(run_stream("run"), 0, [], saved.state)
    assert (rejected.value.expected, rejected.value.actual) == (0, 1)
    assert "stale" in str(rejected.value)
    assert store.list_events("run") == [first]
    assert store.projection(run_stream("run")) == saved

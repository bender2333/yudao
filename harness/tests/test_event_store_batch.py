import sqlite3

import pytest

from harness.event_store import EventStore, NewEvent


def test_event_batch_commits_in_order_and_uses_one_contiguous_stream_version_range(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    [first] = store.append_batch("run", [NewEvent("before", state_before="CREATED", state_after="PRODUCT_SPEC")])
    batch = store.append_batch("run", [
        NewEvent("spec_accepted", state_before="PRODUCT_SPEC", state_after="PRODUCT_SPEC", payload={"value": "spec"}),
        NewEvent("contract_accepted", state_before="PRODUCT_SPEC", state_after="PRODUCT_SPEC",
                 payload={"value": "contract"}),
    ])
    assert [event.stream_version for event in batch] == [first.stream_version + 1, first.stream_version + 2]
    assert [event.position for event in batch] == [first.position + 1, first.position + 2]
    assert store.list_events("run") == [first, *batch]
    assert len({event.event_id for event in batch}) == 2


def test_failed_later_insert_rolls_back_the_whole_batch_without_consuming_versions_or_positions(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    [first] = store.append_batch("run", [NewEvent("before", state_before="CREATED", state_after="PRODUCT_SPEC")])
    with pytest.raises(TypeError):
        store.append_batch("run", [
            NewEvent("spec_accepted", state_before="PRODUCT_SPEC", state_after="PRODUCT_SPEC"),
            NewEvent("contract_accepted", state_before="PRODUCT_SPEC", state_after="PRODUCT_SPEC",
                     payload={"invalid": object()}),
        ])
    assert store.list_events("run") == [first]
    [after] = store.append_batch("run", [NewEvent("after", state_before="PRODUCT_SPEC", state_after="ENGINEERING")])
    assert (after.stream_version, after.position) == (first.stream_version + 1, first.position + 1)


def test_invalid_batch_entry_cannot_begin_a_partial_commit(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    with pytest.raises(sqlite3.IntegrityError):
        store.append_batch("run", [
            NewEvent("valid", state_before="CREATED", state_after="PRODUCT_SPEC"),
            NewEvent("invalid", state_before="PRODUCT_SPEC", state_after=None),
        ])
    assert store.list_events("run") == []

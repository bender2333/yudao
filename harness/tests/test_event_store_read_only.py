from pathlib import Path

import pytest

from harness.event_store import EventStore


def test_read_only_event_store_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError, match="event log does not exist"):
        EventStore(missing, read_only=True)


def test_read_only_event_store_refuses_write_methods_at_python_layer(tmp_path: Path) -> None:
    db_path = tmp_path / "events.sqlite"
    writable = EventStore(db_path)
    writable.close()

    store = EventStore(db_path, read_only=True)
    try:
        with pytest.raises(RuntimeError, match="the event store is open read-only"):
            store.commit("run:r1", 0, [], "running")
        with pytest.raises(RuntimeError, match="the event store is open read-only"):
            store.claim_execution_right("run:r1", 1, [], "running")
        with pytest.raises(RuntimeError, match="the event store is open read-only"):
            store.replace_projection("run:r1", "running", 0, 0)
    finally:
        store.close()


def test_read_only_event_store_allows_reading(tmp_path: Path) -> None:
    db_path = tmp_path / "events.sqlite"
    writable = EventStore(db_path)
    log_id = writable.log_id
    writable.close()

    store = EventStore(db_path, read_only=True)
    try:
        assert store.log_id == log_id
        assert store.list_run_ids() == []
    finally:
        store.close()

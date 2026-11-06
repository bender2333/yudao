# 事件库按全局位置取事件的合同（R2，docs/design/test-pyramid.md「测试按三环留」）：位置清单为空时返回空结果，
# 不读事件日志。接口层拒绝空清单的那一条在 harness/tests/test_event_positions.py；事件库自己的读取合同
# 要有一份守在内核目录里（特别规则 7）。
#
# 用真实的 SQLite 事件库：先写入一条事件并按位置取到它，证明这份日志里确实有事件；关掉事件库以后，
# 空位置清单仍然返回空结果，同一个调用要读日志时失败——空结果来自这一条早返回，不来自事件日志。
#
# 读真实的 SQLite 事件库，用临时目录，属于模块层。

import sqlite3

import pytest

from harness.event_store import EventStore, run_stream
from harness.projection import run_handler
from harness.write_path import NewEvent, WritePath


def test_an_empty_position_list_reads_nothing_without_touching_the_event_log(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    writes = WritePath(store, lambda _stream: run_handler())
    [event] = writes.append(run_stream("run"), NewEvent(
        "note", state_before="running", state_after="running", actor="system"))
    assert store.events_at([event.position]) == {event.position: event}

    store.close()
    # 空位置清单不需要打开事件日志：关掉连接以后仍然是空结果
    assert store.events_at([]) == {}
    # 对照：同一个调用要读日志时，关掉的连接让它失败
    with pytest.raises(sqlite3.ProgrammingError):
        store.events_at([event.position])

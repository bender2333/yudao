import sqlite3
from contextlib import closing

from harness.event_store import run_stream
from harness.models import json_dumps, new_id
from harness.projection import dump_projection

# 核对与审计必须面对已经保存的事实。这些辅助用 SQLite 的普通连接直接改写事件行、保存的投影与事件顺序，
# 不替换运行系统、事件库或工件库的任何读取方法。


def rewrite_saved_event(store, event) -> None:
    # 把内存中改过的事件写回它的事件行：载荷、上下文摘要与工件摘要
    with closing(_connection(store)) as connection:
        cursor = connection.execute(
            "UPDATE events SET payload_json = ?, context_digest = ?, artifact_hashes_json = ? WHERE event_id = ?",
            (json_dumps(event.payload), event.context_digest, json_dumps(event.artifact_hashes), event.event_id),
        )
        if cursor.rowcount != 1:
            raise AssertionError(f"event {event.event_id} was not rewritten")
        connection.commit()


def rewrite_saved_events(store, events) -> None:
    for event in events:
        rewrite_saved_event(store, event)


def rewrite_saved_projection(store, run_id, projection) -> None:
    # 把改过的运行状态写回这个流保存的投影：之后 project() 读到的就是这行
    with closing(_connection(store)) as connection:
        cursor = connection.execute(
            "UPDATE projections SET state = ? WHERE stream = ?",
            (dump_projection(projection), run_stream(run_id)),
        )
        if cursor.rowcount != 1:
            raise AssertionError(f"saved projection for {run_id} was not rewritten")
        connection.commit()


def delete_saved_events(store, event_ids) -> None:
    # 从事件库删除事件行：审计读到的就是这个流的实际记录
    event_ids = list(event_ids)
    if not event_ids:
        raise AssertionError("no saved events to delete")
    with closing(_connection(store)) as connection:
        cursor = connection.executemany("DELETE FROM events WHERE event_id = ?", [(event_id,) for event_id in event_ids])
        if cursor.rowcount != len(event_ids):
            raise AssertionError("saved events were not all deleted")
        connection.commit()


def insert_saved_event_after(store, source_event_id, after_event_id) -> str:
    # 在指定事件之后插入源事件的一份副本，返回新事件的身份。流内版本必须唯一，把后面的版本依次后移
    with closing(_connection(store)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            after = connection.execute(
                "SELECT stream, stream_version FROM events WHERE event_id = ?", (after_event_id,)
            ).fetchone()
            if after is None:
                raise AssertionError(f"event {after_event_id} is not saved")
            connection.execute(
                "UPDATE events SET stream_version = -stream_version WHERE stream = ? AND stream_version > ?",
                (after["stream"], after["stream_version"]),
            )
            connection.execute(
                "UPDATE events SET stream_version = -stream_version + 1 WHERE stream = ? AND stream_version < 0",
                (after["stream"],),
            )
            source = connection.execute("SELECT * FROM events WHERE event_id = ?", (source_event_id,)).fetchone()
            if source is None:
                raise AssertionError(f"event {source_event_id} is not saved")
            event_id = new_id("event")
            columns = [name for name in source.keys() if name != "position"]
            values = [
                event_id if name == "event_id"
                else after["stream_version"] + 1 if name == "stream_version"
                else source[name]
                for name in columns
            ]
            connection.execute(
                f"INSERT INTO events ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                values,
            )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    return event_id



def reload_without_saved_projection(data_dir) -> None:
    # 保存的投影位于事件日志的同一个文件里，改写事件以后要从事件重放补建，才与升级以后的数据目录一致
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        connection.execute("DELETE FROM projections")
        connection.commit()
    finally:
        connection.close()


def _connection(store) -> sqlite3.Connection:
    connection = sqlite3.connect(store.path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection

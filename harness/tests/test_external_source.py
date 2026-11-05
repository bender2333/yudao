# 外部来源工件的保存与读取（工单 #1171；网络取回与 MCP 设计说明第 6.4、9 节）。
#
# 本工单只做「存」与「读」两段：取回与 MCP 的保存随后接上。这里查三件事：
# 1. 存下来的多页文本按行范围与游标读，第二页接着第一页，超过输出上限的部分被标记；
# 2. 来源字段（来源、最终地址、状态码、内容类型、取得时间）随正文一起存下来并读得回来；
# 3. 读取查询按工件引用返回内容与来源字段，位置是所属事件的位置，内容被改动时返回错误，
#    调用前后事件日志末尾位置不变，能力清单列出这个查询。
#
# 层：模块层（工件库、事件库与工作区文件，都是真实实现）。守 R2（外部来源工件与查询的交换字段）
# 与 R3（部门经合同读取已保存的外部来源，界面与证据核对读取同一份原文）。

from __future__ import annotations

import asyncio

import pytest

from harness.actions import Action
from harness.app.application import Application, ReadOnlyCore
from harness.app.evidence_queries import ExternalSourceEvidence
from harness.app.project_queries import NotFound
from harness.artifacts import ArtifactStore, EXTERNAL_SOURCE_KIND
from harness.environment import LocalEnvironment
from harness.event_store import EventStore, run_stream
from harness.models import EventType
from harness.projection import run_handler
from harness.write_path import NewEvent, WritePath

RUN = "run_external_source"


def _source_text(lines: int, width: int = 40) -> str:
    return "".join(f"line {number:04d} " + "x" * width + "\n" for number in range(1, lines + 1))


def _store_text(tmp_path, text: str, **fields) -> tuple[ArtifactStore, object]:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.put_external_source(RUN, text, **fields)
    return store, ref


def _environment(tmp_path, store: ArtifactStore) -> LocalEnvironment:
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    return LocalEnvironment.open(root, artifacts=store, run_id=RUN)


def _read(environment: LocalEnvironment, tool_input: dict) -> object:
    return asyncio.run(environment.perform(Action(
        action_id="act:read", kind="read", tool="read_external_source", department="product", input=tool_input)))


def _recorded_event(data_dir, payload: dict, run_id: str = RUN) -> object:
    # 一条工具调用的记录，作为外部来源工件的所属事件（查询的位置取自它）
    store = EventStore(data_dir / "events.sqlite")
    writes = WritePath(store, lambda _stream: run_handler())
    [event] = writes.append(run_stream(run_id), NewEvent(
        EventType.TOOL_CALLED, state_before="running", state_after="running", actor="system", payload=payload))
    store.close()
    return event


def _application(data_dir) -> Application:
    return Application(ReadOnlyCore(data_dir))


def test_a_saved_source_is_read_by_page_with_a_cursor(tmp_path):
    # 一段比输出上限长的正文：第一页带截断标记与游标，第二页从第一页结束处接着读，
    # 两次读到的是同一份工件（摘要相同），不重新取回
    store, ref = _store_text(tmp_path, _source_text(400, width=80), source="https://example.com/long")
    environment = _environment(tmp_path, store)

    first = _read(environment, {"source": ref.content_hash, "start_line": 1})
    assert first.status == "completed" and first.ok
    assert first.output["truncated"] is True and first.output["next_cursor"] is not None
    assert first.output["content_hash"] == ref.content_hash
    assert first.output["total_lines"] == 400

    second = _read(environment, {
        "source": ref.content_hash, "start_line": 1, "cursor": first.output["next_cursor"]})
    assert second.status == "completed" and second.ok
    assert second.output["content_hash"] == ref.content_hash
    assert second.output["lines"][0]["line"] == first.output["end_line"] + 1
    assert second.output["lines"][-1]["text"] == f"line {second.output['end_line']:04d} " + "x" * 80


def test_the_source_fields_travel_with_the_content(tmp_path):
    store, ref = _store_text(
        tmp_path, "first\nsecond\n", source="https://example.com/a", final_url="https://example.com/b",
        status_code=200, content_type="text/plain")
    environment = _environment(tmp_path, store)

    read = _read(environment, {"source": ref.content_hash, "start_line": 1, "end_line": 1})

    assert read.output["lines"] == [{"line": 1, "text": "first"}]
    assert read.output["total_lines"] == 2
    assert read.output["source"] == "https://example.com/a"
    assert read.output["final_url"] == "https://example.com/b"
    assert read.output["status_code"] == 200
    assert read.output["content_type"] == "text/plain"
    assert read.output["fetched_at"]


def test_carriage_returns_are_stored_as_plain_newlines(tmp_path):
    store, ref = _store_text(tmp_path, "第一行\r\n第二行\r\n", source="https://example.com/crlf")
    environment = _environment(tmp_path, store)

    read = _read(environment, {"source": ref.content_hash, "start_line": 2})

    assert read.output["total_lines"] == 2
    assert read.output["lines"] == [{"line": 2, "text": "第二行"}]


def test_a_changed_artifact_fails_the_read(tmp_path):
    # 工件正文被改动过：摘要与引用不符，读不出来，回执写明原因
    store, ref = _store_text(tmp_path, "first\nsecond\n", source="https://example.com/tampered")
    path = tmp_path / "artifacts" / ref.path
    path.write_bytes("first\nsecond\nchanged\n".encode("utf-8"))
    environment = _environment(tmp_path, store)

    read = _read(environment, {"source": ref.content_hash, "start_line": 1})

    assert read.status == "failed" and not read.ok
    assert "content hash mismatch" in (read.error or "")


def test_the_query_returns_the_content_and_the_source_with_the_event_position(tmp_path):
    data_dir = tmp_path / "data"
    event = _recorded_event(data_dir, {"tool": "fetch_url", "ok": True})
    store = ArtifactStore(data_dir / "artifacts")
    ref = store.put_external_source(
        RUN, "first\nsecond\n", source="https://example.com/q", final_url="https://example.com/final",
        status_code=204, content_type="text/plain")
    application = _application(data_dir)
    try:
        before = application.system.store.end_position()
        snapshot = application.query("evidence.external_source", ExternalSourceEvidence(
            event_id=event.event_id, kind=ref.kind, content_hash=ref.content_hash, path=ref.path,
            media_type=ref.media_type))
        after = application.system.store.end_position()

        assert snapshot.position == event.position
        assert snapshot.data.content == "first\nsecond\n"
        assert snapshot.data.source == "https://example.com/q"
        assert snapshot.data.final_url == "https://example.com/final"
        assert snapshot.data.status_code == 204
        assert snapshot.data.content_type == "text/plain"
        assert snapshot.data.content_hash == ref.content_hash
        assert snapshot.data.total_lines == 2
        assert snapshot.data.fetched_at
        assert before == after, "读这份证据改变了事件日志"
        capabilities = application.capabilities("sha256:" + "0" * 64, access="local")
        assert "evidence.external_source" in [item.name for item in capabilities.queries]
    finally:
        application.close()


def test_the_query_rejects_another_run_and_a_changed_content(tmp_path):
    data_dir = tmp_path / "data"
    event = _recorded_event(data_dir, {"tool": "fetch_url", "ok": True})
    store = ArtifactStore(data_dir / "artifacts")
    kept = store.put_external_source(RUN, "kept\n", source="https://example.com/kept")
    other = store.put_external_source("run_other", "other\n", source="https://example.com/other")
    application = _application(data_dir)
    try:
        with pytest.raises(NotFound, match="does not belong to the event"):
            application.query("evidence.external_source", ExternalSourceEvidence(
                event_id=event.event_id, kind=other.kind, content_hash=other.content_hash, path=other.path))
        path = data_dir / "artifacts" / kept.path
        path.write_bytes("tampered\n".encode("utf-8"))
        with pytest.raises(NotFound, match="does not match its reference"):
            application.query("evidence.external_source", ExternalSourceEvidence(
                event_id=event.event_id, kind=kept.kind, content_hash=kept.content_hash, path=kept.path))
    finally:
        application.close()


def test_a_reference_that_is_not_an_external_source_is_rejected(tmp_path):
    data_dir = tmp_path / "data"
    event = _recorded_event(data_dir, {"tool": "fetch_url", "ok": True})
    application = _application(data_dir)
    try:
        with pytest.raises(NotFound, match="not an external source reference"):
            application.query("evidence.external_source", ExternalSourceEvidence(
                event_id=event.event_id, kind="tree_manifest", content_hash="sha256:" + "b" * 64,
                path=f"{RUN}/bb/" + "b" * 64))
    finally:
        application.close()


def test_the_query_asks_for_an_event_that_exists(tmp_path):
    data_dir = tmp_path / "data"
    _recorded_event(data_dir, {"tool": "fetch_url", "ok": True})
    store = ArtifactStore(data_dir / "artifacts")
    ref = store.put_external_source(RUN, "text\n", source="https://example.com/missing-event")
    application = _application(data_dir)
    try:
        with pytest.raises(NotFound, match="event not found"):
            application.query("evidence.external_source", ExternalSourceEvidence(
                event_id="evt_missing", kind=EXTERNAL_SOURCE_KIND, content_hash=ref.content_hash,
                path=ref.path))
    finally:
        application.close()

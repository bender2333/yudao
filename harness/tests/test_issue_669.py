# run_created 载荷里不再有事项级窗口（工单 #669）：窗口是调用目标的属性。
# 生效的窗口取自模型目录里的调用目标，记在每一次模型请求里；旧版本写下的这个字段读的时候忽略。
# 事件日志由事件库直接改写构造，不用 mock。

import json
import sqlite3

from harness.adapters.fake import FakeAdapter
from harness.event_store import run_stream
from harness.models import EventType
from harness.projection import project_run
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script


def _fake_model(system: LoopSystem) -> dict:
    models = system.facade.providers_view()["models"]
    model_id = f"{system.orchestrator.test_provider}-model"
    return next(model for model in models if model["id"] == model_id)


def test_new_run_created_has_no_window_and_the_call_target_carries_it(data_dir):
    # 新写入的 run_created 载荷不带事项级窗口；声明的窗口写进调用目标（模型目录里的 fake 模型），
    # 这一次运行生效的窗口记在模型请求里
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    try:
        run_id = system.create_run("核对窗口", context_window=6000)
        [created] = [event for event in system.store.list_events(run_id) if event.type == EventType.RUN_CREATED]
        assert "context_window" not in created.payload
        assert _fake_model(system)["context_window"] == 6000

        system.activate_once(run_id)
        [requested] = [event for event in system.store.list_events(run_id)
                       if event.type == EventType.MODEL_REQUESTED]
        assert requested.payload["effective_context_window"] == 6000
        # 投影里也没有事项级窗口字段
        assert not hasattr(project_run(system.store, run_id), "context_window")
    finally:
        system.close()


def test_old_run_created_with_window_is_read_without_it(data_dir):
    # 旧版本写下的 run_created 带着不再生效的事项级窗口：读的时候忽略这个字段，
    # 事件里的其它取值仍然生效（限额照旧，阶段照旧）
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    try:
        run_id = system.create_run("旧事件")
        [created] = [event for event in system.store.list_events(run_id) if event.type == EventType.RUN_CREATED]
        max_cycles = created.payload["max_cycles"]
        run_time_limit_sec = created.payload["run_time_limit_sec"]
    finally:
        system.close()
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        row = connection.execute(
            "SELECT payload_json FROM events WHERE stream = ? AND type = ?",
            (run_stream(run_id), "run_created")).fetchone()
        assert row is not None, "no run_created event"
        document = json.loads(row[0])
        document["context_window"] = 32000
        connection.execute("UPDATE events SET payload_json = ? WHERE stream = ? AND type = ?",
                           (json.dumps(document, ensure_ascii=False, sort_keys=True),
                            run_stream(run_id), "run_created"))
        # 保存的投影一并删掉，重新打开数据目录时按事件重放补建
        connection.execute("DELETE FROM projections")
        connection.commit()
    finally:
        connection.close()

    reopened = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()), resume_on_startup=False)
    try:
        run = project_run(reopened.store, run_id)
        assert not hasattr(run, "context_window")
        assert run.max_cycles == max_cycles
        assert run.run_time_limit_sec == run_time_limit_sec
        assert run.phase == "PRODUCT_SPEC"
    finally:
        reopened.close()

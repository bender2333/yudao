# run 事件版本（ADR-0019，工单 #126）：代码中声明当前的 run 事件版本，每个 run 在创建时记录它。
# 系统整体运行，模型回答由 FakeAdapter 给出。

from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.projection import project_run
from harness.runtime import LoopSystem
from harness.streams import RUN_EVENT_VERSION
from harness.tests.helpers import happy_script

def test_a_run_records_the_current_run_event_version(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    run_id = system.create_run("带版本的事项")
    [created] = [event for event in system.store.list_events(run_id) if event.type == EventType.RUN_CREATED]
    assert created.payload["run_event_version"] == RUN_EVENT_VERSION
    assert project_run(system.store, run_id).run_event_version == RUN_EVENT_VERSION



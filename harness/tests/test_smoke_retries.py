import json

import pytest

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import product_spec
from harness.providers.call import ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.smoke import isolation_fields
from harness.tests.helpers import FAST_RETRIES, after_event, system_on_copy
from harness.tests.saved_rewrite import insert_saved_event_after, rewrite_saved_event

# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次记录，每项测试复制一份数据目录，
# 在自己的副本上改写与检查。数据来自真实运行，登记为集成层。


def _retry_source(tmp_path):
    # 第一次请求重试一次以后给出有效要求停在工程部
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("retry audit")
    assert system.activate_once(run_id).phase == "ENGINEERING"
    return system, run_id


def _partial_source(tmp_path):
    # 流到一半失败：BOOL_HISTORY 中不留这次的输出，重试以后停在工程部
    partial = {
        "id": "failed-partial",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "partial output"}],
    }

    def fail_after_partial(request):
        yield ModelStreamEvent(kind="message", id="failed-partial", payload=partial, text="partial output")
        raise ProviderError("stream disconnected", retryable=True)

    adapter = FakeAdapter([fail_after_partial, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("partial retry audit")
    assert system.activate_once(run_id).phase == "ENGINEERING"
    assert "failed-partial" not in json.dumps(adapter.invocations[1].input_items)
    return system, run_id


def _saved_source(builder, directory):
    # 建完以后关闭系统：事件库连接关闭时把预写日志收回主文件，此后整目录复制即是一份新的数据目录
    system, run_id = builder(directory)
    system.close()
    return system.data_dir, run_id


@pytest.fixture(scope="module")
def saved_retry(tmp_path_factory):
    return _saved_source(_retry_source, tmp_path_factory.mktemp("retry"))


@pytest.fixture
def retry_run(saved_retry, tmp_path):
    saved, run_id = saved_retry
    return system_on_copy(saved, tmp_path / "retry"), run_id


@pytest.fixture(scope="module")
def saved_partial(tmp_path_factory):
    return _saved_source(_partial_source, tmp_path_factory.mktemp("partial"))


@pytest.fixture
def partial_run(saved_partial, tmp_path):
    saved, run_id = saved_partial
    return system_on_copy(saved, tmp_path / "partial"), run_id


def _prepared_source(tmp_path):
    adapter = FakeAdapter([ModelResponse(), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("prepared but not sent")

    def input_after_second_preparation(event):
        # 第二步装配好以后到达新输入，这一步的请求不再发出
        if event.payload["step_id"] == 2:
            system.add_input(run_id, "a new input before the second request")

    after_event(system, EventType.CONTEXT_ASSEMBLED, input_after_second_preparation)
    return system, run_id


@pytest.fixture(scope="module")
def saved_prepared(tmp_path_factory):
    def build(directory):
        system, run_id = _prepared_source(directory)
        assert system.activate_once(run_id).phase == "PRODUCT_SPEC"
        return system, run_id

    return _saved_source(build, tmp_path_factory.mktemp("prepared"))


@pytest.fixture
def prepared_run(saved_prepared, tmp_path):
    saved, run_id = saved_prepared
    return system_on_copy(saved, tmp_path / "prepared"), run_id


def _saved_events(system, run_id):
    # 审计读到的必须是事件库中保存的事件；测试改动以后写回事件行，再经公开接口运行审计
    return system.store.list_events(run_id)



def test_native_retry_events_are_verified_by_model_input_audit(retry_run):
    system, run_id = retry_run

    fields = isolation_fields(system.store, system.artifacts, run_id)
    audit = fields["model_input_audit"]
    assert fields["context_isolated"] is True, audit
    assert audit["status"] == "verified", audit
    assert audit["prepared_count"] == 2
    assert audit["request_count"] == audit["attempt_count"] == 2
    assert audit["retry_count"] == 1
    assert audit["logical_request_count"] == 1

    events = system.store.list_events(run_id)
    assert sum(event.type == EventType.MODEL_ATTEMPT_FAILED for event in events) == 1
    assert sum(event.type == EventType.MODEL_RETRY_SCHEDULED for event in events) == 1


def test_model_input_audit_rejects_retry_event_without_max_attempts(retry_run):
    system, run_id = retry_run
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    events = _saved_events(system, run_id)
    schedule = next(event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED)
    schedule.payload.pop("max_attempts")
    rewrite_saved_event(system.store, schedule)

    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert audit["status"] == "unverified"
    assert any("max_attempts" in note for note in audit["notes"])


def test_model_input_audit_rejects_retry_event_with_wrong_next_attempt(retry_run):
    system, run_id = retry_run
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    events = _saved_events(system, run_id)
    schedule = next(event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED)
    schedule.payload["next_attempt"] = schedule.payload["attempt"] + 2
    rewrite_saved_event(system.store, schedule)

    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert audit["status"] == "unverified"
    assert any("invalid retryability or attempt" in note for note in audit["notes"])


@pytest.mark.parametrize("event_type,field", [
    (EventType.MODEL_ATTEMPT_FAILED, "attempt"),
    (EventType.MODEL_RETRY_SCHEDULED, "max_attempts"),
    (EventType.MODEL_REQUESTED, "attempt"),
    (EventType.MODEL_REQUESTED, "max_attempts"),
    (EventType.MODEL_REQUESTED, "root_step_id"),
    (EventType.MODEL_REQUESTED, "retry_of_step_id"),
])
def test_model_input_audit_rejects_missing_retry_metadata(retry_run, event_type, field):
    system, run_id = retry_run
    assert isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]["status"] == "verified"
    events = _saved_events(system, run_id)
    event = next(item for item in events if item.type == event_type)
    event.payload.pop(field)
    rewrite_saved_event(system.store, event)

    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert audit["status"] == "unverified"
    assert any(field in note for note in audit["notes"])


def test_failed_partial_output_is_removed_from_retry_history_and_late_residue_fails_audit(partial_run):
    system, run_id = partial_run

    clean = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert clean["status"] == "verified", clean

    events = _saved_events(system, run_id)
    partial_event = next(event for event in events
                         if event.type == EventType.MODEL_MESSAGE
                         and event.payload.get("response_id") == "failed-partial")
    failure = next(event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED)
    # 失败之后又保存了一条这个步骤的输出：插入一条真实的事件行，审计必须发现
    insert_saved_event_after(system.store, partial_event.event_id, failure.event_id)
    residue = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert residue["status"] == "unverified"
    assert any("failed model step produced output" in note for note in residue["notes"])


def test_model_input_audit_counts_prepared_step_without_request_separately(prepared_run):
    system, run_id = prepared_run

    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert audit["prepared_count"] == 2
    assert audit["request_count"] == audit["attempt_count"] == 1
    assert audit["unrequested_count"] == 1
    assert audit["status"] == "verified", audit["notes"]

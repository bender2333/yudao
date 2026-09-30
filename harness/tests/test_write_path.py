import threading

import pytest

from harness.adapters.fake import FakeAdapter
from harness.event_store import (
    Command, CommandIdReused, DuplicateCommand, StaleExecutionRight, StreamVersionConflict, project_stream, run_stream,
)
from harness.models import ProjectEventType
from harness.runtime import LoopSystem
from harness.write_path import MAX_JUDGMENTS, NewEvent, NewProjectEvent

# 写入口：在同一事务中读取保存的投影、判断并追加；提交时核对流版本、命令身份与执行权编号，提交以后通知订阅方。
# 系统整体运行，模型回答由 FakeAdapter 脚本给出，事件库是真实的 SQLite 文件。


def _project(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("项目", "逐行文本处理工具")
    return system, project_id, project_stream(project_id)


def _rename(name):
    return NewProjectEvent(ProjectEventType.PROJECT_RENAMED, {"name": name}, actor="user:local")


def _types(system, project_id):
    return [event.type for event in system.store.list_project_events(project_id)]


def test_two_writes_with_the_same_expected_version_only_one_succeeds(data_dir):
    system, project_id, stream = _project(data_dir)
    version = system.writes.read(stream).version
    both_read = threading.Barrier(2)
    outcomes = {}

    def rename(name):
        def decide(transaction):
            # 两次写入都在对方提交之前读取了同一个版本
            both_read.wait(5)
            transaction.append(_rename(name))

        try:
            system.writes.transact(stream, decide, expected_version=version)
            outcomes[name] = "committed"
        except StreamVersionConflict as exc:
            outcomes[name] = exc

    threads = [threading.Thread(target=rename, args=(name,)) for name in ("甲", "乙")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    committed = [name for name, outcome in outcomes.items() if outcome == "committed"]
    rejected = [outcome for outcome in outcomes.values() if outcome != "committed"]
    assert len(committed) == 1 and len(rejected) == 1
    assert (rejected[0].stream, rejected[0].expected, rejected[0].actual) == (stream, version, version + 1)
    assert f"at version {version + 1}, not the expected version {version}" in str(rejected[0])
    assert _types(system, project_id) == [ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED]
    assert system.projects.projection(project_id).name == committed[0]


def test_a_judgment_made_stale_by_a_concurrent_write_is_rejected_and_made_again(data_dir):
    system, project_id, stream = _project(data_dir)
    seen = []

    def rename_unless_pinned(transaction):
        seen.append(transaction.projection.pinned)
        if len(seen) == 1:
            # 判断以后、提交之前，另一个线程把项目置顶
            other = threading.Thread(target=system.projects.pin, args=(project_id, True))
            other.start()
            other.join(10)
        if not transaction.projection.pinned:
            transaction.append(_rename("新名字"))

    system.writes.transact(stream, rename_unless_pinned)
    # 第一次判断的依据过期，提交被拒绝；按写入以后的状态重新判断，不再改名
    assert seen == [False, True]
    assert _types(system, project_id) == [ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_PINNED]


def test_a_stale_expected_version_is_rejected_without_judging_again(data_dir):
    system, project_id, stream = _project(data_dir)
    version = system.writes.read(stream).version
    calls = []

    def rename_with_concurrent_pin(transaction):
        calls.append(transaction.version)
        other = threading.Thread(target=system.projects.pin, args=(project_id, True))
        other.start()
        other.join(10)
        transaction.append(_rename("新名字"))

    with pytest.raises(StreamVersionConflict):
        system.writes.transact(stream, rename_with_concurrent_pin, expected_version=version)
    assert calls == [version]
    with pytest.raises(StreamVersionConflict):
        system.writes.transact(stream, rename_with_concurrent_pin, expected_version=version)
    assert calls == [version]
    assert _types(system, project_id) == [ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_PINNED]


def test_one_command_identity_is_registered_once(data_dir):
    system, project_id, stream = _project(data_dir)
    calls = []

    def rename(transaction):
        calls.append(transaction.version)
        transaction.append(_rename(f"名字 {len(calls)}"))

    command = Command("command-1", "project.rename", "sha256:first", "user:local")
    system.writes.transact(stream, rename, command=command)
    renamed = system.store.list_project_events(project_id)[-1]
    position = renamed.position
    # 命令追加的事件记下命令身份与提出者；不是由命令写入的事件没有命令身份，提出者由写入方声明（第 5.2 节）
    assert (renamed.command_id, renamed.actor) == ("command-1", "user:local")
    assert (system.store.list_project_events(project_id)[0].command_id,
            system.store.list_project_events(project_id)[0].actor) == (None, "user:local")
    assert [event.event_id for event in system.store.command_events("command-1")] == [renamed.event_id]
    record = system.store.command("command-1")
    assert (record.name, record.digest, record.stream, record.position) == (
        "project.rename", "sha256:first", stream, position)
    assert system.store.command("command-unknown") is None
    with pytest.raises(DuplicateCommand) as duplicate:
        system.writes.transact(stream, rename, command=command)
    assert (duplicate.value.record.position, duplicate.value.record.stream) == (position, stream)
    # 重复与否只比较名称与摘要，不比较提出者
    with pytest.raises(DuplicateCommand):
        system.writes.transact(stream, rename, command=Command("command-1", "project.rename", "sha256:first",
                                                               "user:laptop"))
    with pytest.raises(CommandIdReused):
        system.writes.transact(stream, rename, command=Command("command-1", "project.rename", "sha256:other",
                                                               "user:local"))
    assert len(calls) == 1 and len(system.store.list_project_events(project_id)) == 2

    # 被拒绝的命令不登记，同一身份重试时重新判断
    def refuse(_transaction):
        raise ValueError("stale_base")

    second = Command("command-2", "project.rename", "sha256:second", "user:local")
    with pytest.raises(ValueError):
        system.writes.transact(stream, refuse, command=second)
    assert system.store.command("command-2") is None
    system.writes.transact(stream, rename, command=second)
    assert len(calls) == 2

    # 同一命令同时提交两次：只有一次写入，另一次得到原来的结果
    both_read = threading.Barrier(2)
    outcomes = []

    def submit():
        def decide(transaction):
            both_read.wait(5)
            transaction.append(_rename("同时提交"))

        try:
            system.writes.transact(stream, decide,
                                   command=Command("command-3", "project.rename", "sha256:third", "user:local"))
            outcomes.append("committed")
        except DuplicateCommand as exc:
            outcomes.append(exc.record.position)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    events = system.store.list_project_events(project_id)
    assert sorted(outcomes, key=str) == sorted(["committed", events[-1].position], key=str)
    assert [event.payload["name"] for event in events[1:]] == ["名字 1", "名字 2", "同时提交"]


def test_a_command_that_appends_nothing_is_registered_at_the_end_of_the_log(data_dir):
    system, project_id, stream = _project(data_dir)
    end = system.store.end_position()
    system.writes.transact(stream, lambda _transaction: None,
                           command=Command("command-1", "project.restore", "sha256:first", "user:local"))
    assert system.store.command("command-1").position == end
    assert system.store.command_events("command-1") == []
    assert system.store.end_position() == end


def test_the_log_identity_stays_with_the_data_directory(tmp_path):
    first = LoopSystem.for_testing(tmp_path / "first", FakeAdapter([]))
    identity = first.store.log_id
    first.close()
    # 重新打开同一个数据目录得到同一个日志身份；另一个数据目录的日志身份不同
    assert LoopSystem.for_testing(tmp_path / "first", FakeAdapter([])).store.log_id == identity
    assert LoopSystem.for_testing(tmp_path / "second", FakeAdapter([])).store.log_id != identity


def test_the_execution_right_number_is_recorded_and_an_older_number_is_refused(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    run_id = system.create_run("build echo")
    stream = run_stream(run_id)

    def note(transaction):
        phase = transaction.projection.phase
        return transaction.append(NewEvent("execution_note", state_before=phase, state_after=phase,
                                           actor="user:local"))[0]

    first = system.writes.transact(stream, note, epoch=2)
    assert first.epoch == 2 and system.store.get_event(first.event_id).epoch == 2
    before = system.store.list_events(run_id)
    with pytest.raises(StaleExecutionRight) as refused:
        system.writes.transact(stream, note, epoch=1)
    assert (refused.value.epoch, refused.value.recorded) == (1, 2)
    assert system.store.list_events(run_id) == before
    # 不带编号的写入（用户的命令与输入）不作比较；更大的编号可以写入
    assert system.writes.transact(stream, note).epoch is None
    assert system.writes.transact(stream, note, epoch=3).epoch == 3
    assert system.store.projection(stream).epoch == 3


def test_subscribers_are_notified_after_each_commit_without_any_lock_held(data_dir):
    system, project_id, stream = _project(data_dir)
    received = []

    def listener(events):
        # 通知时事件已经提交，在其他连接上可以读到
        assert [event.event_id for event in system.store.read(events[0].position - 1, limit=len(events))] == [
            event.event_id for event in events]
        received.append([(event.type, event.position) for event in events])
        if len(received) == 1:
            # 通知时不持有任何锁：订阅方可以写入
            system.projects.pin(project_id, True)

    unsubscribe = system.store.subscribe(listener)
    system.projects.rename(project_id, "新名字")
    unsubscribe()
    system.projects.rename(project_id, "又一个名字")
    renamed, pinned = system.store.list_project_events(project_id)[1:3]
    assert received == [[(ProjectEventType.PROJECT_RENAMED, renamed.position)],
                        [(ProjectEventType.PROJECT_PINNED, pinned.position)]]
    assert len(system.store.list_project_events(project_id)) == 4


def test_a_failing_subscriber_does_not_undo_a_committed_write(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    run_id = system.create_run("original")

    def failing(_events):
        raise RuntimeError("subscriber failed")

    system.store.subscribe(failing)
    with pytest.raises(RuntimeError, match="subscriber failed"):
        system.add_input(run_id, " and more")
    # 写入已经提交：事件与投影都在，发布的原始意图没有被撤回
    assert system.project(run_id).input_version == 2
    assert (data_dir / "materials" / run_id / "intend.md").read_bytes() == b"original and more"


def test_a_judgment_that_keeps_losing_to_other_writes_gives_up_with_the_conflict(data_dir):
    system, project_id, stream = _project(data_dir)
    attempts = []

    def rename_while_others_write(transaction):
        attempts.append(transaction.version)
        other = threading.Thread(target=system.projects.pin, args=(project_id, len(attempts) % 2 == 1))
        other.start()
        other.join(10)
        transaction.append(_rename("不会写入"))

    with pytest.raises(StreamVersionConflict):
        system.writes.transact(stream, rename_while_others_write)
    assert len(attempts) == MAX_JUDGMENTS
    assert ProjectEventType.PROJECT_RENAMED not in _types(system, project_id)

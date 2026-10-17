# 恢复观察与故障矩阵验收（工单 #18，应用层与接口层设计说明第 4.3 节「恢复与动作核实（3.1）」）。
# 数据目录是真实的 SQLite 事件日志，服务启动经真实的 LoopSystem，模型回答由 FakeAdapter 给出；
# 中断由「进程关闭、重新以新的系统打开同一数据目录」表示。查询只读取，事件流重连只补观察事实。

import asyncio
import json
import uuid
from dataclasses import asdict

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.decision_commands import DecisionAnswer
from harness.app.event_stream import EventScope
from harness.app.project_queries import (
    PROJECT_LOOP,
    PROJECTS_LIST,
    REPLAY_CHECK,
    RUN_ACTIONS,
    RUN_RECOVERY,
    ProjectLoop,
    ProjectsList,
    ReplayCheck,
    RunActions,
    RunRecovery,
)
from harness.app.system_queries import SYSTEM_STATUS, SystemStatusRequest
from harness.event_store import run_stream
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.write_path import NewEvent

def _application(system: LoopSystem) -> Application:
    return Application(system)

def _query(application: Application, definition, request):
    return application.query(definition.name, request).data

def _work_item_run(system: LoopSystem, task: str):
    # 一个项目与一个事项：事项的 run 由 start_work_item 创建并记录项目与事项
    project_id = system.projects.register("恢复观察", "核对恢复观察状态")
    work_item_id, run_id = system.projects.start_work_item(project_id, task)
    return project_id, work_item_id, run_id

def _engineering_run(data_dir, script):
    # 一个已完成产品规格、停在 ENGINEERING 的 run：事件版本相同、未结束，进程在这里退出后
    # 启动时会自动继续它。中断前的回答由 script 给出
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    project_id, _work_item_id, run_id = _work_item_run(system, "被中断的事项")
    system.activate_once(run_id)
    assert system.project(run_id).phase == "ENGINEERING"
    return system, project_id, run_id

def _lost_write(system, run_id, *, tool="write_file", action_id="lost-write"):
    # 追加一条动作前快照与一条没有结果的 tool_started：表示「效果已经写入、完成确认没有保存」的中断状态
    ref = system.artifacts.put(run_id, "snapshot/before",
                               json.dumps({"digest": f"sha256:{action_id}", "files": []}, ensure_ascii=False),
                               media_type="application/json")
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.TOOL_STARTED, actor="department:engineering", department="engineering",
        state_before="ENGINEERING", state_after="ENGINEERING",
        payload={"id": action_id, "name": tool, "args": {"path": "src/a.py", "content": "A"},
                 "step_id": 1, "activation_id": "act_" + action_id, "attempt": 1, "purpose": "work",
                 "before_snapshot_ref": asdict(ref)}))
    return ref

def _decision_events(system, run_id, kind=None):
    return [event for event in system.store.list_events(run_id)
            if event.type == EventType.DECISION_REQUESTED and (kind is None or event.payload["kind"] == kind)]

def _answer(system, decision_id, option, *, base_version=1, note=None):
    application = _application(system)
    return asyncio.run(application.command("decision.answer", DecisionAnswer(
        command_id=str(uuid.uuid4()), decision_id=decision_id, option=option, base_version=base_version,
        note=note), actor="user"))

def test_the_interrupted_state_is_reported_with_the_last_confirmed_position(data_dir):
    # 中断：停在 ENGINEERING，进度已经持久化，进程在下一次激活之前退出。查询给出已确认位置与下一项合法操作。
    # 重新打开时不自动继续，观察中断时的状态本身
    system, _project_id, run_id = _engineering_run(data_dir, [product_spec(),])
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "interrupted", recovery
    assert recovery.can_continue is False
    assert recovery.next_legal_action == "continue"
    assert recovery.executable is True
    assert recovery.last_confirmed_event_id == restarted.project(run_id).last_event_id
    restarted.close()

def test_an_unknown_action_is_observed_as_pending_verification(data_dir):
    # 待核实：有结果未知的动作（tool_started 没有结果），恢复时发出核实请求
    system, _project_id, run_id = _engineering_run(data_dir, [product_spec(),])
    _lost_write(system, run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "pending_verification", recovery
    assert recovery.has_unknown_actions is True
    assert recovery.can_continue is False
    assert recovery.next_legal_action == "verify_action"
    assert [item.action_id for item in recovery.unfinished_actions] == ["lost-write"]
    action = recovery.unfinished_actions[0]
    assert action.status == "unknown" and action.tool == "write_file"
    assert action.before_snapshot_ref["content_hash"]
    assert action.started_event_id
    restarted.close()

def test_an_unavailable_model_is_observed_as_waiting_resume(data_dir):
    # 待恢复：模型引用无法使用（凭据缺失）的 run 停在待恢复，写明部门、模型与问题。
    # 脚本在提交规格以后给出模型引用无法使用的错误，run 停在这次请求之前并带一个阻塞整个 run 的请求
    from harness.adapters.base import ProviderError

    system = LoopSystem.for_testing(data_dir, FakeAdapter([
        product_spec(),
        ProviderError("Missing configuration: provider credential", reason="provider_unavailable")]))
    _project_id, _work_item_id, run_id = _work_item_run(system, "等待修复配置")
    system.run_until_stop(run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "waiting_resume", recovery
    assert recovery.can_continue is False
    assert recovery.next_legal_action == "repair_and_resume"
    assert recovery.unusable is not None
    assert recovery.unusable.department
    assert recovery.unusable.problem
    restarted.close()

def test_a_finished_run_is_observed_as_terminated(data_dir):
    # 已终止：完成的 run 观察状态为已终止，继续执行不可用
    system = LoopSystem.for_testing(data_dir, FakeAdapter([
        product_spec(),delivery_turn(), review_turn("release", "checks passed on the snapshot")]))
    _project_id, _work_item_id, run_id = _work_item_run(system, "要完成的事项")
    system.run_until_stop(run_id)
    assert system.project(run_id).phase == "DONE"
    application = _application(system)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "terminated", recovery
    assert recovery.can_continue is False
    assert recovery.next_legal_action is None
    assert recovery.executable is False
    system.close()

def test_a_live_run_is_observed_as_running(data_dir):
    # 运行中：有一次没有结束的激活（DEPARTMENT_ACTIVATED 没有 ACTIVATION_FINISHED），
    # 用直接追加事件构造，表示进程仍在执行这个 run
    system = LoopSystem.for_testing(data_dir, FakeAdapter([product_spec(),]))
    _project_id, _work_item_id, run_id = _work_item_run(system, "进行中的事项")
    system.activate_once(run_id)
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.DEPARTMENT_ACTIVATED, actor="department:engineering", department="engineering",
        state_before="ENGINEERING", state_after="ENGINEERING",
        payload={"activation_id": "act_live", "step_id": 0}))
    application = _application(system)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "running", recovery
    assert recovery.can_continue is True
    assert recovery.next_legal_action == "none"
    system.close()

def test_the_event_stream_reconnect_only_adds_observation(data_dir):
    # 事件流重连只补观察事实：从 after 重新读取不新建执行，不重发模型或工具请求
    system = LoopSystem.for_testing(data_dir, FakeAdapter([product_spec(),]))
    project_id, _work_item_id, run_id = _work_item_run(system, "被观察的事项")
    system.activate_once(run_id)
    application = _application(system)

    def collect(stream, count):
        async def run():
            messages = []
            async for message in stream.messages():
                if type(message).__name__ == "StreamEvent":
                    messages.append(message)
                    if len(messages) >= count:
                        break
            return messages
        return asyncio.run(run())

    before_position = system.store.end_position()
    before_models = len([event for event in system.store.list_events(run_id)
                         if event.type == EventType.MODEL_REQUESTED])
    first = collect(application.open_event_stream(EventScope(projects=(project_id,)), after=0, live=False), 3)
    assert first, "event stream returned no events"
    # 重连：从最后一条之后继续，与第一次不重叠；没有更多历史时为空
    resumed = collect(application.open_event_stream(EventScope(projects=(project_id,)),
                                                    after=first[-1].position, live=False), 1)
    assert resumed == [] or resumed[0].position > first[-1].position
    # 重连不新建执行、不重发模型请求：日志末尾与模型请求数不变，run 的相位不变
    assert system.store.end_position() == before_position
    assert len([event for event in system.store.list_events(run_id)
                if event.type == EventType.MODEL_REQUESTED]) == before_models
    assert system.project(run_id).phase == "ENGINEERING"
    system.close()

def test_system_status_counts_match_the_event_log(data_dir):
    # system.status 的恢复汇总：服务重启后自动继续的事项数、待核实与待恢复的事项数、结果未知的动作数
    # 与事件日志一致
    system = LoopSystem.for_testing(data_dir, FakeAdapter([product_spec(),]))
    _project_id, _work_item_id, run_id = _work_item_run(system, "中断的事项")
    system.activate_once(run_id)
    _lost_write(system, run_id, action_id="another-unknown")
    assert system.project(run_id).phase == "ENGINEERING"
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    application = _application(restarted)
    status = _query(application, SYSTEM_STATUS, SystemStatusRequest())
    assert status.recovery.pending_verification == 1
    assert status.recovery.unknown_actions == 1
    assert status.recovery.waiting_resume == 0
    # 没有重启后自动继续的事项：重新打开时 resume_on_startup=False
    assert status.recovery.auto_resumed == 0
    restarted.close()

def test_projects_list_reports_interruption_pending_and_resume_markers(data_dir):
    # projects.list 返回每个项目的中断、待核实与待恢复标记（计数），为零时仍是 0
    system = LoopSystem.for_testing(data_dir, FakeAdapter([product_spec(),]))
    project_id, _work_item_id, run_id = _work_item_run(system, "中断的事项")
    system.activate_once(run_id)
    assert system.project(run_id).phase == "ENGINEERING"
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    application = _application(restarted)
    rows = _query(application, PROJECTS_LIST, ProjectsList())
    row = next(item for item in rows.projects if item.project_id == project_id)
    assert row.interrupted_count == 1
    assert row.pending_verification_count == 0
    assert row.waiting_resume_count == 0
    restarted.close()

def test_project_loop_reports_the_recovery_observation_per_work_item(data_dir):
    # project.loop 返回每个事项的恢复观察状态
    system, project_id, run_id = _engineering_run(data_dir, [product_spec(),])
    _lost_write(system, run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    restarted.orchestrator.resume_incomplete_run(run_id)
    application = _application(restarted)
    loop = _query(application, PROJECT_LOOP, ProjectLoop(project_id=project_id))
    item = next(entry for entry in loop.work_items if entry.run_id == run_id)
    assert item.recovery_state in ("interrupted", "running"), item
    restarted.close()

def test_run_recovery_describes_the_verification_record_and_next_legal_action(data_dir):
    # 等待核实时查询返回已确认位置、未完成动作、核实依据与下一项合法操作：用户按当前实际状态继续以后，
    # 核实记录出现，未完成动作消失，下一个合法操作回到继续
    system, _project_id, run_id = _engineering_run(data_dir, [product_spec(),])
    _lost_write(system, run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    restarted.writes.append(run_stream(run_id), NewEvent(
        EventType.DECISION_REQUESTED, actor="system", department="engineering",
        state_before="ENGINEERING", state_after="ENGINEERING",
        payload={
            "kind": "unknown_action",
            "blocks": "action",
            "options": [{"id": "continue", "label": "按当前实际状态继续"}, {"id": "stop", "label": "停止事项"}],
            "description": "动作 lost-write（write_file）已经发出，结果没有得到确认。",
            "facts": [],
            "department": "engineering",
            "action_id": "lost-write",
            "tool": "write_file",
            "action_kind": "write",
            "repeatable": False,
            "repeat_attempted": False,
        },
    ))
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "pending_verification"
    request = _decision_events(restarted, run_id, kind="unknown_action")[0]
    _answer(restarted, request.event_id, "continue", note="确认写入已经生效")

    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    # 动作得到处置：未完成动作消失，核实记录写出依据与结果
    assert recovery.unfinished_actions == []
    assert len(recovery.verifications) == 1
    record = recovery.verifications[0]
    assert record.action_id == "lost-write"
    assert record.basis and record.result and record.decided_by == "user"
    assert record.note == "确认写入已经生效"
    assert record.decision_id == request.event_id
    assert recovery.next_legal_action in ("continue", "none")
    restarted.close()

def test_run_actions_reports_the_unknown_status_and_snapshots(data_dir):
    # run.actions 返回每个动作的状态与前后快照：结果未知的动作状态为 unknown，带动作前快照引用
    system, _project_id, run_id = _engineering_run(data_dir, [product_spec(),])
    _lost_write(system, run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    application = _application(restarted)
    actions = _query(application, RUN_ACTIONS, RunActions(run_id=run_id))
    action = next(item for item in actions.actions if item.action_id == "lost-write")
    assert action.status == "unknown"
    assert action.before_snapshot_ref is not None
    restarted.close()

def test_history_queries_export_and_replay_stay_read_only(data_dir):
    # 历史查询、导出与重放保持只读：位置不变，不调用模型，不写入
    system, project_id, run_id = _engineering_run(data_dir, [product_spec(),])
    application = _application(system)
    position = system.store.end_position()
    _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    _query(application, PROJECTS_LIST, ProjectsList())
    _query(application, PROJECT_LOOP, ProjectLoop(project_id=project_id))
    _query(application, RUN_ACTIONS, RunActions(run_id=run_id))
    assert system.store.end_position() == position
    assert system.project(run_id).phase == "ENGINEERING"
    # 重放核对不写入，结果一致
    report = _query(application, REPLAY_CHECK, ReplayCheck(run_id=run_id))
    assert report.consistent is True
    assert system.store.end_position() == position
    system.close()

# 恢复观察与故障矩阵验收（工单 #18，恢复契约与故障矩阵第 4 节「动作分类与处置」、第 6 节「故障矩阵」）。
# 数据目录是真实的 SQLite 事件日志，服务启动经真实的 LoopSystem，模型回答由 FakeAdapter 给出；
# 中断由「进程关闭、重新以新的系统打开同一数据目录」表示。查询只读取，事件流重连只补观察事实。

import json
from dataclasses import asdict

from harness.watched_outputs import has_new_work
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
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
from harness.event_store import run_stream
from harness.models import EventType
from harness.proposals import answer_turn, ask_turn, delivery_turn, product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import TOOL_CALL_REQUIRED_LIMIT as LIMIT, quality_turns
from harness.write_path import NewEvent

def _product_only_script():
    # 这一轮只有产品回答：PRD 被接纳以后工程与质检同时工作，
    # 两个部门各自的脚本是空的（模型再被调用就以脚本用尽失败）
    return {"product": [product_spec()], "engineering": [], "quality": []}


def _empty_script():
    # 恢复时不再调用模型：每个部门的脚本都是空的
    return {"product": [], "engineering": [], "quality": []}


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
    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    project_id, _work_item_id, run_id = _work_item_run(system, "被中断的事项")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")
    return system, project_id, run_id

def _main_session(system: LoopSystem, run_id: str, department: str) -> str:
    # 部门的部门主线会话编号：事项创建事件里记下的那一组（工单 #473）
    created = next(event for event in system.store.list_events(run_id)
                   if event.type == EventType.RUN_CREATED)
    return str((created.payload or {}).get("sessions", {})[department])

def _lost_write(system, run_id, *, tool="write_file", action_id="lost-write"):
    # 追加一条动作前快照与一条没有结果的 tool_started：表示「效果已经写入、完成确认没有保存」的中断状态。
    # 动作与它的核实记录属于发出它的那个会话（工单 #181、#475）
    session_id = _main_session(system, run_id, "engineering")
    ref = system.artifacts.put(run_id, "snapshot/before",
                               json.dumps({"digest": f"sha256:{action_id}", "files": []}, ensure_ascii=False),
                               media_type="application/json")
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.TOOL_STARTED, actor="department:engineering", department="engineering",
        state_before="running", state_after="running", session_id=session_id,
        payload={"id": action_id, "name": tool, "args": {"path": "src/a.py", "content": "A"},
                 "step_id": 1, "activation_id": "act_" + action_id, "attempt": 1, "purpose": "work",
                 "before_snapshot_ref": asdict(ref)}))
    return ref


def test_the_interrupted_state_is_reported_with_the_last_confirmed_position(data_dir):
    # 中断：停在 ENGINEERING，进度已经持久化，进程在下一次激活之前退出。查询给出已确认位置与下一项合法操作。
    # 重新打开时不自动继续，观察中断时的状态本身。最后已确认的位置另带一条事件的文字（工单 #181）
    system, _project_id, run_id = _engineering_run(data_dir, _product_only_script())
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()),
                                      resume_on_startup=False)
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "interrupted", recovery
    assert recovery.can_continue is False
    assert recovery.next_legal_action == "continue"
    assert recovery.executable is True
    assert recovery.last_confirmed_event_id == restarted.project(run_id).last_event_id
    # 最后已确认位置的文字取自最后一条事件：页面要写出这一步做完了什么，不只写事件编号（工单 #181）
    last_event = next(event for event in restarted.store.list_events(run_id)
                      if event.event_id == recovery.last_confirmed_event_id)
    assert recovery.last_confirmed_text
    assert recovery.last_confirmed_text != last_event.type, recovery.last_confirmed_text
    restarted.close()


def test_an_unavailable_model_is_observed_as_waiting_resume(data_dir):
    # 待恢复：模型引用无法使用（凭据缺失）的 run 停在待恢复，写明部门、模型与问题。
    # 脚本在提交规格以后给出模型引用无法使用的错误，run 停在这次请求之前并带一个阻塞整个 run 的请求
    from harness.adapters.base import ProviderError

    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [ProviderError("Missing configuration: provider credential",
                                       reason="provider_unavailable")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }))
    _project_id, _work_item_id, run_id = _work_item_run(system, "等待修复配置")
    system.run_until_stop(run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()),
                                      resume_on_startup=False)
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "waiting_resume", recovery
    assert recovery.can_continue is False
    assert recovery.next_legal_action == "repair_and_resume"
    assert recovery.unusable is not None
    assert recovery.unusable.department
    assert recovery.unusable.problem
    restarted.close()

def test_a_finished_run_is_observed_as_completed(data_dir):
    # 已完成：完成的 run 观察状态为已完成（不是「已终止」，工单 #747），继续执行不可用
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the snapshot"),
    }))
    _project_id, _work_item_id, run_id = _work_item_run(system, "要完成的事项")
    system.run_until_stop(run_id)
    assert system.project(run_id).status == "done"
    application = _application(system)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "completed", recovery
    assert recovery.can_continue is False
    assert recovery.next_legal_action is None
    assert recovery.executable is False
    # 说明按中文写：停止原因的机器标识不直接出现在给用户看的文字里（工单 #747）
    assert recovery.reason == "运行已完成：已完成并放行", recovery.reason
    assert "released" not in recovery.reason
    system.close()

def test_a_cancelled_run_is_observed_as_cancelled(data_dir):
    # 已取消：用户取消的 run 观察状态为已取消，一眼看得出是取消，不是「已终止」（工单 #747）
    system = LoopSystem.for_testing(data_dir, FakeAdapter([product_spec(),]))
    _project_id, _work_item_id, run_id = _work_item_run(system, "被取消的事项")
    system.cancel(run_id)
    assert system.project(run_id).status == "failed"
    assert system.project(run_id).stop_reason == "cancelled"
    application = _application(system)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "cancelled", recovery
    assert recovery.reason == "运行已被取消", recovery.reason
    assert recovery.can_continue is False
    assert recovery.next_legal_action is None
    system.close()

def test_a_paused_run_is_observed_as_paused(data_dir):
    # 已暂停：模型连续没有调用工具，运行暂停等待用户处理，观察状态是已暂停（工单 #747）
    script = [FakeTurn(transcript="先整理一下思路，稍后提交。") for _ in range(LIMIT + 1)]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    _project_id, _work_item_id, run_id = _work_item_run(system, "暂停等待处理的事项")
    system.run_until_stop(run_id)
    assert system.project(run_id).status == "paused"
    application = _application(system)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "paused", recovery
    assert recovery.reason == "运行已暂停，等待处理：部门连续多次没有调用工具", recovery.reason
    assert "no_tool_call" not in recovery.reason
    system.close()

def test_a_failed_run_is_observed_as_stopped(data_dir):
    # 已停止：执行失败的 run 观察状态为已停止，说明写出停止原因的中文名（工单 #747）
    from harness.adapters.base import ProviderError

    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）：
    # 工程与质检各自都会遇到同一个失败，与谁先被调度无关
    failing = ProviderError("模型服务协议不符", reason="provider_protocol")
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [failing],
        "quality": [failing],
    }))
    _project_id, _work_item_id, run_id = _work_item_run(system, "没有通过的事项")
    system.run_until_stop(run_id)
    assert system.project(run_id).status == "failed"
    application = _application(system)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "stopped", recovery
    assert recovery.reason.startswith("运行已停止："), recovery.reason
    assert "provider_protocol" not in recovery.reason
    assert recovery.can_continue is False
    assert recovery.next_legal_action is None
    system.close()

def test_a_live_run_is_observed_as_running(data_dir):
    # 运行中：有一次没有结束的激活（DEPARTMENT_ACTIVATED 没有 ACTIVATION_FINISHED），
    # 用直接追加事件构造，表示进程仍在执行这个 run
    system = LoopSystem.for_testing(data_dir, FakeAdapter(_product_only_script()))
    _project_id, _work_item_id, run_id = _work_item_run(system, "进行中的事项")
    system.activate_once(run_id)
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.DEPARTMENT_ACTIVATED, actor="department:engineering", department="engineering",
        state_before="running", state_after="running",
        payload={"activation_id": "act_live", "step_id": 0}))
    application = _application(system)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.state == "running", recovery
    assert recovery.can_continue is True
    assert recovery.next_legal_action == "none"
    system.close()


def test_projects_list_reports_interruption_pending_and_resume_markers(data_dir):
    # projects.list 返回每个项目的中断与待恢复标记（计数），为零时仍是 0
    system = LoopSystem.for_testing(data_dir, FakeAdapter(_product_only_script()))
    project_id, _work_item_id, run_id = _work_item_run(system, "中断的事项")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()),
                                      resume_on_startup=False)
    application = _application(restarted)
    rows = _query(application, PROJECTS_LIST, ProjectsList())
    row = next(item for item in rows.projects if item.project_id == project_id)
    assert row.interrupted_count == 1
    assert row.waiting_resume_count == 0
    restarted.close()

def test_project_loop_reports_the_recovery_observation_per_work_item(data_dir):
    # project.loop 返回每个事项的恢复观察状态
    system, project_id, run_id = _engineering_run(data_dir, _product_only_script())
    _lost_write(system, run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()),
                                      resume_on_startup=False)
    restarted.orchestrator.resume_incomplete_run(run_id)
    application = _application(restarted)
    loop = _query(application, PROJECT_LOOP, ProjectLoop(project_id=project_id))
    item = next(entry for entry in loop.work_items if entry.run_id == run_id)
    assert item.recovery_state in ("interrupted", "running"), item
    restarted.close()

def test_run_recovery_describes_the_verification_record_and_next_legal_action(data_dir):
    # 交还以后查询返回核实记录：未完成动作消失，核实记录写出依据与结果
    system, _project_id, run_id = _engineering_run(data_dir, _product_only_script())
    _lost_write(system, run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()),
                                      resume_on_startup=False)
    restarted.orchestrator.resume_incomplete_run(run_id)
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    # 动作得到交还处置：状态是中断或运行中，未完成动作消失，核实记录写出依据与结果
    assert recovery.state in ("interrupted", "running"), recovery
    assert recovery.unfinished_actions == []
    assert len(recovery.verifications) == 1
    record = recovery.verifications[0]
    assert record.action_id == "lost-write"
    assert record.basis == "重新启动时结果未知，交还发出它的会话"
    assert record.result
    assert recovery.next_legal_action in ("continue", "none")
    restarted.close()


def test_unknown_actions_keep_the_handling_and_what_was_handed_back(data_dir):
    # 结果未知的动作交还以后仍列在查询里（工单 #181，设计说明第 4.3 节）：处理方式、发出它的会话、
    # 执行前快照与交还给模型的内容都在，项目不因它进入等待用户（没有决定卡片）
    system, _project_id, run_id = _engineering_run(data_dir, _product_only_script())
    _lost_write(system, run_id)
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()),
                                      resume_on_startup=False)
    restarted.orchestrator.resume_incomplete_run(run_id)
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert [entry.action_id for entry in recovery.unknown_actions] == ["lost-write"]
    handled = recovery.unknown_actions[0]
    assert handled.handling == "returned"
    assert handled.tool == "write_file"
    assert handled.department == "engineering"
    assert handled.session_id == _main_session(restarted, run_id, "engineering")
    assert handled.purpose == "work"
    assert handled.before is not None
    # 交还给模型的内容就是写进部门历史的工具结果：模型读到的是「执行被中断、结果未知」
    assert handled.returned
    handed_back = json.loads(handled.returned)
    assert handed_back["ok"] is False
    assert "结果未知" in handed_back["error"]
    assert handled.at
    restarted.close()


def test_sessions_report_the_usage_of_each_session(data_dir):
    # 各会话的用量（工单 #181，三部门的循环结构第 9 节）：部门主线与会话分支各一行，
    # 写部门、主线或分支、已用秒、轮数与步数。分支是工程询问产品时产品的那次旁支工作
    script = {
        "product": [product_spec()],
        "engineering": [ask_turn(recipient="product", question="输出要不要改成大写？")],
        "product:ask": [answer_turn(answer="不改，保持原样。")],
        "quality": [],
    }
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    _project_id, _work_item_id, run_id = _work_item_run(system, "各会话的用量")
    system.activate_once(run_id)  # 产品提交初始 PRD
    system.activate_once(run_id)  # 工程询问产品，产品在询问分支里回答

    application = _application(system)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    mainline = {row.department: row for row in recovery.sessions if row.kind == "main"}
    assert set(mainline) == {"product", "engineering", "quality"}
    assert mainline["product"].activations >= 1
    # 还没有开始工作的部门也有一行主线会话：用量为零，不是「没有这个会话」
    assert mainline["quality"].activations == 0
    assert mainline["quality"].model_steps == 0
    branches = [row for row in recovery.sessions if row.kind == "branch"]
    assert len(branches) == 1
    assert branches[0].department == "product"
    assert branches[0].activations >= 1
    assert branches[0].model_steps >= 1
    # 已用秒是已结算的运行时间：中断的那一轮不计，因此不会是负数
    assert all(row.elapsed_sec >= 0 for row in recovery.sessions)
    system.close()


def test_a_resumed_run_keeps_the_record_of_this_interruption(data_dir):
    # 自动继续以后仍能看到这次中断的记录（工单 #181）：执行权带上这次取得所依据的中断位置与文字，
    # 页面因此能写「自动继续的时间」与中断在哪一步；继续以后事项仍是同一个，记录不因继续而消失
    system, _project_id, run_id = _engineering_run(data_dir, _product_only_script())
    confirmed_before = system.project(run_id).last_event_id
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_empty_script()),
                                      resume_on_startup=False)
    assert restarted.orchestrator.resume_incomplete_run(run_id) is not None
    application = _application(restarted)
    recovery = _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    assert recovery.owner is not None
    assert recovery.owner.interrupted_at_event_id == confirmed_before
    assert recovery.owner.interrupted_at_text
    assert recovery.owner.since
    # 最后已确认的位置随继续前进（继续本身也是一条已提交的事件），中断位置由执行权另记
    assert recovery.last_confirmed_event_id != confirmed_before
    assert recovery.last_confirmed_text
    restarted.close()


def test_history_queries_export_and_replay_stay_read_only(data_dir):
    # 历史查询、导出与重放保持只读：位置不变，不调用模型，不写入
    system, project_id, run_id = _engineering_run(data_dir, _product_only_script())
    application = _application(system)
    position = system.store.end_position()
    _query(application, RUN_RECOVERY, RunRecovery(run_id=run_id))
    _query(application, PROJECTS_LIST, ProjectsList())
    _query(application, PROJECT_LOOP, ProjectLoop(project_id=project_id))
    _query(application, RUN_ACTIONS, RunActions(run_id=run_id))
    assert system.store.end_position() == position
    assert has_new_work(system.project(run_id), "engineering")
    # 重放核对不写入，结果一致
    report = _query(application, REPLAY_CHECK, ReplayCheck(run_id=run_id))
    assert report.consistent is True
    assert system.store.end_position() == position
    system.close()

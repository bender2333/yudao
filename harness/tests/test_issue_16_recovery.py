# 恢复入口与执行权限（工单 #16）。数据目录是真实的 SQLite 事件日志，服务启动经真实的 LoopSystem，
# 模型回答由 FakeAdapter 给出；中断由「进程关闭、重新以新的系统打开同一数据目录」表示，不模拟异常。

import asyncio
import json
import sqlite3

from harness.collaboration import has_new_work
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.decision_queries import DecisionsList
from harness.app.event_stream import EventScope
from harness.definitions import DEFINITIONS
from harness.event_store import Command, StaleExecutionRight, run_stream
from harness.models import EventType, TERMINAL_STATUSES, new_id
from harness.projection import project_run
from harness.proposals import product_spec
from harness.providers import ProviderFacade
from harness.providers.credentials import CredentialChain
from harness.runtime import LoopSystem
from harness.streams import RUN_EVENT_VERSION, STOP_REASON_UPGRADE
from harness.tests.helpers import delivery_turn, review_turn, quality_turns
from harness.tests.protocol_helpers import serve, sse
from harness.tests.saved_rewrite import reload_without_saved_projection as _reload_without_saved_projection
from harness.write_path import NewEvent

def _plain_reply():
    # 部门回复文字、没有调用工具。连续若干次以后主机要求调用工具（_tool_choice 的 required），
    # fake 回答仍不调用工具，引擎因此停止这次激活，run 停在未结束的 PAUSED
    return lambda _call: FakeTurn(transcript="no tool call in this reply")

def _parked_script():
    # 已准入的模型回答用完以后按「模型引用无法使用」收尾：run 停在这次请求之前，并带一个阻塞整个 run 的
    # 待恢复决定请求。重新打开数据目录时它就是「进程在模型回答以后、下一步执行之前退出」留下的状态：
    # 恢复每取得一次执行权恰好推进一次，每一次推进都要重新取得执行权
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    parked = [_plain_reply(), _plain_reply(), _plain_reply(),
              ProviderError("Missing configuration: provider credential", reason="provider_unavailable")]
    return {"engineering": parked, "quality": []}

def _partial_script():
    # 产品提交规格：只走完这一个激活，run 停在 ENGINEERING，之后由完成脚本继续
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {"product": [product_spec()]}

def _blocked_script():
    # 产品提交规格以后工程部门的请求失败：run 停在等待用户修复配置的待恢复状态
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "product": [product_spec()],
        "engineering": [ProviderError("Missing configuration: provider credential",
                                       reason="provider_unavailable")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def _unfinished_run(data_dir, script=None, *, to_stop=False):
    # 一个项目与一个中断在未结束阶段的 run：只激活一次就关闭进程，相当于进程在模型步骤之间退出。
    # to_stop 时运行到停止（用来构造等待用户回答的 run）
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script or _partial_script()))
    project_id = system.projects.register("恢复项目", "核对启动时的自动继续")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "被中断的事项")
    if to_stop:
        system.run_until_stop(run_id)
    else:
        system.activate_once(run_id)
    projection = project_run(system.store, run_id)
    assert projection.status not in TERMINAL_STATUSES, projection.status
    system.close()
    return system, project_id, run_id

def _older_run_event_version(data_dir):
    # 得到一份由较早 run 事件版本写入的数据目录：run_created 事件里没有 run 事件版本字段，
    # 保存的投影也一并删掉——启动时由事件重放补建，这与较早版本留下的数据目录一致
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        rows = connection.execute(
            "SELECT event_id, payload_json FROM events WHERE type = ?", (EventType.RUN_CREATED,)).fetchall()
        assert rows, "no run_created events"
        for event_id, payload in rows:
            document = json.loads(payload)
            document.pop("run_event_version", None)
            connection.execute("UPDATE events SET payload_json = ? WHERE event_id = ?",
                               (json.dumps(document, ensure_ascii=False, sort_keys=True), event_id))
        connection.commit()
    finally:
        connection.close()
    _reload_without_saved_projection(data_dir)

def _older_definitions_version(data_dir, version="sha256:定义版本在升级之前的内容"):
    # 模拟一次升级：把 run_created 记录的定义版本改成另一个版本。ADR-0014 的定义版本只有发布新版本时改变，
    # 因此测试改写事件库中的事实，不加载第二套定义文件
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        rows = connection.execute(
            "SELECT event_id, payload_json FROM events WHERE type = ?", (EventType.RUN_CREATED,)).fetchall()
        assert rows, "no run_created events"
        for event_id, payload in rows:
            document = json.loads(payload)
            document["definitions_version"] = version
            connection.execute("UPDATE events SET payload_json = ? WHERE event_id = ?",
                               (json.dumps(document, ensure_ascii=False, sort_keys=True), event_id))
        connection.commit()
    finally:
        connection.close()
    _reload_without_saved_projection(data_dir)
    return version

def _resumed_events(system, run_id):
    return [event for event in system.store.list_events(run_id) if event.type == EventType.RUN_RESUMED]

def _answer_command():
    # 回答决定请求经应用层的 decision.answer 命令；测试直接调用流程编排时造一个身份
    return Command(command_id=new_id("cmd"), name="decision.answer", digest="test", actor="user")

def _spec_reply():
    # 一个真实 HTTP 的 Responses 协议回复：调用 submit_product_spec，用于凭据按引用解析的用例
    def responder(body: dict):
        payload = product_spec()
        payload.pop("kind")
        item = {"id": "spec-1", "type": "function_call", "call_id": "spec-1",
                "name": "submit_product_spec", "arguments": json.dumps(payload, ensure_ascii=False)}
        def event(kind: str, data: dict) -> str:
            return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        model = body.get("model") or "fake-model"
        events = [
            event("response.output_item.done", {"type": "response.output_item.done", "item": item}),
            event("response.completed", {"type": "response.completed", "response": {
                "id": "resp-1", "model": model, "status": "completed", "output": [item],
                "usage": {"input_tokens": 9, "output_tokens": 2, "total_tokens": 11}}}),
        ]
        return 200, "text/event-stream", [sse(*events)]
    return responder

def _completion_script():
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def test_startup_resumes_an_interrupted_run_without_user_action(data_dir):
    # 中断的 run 在启动时自动继续到终态，不需要用户操作
    _system, _project_id, run_id = _unfinished_run(data_dir)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script()))
    assert run_id in restarted.resumed_runs
    projection = project_run(restarted.store, run_id)
    assert projection.status == "done", (projection.status, projection.stop_reason)
    restarted.close()

def test_resume_records_the_interrupted_position_and_the_basis(data_dir):
    # 事件中记录中断位置与继续的依据
    _system, _project_id, run_id = _unfinished_run(data_dir)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script()))
    events = _resumed_events(restarted, run_id)
    assert len(events) == 1, events
    basis = events[0].payload["basis"]
    assert basis["interrupted_at_status"] == "running", basis
    assert basis["interrupted_at_event_id"] is not None
    assert basis["current_run_event_version"] == RUN_EVENT_VERSION
    assert basis["recorded_run_event_version"] == RUN_EVENT_VERSION
    # 继续的依据是中断时的流版本，不是重置后的起点
    assert isinstance(basis["interrupted_at_version"], int) and basis["interrupted_at_version"] > 0
    restarted.close()

def test_resume_does_not_grant_a_free_activation(data_dir):
    # 恢复不新增一次免费的部门激活：恢复事件本身不是激活，之后的每一次激活都由激活写入；
    # 恢复也不把模型步骤重新计满（工单 #16 验收 5）
    _system, _project_id, run_id = _unfinished_run(data_dir)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script()))
    events = restarted.store.list_events(run_id)
    resumed = _resumed_events(restarted, run_id)
    assert len(resumed) == 1
    # 恢复事件不携带停止原因，也不改写限额字段
    assert resumed[0].stop_reason is None
    assert resumed[0].payload["acquired_epoch"] >= 1
    # 恢复事件之前只有一次激活（中断时的激活，由 activate_once 写入）；恢复事件本身不新增一次激活，
    # 它之后的每一次激活都由激活写入
    activation_of_resume = len([event for event in events
                                if event.type == EventType.DEPARTMENT_ACTIVATED
                                and event.stream_version < resumed[0].stream_version])
    assert activation_of_resume >= 1
    activated = [event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED]
    assert len(activated) > activation_of_resume
    assert not [event for event in events if event.stream_version == resumed[0].stream_version
                and event.type != EventType.RUN_RESUMED]
    # 恢复不把已用的模型步骤与循环次数清零
    assert len([event for event in events if event.type == EventType.MODEL_REQUESTED]) >= 2
    assert project_run(restarted.store, run_id).cycle_count >= 1
    restarted.close()

def test_finished_cancelled_and_exhausted_runs_are_not_restarted(data_dir):
    # 已完成、已取消及次数耗尽停止的任务不能通过恢复重新开始
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()], **_completion_script()}))
    project_id = system.projects.register("终态项目", "核对终态不重新开始")
    _work_item_id, done_run = system.projects.start_work_item(project_id, "要完成的事项")
    system.run_until_stop(done_run)
    system.projects.settle(done_run)
    assert project_run(system.store, done_run).status == "done"

    _work_item_id, cancelled_run = system.projects.start_work_item(project_id, "要取消的事项")
    system.activate_once(cancelled_run)
    system.cancel(cancelled_run)
    assert project_run(system.store, cancelled_run).status == "failed"

    _work_item_id, exhausted_run = system.projects.start_work_item(project_id, "次数耗尽的事项", max_cycles=1)
    system.run_until_stop(exhausted_run)
    exhausted = project_run(system.store, exhausted_run)
    assert exhausted.status in TERMINAL_STATUSES, exhausted.status
    system.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_parked_script()))
    for run_id in (done_run, cancelled_run, exhausted_run):
        assert _resumed_events(restarted, run_id) == [], run_id
    # 终态 run 不取得执行权
    assert restarted.resumed_runs == {}
    assert done_run in restarted.startup_runs.finished
    restarted.close()

def test_two_processes_recovering_the_same_run_only_one_advances(data_dir):
    # 双进程同时恢复同一任务，最多一个可以推进：执行权编号在写入口与领域写入一起核对，没有期限与续期
    _system, _project_id, run_id = _unfinished_run(data_dir)

    # 两个进程各自以同一数据目录打开事件日志（两个互相独立的连接），都取得同一个 run 的执行权。
    # 两个进程都在取得执行权之后、继续执行之前退出（_resume 只取得执行权，不运行到停止），
    # 因此 run 保持未结束，双方都要取得执行权
    first_epoch = LoopSystem._resume(data_dir, FakeAdapter([]))[run_id]
    second_epoch = LoopSystem._resume(data_dir, FakeAdapter([]))[run_id]
    # 两个进程取得的执行权编号严格递增，后取得的一方更大
    assert second_epoch == first_epoch + 1, (first_epoch, second_epoch)

    # 旧执行者的迟到结果只能作为历史事实：携带已经不是最新的编号时写入被拒绝
    late = NewEvent(EventType.DEPARTMENT_INPUT, actor="department:engineering", department="engineering",
                    state_before="running", state_after="running", payload={"text": "late result"})
    first = LoopSystem.for_testing(data_dir, FakeAdapter(_parked_script()))
    second = LoopSystem.for_testing(data_dir, FakeAdapter(_parked_script()))
    # 两次取得都写进了同一份事件日志（第三个进程的恢复会再取得一次，所以只看前两次）
    epochs = [event.payload["acquired_epoch"] for event in _resumed_events(second, run_id)]
    assert epochs[:2] == [first_epoch, second_epoch], epochs

    try:
        first.writes.append(run_stream(run_id), late, epoch=first_epoch)
        raise AssertionError("a stale execution right was accepted")
    except StaleExecutionRight as refused:
        recorded = first.store.projection(run_stream(run_id)).epoch
        assert (refused.epoch, refused.recorded) == (first_epoch, recorded)
        assert refused.epoch < recorded
    # 事件日志没有增加旧执行者的写入
    assert not [event for event in first.store.list_events(run_id)
                if event.payload.get("text") == "late result"]
    # 持有最新编号的一方照常写入：最多一个可以推进
    second.writes.append(run_stream(run_id), late, epoch=second.store.projection(run_stream(run_id)).epoch)
    assert [event for event in second.store.list_events(run_id)
            if event.payload.get("text") == "late result"]
    first.close()
    second.close()

def test_a_run_with_an_older_definitions_version_asks_the_user_before_continuing(data_dir):
    # 升级以后继续旧事项：定义版本不同时发出决定请求，取得执行权之前交给用户决定（ADR-0014，工单 #16）
    _system, _project_id, run_id = _unfinished_run(data_dir)
    recorded = _older_definitions_version(data_dir)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script()))
    # 没有取得执行权，也没有继续运行
    assert run_id not in restarted.resumed_runs
    assert _resumed_events(restarted, run_id) == []
    requests = [decision for decision in restarted.writes.read(run_stream(run_id)).decisions.values()
                if decision.request["kind"] == "definitions_changed"]
    assert len(requests) == 1, requests
    request = requests[0]
    assert request.request["blocks"] == "run"
    assert [option["id"] for option in request.request["options"]] == ["continue", "stop"]
    assert request.request["recorded_definitions_version"] == recorded
    assert request.request["current_definitions_version"] == DEFINITIONS.version
    # 再次启动不重复发出同一个请求
    restarted.close()
    again = LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script()))
    kinds = [decision.request["kind"] for decision in again.writes.read(run_stream(run_id)).decisions.values()]
    assert kinds.count("definitions_changed") == 1, kinds
    again.close()

def _collect(stream, limit: int, timeout: float = 5.0):
    # 读事件流的前几条消息（与其他事件流用例的做法相同）
    async def run():
        messages = []
        async for message in stream.messages():
            messages.append(message)
            if len(messages) >= limit:
                break
        return messages
    return asyncio.run(asyncio.wait_for(run(), timeout))

def test_the_definitions_changed_request_is_read_through_the_decisions_query(data_dir):
    # 定义版本不同的请求在接口合同里（工单 #894）：decisions.list 读得出这条请求，载荷里带两个定义版本与两个选项。
    # 合同里缺这一种时，只要有一条这样的请求，列表就构造不出来，首页的「待你决定」读不出（设计说明第 3.3 节）
    _system, _project_id, run_id = _unfinished_run(data_dir)
    recorded = _older_definitions_version(data_dir)

    application = Application(LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script())))
    try:
        listed = application.query("decisions.list", DecisionsList(status=["open"])).data
    finally:
        application.close()

    requests = [item for item in listed.decisions if item.kind == "definitions_changed"]
    assert len(requests) == 1, [item.kind for item in listed.decisions]
    request = requests[0]
    assert request.run_id == run_id
    assert request.blocks == "run"
    assert [option.id for option in request.request.options] == ["continue", "stop"]
    assert request.request.recorded_definitions_version == recorded
    assert request.request.current_definitions_version == DEFINITIONS.version

def test_the_two_definition_versions_survive_reading_the_event_stream(data_dir):
    # 读事件流时两个定义版本不再被丢掉（工单 #894）：事件对象按合同过滤载荷，
    # 合同里没有这两个字段时它们从读到的事件里消失
    _system, _project_id, run_id = _unfinished_run(data_dir)
    recorded = _older_definitions_version(data_dir)

    application = Application(LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script())))
    try:
        stream = application.open_event_stream(
            EventScope(runs=(run_id,), types=(EventType.DECISION_REQUESTED,)), after=0, live=False)
        messages = _collect(stream, 1)
    finally:
        application.close()

    payload = messages[0].event.payload
    assert payload.kind == "definitions_changed"
    assert payload.recorded_definitions_version == recorded
    assert payload.current_definitions_version == DEFINITIONS.version

def test_continuing_on_the_new_definitions_version_records_it_in_later_events(data_dir):
    # 选择「按新版本继续」以后，后续的模型请求与裁决照常记录新版本（ADR-0014）
    _system, _project_id, run_id = _unfinished_run(data_dir)
    _older_definitions_version(data_dir)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script()))
    request = next(decision for decision in restarted.writes.read(run_stream(run_id)).decisions.values()
                   if decision.request["kind"] == "definitions_changed")
    restarted.orchestrator.answer_decision(request.decision_id, "continue", None,
                                           base_version=request.version, command=_answer_command())
    restarted.run_until_stop(run_id)
    projection = project_run(restarted.store, run_id)
    assert projection.status == "done", (projection.status, projection.stop_reason)
    # 决定以后写入的请求与裁决事件记录当前加载的版本
    later = [event for event in restarted.store.list_events(run_id)
             if event.stream_version > request.version and event.type in (EventType.MODEL_REQUESTED,
                                                                          EventType.PROPOSAL_SUBMITTED)]
    assert later, "no later model request or proposal"
    assert {event.payload["definitions_version"] for event in later} == {DEFINITIONS.version}
    restarted.close()

def test_stopping_on_a_changed_definitions_version_ends_the_run(data_dir):
    # 选择「停止」以后运行结束，不再继续
    _system, _project_id, run_id = _unfinished_run(data_dir)
    _older_definitions_version(data_dir)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script()))
    request = next(decision for decision in restarted.writes.read(run_stream(run_id)).decisions.values()
                   if decision.request["kind"] == "definitions_changed")
    restarted.orchestrator.answer_decision(request.decision_id, "stop", None,
                                           base_version=request.version, command=_answer_command())
    projection = project_run(restarted.store, run_id)
    assert projection.status in TERMINAL_STATUSES, projection.status
    assert _resumed_events(restarted, run_id) == []
    restarted.close()

def test_credentials_are_resolved_from_the_host_again_and_not_written_into_events(data_dir):
    # 凭据按原引用从宿主重新解析、不写入事件与工件；缺失时说明缺哪一项（ADR-0005，工单 #16）
    secret = "host-only-secret-value"
    server, _capture, base = serve(_spec_reply())
    try:
        def document():
            return {"providers": [{"id": "provider-1", "name": "provider-1",
                                   "base_url": base, "credential_ref": "RECOVERY_KEY", "timeout_sec": 20}],
                    "models": [{"id": "model-1", "provider_id": "provider-1", "model": "fake-model",
                                "protocol": "responses",
                                "context_window": 32_000, "max_output_tokens": 2_048}],
                    "bindings": {department: {"provider_id": "provider-1", "model_id": "model-1"}
                                 for department in ("product", "engineering", "quality")}}

        facade = ProviderFacade(credentials=CredentialChain(overrides={"RECOVERY_KEY": secret}, use_env=False))
        facade.store_document(document())
        facade.record_admission("provider-1", "model-1", admitted_model="fake-model")
        system = LoopSystem(data_dir, facade=facade)
        project_id = system.projects.register("恢复项目", "核对凭据按引用重新解析")
        _work_item_id, run_id = system.projects.start_work_item(project_id, "被中断的事项")
        system.activate_once(run_id)
        assert project_run(system.store, run_id).status not in TERMINAL_STATUSES
        config_path, dotenv_path = system.provider_config_path, system.dotenv_path
        system.close()

        # 重新打开时宿主凭据仍然存在：恢复取得执行权并继续
        kept = ProviderFacade(credentials=CredentialChain(overrides={"RECOVERY_KEY": secret}, use_env=False))
        kept.store_document(document())
        kept.record_admission("provider-1", "model-1", admitted_model="fake-model")
        restarted = LoopSystem(data_dir, facade=kept)
        assert run_id in restarted.resumed_runs
        # 事件与工件中没有凭据本身（工单 #16 验收 4）
        assert secret.encode() not in (data_dir / "events.sqlite").read_bytes()
        for path in (data_dir / "artifacts").rglob("*"):
            if path.is_file():
                assert secret.encode() not in path.read_bytes()
        restarted.close()

        # 宿主凭据缺失：模型引用无法使用，事项进入待恢复，决定请求写明缺哪一项。另一个事项用来观察这一步
        system = LoopSystem(data_dir, facade=facade)
        _work_item_id, blocked_run = system.projects.start_work_item(project_id, "等待修复凭据的事项")
        system.activate_once(blocked_run)
        system.close()
        absent = LoopSystem(data_dir, facade=ProviderFacade(credentials=CredentialChain(use_env=False)))
        requests = [decision for decision in absent.writes.read(run_stream(blocked_run)).decisions.values()
                    if decision.request["kind"] == "model_unavailable"]
        # 同时运行以后几个部门可能各自发出一条待恢复的请求（工单 #557）：
        # 断言的是每一条都写明缺哪一项
        assert requests, requests
        assert requests[0].request["department"]
        # 缺少的是哪一项写在请求里：部门、具体问题与原因，供用户修复
        assert requests[0].request["department"] in requests[0].request["description"]
        assert requests[0].request["message"], requests[0].request
        assert requests[0].request["reason"], requests[0].request
        absent.close()
    finally:
        server.shutdown()
        server.server_close()

def test_resumed_runs_are_distinct_from_runs_stopped_for_an_upgrade(data_dir):
    # run 事件版本不同的未结束 run 按强制升级处理（工单 #322）：记为因升级停止，不由恢复继续，
    # 恢复继续的只有版本与当前相同的 run
    _system, _project_id, run_id = _unfinished_run(data_dir)
    _older_run_event_version(data_dir)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_parked_script()))
    assert restarted.startup_runs.other_version == ()
    assert run_id not in restarted.resumed_runs, "版本不同的 run 已经停止并重新开始，恢复不再继续它"
    assert _resumed_events(restarted, run_id) == []
    assert project_run(restarted.store, run_id).stop_reason == STOP_REASON_UPGRADE
    restarted.close()

def test_a_run_waiting_for_the_user_is_not_continued_by_startup(data_dir):
    # 模型引用无法使用时 run 等待用户修复配置：启动不自动开始新的激活
    _system, _project_id, run_id = _unfinished_run(data_dir, script=_blocked_script(), to_stop=True)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_parked_script()))
    # 待恢复的决定请求仍然打开，run 没有被继续
    assert run_id not in restarted.resumed_runs
    assert _resumed_events(restarted, run_id) == []
    restarted.close()

def test_replay_and_query_paths_do_not_invoke_the_model(data_dir):
    # 历史查询与消息重连不隐式调用模型
    _system, _project_id, run_id = _unfinished_run(data_dir)
    adapter = FakeAdapter(_completion_script())
    restarted = LoopSystem.for_testing(data_dir, adapter)
    invocations = len(adapter.invocations)
    assert invocations > 0
    before = restarted.store.end_position()
    # 只读重放与状态查询不推进 run，也不调用模型
    assert restarted.replay(run_id).status == "done"
    restarted.project(run_id)
    assert len(adapter.invocations) == invocations
    assert restarted.store.end_position() == before
    restarted.close()

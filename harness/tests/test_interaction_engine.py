import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.compaction import visible_history
from harness.definitions import DEFINITIONS
from harness.engine import StepLimits
from harness.models import EventType, json_dumps
from harness.proposals import (
    delivery_turn, product_decision, product_spec, product_spec_turn,
    review_turn,
)
from harness.providers.call import ModelResponse
from harness.providers.selection import ModelSelection
from harness.runtime import LoopSystem, RunTerminalError
from harness.tests.helpers import (WAIT_FOR_RELEASE, after_event, department_history,
                                    from_another_thread, list_files_turn, quality_turns,
                                    recorded_context, wait_for_file)
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

CHANGE_RECORD = {
    "changed": ["Print the argument in uppercase"],
    "retained": ["Accept one command-line argument"],
    "retired": ["Preserve original letter casing"],
    "rationale": "Apply the user's explicit change to uppercase output",
}

# 提交依据的版本由工厂从请求里的当前版本取（工单 #471）：修订必须声明它依据的那一版
def _revision():
    return product_spec_turn(requirements=["print the argument in uppercase"], change_record=CHANGE_RECORD)

def _call(identity, name, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}

def _steps(system, run_id, count):
    for _ in range(count):
        current = system.activate_once(run_id)
    return current

def _events(system, run_id, kind):
    return [event for event in system.store.list_events(run_id) if event.type == kind]

def _parts(system, request):
    return {part.source: part.text for part in recorded_context(system, request).parts}

def _manifest(system, request):
    return recorded_context(system, request).manifest

@pytest.mark.parametrize("operation", ["input", "stop", "guidance"])
def test_operations_arriving_when_the_request_cannot_fit_find_the_run_ended(tmp_path, operation):
    # 固定部分与部门历史超过窗口、压缩也放不下：运行以 context_overflow 结束，紧接着到达的操作得到 RunTerminalError，
    # 什么也不写入。调用目标声明了输出上限（#45 起测试也走调用目标），装配在窗口放不下这次请求时交回 context_overflow
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI. " + "Keep the requirement text. " * 370, context_window=8000)
    operations = {
        "input": lambda: system.add_input(run_id, "late input"),
        "stop": lambda: system.add_input(run_id, "/stop"),
        "guidance": lambda: system.add_guidance(run_id, "product", "late guidance"),
    }
    waiting = []

    def arrive(_event):
        waiting.append(from_another_thread(operations[operation]))

    after_event(system, EventType.RUN_FAILED, arrive)
    result = system.activate_once(run_id)
    [late] = waiting
    assert result.status == "failed" and result.stop_reason == "context_overflow"
    assert len(late.errors) == 1 and isinstance(late.errors[0], RunTerminalError)
    assert not adapter.invocations
    kinds = {event.type for event in system.store.list_events(run_id)}
    assert not kinds & {EventType.USER_INPUT_RECEIVED, EventType.DEPARTMENT_GUIDANCE_RECEIVED}
    assert result.canonical_state() == system.replay(run_id).canonical_state()

def test_original_input_bytes_and_three_progress_versions_are_independent(tmp_path):
    texts = ["  build echo\r\n", "Uppercase output", "\n\n  keep one argument  "]
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run(texts[0])
    for text in texts[1:]:
        received = system.add_input(run_id, text)
    assert (received.input_version, received.product_work_input_version, received.processed_input_version) == (3, 1, 0)
    expected = "".join(texts).encode("utf-8")
    assert (tmp_path / "materials" / run_id / "intend.md").read_bytes() == expected
    assert received.task == "".join(texts)
    for index, item in enumerate(received.inputs):
        assert item.version == index + 1 and item.text == texts[index]
        assert item.byte_start == sum(len(value.encode("utf-8")) for value in texts[:index])
        assert expected[item.byte_start:item.byte_end] == system.artifacts.get_for_run(run_id, item.input_ref)
    accepted = system.activate_once(run_id)
    assert (accepted.input_version, accepted.product_work_input_version, accepted.processed_input_version) == (3, 3, 3)
    assert accepted.product_spec.input_version == accepted.effective_contract.input_version == 3
    request = system.test_adapter.invocations[-1]
    assert _manifest(system, request).input_version == 3 and _parts(system, request)["intend"] == "".join(texts)
    assert [item["text"] for item in json.loads(_parts(system, request)["pending_inputs"])] == texts
    assert accepted.canonical_state() == system.replay(run_id).canonical_state()


def test_only_complete_product_spec_can_process_received_input(tmp_path):
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec(), product_decision("Uppercase all output", "This cannot consume pending input"),
                    product_spec_turn(requirements=["print the argument in uppercase"]), _revision()],
        "engineering": [],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }))
    run_id = system.create_run("build echo")
    old = system.activate_once(run_id)
    system.add_input(run_id, "Print uppercase now")
    decision_rejected = system.activate_once(run_id)
    assert has_new_work(decision_rejected, "product")
    assert not decision_rejected.product_decisions and decision_rejected.processed_input_version == 1
    missing_record = system.activate_once(run_id)
    assert missing_record.processed_input_version == 1
    assert missing_record.rejections[-1]["errors"][0]["field"] == "change_record"
    accepted = system.activate_once(run_id)
    assert accepted.processed_input_version == 2 and accepted.product_spec.change_record == CHANGE_RECORD
    assert accepted.product_spec.parent_hash == old.product_spec.content_hash
    assert accepted.effective_contract.content_hash != old.effective_contract.content_hash
    prd = system.artifacts.get_for_run(run_id, accepted.effective_contract.prd_ref).decode("utf-8")
    assert "Accepted user input through version: 2" in prd
    assert CHANGE_RECORD["rationale"] in prd and old.product_spec.content_hash in prd

def test_new_input_during_product_model_call_is_delivered_as_a_notification(tmp_path):
    # 工单 #964：输入到达不再结束部门当前这一轮，它作为通知在这个会话的下一步送达，部门接着工作。
    # 模型还没有看见新输入时，这次提交推迟（工具许可），通知送达以后再提交。
    def old_spec(request):
        assert _manifest(system, request).input_version == 1
        system.add_input(request.run_id, "Also require uppercase output")
        return product_spec()

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([old_spec, product_spec(requirements=["Print uppercase output"])]))
    run_id = system.create_run("build echo")
    current = system.activate_once(run_id)
    # 这一轮没有因为输入结束：模型在下一步看见通知以后提交的要求被接纳
    assert current.product_spec is not None and current.product_spec.revision == 1
    assert current.processed_input_version == 2
    assert [_manifest(system, request).input_version for request in system.test_adapter.invocations] == [1, 2]
    # 第一次的提交被推迟：模型还没有看见新输入，部门没有因此结束这一轮
    submissions = [event for event in _events(system, run_id, EventType.TOOL_CALLED)
                   if event.payload["name"] == "submit_product_spec"]
    assert [event.payload["ok"] for event in submissions] == [False, True]
    assert "has not entered this session's model input yet" in submissions[0].payload["error"]
    # 下一步的请求里有这条输入的通知
    notification = json.loads(_parts(system, system.test_adapter.invocations[1])["work_notification"])
    assert [item["kind"] for item in notification] == ["user_input_received"]
    assert notification[0]["version"] == 2 and "uppercase" in notification[0]["text"]

def test_input_before_model_request_start_does_not_end_the_activation(tmp_path):
    # 工单 #964：输入在请求发出以前到达，已经装配好的请求照常发出（输入不再作废它），
    # 这一轮不结束，通知在下一步送达
    received = False

    def receive_before_start(_event):
        nonlocal received
        if not received:
            received = True
            system.add_input(run_id, "Confirm uppercase output")

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(),
                                                           product_spec(requirements=["Print uppercase output"])]))
    run_id = system.create_run("build echo")
    after_event(system, EventType.CONTEXT_ASSEMBLED, receive_before_start)
    current = system.activate_once(run_id)
    # 这一轮没有结束：模型在下一步看见通知以后提交的要求被接纳
    assert current.product_spec is not None and current.processed_input_version == 2
    assert _manifest(system, system.test_adapter.invocations[-1]).input_version == 2
    # 下一步的请求里有这条输入的通知
    notification = json.loads(_parts(system, system.test_adapter.invocations[-1])["work_notification"])
    assert [item["kind"] for item in notification] == ["user_input_received"]
    assert notification[0]["version"] == 2

def test_input_at_last_toolless_model_step_does_not_end_the_activation_before_its_step_limit(tmp_path):
    # 工单 #964：输入到达不再结束部门当前这一轮，它作为通知在这个会话的下一步送达。
    # 这一轮走到自己的步骤上限才停；运行不因此暂停（有新的工作要处理：产品处理这条输入）
    def final_old_response(request):
        system.add_input(run_id, "Confirm uppercase output")
        return ModelResponse(output=[{"type": "message", "id": "old-output", "role": "assistant",
                                      "content": [{"type": "output_text", "text": "A response to the original input."}]}])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([final_old_response, product_spec()]),
                                    step_limits=StepLimits(max_model_steps=1))
    run_id = system.create_run("build echo")
    current = system.activate_once(run_id)
    assert has_new_work(current, "product") and current.stop_reason is None
    assert current.product_work_input_version == 2 and current.processed_input_version == 0
    assert system.activate_once(run_id).processed_input_version == 2

def test_started_tool_finishes_and_remaining_model_tools_run_on_new_input(tmp_path):
    # 工单 #964：输入到达不再结束部门当前这一轮，已经开始的工具照常结束，其余工具照常执行；
    # 正式成果等模型看见新输入以后再提交（这次提交推迟到下一步）
    signals = tmp_path / "signals"
    signals.mkdir()
    code = ("import pathlib; pathlib.Path('src').mkdir(exist_ok=True); "
            "pathlib.Path('src/first.py').write_text('completed first tool'); " + WAIT_FOR_RELEASE)
    command = f'"{sys.executable.replace(chr(92), "/")}" -c "{code}" "{Path(signals).as_posix()}"'
    calls = [{"id": "first", "call_id": "first", "type": "function_call", "name": "bash",
              "arguments": json_dumps({"command": command})},
             _call("second", "write_file", path="src/second.py", content="must not start"),
             _call("submission", "submit_delivery", summary="old delivery", check_names=["smoke"])]
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec(),
                    product_spec_turn(requirements=["print the argument in uppercase"], change_record=CHANGE_RECORD)],
        "engineering": [ModelResponse(output=calls), delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }))
    run_id = system.create_run("build echo")
    _steps(system, run_id, 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            wait_for_file(signals / "started")
            received = system.add_input(run_id, "Print uppercase instead")
            assert received.product_work_input_version == 1
        finally:
            (signals / "release").write_text("go")
        current = future.result(timeout=WAIT_FOR_HOST_WORK_SEC)
    assert has_new_work(current, "product") and current.processed_input_version == 1
    # 部门接着工作：其余工具照常执行
    assert system.workspace(run_id).list_files() == ["src/echo.py", "src/first.py", "src/second.py"]
    events = system.store.list_events(run_id)
    started = next(event for event in events if event.type == EventType.TOOL_STARTED and event.payload["id"] == "first")
    received = _events(system, run_id, EventType.USER_INPUT_RECEIVED)[0]
    finished = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("id") == "first")
    assert started.stream_version < received.stream_version < finished.stream_version
    assert finished.payload["ok"] and finished.payload["input_version"] == 1
    # 这次交付推迟：模型还没有看见新输入
    submission = next(event for event in events if event.type == EventType.TOOL_CALLED
                       and event.payload.get("id") == "submission")
    assert not submission.payload["ok"]
    assert "has not entered this session's model input yet" in submission.payload["error"]
    visible_history(department_history(system, run_id, "engineering"))
    assert system.activate_once(run_id).processed_input_version == 2

def test_user_input_during_a_quality_round_is_delivered_as_a_notification(tmp_path):
    # 工单 #964 验收第 1 条：用户在质检一轮工作进行中追加了输入，质检这一轮不结束，
    # 它的下一步请求里包含这条输入的通知，它接着工作
    def in_flight_input(request):
        system.add_input(request.run_id, "Print uppercase instead")
        return list_files_turn(request)

    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [in_flight_input, review_turn("release", "checks passed on the current snapshot")],
    }))
    run_id = system.create_run("build echo")
    _steps(system, run_id, 2)
    current = system.activate_once(run_id)
    quality = [request for request in system.test_adapter.invocations if request.department == "quality"]
    # 这一轮没有因为输入结束：质检接着工作，走到了下一步
    assert len(quality) == 2
    assert current.input_version == 2 and current.processed_input_version == 1
    # 下一步的请求里有这条输入的通知（第一条请求在输入到达以前装配，没有这条通知）
    first = _parts(system, quality[0]).get("work_notification")
    assert "user_input_received" not in (first or "")
    notification = json.loads(_parts(system, quality[1])["work_notification"])
    assert [item["kind"] for item in notification] == ["user_input_received"]
    assert notification[0]["version"] == 2 and "uppercase" in notification[0]["text"]

def test_input_received_during_quality_model_response_is_delivered_as_a_notification(tmp_path):
    # 工单 #964：输入到达不再结束质检这一轮，它作为通知在这个会话的下一步送达，质检接着工作。
    # 模型还没有看见新输入时，这次放行推迟到下一步；输入处理完以前不放行（循环结构第 6 节）
    def stale_release(request):
        system.add_input(request.run_id, "Print uppercase instead")
        return review_turn("release", "This belongs to the old input")(request)

    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [stale_release, review_turn("release", "checks passed on the current snapshot")],
    }))
    run_id = system.create_run("build echo")
    _steps(system, run_id, 2)
    current = system.activate_once(run_id)
    assert has_new_work(current, "product") and current.last_review is None
    assert current.input_version == 2 and current.processed_input_version == 1
    assert not _events(system, run_id, EventType.RUN_DONE)
    # 放行没有生效：模型还没有看见新输入，这次提交推迟
    reviews = [event for event in _events(system, run_id, EventType.TOOL_CALLED)
               if event.payload["name"] == "submit_review"]
    assert reviews and not reviews[0].payload["ok"]
    assert "has not entered this session's model input yet" in reviews[0].payload["error"]
    # 下一步的请求里有这条输入的通知
    quality = [request for request in system.test_adapter.invocations if request.department == "quality"]
    notification = json.loads(_parts(system, quality[-1])["work_notification"])
    assert [item["kind"] for item in notification] == ["user_input_received"]
    assert notification[0]["version"] == 2

def test_input_committed_while_the_release_is_prepared_rejects_the_release(tmp_path, monkeypatch):
    # 质检放行正在准备接纳时另一个线程写入新输入：放行的提交因流版本改变被写入口拒绝，按写入以后的状态重新判断；
    # 输入处理完以前不放行（循环结构第 6 节），新输入保留，运行没有结束
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [review_turn("release", "Current check passed")],
    }))
    run_id = system.create_run("build echo")
    _steps(system, run_id, 2)
    prepare = system.orchestrator.submissions.prepare
    receivers = []

    def prepare_with_input(transaction, **arguments):
        if not receivers:
            receivers.append(from_another_thread(lambda: system.add_input(run_id, "This arrives during the release")))
        return prepare(transaction, **arguments)

    monkeypatch.setattr(system.orchestrator.submissions, "prepare", prepare_with_input)
    current = system.activate_once(run_id)
    [receiver] = receivers
    assert not receiver.errors
    assert current.status != "done" and current.input_version == 2
    assert not _events(system, run_id, EventType.RUN_DONE) and not _events(system, run_id, EventType.QA_SUBMITTED)
    [rejected] = _events(system, run_id, EventType.PROPOSAL_REJECTED)
    assert [error["field"] for error in rejected.payload["errors"]] == ["kind"]
    assert current.canonical_state() == system.replay(run_id).canonical_state()

@pytest.mark.parametrize("command", ["/stop", "  /cancel\r\n"])
def test_text_stop_commands_preserve_original_before_immediate_cancellation(tmp_path, command):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("original")
    current = system.add_input(run_id, command)
    assert current.status == "failed" and current.stop_reason == "cancelled"
    assert current.inputs[-1].text == command and current.inputs[-1].kind == "command"
    assert current.processed_input_version == 0
    assert (tmp_path / "materials" / run_id / "intend.md").read_bytes() == ("original" + command).encode("utf-8")
    assert (_events(system, run_id, EventType.USER_INPUT_RECEIVED)[0].stream_version
            < _events(system, run_id, EventType.RUN_FAILED)[0].stream_version)

def test_cancel_button_does_not_fabricate_text_and_terminal_work_never_resumes(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("original")
    current = system.cancel(run_id)
    assert len(current.inputs) == 1 and current.input_version == 1
    before = current.canonical_state()
    with pytest.raises(RunTerminalError):
        system.add_input(run_id, "new work")
    with pytest.raises(RunTerminalError):
        system.add_guidance(run_id, "product", "new instructions")
    assert system.project(run_id).canonical_state() == before

def test_project_department_prompt_changes_apply_from_the_next_model_request(tmp_path):
    # 部门 Prompt 保存在项目部门设置中，run 内没有副本：修改发生在工程部门的第一次请求之后，
    # 同一次激活内的下一次请求就使用新 Prompt，请求事件记录项目部门设置的版本（设计说明第 5.4 节）
    replacement = "  Engineer: document the reason for each planned change.\r\n"
    default_text = DEFINITIONS.role("engineering").prompt
    project_id = {"value": ""}

    def update(request):
        system.projects.configure_department_settings(
            project_id["value"], "engineering", ModelSelection(department_prompt=replacement), 0)
        return ModelResponse(output=[_call("inspect", "list_files")])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
        # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
        "product": [product_spec()],
        "engineering": [update, delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }))
    project_id["value"] = system.projects.register("P", "验证部门 Prompt 生效时机")
    _work_item_id, run_id = system.projects.start_work_item(project_id["value"], "build echo")
    for _ in range(3):
        system.activate_once(run_id)
    engineering = [request for request in system.test_adapter.invocations
                   if request.department == "engineering"]
    assert len(engineering) >= 2, [request.department for request in system.test_adapter.invocations]
    # 第一次请求用内置默认 Prompt（版本 0）；修改之后的下一次请求用项目部门设置（版本 1）
    first = _manifest(system, engineering[0])
    assert first.prompt_version == 0
    assert _parts(system, engineering[0])["department_rules"] == default_text
    later = [_manifest(system, request) for request in engineering[1:]]
    assert later and all(manifest.prompt_version == 1 for manifest in later)
    assert all(_parts(system, request)["department_rules"] == replacement for request in engineering[1:])
    # 同一次激活内也按请求读取（第二次请求仍在第一次激活里）
    assert engineering[0].activation_id == engineering[1].activation_id
    current = system.project(run_id)
    # run 内没有部门 Prompt 的副本
    assert not hasattr(current, "department_prompts")
    assert system.projects.read_department_setting(project_id["value"], "engineering")["version"] == 1
    assert current.canonical_state() == system.replay(run_id).canonical_state()

def test_identical_requirement_text_for_new_input_still_has_new_contract_binding(tmp_path):
    same_requirements = product_spec_turn(change_record={
        "changed": [], "retained": ["Echo the argument exactly"], "retired": [],
        "rationale": "The new user input confirms the existing behavior",
    })
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec(), same_requirements],
        "engineering": [],
        "quality": [],
    }))
    run_id = system.create_run("build echo")
    old = _steps(system, run_id, 1)
    system.add_input(run_id, "Confirm the existing echo behavior")
    current = system.activate_once(run_id)
    assert current.product_spec.requirements == old.product_spec.requirements
    assert current.effective_contract.content_hash != old.effective_contract.content_hash
    assert current.effective_contract.input_version == 2
    assert not hasattr(current, "engineering_plan")

def test_compaction_keeps_activation_versions_and_carries_the_new_input(tmp_path):
    # 工单 #964：输入到达不再结束这一轮，压缩照常生效（不再因为输入版本变化而作废）；
    # 压缩以后的请求带着新的输入版本，压缩记录仍记着装配时的版本
    counts = {}
    changed = False
    first_activation = None

    def respond(request):
        nonlocal changed, first_activation
        if first_activation is None:
            first_activation = request.activation_id
        if request.purpose == "compaction":
            if not changed:
                changed = True
                system.add_input(run_id, "Confirm the existing echo requirement")
            return ModelResponse(output=[{
                "id": f"memory-{request.activation_id}-{request.step_id}", "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "The public notes were read. Preserve their evidence while defining the requirements."}],
            }])
        count = counts.get(request.activation_id, 0)
        counts[request.activation_id] = count + 1
        if count == 0:
            return ModelResponse(output=[_call(f"read-{request.activation_id}", "read_file", path="notes.txt")])
        return product_spec()

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([respond] * 100))
    run_id = system.create_run("build echo", context_window=8000)
    system.workspace(run_id).write_file("notes.txt", "PRESERVED_TOOL_BYTES " * 1800)
    first = system.activate_once(run_id)
    # 压缩照常生效：输入到达不再作废这次压缩
    assert first.compactions and first.input_version == 2
    assert {item["input_version"] for item in first.compactions} == {1, 2}
    # 这一轮没有因为输入结束：模型在下一步看见通知以后提交的要求被接纳，这条输入被产品处理掉
    assert first.product_spec is not None and first.processed_input_version == 2
    first_ids = {item["source_event_id"] for item in first.compactions}
    second = system.activate_once(run_id)
    # 产品要求被接纳以后工程有新的工作（工单 #556：工程关注 PRD 的新版本）
    assert has_new_work(second, "engineering"), second.error
    # bare run 的部门 Prompt 是内置默认 Prompt（版本 0），run 内没有副本
    expected_input, expected_prompt = 2, 0
    assert second.processed_input_version == expected_input
    later = [item for item in second.compactions if item["source_event_id"] not in first_ids]
    # 检查点按输入版本绑定（与合同同理，工单 #840）：新一轮的压缩从原始记录重建
    assert later and later[0]["previous_compaction_event_id"] is None
    assert all(item["input_version"] == expected_input and item["prompt_version"] == expected_prompt for item in later)
    original = next(event for event in _events(system, run_id, EventType.TOOL_CALLED)
                    if event.payload.get("name") == "read_file")
    # 这一轮的压缩保留了工具结果：原始记录里的字节仍在
    assert original.event_id in {ref["event_id"] for item in first.compactions for ref in item["source_refs"]}
    assert system.artifacts.get_text(original.payload["output_ref"]["content_hash"]).count("PRESERVED_TOOL_BYTES") == 1800
    versions = [_manifest(system, request).input_version for request in system.test_adapter.invocations]
    # 第一条请求在输入到达以前装配，以后的请求带着新的输入版本
    assert versions[0] == 1 and versions[-1] == 2
    assert all(_manifest(system, request).prompt_version == expected_prompt
               for request in system.test_adapter.invocations)
    assert second.canonical_state() == system.replay(run_id).canonical_state()

def test_updated_requirements_flow_through_new_delivery_and_independent_quality(tmp_path):
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec(), _revision()],
        "engineering": [delivery_turn(),
                        delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"})],
        "quality": quality_turns("release", "Independently checked the updated uppercase output"),
    }))
    run_id = system.create_run("build echo", max_cycles=12)
    old = _steps(system, run_id, 2)
    system.add_input(run_id, "Print the argument in uppercase")
    done = system.run_until_stop(run_id)
    assert done.status == "done", done.error
    assert done.processed_input_version == done.input_version == 2
    assert done.product_spec.change_record == CHANGE_RECORD
    assert done.effective_contract.content_hash != old.effective_contract.content_hash
    assert done.delivery_spec.effective_contract_hash == done.last_review.effective_contract_hash == done.effective_contract.content_hash
    assert done.delivery_specs[0].status == "superseded"
    assert done.canonical_state() == system.replay(run_id).canonical_state()

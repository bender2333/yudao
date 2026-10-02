import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import harness.interactions as interactions
from harness.adapters.fake import FakeAdapter, FakeTurn, pending_request_id
from harness.compaction import visible_history
from harness.definitions import DEFINITIONS
from harness.engine import StepLimits
from harness.models import EventType, json_dumps
from harness.proposals import (
    collaboration_request, collaboration_response, delivery_turn, plan_turn,
    product_decision, product_spec, response_turn, review_turn,
)
from harness.providers.call import ModelResponse
from harness.providers.selection import ModelSelection
from harness.runtime import LoopSystem, RunTerminalError
from harness.tests.helpers import (WAIT_FOR_RELEASE, after_event, department_history, from_another_thread,
                                   recorded_context, wait_for_file)


CHANGE_RECORD = {
    "changed": ["Print the argument in uppercase"],
    "retained": ["Accept one command-line argument"],
    "retired": ["Preserve original letter casing"],
    "rationale": "Apply the user's explicit change to uppercase output",
}


def _revision():
    return product_spec(requirements=["print the argument in uppercase"], change_record=CHANGE_RECORD)


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
    assert result.phase == "FAILED" and result.stop_reason == "context_overflow"
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


@pytest.mark.parametrize("failure", ["partial_write", "replace"])
def test_failed_intend_publication_preserves_previous_original_and_received_state(tmp_path, monkeypatch, failure):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("original input without newline")
    before = system.project(run_id).canonical_state()
    path = tmp_path / "materials" / run_id / "intend.md"
    original = path.read_bytes()
    if failure == "replace":
        def fail_replace(*args):
            raise OSError("cannot replace the published original")
        monkeypatch.setattr(interactions.os, "replace", fail_replace)
    else:
        temporary_file = interactions.tempfile.NamedTemporaryFile

        class PartialFile:
            def __init__(self, *args, **kwargs):
                self.stream = temporary_file(*args, **kwargs)
                self.name = self.stream.name

            def __enter__(self):
                return self

            def write(self, data):
                self.stream.write(data[:2])
                raise OSError("disk stopped during a write")

            def __exit__(self, *args):
                self.stream.close()

        monkeypatch.setattr(interactions.tempfile, "NamedTemporaryFile", PartialFile)
    with pytest.raises(OSError):
        system.add_input(run_id, "new original")
    assert path.read_bytes() == original
    assert system.project(run_id).canonical_state() == before
    assert list(path.parent.glob(".intend-*.tmp")) == []


def test_only_complete_product_spec_can_process_received_input(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), product_decision("Uppercase all output", "This cannot consume pending input"),
        product_spec(requirements=["print the argument in uppercase"]), _revision(),
    ]))
    run_id = system.create_run("build echo")
    old = system.activate_once(run_id)
    system.add_input(run_id, "Print uppercase now")
    decision_rejected = system.activate_once(run_id)
    assert decision_rejected.phase == "PRODUCT_SPEC"
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


def test_product_can_consult_while_current_inputs_still_wait_for_requirement_acceptance(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), collaboration_request("quality", "How should uppercase output be verified?"),
        response_turn("answered", "Check mixed-case input against uppercase output."), _revision(),
    ]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.add_input(run_id, "Print uppercase")
    pending = system.activate_once(run_id)
    assert pending.pending_request.recipient == "quality"
    assert pending.processed_input_version == 1 and pending.product_work_input_version == 2
    returned = system.activate_once(run_id)
    assert returned.pending_request is None and returned.phase == "PRODUCT_SPEC"
    assert returned.processed_input_version == 1 and returned.responses[-1].return_work_valid
    assert len(_events(system, run_id, EventType.PRODUCT_INPUT_ASSIGNED)) == 1
    assert system.activate_once(run_id).processed_input_version == 2


def test_new_input_during_pre_prd_consultation_supersedes_old_request_and_response(tmp_path):
    def reply(request):
        system.add_input(request.run_id, "Make the output uppercase")
        return collaboration_response(pending_request_id(request), "answered", "Advice for the earlier input")

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([collaboration_request("engineering"), reply, product_spec()]))
    run_id = system.create_run("build echo")
    pending = system.activate_once(run_id)
    current = system.activate_once(run_id)
    assert current.phase == "PRODUCT_SPEC" and current.pending_request is None
    assert current.requests[-1].status == "superseded" and current.requests[-1].basis == pending.pending_request.basis
    assert current.responses == [] and current.processed_input_version == 0
    assert _events(system, run_id, EventType.TOOL_SKIPPED)[-1].payload["name"] == "submit_response"
    assert system.activate_once(run_id).product_spec.input_version == 2


def test_new_input_during_product_model_call_prevents_old_spec_acceptance(tmp_path):
    def old_spec(request):
        assert _manifest(system, request).input_version == 1
        system.add_input(request.run_id, "Also require uppercase output")
        return product_spec()

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([old_spec, product_spec(requirements=["Print uppercase output"])]))
    run_id = system.create_run("build echo")
    stale = system.activate_once(run_id)
    assert stale.phase == "PRODUCT_SPEC" and stale.product_spec is None and stale.processed_input_version == 0
    assert len(_events(system, run_id, EventType.TOOL_SKIPPED)) == 1
    current = system.activate_once(run_id)
    assert current.product_spec.revision == 1 and current.processed_input_version == 2
    assert [_manifest(system, request).input_version for request in system.test_adapter.invocations] == [1, 2]


def test_input_before_model_request_start_does_not_send_the_prepared_old_context(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("build echo")
    received = False

    def receive_before_start(_event):
        nonlocal received
        if not received:
            received = True
            system.add_input(run_id, "Confirm uppercase output")

    after_event(system, EventType.CONTEXT_ASSEMBLED, receive_before_start)
    stopped = system.activate_once(run_id)
    assert stopped.phase == "PRODUCT_SPEC" and not system.test_adapter.invocations
    assert not _events(system, run_id, EventType.MODEL_REQUESTED)
    assert system.activate_once(run_id).processed_input_version == 2
    assert _manifest(system, system.test_adapter.invocations[-1]).input_version == 2


def test_input_at_last_toolless_model_step_ends_old_activation_before_its_step_limit(tmp_path):
    def final_old_response(request):
        system.add_input(run_id, "Confirm uppercase output")
        return ModelResponse(output=[{"type": "message", "id": "old-output", "role": "assistant",
                                      "content": [{"type": "output_text", "text": "A response to the original input."}]}])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([final_old_response, product_spec()]),
                                    step_limits=StepLimits(max_model_steps=1))
    run_id = system.create_run("build echo")
    current = system.activate_once(run_id)
    assert current.phase == "PRODUCT_SPEC" and current.stop_reason is None
    assert current.product_work_input_version == 2 and current.processed_input_version == 0
    assert system.activate_once(run_id).processed_input_version == 2


def test_started_tool_finishes_and_remaining_model_tools_are_skipped_on_new_input(tmp_path):
    # 登记命令运行中收到新输入：这个命令照常完成并记录，其余工具跳过
    signals = tmp_path / "signals"
    signals.mkdir()
    code = ("import pathlib; pathlib.Path('src').mkdir(exist_ok=True); "
            "pathlib.Path('src/first.py').write_text('completed first tool'); " + WAIT_FOR_RELEASE)
    registry = {"first": {"argv": ["python", "-c", code, str(signals)], "args": [], "timeout_sec": 60,
                          "output_limit": 4000}}
    calls = [{"id": "first", "call_id": "first", "type": "function_call", "name": "run_command",
              "arguments": json_dumps({"name": "first"})},
             _call("second", "write_file", path="src/second.py", content="must not start"),
             _call("submission", "submit_delivery", summary="old delivery", files=["src/first.py"], check_names=["smoke"])]
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(), ModelResponse(output=calls), _revision()]))
    run_id = system.create_run("build echo", registered_commands=registry, command_versions={"first": 1})
    _steps(system, run_id, 2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            wait_for_file(signals / "started")
            received = system.add_input(run_id, "Print uppercase instead")
            assert received.product_work_input_version == 1
        finally:
            (signals / "release").write_text("go")
        current = future.result(timeout=30)
    assert current.phase == "PRODUCT_SPEC" and current.processed_input_version == 1
    assert system.workspace(run_id).list_files() == ["src/first.py"]
    events = system.store.list_events(run_id)
    started = next(event for event in events if event.type == EventType.TOOL_STARTED and event.payload["id"] == "first")
    received = _events(system, run_id, EventType.USER_INPUT_RECEIVED)[0]
    finished = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("id") == "first")
    assert started.stream_version < received.stream_version < finished.stream_version
    assert finished.payload["ok"] and finished.payload["input_version"] == 1
    skipped = _events(system, run_id, EventType.TOOL_SKIPPED)
    assert [event.payload["id"] for event in skipped] == ["second", "submission"]
    assert all(event.payload["input_version"] == 1 for event in skipped)
    visible_history(department_history(system, run_id, "engineering"))
    assert system.activate_once(run_id).processed_input_version == 2


def test_input_received_during_quality_model_response_prevents_its_old_release(tmp_path):
    def stale_release(request):
        system.add_input(request.run_id, "Print uppercase instead")
        return review_turn("release", "This belongs to the old input")

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(), delivery_turn(), stale_release]))
    run_id = system.create_run("build echo")
    _steps(system, run_id, 3)
    current = system.activate_once(run_id)
    assert current.phase == "PRODUCT_SPEC" and current.last_review is None
    assert current.input_version == 2 and current.processed_input_version == 1
    assert not _events(system, run_id, EventType.RUN_DONE)
    assert [event.payload["name"] for event in _events(system, run_id, EventType.TOOL_SKIPPED)] == ["run_check", "submit_review"]


def test_input_committed_while_the_release_is_prepared_rejects_the_release(tmp_path, monkeypatch):
    # 质检放行正在准备接纳时另一个线程写入新输入：放行的提交因流版本改变被写入口拒绝，按写入以后的状态重新判断；
    # 激活开始以后输入改变，放行按 execution_basis 拒绝，新输入保留，运行没有结束
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(), review_turn("release", "Current check passed"),
    ]))
    run_id = system.create_run("build echo")
    _steps(system, run_id, 3)
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
    assert current.phase != "DONE" and current.input_version == 2
    assert not _events(system, run_id, EventType.RUN_DONE) and not _events(system, run_id, EventType.QA_SUBMITTED)
    [rejected] = _events(system, run_id, EventType.PROPOSAL_REJECTED)
    assert [error["field"] for error in rejected.payload["errors"]] == ["execution_basis"]
    assert current.canonical_state() == system.replay(run_id).canonical_state()


@pytest.mark.parametrize("command", ["/stop", "  /cancel\r\n"])
def test_text_stop_commands_preserve_original_before_immediate_cancellation(tmp_path, command):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("original")
    current = system.add_input(run_id, command)
    assert current.phase == "FAILED" and current.stop_reason == "cancelled"
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

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), update, plan_turn(), collaboration_request("product"),
    ]))
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


def test_identical_requirement_text_for_new_input_still_has_new_contract_and_plan_binding(tmp_path):
    same_requirements = product_spec(change_record={
        "changed": [], "retained": ["Echo the argument exactly"], "retired": [],
        "rationale": "The new user input confirms the existing behavior",
    })
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(), same_requirements]))
    run_id = system.create_run("build echo")
    old = _steps(system, run_id, 2)
    system.add_input(run_id, "Confirm the existing echo behavior")
    current = system.activate_once(run_id)
    assert current.product_spec.requirements == old.product_spec.requirements
    assert current.effective_contract.content_hash != old.effective_contract.content_hash
    assert current.effective_contract.input_version == 2 and current.engineering_plan is None
    assert current.engineering_plans[-1].status == "superseded"


def test_compaction_keeps_activation_versions_and_rebuilds_after_version_change(tmp_path):
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
    assert changed and first.phase == "PRODUCT_SPEC", first.error
    assert not first.compactions and first.input_version == 2 and first.product_spec is None
    first_ids = {item["source_event_id"] for item in first.compactions}
    second = system.activate_once(run_id)
    assert second.phase == "ENGINEERING", second.error
    # bare run 的部门 Prompt 是内置默认 Prompt（版本 0），run 内没有副本
    expected_input, expected_prompt = 2, 0
    assert second.processed_input_version == expected_input
    later = [item for item in second.compactions if item["source_event_id"] not in first_ids]
    assert later and later[0]["previous_compaction_event_id"] is None
    assert all(item["input_version"] == expected_input and item["prompt_version"] == expected_prompt for item in later)
    original = next(event for event in _events(system, run_id, EventType.TOOL_CALLED)
                    if event.payload.get("name") == "read_file")
    assert original.event_id in {ref["event_id"] for item in later for ref in item["source_refs"]}
    assert system.artifacts.get_text(original.payload["output_ref"]["content_hash"]).count("PRESERVED_TOOL_BYTES") == 1800
    for request in system.test_adapter.invocations:
        manifest = _manifest(system, request)
        if request.activation_id == first_activation:
            assert manifest.input_version == 1 and manifest.prompt_version == 0
        else:
            assert manifest.input_version == expected_input and manifest.prompt_version == expected_prompt
    assert second.canonical_state() == system.replay(run_id).canonical_state()


def test_updated_requirements_flow_through_new_plan_delivery_and_independent_quality(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(), _revision(),
        plan_turn(reason="Implement the newly accepted uppercase requirement"),
        delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        review_turn("release", "Independently checked the updated uppercase output"),
    ]))
    run_id = system.create_run("build echo", max_cycles=12)
    old = _steps(system, run_id, 3)
    system.add_input(run_id, "Print the argument in uppercase")
    done = system.run_until_stop(run_id)
    assert done.phase == "DONE", done.error
    assert done.processed_input_version == done.input_version == 2
    assert done.product_spec.change_record == CHANGE_RECORD
    assert done.effective_contract.content_hash != old.effective_contract.content_hash
    assert done.engineering_plan.effective_contract_hash == done.effective_contract.content_hash
    assert done.delivery_spec.effective_contract_hash == done.last_review.effective_contract_hash == done.effective_contract.content_hash
    assert done.delivery_spec.engineering_plan_hash == done.last_review.engineering_plan_hash == done.engineering_plan.content_hash
    assert done.delivery_specs[0].status == "superseded" and done.engineering_plans[0].status == "superseded"
    assert done.canonical_state() == system.replay(run_id).canonical_state()

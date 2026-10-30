# 工单 #1234：run.steps 按激活与步骤给出推理、模型文字、动作与回执（应用层与接口层设计说明第 4.3 节），
# event.detail 给出推理与模型输出的可读文字。夹具直接写入主机写的那几种事件与工件，形状参照
# harness/tests/test_protocol_reasoning.py 里三种协议的真实回答：Chat Completions 的 reasoning_content、
# Messages 的 thinking 块、Responses 的 summary 与加密内容；一条回答里同时有文字条目与工具调用条目。
# 查询只读事件与工件：不调用模型，不回写事实，不新增事件种类。

import json
import time
from dataclasses import asdict

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import EventDetail, NotFound, RunActions, RunSteps
from harness.event_store import run_stream
from harness.models import EventType
from harness.runtime import LoopSystem
from harness.write_path import NewEvent

PRODUCT = "product"
ENGINEERING = "engineering"
ACTIVATION = "act-1"
EARLIER_ACTIVATION = "act-0"
ENGINEERING_ACTIVATION = "act-e"
LONG_REASONING = "先看代码，再动手。" * 32  # 224 字：超过前 200 字的预览
TEXT_ENTRY = "我先看一下代码。"
TOOL_CALL_ENTRY = "list_files"


def _append(system, run_id, event_type, *, department=PRODUCT, payload=None, session_id=None):
    return system.writes.append(run_stream(run_id), NewEvent(
        event_type, actor="department:" + department, department=department,
        state_before="running", state_after="running", session_id=session_id,
        payload=payload or {}))[0]


def _artifact(system, run_id, name, item):
    return asdict(system.artifacts.put(run_id, name, json.dumps(item, ensure_ascii=False),
                                      media_type="application/json"))


def _chat_reasoning(text):
    # Chat Completions 的推理内容：assistant 消息上的 reasoning_content
    return {"type": "reasoning", "reasoning_content": text}


def _messages_reasoning(text):
    # Messages 的推理内容：thinking 块与它的签名
    return {"type": "reasoning", "call_id": "call-a",
            "blocks": [{"type": "thinking", "thinking": text, "signature": "sig-abc"}]}


def _responses_reasoning(text):
    # Responses 的推理条目：可读的摘要文字与加密内容
    return {"id": "rs-1", "type": "reasoning", "summary": [{"type": "summary_text", "text": text}],
            "encrypted_content": "CIPHER-1"}


def _encrypted_reasoning():
    # 上游只给加密内容的推理条目：没有可读文字
    return {"id": "rs-2", "type": "reasoning", "summary": [], "encrypted_content": "CIPHER-2"}


def _text_message(text):
    # 文字条目：模型说的一句话
    return {"id": "msg-1", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}


def _tool_call_message(name):
    # 工具调用条目：模型要调用的工具（已经由 tool_started 与 tool_called 表达）
    return {"id": "fc-1", "type": "function_call", "call_id": "call-a", "name": name,
            "arguments": "{}"}


def _reasoning(system, run_id, *, department=PRODUCT, activation=ACTIVATION, step_id, attempt_id, item):
    return _append(system, run_id, EventType.MODEL_REASONING, department=department, payload={
        "activation_id": activation, "step_id": step_id, "attempt_id": attempt_id,
        "reasoning_ref": _artifact(system, run_id, "model_reasoning", item)})


def _message(system, run_id, *, department=PRODUCT, activation=ACTIVATION, step_id, attempt_id, item,
             index=0):
    return _append(system, run_id, EventType.MODEL_MESSAGE, department=department, payload={
        "activation_id": activation, "step_id": step_id, "attempt_id": attempt_id,
        "message_index": index, "message_ref": _artifact(system, run_id, "model_message", item)})


def _request(system, run_id, *, department=PRODUCT, activation=ACTIVATION, step_id, root_step_id,
             attempt, attempt_id):
    return _append(system, run_id, EventType.MODEL_REQUESTED, department=department, payload={
        "activation_id": activation, "step_id": step_id, "root_step_id": root_step_id,
        "attempt": attempt, "attempt_id": attempt_id, "max_attempts": 3, "purpose": "work"})


def _tool(system, run_id, *, department=PRODUCT, activation=ACTIVATION, action_id, name, step_id,
          ok=True, error=None, args=None):
    started = _append(system, run_id, EventType.TOOL_STARTED, department=department, payload={
        "id": action_id, "name": name, "args": args or {}, "purpose": "work",
        "activation_id": activation, "step_id": step_id, "input_version": 1})
    called = _append(system, run_id, EventType.TOOL_CALLED, department=department, payload={
        "id": action_id, "name": name, "args": args or {}, "ok": ok, "error": error,
        "activation_id": activation, "step_id": step_id, "input_version": 1})
    return started, called


def steps_fixture(data_dir):
    """一个部门两次激活、另一个部门一次激活的运行：覆盖本工单验收里的全部形状。

    产品部门的后一次激活（`act-1`）有五个逻辑步：第一步有推理、一条文字条目、一条工具调用条目与
    两个动作；第二步只有动作；第三步第一次尝试失败、第二次成功；第五步是 Responses 的推理与只有
    加密内容的一条。另外有一条没有归到步骤的动作与一条后台命令。
    """
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("逐步记录", "核对 run.steps")
    work_item_id, run_id = system.projects.start_work_item(project_id, "看部门每一步")

    # 更早的一次激活：问它时要返回这一次的步骤
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED,
            payload={"activation_id": EARLIER_ACTIVATION, "cycle": 1})
    _request(system, run_id, activation=EARLIER_ACTIVATION, step_id=1, root_step_id=1, attempt=1,
             attempt_id="att-0")
    _reasoning(system, run_id, activation=EARLIER_ACTIVATION, step_id=1, attempt_id="att-0",
               item=_chat_reasoning("更早这次激活的推理"))
    _message(system, run_id, activation=EARLIER_ACTIVATION, step_id=1, attempt_id="att-0",
             item=_text_message("更早这次激活说的话"))
    _append(system, run_id, EventType.ACTIVATION_FINISHED, payload={"activation_id": EARLIER_ACTIVATION})

    # 后一次激活（默认看这一次）
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, payload={"activation_id": ACTIVATION, "cycle": 2})
    steps = {}
    _request(system, run_id, step_id=1, root_step_id=1, attempt=1, attempt_id="att-1")
    steps["reasoning"] = _reasoning(system, run_id, step_id=1, attempt_id="att-1",
                                    item=_chat_reasoning(LONG_REASONING))
    steps["text"] = _message(system, run_id, step_id=1, attempt_id="att-1",
                             item=_text_message(TEXT_ENTRY))
    steps["tool_entry"] = _message(system, run_id, step_id=1, attempt_id="att-1",
                                   item=_tool_call_message(TOOL_CALL_ENTRY), index=1)
    _tool(system, run_id, action_id="call-a", name="list_files", step_id=1)
    _tool(system, run_id, action_id="call-b", name="read_file", step_id=1)

    _request(system, run_id, step_id=2, root_step_id=2, attempt=1, attempt_id="att-2")
    _tool(system, run_id, action_id="call-c", name="list_files", step_id=2)

    # 第三步：第一次尝试失败（它的推理与文字被丢弃），第二次尝试成功
    _request(system, run_id, step_id=3, root_step_id=3, attempt=1, attempt_id="att-3a")
    _reasoning(system, run_id, step_id=3, attempt_id="att-3a", item=_chat_reasoning("失败这一次的推理"))
    _message(system, run_id, step_id=3, attempt_id="att-3a", item=_text_message("失败这一次的文字"))
    _append(system, run_id, EventType.MODEL_ATTEMPT_FAILED, payload={
        "attempt_id": "att-3a", "activation_id": ACTIVATION, "step_id": 3, "status": "failed",
        "reason": "provider_timeout", "retryable": True, "will_retry": True, "max_attempts": 3})
    _request(system, run_id, step_id=4, root_step_id=3, attempt=2, attempt_id="att-3b")
    _reasoning(system, run_id, step_id=4, attempt_id="att-3b", item=_messages_reasoning("重试以后的推理"))
    _message(system, run_id, step_id=4, attempt_id="att-3b", item=_text_message("重试以后的文字"))
    _append(system, run_id, EventType.MODEL_ATTEMPT_FINISHED, payload={
        "attempt_id": "att-3b", "activation_id": ACTIVATION, "step_id": 4, "status": "completed"})

    # 第五步：Responses 的推理（摘要可读）与一条只有加密内容的推理
    _request(system, run_id, step_id=5, root_step_id=5, attempt=1, attempt_id="att-5")
    _reasoning(system, run_id, step_id=5, attempt_id="att-5",
               item=_responses_reasoning("Responses 的推理摘要"))
    _reasoning(system, run_id, step_id=5, attempt_id="att-5", item=_encrypted_reasoning())
    _tool(system, run_id, action_id="call-bg", name="bash", step_id=5,
          args={"command": "wait-for-release", "background": True})

    # 没有归到步骤的动作：没有 step_id
    steps["unassigned"] = _tool(system, run_id, action_id="call-x", name="run_check", step_id=None)[0]

    _append(system, run_id, EventType.ACTIVATION_FINISHED, payload={"activation_id": ACTIVATION})

    # 另一个部门的一次激活：它的步骤、推理与后台命令不出现
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, department=ENGINEERING,
            payload={"activation_id": ENGINEERING_ACTIVATION, "cycle": 1})
    _request(system, run_id, department=ENGINEERING, activation=ENGINEERING_ACTIVATION, step_id=1,
             root_step_id=1, attempt=1, attempt_id="att-e")
    _reasoning(system, run_id, department=ENGINEERING, activation=ENGINEERING_ACTIVATION, step_id=1,
               attempt_id="att-e", item=_chat_reasoning("工程的推理"))
    _tool(system, run_id, department=ENGINEERING, activation=ENGINEERING_ACTIVATION,
          action_id="call-ebg", name="bash", step_id=1,
          args={"command": "wait-for-release", "background": True})
    _append(system, run_id, EventType.ACTIVATION_FINISHED, department=ENGINEERING,
            payload={"activation_id": ENGINEERING_ACTIVATION})

    application = Application(system)
    return system, application, run_id, steps


def _query(application, request):
    return application.query("run.steps", request).data


def _step(steps, step_id):
    return next(step for step in steps if step.step_id == step_id)


def test_a_step_groups_its_reasoning_texts_and_actions(data_dir):
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert result.activation_id == ACTIVATION
        assert [step.step_id for step in result.steps] == [1, 2, 3, 5]
        first = _step(result.steps, 1)
        assert [item.event_id for item in first.reasoning] == [_steps["reasoning"].event_id]
        assert first.reasoning[0].readable is True
        assert first.reasoning[0].length == len(LONG_REASONING)
        assert first.reasoning[0].preview == LONG_REASONING[:200]
        assert [item.event_id for item in first.texts] == [_steps["text"].event_id]
        assert first.texts[0].readable is True
        assert first.texts[0].length == len(TEXT_ENTRY)
        assert first.texts[0].preview == TEXT_ENTRY
        assert [action.action_id for action in first.actions] == ["call-a", "call-b"]
        assert first.requested_at
        assert first.discarded_attempts == 0
        second = _step(result.steps, 2)
        assert second.reasoning == [] and second.texts == []
        assert [action.action_id for action in second.actions] == ["call-c"]
    finally:
        system.close()


def test_a_tool_call_entry_is_not_model_text(data_dir):
    # 模型要调用工具的那一条（function_call）不是模型说的话：这一步的 texts 只有文字条目
    system, application, run_id, steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        first = _step(result.steps, 1)
        assert len(first.texts) == 1
        assert steps["tool_entry"].event_id not in [item.event_id for item in first.texts]
        detail = application.query("event.detail", EventDetail(event_id=steps["tool_entry"].event_id)).data
        assert detail.artifacts["message"]["type"] == "function_call"
        assert detail.artifacts["message_text"] == ""
    finally:
        system.close()


def test_a_failed_attempt_counts_but_its_texts_stay_out(data_dir):
    # 第三步第一次尝试失败：它的推理与文字不进这一步，只计入被丢弃的尝试数
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        third = _step(result.steps, 3)
        assert third.discarded_attempts == 1
        assert [item.preview for item in third.reasoning] == ["重试以后的推理"]
        assert [item.preview for item in third.texts] == ["重试以后的文字"]
        # 前面两步没有失败的尝试
        assert [step.discarded_attempts for step in result.steps if step.step_id in (1, 2)] == [0, 0]
    finally:
        system.close()


def test_the_three_protocols_and_encrypted_reasoning(data_dir):
    # 三种协议的可读文字各一条；只有加密内容的那条不可读（长度为 0、预览为空）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert [_step(result.steps, 1).reasoning[0].preview] == [LONG_REASONING[:200]]
        assert [_step(result.steps, 3).reasoning[0].preview] == ["重试以后的推理"]
        fifth = _step(result.steps, 5)
        readable, encrypted = fifth.reasoning
        assert readable.readable is True
        assert readable.preview == "Responses 的推理摘要"
        assert encrypted.readable is False
        assert encrypted.length == 0
        assert encrypted.preview == ""
    finally:
        system.close()


def test_actions_without_a_step_are_listed_separately(data_dir):
    # 没有 step_id 的动作在 unassigned_actions，不出现在任何一步里
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert [action.action_id for action in result.unassigned_actions] == ["call-x"]
        assert result.unassigned_actions[0].status == "completed"
        listed = [action.action_id for step in result.steps for action in step.actions]
        assert "call-x" not in listed
    finally:
        system.close()


def test_only_this_department_is_included(data_dir):
    # 只返回本部门的步骤、推理与后台命令
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        product = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert [activation.activation_id for activation in product.activations] == [EARLIER_ACTIVATION, ACTIVATION]
        # 这次返回的激活里的动作都属于本部门、都属于这个激活（另一个部门的动作不会混进来）
        assert all(action.department == PRODUCT and action.activation_id == ACTIVATION
                   for step in product.steps for action in step.actions)
        previews = [item.preview for step in product.steps for item in step.reasoning]
        assert "工程的推理" not in previews
        assert [command.command for command in product.background_commands] == ["wait-for-release"]

        engineering = _query(application, RunSteps(run_id=run_id, department=ENGINEERING))
        assert engineering.activation_id == ENGINEERING_ACTIVATION
        assert [item.preview for step in engineering.steps for item in step.reasoning] == ["工程的推理"]
        assert [command.command for command in engineering.background_commands] == ["wait-for-release"]
        assert [len(step.actions) for step in engineering.steps] == [1]
    finally:
        system.close()


def test_an_earlier_activation_can_be_asked_for(data_dir):
    # activation_id 指向更早的激活时返回那一次的步骤
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT,
                                              activation_id=EARLIER_ACTIVATION))
        assert result.activation_id == EARLIER_ACTIVATION
        assert [step.step_id for step in result.steps] == [1]
        assert [item.preview for item in result.steps[0].reasoning] == ["更早这次激活的推理"]
        assert [item.preview for item in result.steps[0].texts] == ["更早这次激活说的话"]
    finally:
        system.close()


def test_an_activation_of_another_department_is_not_found(data_dir):
    # 不属于这个部门的激活回「找不到」
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        with_error = None
        try:
            _query(application, RunSteps(run_id=run_id, department=PRODUCT,
                                         activation_id=ENGINEERING_ACTIVATION))
        except NotFound as error:
            with_error = error
        assert with_error is not None
    finally:
        system.close()


def test_activations_list_carries_times_and_step_counts(data_dir):
    # 该部门的全部激活：开始与结束时间、步数（重试与它重试的那一步算一步）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        earlier, current = result.activations
        assert earlier.activation_id == EARLIER_ACTIVATION
        assert earlier.step_count == 1
        assert earlier.finished_at is not None
        assert current.activation_id == ACTIVATION
        assert current.step_count == 4
        assert current.started_at <= current.finished_at
    finally:
        system.close()


def test_event_detail_returns_reasoning_and_model_texts(data_dir):
    # event.detail：model_reasoning 返回原文与可读文字；model_message 另给 message_text
    system, application, run_id, steps = steps_fixture(data_dir)
    try:
        reasoning = application.query("event.detail", EventDetail(event_id=steps["reasoning"].event_id)).data
        assert reasoning.artifacts["reasoning"]["reasoning_content"] == LONG_REASONING
        assert reasoning.artifacts["reasoning_text"] == LONG_REASONING
        text = application.query("event.detail", EventDetail(event_id=steps["text"].event_id)).data
        assert text.artifacts["message_text"] == TEXT_ENTRY
        # 工具调用条目的 message_text 是空串（与 run.steps 只取文字条目是同一条规则）
        tool_entry = application.query("event.detail",
                                       EventDetail(event_id=steps["tool_entry"].event_id)).data
        assert tool_entry.artifacts["message_text"] == ""
    finally:
        system.close()


def test_run_actions_output_is_unchanged(data_dir):
    # run.actions 照旧返回全部部门的动作与后台命令（建档页与 process_kill 仍读它）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        actions = application.query("run.actions", RunActions(run_id=run_id)).data
        assert {action.action_id for action in actions.actions} == {
            "call-a", "call-b", "call-c", "call-bg", "call-x", "call-ebg"}
        assert sorted(command.command for command in actions.background_commands) == [
            "wait-for-release", "wait-for-release"]
    finally:
        system.close()


def test_a_long_activation_is_read_within_a_second(data_dir):
    # 读数（验收第 9 条）：93 步、52 条推理的一次读取。超时说明本机负载或查询需要分页
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("长激活", "核对读取耗时")
    work_item_id, run_id = system.projects.start_work_item(project_id, "93 步")
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, payload={"activation_id": ACTIVATION, "cycle": 1})
    for step_id in range(1, 94):
        _request(system, run_id, step_id=step_id, root_step_id=step_id, attempt=1,
                 attempt_id="att-%d" % step_id)
        if step_id <= 52:
            _reasoning(system, run_id, step_id=step_id, attempt_id="att-%d" % step_id,
                       item=_chat_reasoning("第 %d 步的推理：先看代码，再动手。" % step_id))
        _tool(system, run_id, action_id="call-%d" % step_id, name="list_files", step_id=step_id)
    _append(system, run_id, EventType.ACTIVATION_FINISHED, payload={"activation_id": ACTIVATION})
    application = Application(system)
    try:
        started = time.monotonic()
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        elapsed = time.monotonic() - started
        assert len(result.steps) == 93
        assert sum(len(step.reasoning) for step in result.steps) == 52
        # 读数写进交付说明；本机应远低于 1 秒，超过时这里失败并写明读数
        print("run.steps 在 93 步、52 条推理上的读数：%.3f 秒" % elapsed)
        assert elapsed < 1.0, "run.steps 用时 %.3f 秒" % elapsed
    finally:
        system.close()

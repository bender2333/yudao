# 工单 #1234：run.steps 按激活与步骤给出推理、模型文字、动作与回执（应用层与接口层 docs/design/app-and-interface.md「查询清单」），
# event.detail 给出推理与模型输出的可读文字。夹具直接写入主机写的那几种事件与工件，形状参照
# harness/tests/test_protocol_reasoning.py 里三种协议的真实回答：Chat Completions 的 reasoning_content、
# Messages 的 thinking 块、Responses 的 summary 与加密内容；一条回答里同时有文字条目与工具调用条目。
# 查询只读事件与工件：不调用模型，不回写事实，不新增事件种类。

import json
import time
from dataclasses import asdict

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.labels import event_label
from harness.app.project_queries import (EventDetail, NotFound, ProjectAttempts, RunAsks, RunAttempt, RunSteps)
from harness.event_store import run_stream
from harness.models import EventType
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.write_path import NewEvent

PRODUCT = "product"
ENGINEERING = "engineering"
QUALITY = "quality"
ACTIVATION = "act-1"
EARLIER_ACTIVATION = "act-0"
ENGINEERING_ACTIVATION = "act-e"
# 主线会话的编号：激活事件的信封上带它，询问分支的激活这里是询问编号（工单 #1657）
SESSION = "sess-main"
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
          ok=True, error=None, args=None, exit_code=None, status=None, before_ref=None, after_ref=None,
          refused=False):
    started_payload = {
        "id": action_id, "name": name, "args": args or {}, "purpose": "work",
        "activation_id": activation, "step_id": step_id, "input_version": 1}
    if before_ref is not None:
        started_payload["before_snapshot_ref"] = before_ref
    called_payload = {
        "id": action_id, "name": name, "args": args or {}, "ok": ok, "error": error,
        "activation_id": activation, "step_id": step_id, "input_version": 1}
    if exit_code is not None or status is not None:
        # 工具结果进入部门历史的那一条：执行层把回执写成 {"ok", "output", "error"}，
        # 退出状态与超时在 output.exit_code、output.status 里（与 harness/engine.py 的 tool_result_item 一致）
        called_payload["input_item"] = {
            "type": "function_call_output", "call_id": action_id,
            "output": json.dumps({"ok": ok, "output": {"exit_code": exit_code, "status": status},
                                  "error": error}, ensure_ascii=False)}
    if after_ref is not None:
        called_payload["after_snapshot_ref"] = after_ref
    if refused:
        called_payload["refused"] = True
    started = _append(system, run_id, EventType.TOOL_STARTED, department=department, payload=started_payload)
    called = _append(system, run_id, EventType.TOOL_CALLED, department=department, payload=called_payload)
    return started, called


def _snapshot_ref(seed: str) -> dict:
    # 动作前后的公开树快照引用：两个引用的 kind 不同，比较的只有 content_hash（工单 #1657）
    return {"kind": "tree", "content_hash": "sha256:" + seed * 64, "path": "snapshots/tree.json"}


def _plan_call(system, run_id, *, department=PRODUCT, activation=ACTIVATION, action_id="plan-1",
               step_id=1, entries, ok=True):
    # 更新计划的调用（工单 #1660）：一条普通的工具调用记录，工具开始与工具结果两条；
    # 格式错误时工具结果里 ok 为假（工单 #1661 按这一项判断它算不算计划）
    started_payload = {"id": action_id, "name": "update_plan", "args": {"plan": entries},
                       "purpose": "work", "activation_id": activation, "step_id": step_id,
                       "input_version": 1}
    called_payload = {**started_payload, "ok": ok,
                      "error": None if ok else "plan[0].status must be one of pending, in_progress, completed"}
    started = _append(system, run_id, EventType.TOOL_STARTED, department=department,
                      payload=started_payload)
    called = _append(system, run_id, EventType.TOOL_CALLED, department=department,
                     payload=called_payload)
    return started, called


PLAN_ONE = [{"content": "先看一遍现有实现", "status": "in_progress"},
            {"content": "跑检查", "status": "pending"}]
PLAN_TWO = [{"content": "先看一遍现有实现", "status": "completed"},
            {"content": "跑检查", "status": "in_progress"},
            {"content": "写交付说明", "status": "pending"}]
PLAN_THREE = [{"content": "先看一遍现有实现", "status": "completed"},
              {"content": "跑检查", "status": "in_progress"}]
PLAN_EARLIER = [{"content": "更早那次的做法", "status": "in_progress"}]


def steps_fixture(data_dir):
    """一个部门两次激活、另一个部门一次激活的运行：覆盖本工单验收里的全部形状。

    产品部门的后一次激活（`act-1`）有五个逻辑步：第一步有推理、一条文字条目、一条工具调用条目与
    两个动作；第二步只有动作；第三步第一次尝试失败、第二次成功；第五步是 Responses 的推理与只有
    加密内容的一条。另外有一条没有归到步骤的动作与一条后台命令。
    这一轮里更新三次计划（第一步、第二步、第五步各一次，工单 #1661）；更早那次激活自己有一份计划。
    """
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("逐步记录", "核对 run.steps")
    work_item_id, run_id = system.projects.start_work_item(project_id, "看部门每一步")
    steps = {}

    # 更早的一次激活：问它时要返回这一次的步骤；它自己的计划与动作不进入后一次激活的分组
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, session_id=SESSION,
            payload={"activation_id": EARLIER_ACTIVATION, "cycle": 1})
    _request(system, run_id, activation=EARLIER_ACTIVATION, step_id=1, root_step_id=1, attempt=1,
             attempt_id="att-0")
    _reasoning(system, run_id, activation=EARLIER_ACTIVATION, step_id=1, attempt_id="att-0",
               item=_chat_reasoning("更早这次激活的推理"))
    _message(system, run_id, activation=EARLIER_ACTIVATION, step_id=1, attempt_id="att-0",
             item=_text_message("更早这次激活说的话"))
    _plan_call(system, run_id, activation=EARLIER_ACTIVATION, action_id="plan-earlier",
               entries=PLAN_EARLIER)
    steps["earlier_action"] = _tool(system, run_id, activation=EARLIER_ACTIVATION,
                                    action_id="call-earlier", name="read_file", step_id=1,
                                    args={"path": "src/earlier.py"})
    _append(system, run_id, EventType.ACTIVATION_FINISHED, payload={"activation_id": EARLIER_ACTIVATION})

    # 后一次激活（默认看这一次）
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, session_id=SESSION,
            payload={"activation_id": ACTIVATION, "cycle": 2})
    _request(system, run_id, step_id=1, root_step_id=1, attempt=1, attempt_id="att-1")
    # 第一步里先发更新计划、后发动作：这一步的动作归新计划的第一条进行中任务
    _plan_call(system, run_id, action_id="plan-1", step_id=1, entries=PLAN_ONE)
    steps["reasoning"] = _reasoning(system, run_id, step_id=1, attempt_id="att-1",
                                    item=_chat_reasoning(LONG_REASONING))
    steps["text"] = _message(system, run_id, step_id=1, attempt_id="att-1",
                             item=_text_message(TEXT_ENTRY))
    steps["tool_entry"] = _message(system, run_id, step_id=1, attempt_id="att-1",
                                   item=_tool_call_message(TOOL_CALL_ENTRY), index=1)
    steps["list_files"] = _tool(system, run_id, action_id="call-a", name="list_files", step_id=1)
    steps["read_file"] = _tool(system, run_id, action_id="call-b", name="read_file", step_id=1,
                               args={"path": "src/a.py"})

    _request(system, run_id, step_id=2, root_step_id=2, attempt=1, attempt_id="att-2")
    _plan_call(system, run_id, action_id="plan-2", step_id=2, entries=PLAN_TWO)
    _tool(system, run_id, action_id="call-c", name="list_files", step_id=2)
    # 命令的失败与超时看退出状态，不看 ok：这两条的回执里 ok 都是真（工单 #1657）
    _tool(system, run_id, action_id="call-fail", name="bash", step_id=2,
          args={"command": "false"}, ok=True, exit_code=3, status="failed")
    _tool(system, run_id, action_id="call-timeout", name="bash", step_id=2,
          args={"command": "sleep 999"}, ok=True, exit_code=124, status="timeout")
    # 改了文件：动作前后的公开树摘要不同；摘要相同的一条不标
    _tool(system, run_id, action_id="call-write", name="write_file", step_id=2,
          args={"path": "a.txt", "content": "新的内容"},
          before_ref=_snapshot_ref("a"), after_ref=_snapshot_ref("b"))
    _tool(system, run_id, action_id="call-same", name="write_file", step_id=2,
          args={"path": "b.txt", "content": "一样的内容"},
          before_ref=_snapshot_ref("c"), after_ref=_snapshot_ref("c"))

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

    # 第五步：Responses 的推理（摘要可读）与一条只有加密内容的推理；这一步的计划去掉了「写交付说明」
    _request(system, run_id, step_id=5, root_step_id=5, attempt=1, attempt_id="att-5")
    _plan_call(system, run_id, action_id="plan-3", step_id=5, entries=PLAN_THREE)
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
        assert [action.action_id for action in second.actions] == [
            "call-c", "call-fail", "call-timeout", "call-write", "call-same"]
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


# ---------------------------------------------------------------------------
# 工单 #1657：动作标记与标题、会话编号与第几轮、调用尝试编号


def _actions(result, step_id):
    return {action.action_id: action for action in _step(result.steps, step_id).actions}


def test_every_action_carries_a_mark_a_title_and_its_source(data_dir):
    # R3：每个动作一行，标记加标题；标题与来源由工具定义与参数重算，读、写、运行各写明对象（工单 #1657）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        first = _actions(result, 1)
        assert (first["call-a"].mark, first["call-a"].title) == ("读", "列出文件")
        assert (first["call-b"].mark, first["call-b"].title) == ("读", "读取 src/a.py")
        second = _actions(result, 2)
        assert (second["call-write"].mark, second["call-write"].title) == ("写", "写入 a.txt")
        assert (second["call-fail"].mark, second["call-fail"].title) == ("运行", "运行命令：false")
        # 来源是系统：这些标题不是角色写的
        assert all(action.title_source == "系统" for step in result.steps for action in step.actions)
        # 后台命令另有一张表（BackgroundCommandView），它发起的那次调用照样是一行动作行
        assert [command.command for command in result.background_commands] == ["wait-for-release"]
        fifth = _actions(result, 5)
        assert (fifth["call-bg"].mark, fifth["call-bg"].title) == ("运行", "运行命令：wait-for-release")
    finally:
        system.close()


def test_failure_and_timeout_come_from_the_exit_status_not_from_ok(data_dir):
    # R3：失败（退出状态非零）与超时、改了文件都由事实得出；退出状态非零时 ok 仍为真，用 ok 判不出来（工单 #1657）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        second = _actions(result, 2)
        assert second["call-fail"].receipt.ok is True
        assert second["call-fail"].facts == ["失败"]
        assert second["call-timeout"].facts == ["超时", "失败"]
        assert second["call-write"].facts == ["改了文件"]
        # 摘要相同、没有两个快照、成功的动作都不标
        assert second["call-same"].facts == []
        assert second["call-c"].facts == []
        assert _actions(result, 1)["call-b"].facts == []
    finally:
        system.close()


def test_the_event_text_and_the_step_title_are_the_same_words(data_dir):
    # R2：工具开始与工具结果两种事件的文字，与 run.steps 的动作行标题逐字相同（同一个函数算，工单 #1657）
    system, application, run_id, steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        actions = {action.action_id: action for step in result.steps for action in step.actions}
        for key, action_id in (("list_files", "call-a"), ("read_file", "call-b")):
            started, called = steps[key]
            assert event_label(started.type, started.payload) == actions[action_id].title
            assert event_label(called.type, called.payload) == actions[action_id].title
        assert actions["call-a"].title == "列出文件"
    finally:
        system.close()


def test_a_text_only_step_is_one_row_named_by_its_text(data_dir):
    # R3：只有文字、没有动作的一步只有一行：这段文字的开头，来源记作者；有动作的一步不另给标题（工单 #1657）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        text_only = _step(result.steps, 3)
        assert text_only.actions == []
        assert (text_only.title, text_only.title_source) == ("重试以后的文字", "作者")
        # 有动作的两步由动作行说，不再另给一行
        assert (_step(result.steps, 1).title, _step(result.steps, 1).title_source) == (None, None)
        assert (_step(result.steps, 2).title, _step(result.steps, 2).title_source) == (None, None)
    finally:
        system.close()


def test_activations_carry_the_session_and_the_cycle(data_dir):
    # R3：每一次激活带它所在的会话编号与第几轮（工单 #1657）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        earlier, current = result.activations
        assert (earlier.session_id, earlier.cycle) == (SESSION, 1)
        assert (current.session_id, current.cycle) == (SESSION, 2)
    finally:
        system.close()


def test_an_ask_branch_activation_is_found_by_the_ask_id(data_dir):
    # R3：询问分支的激活，会话编号就是 run.asks 的询问编号，由它找到那次激活；分支不算轮次（工单 #1657）
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("询问分支", "核对激活的会话编号")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "分支")
    _append(system, run_id, EventType.ASK_STARTED, payload={
        "requester": PRODUCT, "recipient": QUALITY, "question": "能放行吗", "branch_session_id": "ask-1"})
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, department=QUALITY, session_id="ask-1",
            payload={"activation_id": "act-ask"})
    _append(system, run_id, EventType.ACTIVATION_FINISHED, department=QUALITY,
            payload={"activation_id": "act-ask"})
    application = Application(system)
    try:
        asks = application.query("run.asks", RunAsks(run_id=run_id)).data.asks
        assert [ask.id for ask in asks] == ["ask-1"]
        result = _query(application, RunSteps(run_id=run_id, department=QUALITY))
        assert [activation.session_id for activation in result.activations] == [asks[0].id]
        assert result.activations[0].cycle is None
    finally:
        system.close()


def test_every_step_carries_its_attempt_ids_including_the_discarded_one(data_dir):
    # R3：每一步带它的调用尝试编号，含被丢弃的（工单 #1657）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert _step(result.steps, 1).attempt_ids == ["att-1"]
        # 第三步的第一次尝试失败、被丢弃，编号照样在这一步里
        assert _step(result.steps, 3).attempt_ids == ["att-3a", "att-3b"]
        assert _step(result.steps, 3).discarded_attempts == 1
        assert _step(result.steps, 5).attempt_ids == ["att-5"]
    finally:
        system.close()


def test_a_step_attempt_id_opens_the_attempt(data_dir):
    # R3：每一步的调用尝试编号能打开 run.attempt（工单 #1657）
    system = LoopSystem.for_testing(data_dir, FakeAdapter([FakeTurn(proposal=product_spec())]))
    project_id = system.projects.register("尝试编号", "核对 run.steps 与 run.attempt 对得上")
    work_item_id, run_id = system.projects.start_work_item(project_id, "一次激活")
    system.activate_once(run_id)
    application = Application(system)
    try:
        steps = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        attempt_ids = [attempt_id for step in steps.steps for attempt_id in step.attempt_ids]
        assert attempt_ids
        recorded = application.query("project.attempts", ProjectAttempts(
            project_id=project_id, work_item=work_item_id)).data.attempts
        assert {row.attempt_id for row in recorded} <= set(attempt_ids)
        for attempt_id in attempt_ids:
            detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=attempt_id)).data
            assert detail.attempt["id"] == attempt_id
        # 真实的一次激活：会话编号与第几轮从激活事件读出
        activation = steps.activations[-1]
        assert activation.session_id and activation.cycle == 1
    finally:
        system.close()


def test_reading_old_events_gives_titles_and_leaves_the_events_alone(data_dir):
    # R2：老事件（没有一句话、没有更新计划）照样给标题；查询不改事件，读两次结果一样（工单 #1657）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        before = len(system.store.list_events(run_id))
        first = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        second = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert first == second
        assert len(system.store.list_events(run_id)) == before
        # 运行命令那一句由系统写：老事件没有角色写的一句话时写「运行命令：<命令开头>」
        assert _actions(first, 2)["call-fail"].title == "运行命令：false"
    finally:
        system.close()


def test_a_long_activation_is_read_within_a_second(data_dir):
    # 读数（验收第 8 条）：93 步、52 条推理、93 个动作的一次读取。超时说明本机负载或查询需要分页。
    # 这一条同时守着动作标题与回执事实的代价：每个动作都要查一次工具定义、解析一条回执（工单 #1657）。
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("长激活", "核对读取耗时")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "93 步")
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, session_id=SESSION,
            payload={"activation_id": ACTIVATION, "cycle": 1})
    for step_id in range(1, 94):
        _request(system, run_id, step_id=step_id, root_step_id=step_id, attempt=1,
                 attempt_id="att-%d" % step_id)
        if step_id <= 52:
            _reasoning(system, run_id, step_id=step_id, attempt_id="att-%d" % step_id,
                       item=_chat_reasoning("第 %d 步的推理：先看代码，再动手。" % step_id))
        _tool(system, run_id, action_id="call-%d" % step_id, name="bash", step_id=step_id,
              args={"command": "make check"}, ok=True, exit_code=0, status="ok")
    _append(system, run_id, EventType.ACTIVATION_FINISHED, payload={"activation_id": ACTIVATION})
    application = Application(system)
    try:
        started = time.monotonic()
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        elapsed = time.monotonic() - started
        assert len(result.steps) == 93
        assert sum(len(step.reasoning) for step in result.steps) == 52
        assert sum(len(step.actions) for step in result.steps) == 93
        # 读数写进交付说明；本机应远低于 1 秒，超过时这里失败并写明读数
        print("run.steps 在 93 步、52 条推理、93 个动作上的读数：%.3f 秒" % elapsed)
        assert elapsed < 1.0, "run.steps 用时 %.3f 秒" % elapsed
    finally:
        system.close()


# ---------------------------------------------------------------------------
# 工单 #1661：任务列表与每个动作的所属任务


def _task_rows(result):
    return [(task.number, task.content, task.status) for task in result.tasks]


def test_a_round_carries_its_tasks_and_every_action_belongs_to_one(data_dir):
    # R3（验收第 1、2 条）：一轮里更新三次计划，动作归到当时进行中的条目；同一句话的几段动作归同一条；
    # 后来的计划里没有了的写「已从计划里去掉」；从没进行过的排在最后
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert _task_rows(result) == [(1, "先看一遍现有实现", "完成"),
                                      (2, "跑检查", "进行中"),
                                      (3, "写交付说明", "已从计划里去掉")]
        # 第一步与第二步的动作各归当时进行中的那一条；第三、五步没有新计划，仍归第二步定下的「跑检查」
        assert {action.action_id: action.task for step in result.steps
                for action in step.actions} == {
            "call-a": 1, "call-b": 1,
            "call-c": 2, "call-fail": 2, "call-timeout": 2, "call-write": 2, "call-same": 2,
            "call-bg": 2,
        }
        # 没有归到步骤的动作也带所属任务
        assert [action.task for action in result.unassigned_actions] == [2]
    finally:
        system.close()


def test_the_plan_update_is_not_a_row_and_its_call_is_still_in_the_events(data_dir):
    # R3（验收第 5 条）：更新计划自己不单独成行，它的原始调用仍在事件里，事件详情读得到
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert all(action.tool != "update_plan" for step in result.steps for action in step.actions)
        assert all(action.tool != "update_plan" for action in result.unassigned_actions)
        planned = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.TOOL_CALLED
                   and (event.payload or {}).get("name") == "update_plan"
                   and (event.payload or {}).get("activation_id") == ACTIVATION]
        assert len(planned) == 3
        detail = application.query("event.detail", EventDetail(event_id=planned[0].event_id)).data
        assert detail.event["payload"]["args"]["plan"][0]["content"] == "先看一遍现有实现"
    finally:
        system.close()


def test_a_round_without_a_plan_has_no_tasks_and_no_action_owners(data_dir):
    # R3（验收第 5 条）：没有计划的轮次任务列表为空、动作不带所属任务（页面平铺）
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        engineering = _query(application, RunSteps(run_id=run_id, department=ENGINEERING))
        assert engineering.tasks == []
        assert [action.task for step in engineering.steps for action in step.actions] == [None]
    finally:
        system.close()


def test_a_plan_only_groups_the_round_it_was_written_in(data_dir):
    # R3（验收第 4 条）：上一轮的计划不影响这一轮；问上一轮时看到的是它自己的任务
    system, application, run_id, _steps = steps_fixture(data_dir)
    try:
        earlier = _query(application, RunSteps(run_id=run_id, department=PRODUCT,
                                               activation_id=EARLIER_ACTIVATION))
        assert _task_rows(earlier) == [(1, "更早那次的做法", "进行中")]
        assert [action.task for step in earlier.steps for action in step.actions] == [1]
        current = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert "更早那次的做法" not in [task.content for task in current.tasks]
    finally:
        system.close()


def test_an_action_without_an_in_progress_entry_is_unnumbered(data_dir):
    # R3（验收第 3 条）：没有进行中条目时的动作不编号，任务列表照旧给出那几条任务
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("没有进行中", "核对不编号的动作")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "一条")
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, session_id=SESSION,
            payload={"activation_id": ACTIVATION, "cycle": 1})
    _request(system, run_id, step_id=1, root_step_id=1, attempt=1, attempt_id="att-1")
    _plan_call(system, run_id, action_id="plan-1", step_id=1,
               entries=[{"content": "写代码", "status": "completed"}])
    _tool(system, run_id, action_id="call-a", name="read_file", step_id=1)
    _append(system, run_id, EventType.ACTIVATION_FINISHED, payload={"activation_id": ACTIVATION})
    application = Application(system)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert _task_rows(result) == [(1, "写代码", "完成")]
        assert [action.task for action in result.steps[0].actions] == [None]
    finally:
        system.close()


def test_a_rejected_plan_is_not_a_plan_and_not_a_row(data_dir):
    # R3（自定的边界）：格式错误的更新计划是工具结果里的错误，不当成计划，分组仍按上一份已接受的计划；
    # 它自己也不单独成行
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("格式错误", "核对被拒绝的计划")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "一条")
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, session_id=SESSION,
            payload={"activation_id": ACTIVATION, "cycle": 1})
    _request(system, run_id, step_id=1, root_step_id=1, attempt=1, attempt_id="att-1")
    _plan_call(system, run_id, action_id="plan-1", step_id=1,
               entries=[{"content": "写代码", "status": "in_progress"}])
    _tool(system, run_id, action_id="call-a", name="read_file", step_id=1)
    _request(system, run_id, step_id=2, root_step_id=2, attempt=1, attempt_id="att-2")
    _plan_call(system, run_id, action_id="plan-2", step_id=2, ok=False,
               entries=[{"content": "写代码", "status": "doing"}])
    _tool(system, run_id, action_id="call-b", name="read_file", step_id=2)
    _append(system, run_id, EventType.ACTIVATION_FINISHED, payload={"activation_id": ACTIVATION})
    application = Application(system)
    try:
        result = _query(application, RunSteps(run_id=run_id, department=PRODUCT))
        assert _task_rows(result) == [(1, "写代码", "进行中")]
        assert [action.task for step in result.steps for action in step.actions] == [1, 1]
    finally:
        system.close()

def test_a_plan_in_an_ask_branch_groups_only_that_branch(data_dir):
    # R3（验收第 4 条）：询问分支的计划只作用于这个分支；主线那一轮的计划不影响它
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("询问分支的计划", "核对分组的范围")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "分支")
    _append(system, run_id, EventType.ASK_STARTED, payload={
        "requester": PRODUCT, "recipient": QUALITY, "question": "能放行吗", "branch_session_id": "ask-1"})
    # 主线这一轮：工程的一次激活，写了一份自己的计划
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, department=ENGINEERING, session_id=SESSION,
            payload={"activation_id": ENGINEERING_ACTIVATION, "cycle": 1})
    _plan_call(system, run_id, department=ENGINEERING, activation=ENGINEERING_ACTIVATION,
               action_id="plan-main", step_id=1,
               entries=[{"content": "主线那一轮的事", "status": "in_progress"}])
    _append(system, run_id, EventType.ACTIVATION_FINISHED, department=ENGINEERING,
            payload={"activation_id": ENGINEERING_ACTIVATION})
    # 询问分支是质检的一次激活：计划与动作都写在这个分支里
    _append(system, run_id, EventType.DEPARTMENT_ACTIVATED, department=QUALITY, session_id="ask-1",
            payload={"activation_id": "act-ask"})
    _plan_call(system, run_id, department=QUALITY, activation="act-ask", action_id="plan-ask",
               step_id=1, entries=[{"content": "回答这个询问", "status": "in_progress"}])
    _tool(system, run_id, department=QUALITY, activation="act-ask", action_id="call-ask",
          name="answer", step_id=1, args={"answer": "可以"})
    _append(system, run_id, EventType.ACTIVATION_FINISHED, department=QUALITY,
            payload={"activation_id": "act-ask"})
    application = Application(system)
    try:
        branch = _query(application, RunSteps(run_id=run_id, department=QUALITY,
                                              activation_id="act-ask"))
        assert [task.content for task in branch.tasks] == ["回答这个询问"]
        assert [action.task for action in branch.unassigned_actions] == [1]
        main = _query(application, RunSteps(run_id=run_id, department=ENGINEERING))
        assert [task.content for task in main.tasks] == ["主线那一轮的事"]
    finally:
        system.close()

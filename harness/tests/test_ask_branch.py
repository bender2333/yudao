import json
from pathlib import Path
from typing import Any

import pytest

from harness.adapters.fake import FakeAdapter, prompt_part
from harness.minimal_projection import fold_events
from harness.models import EventType
from harness.proposals import answer_turn, ask_turn, delivery_turn, product_spec, review_turn
from harness.providers.call import ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.helpers import quality_turns
from harness.tests.helpers import adjudication_view, work_basis
from harness.tightening import WATCHED_OUTPUTS


def test_quality_asks_the_product_and_the_answer_revises_the_prd(tmp_path: Path):
    # 工单 #555：质检的结论只有缺陷记录与放行，要求有问题时质检询问产品，
    # 产品在回答里修订 PRD；质检对旧交付的放行被拒绝（交付依据的 PRD 版本过期，#471）
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            ask_turn(recipient="product", question="验收标准漏了空输入，请修订 PRD。"),
            review_turn("release", "the delivery passed the criterion the quality had"),
        ],
        "product:ask": [answer_turn(
            answer="已补上空输入的验收标准。",
            requirements=["print the given argument to stdout"],
            acceptance=["running the program with a word prints that word",
                        "empty input prints a blank line"],
            change_record={
                "changed": ["empty input prints a blank line"],
                "retained": ["running the program with a word prints that word"],
                "retired": [], "rationale": "The acceptance criteria missed the empty input."})],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # 产品提交初始 PRD
    system.activate_once(run_id)  # 工程交付
    projection = system.activate_once(run_id)  # 质检询问产品，产品在回答里修订 PRD，质检的放行被拒绝

    # 产品在回答里修订了 PRD，修订版是第 2 版
    assert projection.product_spec is not None
    assert projection.product_spec.revision == 2
    # 询问与回答各有一条事件，修订由产品的回答带来
    events = system.store.list_events(run_id)
    assert any(event.type == EventType.ASK_STARTED for event in events)
    answered = [event for event in events if event.type == EventType.ASK_ANSWERED]
    assert len(answered) == 1
    assert answered[0].payload["with_spec_revision"] is True
    assert answered[0].payload["revision"] == 2
    # 质检对旧交付的放行被拒绝：交付依据的 PRD 版本过期
    assert any(
        error["field"] == "delivery_spec"
        for item in projection.rejections
        for error in item["errors"]
    )


def _call(identity: str, name: str, **args: Any) -> dict[str, Any]:
    return {
        "id": identity,
        "call_id": identity,
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args),
    }


def test_ask_answer_with_spec_revision_continuous_work(tmp_path: Path):
    # AC1: 工程询问产品，产品在分支里修订 PRD 并回答，工程收到回答与 PRD 新版本，
    # 接着写入并提交交付，质检放行；工程这一轮工作没有因为询问或 PRD 变化而结束。
    # 假模型按会话给出脚本
    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Should output be uppercase?",
                      background="Clarification needed", expected="Specification update"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        ],
        "product:ask": [
            lambda call: ModelResponse(output=[
                _call("ans-1", "answer",
                      answer="Yes, print in uppercase.",
                      goal="build an echo CLI",
                      requirements=["print the given argument in uppercase to stdout"],
                      acceptance_criteria=["running the program with a word prints that word in uppercase"],
                      requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]}],
                      change_record={
                          "changed": ["print the given argument in uppercase to stdout"],
                          "retained": ["single file implementation"],
                          "retired": [],
                          "rationale": "Clarification revision.",
                      },
                      basis_product_spec_hash=json.loads(
                          next(item["content"] for item in call.input_items
                               if "[current_product_spec]" in item.get("content", ""))
                          .split("[current_product_spec]\n")[1]
                          .split("\n\n")[0]
                      )["content_hash"]),
            ]),
        ],
        "quality": quality_turns("release", "valid uppercase implementation"),
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.status == "done"
    assert projection.status == "done"
    assert projection.product_spec is not None
    assert projection.product_spec.revision == 2

    events = system.store.list_events(run_id)
    event_types = [event.type for event in events]
    assert EventType.ASK_STARTED in event_types
    assert EventType.ASK_ANSWERED in event_types
    assert EventType.SPEC_ACCEPTED in event_types
    assert EventType.DELIVERY_ACCEPTED in event_types
    assert EventType.QA_SUBMITTED in event_types

    # 工程部门仅激活了一次（没有因为 ask 或 PRD 变化而结束本次激活）
    eng_activations = [e for e in events if e.type == EventType.DEPARTMENT_ACTIVATED and e.department == "engineering"]
    assert len(eng_activations) == 1


def test_ask_branch_history_isolation(tmp_path: Path):
    # AC2: 分支结束后产品的历史只多一条问题与回答的记录；产品以后的请求中没有分支里的读取过程；
    # 分支的请求中包含产品到开出分支时为止的历史。
    branch_call_captured = []

    def product_branch_turn(call):
        branch_call_captured.append(call)
        return ModelResponse(output=[
            _call("ans-1", "answer", answer="Clarification given without spec change."),
        ])

    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Clarify something?",
                      background="Bg", expected="Exp"),
            ]),
            delivery_turn(),
        ],
        "product:ask": [product_branch_turn],
        "quality": quality_turns("release", "ok"),
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")

    # 激活产品一次
    system.activate_once(run_id)
    events_after_p1 = system.store.list_events(run_id)
    hist_p1 = system.orchestrator.assembly.department_history(events_after_p1, "product")
    assert len(hist_p1) >= 1

    # 运行到结束
    system.run_until_stop(run_id)
    assert len(branch_call_captured) == 1
    branch_call = branch_call_captured[0]

    # 分支的请求中包含产品到开出分支时为止的历史
    # branch_call.input_items 中包含 hist_p1 的全部 item
    assert branch_call.input_items[1:1 + len(hist_p1)] == [r["item"] for r in hist_p1]

    # 分支结束后产品的历史只多一条问题与回答的记录
    events_final = system.store.list_events(run_id)
    hist_final = system.orchestrator.assembly.department_history(events_final, "product")
    assert len(hist_final) == len(hist_p1) + 1
    assert hist_final[-1]["type"] == EventType.ASK_ANSWERED


def test_ask_branch_tool_permissions_rejected(tmp_path: Path):
    # AC3: 工程或质检的分支试图写入运行工作区、提交交付、缺陷记录或放行，被工具许可拒绝。
    from harness.adjudication import tool_permission, facts_query, WorkBasis
    from harness.models import RunProjection
    from harness.actions import WorkspaceFacts

    projection = RunProjection(
        run_id="run_test",
        status="running",
        ask_stack=[{"requester": "product", "recipient": "engineering", "branch_session_id": "ses_ask_eng"}],
    )
    basis = work_basis(projection, "engineering")

    # 工程分支试图写入
    perm_write = tool_permission(adjudication_view(projection),
        {"name": "write_file", "args": {"path": "src/new.py", "content": "x"}},
        department="engineering",
        session_id="ses_ask_eng",
        basis=basis,
        aborted=False,
        facts=WorkspaceFacts(),
     tightening=WATCHED_OUTPUTS)
    assert not perm_write.allowed

    # 工程分支试图提交交付
    perm_del = tool_permission(adjudication_view(projection),
        {"name": "submit_delivery", "args": {"summary": "done", "check_names": []}},
        department="engineering",
        session_id="ses_ask_eng",
        basis=basis,
        aborted=False,
        facts=WorkspaceFacts(),
     tightening=WATCHED_OUTPUTS)
    assert not perm_del.allowed

    # 质检分支试图提交放行或缺陷记录
    qa_projection = RunProjection(
        run_id="run_test",
        status="running",
        ask_stack=[{"requester": "engineering", "recipient": "quality", "branch_session_id": "ses_ask_qa"}],
    )
    qa_basis = work_basis(qa_projection, "quality")
    perm_rev = tool_permission(adjudication_view(qa_projection),
        {"name": "submit_review", "args": {"verdict": "release", "rationale": "ok", "checks": []}},
        department="quality",
        session_id="ses_ask_qa",
        basis=qa_basis,
        aborted=False,
        facts=WorkspaceFacts(),
     tightening=WATCHED_OUTPUTS)
    assert not perm_rev.allowed

    # 产品分支试图执行除 answer 之外的工具被拒绝
    prod_projection = RunProjection(
        run_id="run_test",
        status="running",
        ask_stack=[{"requester": "engineering", "recipient": "product", "branch_session_id": "ses_ask_pro"}],
    )
    prod_basis = work_basis(prod_projection, "product")
    perm_prod_read = tool_permission(adjudication_view(prod_projection),
        {"name": "read_file", "args": {"path": "src/echo.py"}},
        department="product",
        session_id="ses_ask_pro",
        basis=prod_basis,
        aborted=False,
        facts=WorkspaceFacts(),
     tightening=WATCHED_OUTPUTS)
    assert not perm_prod_read.allowed


def test_ask_answer_requirements_only_rejected_and_cannot_lose_acceptance_criteria(tmp_path: Path):
    # 1.1: 只带 requirements 的回答被拒收（不能让 rev2 丢 acceptance_criteria），重答带完整规格后接纳
    def product_branch_steps(call):
        current_spec = json.loads(
            next(item["content"] for item in call.input_items
                 if "[current_product_spec]" in item.get("content", ""))
            .split("[current_product_spec]\n")[1]
            .split("\n\n")[0]
        )
        # 检查是否收到上一步 answer 被拒的错误回执
        has_err = any(
            item.get("type") == "function_call_output" and "ans-err" in item.get("call_id", "")
            for item in call.input_items
        )
        if not has_err:
            # 第一步：只带 requirements（缺失 goal, acceptance_criteria, change_record 等），绕过规则应被拒
            return ModelResponse(output=[
                _call("ans-err", "answer",
                      answer="Yes, print in uppercase.",
                      requirements=["print the given argument in uppercase to stdout"],
                      basis_product_spec_hash=current_spec["content_hash"]),
            ])
        # 第二步：收到错误后提供完整有效的修订规格
        return ModelResponse(output=[
            _call("ans-ok", "answer",
                  answer="Yes, print in uppercase.",
                  goal="build an echo CLI",
                  requirements=["print the given argument in uppercase to stdout"],
                  acceptance_criteria=["running the program with a word prints that word in uppercase"],
                  requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]}],
                  change_record={
                      "changed": ["print the given argument in uppercase to stdout"],
                      "retained": ["single file implementation"],
                      "retired": [],
                      "rationale": "Clarification revision.",
                  },
                  basis_product_spec_hash=current_spec["content_hash"]),
        ])

    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Should output be uppercase?",
                      background="Clarification needed", expected="Specification update"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        ],
        "product:ask": [product_branch_steps, product_branch_steps],
        "quality": quality_turns("release", "valid uppercase implementation"),
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.status == "done"
    assert projection.product_spec.revision == 2
    assert projection.product_spec.acceptance_criteria == ["running the program with a word prints that word in uppercase"]

    events = system.store.list_events(run_id)
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALLED and e.payload.get("name") == "answer"]
    # 第一次 answer 调用失败并带有字段错误
    err_calls = [e for e in tool_calls if e.payload.get("id") == "ans-err"]
    assert len(err_calls) == 1
    assert err_calls[0].payload["ok"] is False
    assert "acceptance_criteria" in (err_calls[0].payload.get("error") or "")
    # 第二次 answer 成功
    ok_calls = [e for e in tool_calls if e.payload.get("id") == "ans-ok"]
    assert len(ok_calls) == 1
    assert ok_calls[0].payload["ok"] is True


def test_ask_answer_echoing_only_basis_hash_creates_no_revision(tmp_path: Path):
    # 1.1: 只回显 basis_product_spec_hash（不带修订字段）不出新版本
    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Should output be uppercase?",
                      background="Clarification needed", expected="Specification update"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [
            lambda call: ModelResponse(output=[
                _call("ans-1", "answer",
                      answer="No, keep existing behavior unchanged.",
                      basis_product_spec_hash=json.loads(
                          next(item["content"] for item in call.input_items
                               if "[current_product_spec]" in item.get("content", ""))
                          .split("[current_product_spec]\n")[1]
                          .split("\n\n")[0]
                      )["content_hash"]),
            ]),
        ],
        "quality": quality_turns("release", "valid echo implementation"),
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.status == "done"
    # 没有出新版本，仍然是 rev 1
    assert projection.product_spec.revision == 1
    assert len(projection.product_spec.requirements) >= 1
    assert len(projection.product_spec.acceptance_criteria) >= 1

    events = system.store.list_events(run_id)
    # SPEC_ACCEPTED 只有初始的 1 次
    spec_accepted_events = [e for e in events if e.type == EventType.SPEC_ACCEPTED]
    assert len(spec_accepted_events) == 1
    # ASK_ANSWERED 标明没有规格修订
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    assert ask_answered_events[0].payload["with_spec_revision"] is False
    assert ask_answered_events[0].payload["revision"] is None


def test_ask_answered_payload_parties_and_status(tmp_path: Path):
    # AC3: ask_answered 标明 requester, recipient, status="answered", reason=""
    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Clarify something?",
                      background="Bg", expected="Exp"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [
            lambda call: ModelResponse(output=[
                _call("ans-1", "answer", answer="Clarification given."),
            ]),
        ],
        "quality": quality_turns("release", "ok"),
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    payload = ask_answered_events[0].payload
    assert payload["requester"] == "engineering"
    assert payload["recipient"] == "product"
    assert payload["status"] == "answered"
    assert payload["reason"] == ""
    assert payload["answer"] == "Clarification given."


def test_ask_branch_exhausted_ends_with_unable_and_usage_charged(tmp_path: Path):
    # AC1 & AC4: 分支达到上限以 unable 结束，提问方的工具结果写明原因；分支的用量计入提问方
    from harness.engine import StepLimits

    def product_branch_invalid(call):
        return ModelResponse(output=[
            _call("ans-err", "answer", answer=""),
        ])

    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Clarify something?",
                      background="Bg", expected="Exp"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [product_branch_invalid],
        "quality": quality_turns("release", "ok"),
    }
    adapter = FakeAdapter(scripts)
    # 提问方上限 4 步，被询问部门声明上限 1 步
    step_limits = StepLimits(max_model_steps=4, department_max_model_steps={"product": 1})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=step_limits)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    payload = ask_answered_events[0].payload
    assert payload["requester"] == "engineering"
    assert payload["recipient"] == "product"
    assert payload["status"] == "unable"
    assert payload["answer"] == ""
    assert "step limit" in payload["reason"]

    # 提问方的工具结果写明原因
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALLED and e.payload.get("name") == "ask"]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["ok"] is False
    assert "step limit" in (tool_calls[0].payload.get("error") or "")

    # 提问方投影的已用量包含分支的步骤：分支的模型请求计入提问方的用量。
    # 激活结束时记下的 model_steps 是这个 run 累计的模型请求数，同时运行的会话各自写自己的，
    # 这个数因此取决于会话的先后（工单 #557）。这里断言的是结果：分支的步骤计入提问方，
    # 提问方自己只用了自己的两步（发起询问与提交交付）。
    finished_events = [e for e in events if e.type == EventType.ACTIVATION_FINISHED and e.department == "engineering"]
    asker_requests = [e for e in events if e.type == EventType.MODEL_REQUESTED
                      and e.department == "engineering" and not (e.session_id or "").startswith("ses_ask_")]
    branch_requests = [e for e in events if e.type == EventType.MODEL_REQUESTED
                       and (e.session_id or "").startswith("ses_ask_")]
    assert len(asker_requests) == 2 and len(branch_requests) == 1
    assert max(e.payload["model_steps"] for e in finished_events) >= len(asker_requests) + len(branch_requests)
    assert system.project(run_id).status == "done"

def test_ask_branch_exhausted_by_requester_remaining_steps_ends_with_unable(tmp_path: Path):
    # 提问方剩余可用步数生效：声明 4 步、提问方剩余 1 步时，分支上限取 1 步；两步才回答的分支以 unable 结束
    from harness.engine import StepLimits

    branch_steps_called = 0

    def product_branch_two_steps(call):
        nonlocal branch_steps_called
        branch_steps_called += 1
        if branch_steps_called == 1:
            return ModelResponse(output=[_call("ans-1", "answer", answer="")])
        return ModelResponse(output=[_call("ans-2", "answer", answer="valid answer")])

    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Clarify something?",
                      background="Bg", expected="Exp"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [product_branch_two_steps],
        "quality": quality_turns("release", "ok"),
    }
    adapter = FakeAdapter(scripts)
    # 提问方上限 2 步（发起 ask 消耗 1 步，剩余 1 步），被询问部门声明上限 4 步
    step_limits = StepLimits(max_model_steps=2, department_max_model_steps={"product": 4})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=step_limits)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    payload = ask_answered_events[0].payload
    assert payload["requester"] == "engineering"
    assert payload["recipient"] == "product"
    assert payload["status"] == "unable"
    assert "step limit" in payload["reason"]

    tool_calls = [e for e in events if e.type == EventType.TOOL_CALLED and e.payload.get("name") == "ask"]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["ok"] is False
    assert "step limit" in (tool_calls[0].payload.get("error") or "")
    assert system.project(run_id).status == "paused"
    assert system.project(run_id).stop_reason == "model_steps_exhausted"
    finished_events = [e for e in events if e.type == EventType.ACTIVATION_FINISHED and e.department == "engineering"]
    # 提问方的用量包含分支的步骤：分支的模型请求计入提问方。
    # 激活结束时记下的 model_steps 是这个 run 累计的模型请求数，同时运行的会话各自写自己的，
    # 这个数因此取决于会话的先后（工单 #557）。这里断言的是结果：分支的步骤计入提问方。
    asker_requests = [e for e in events if e.type == EventType.MODEL_REQUESTED
                      and e.department == "engineering" and not (e.session_id or "").startswith("ses_ask_")]
    branch_requests = [e for e in events if e.type == EventType.MODEL_REQUESTED
                       and (e.session_id or "").startswith("ses_ask_")]
    assert len(asker_requests) == 1 and len(branch_requests) == 1
    assert max(e.payload["model_steps"] for e in finished_events) >= len(asker_requests) + len(branch_requests)

def test_ask_branch_resumes_across_system_restart(tmp_path: Path):
    # AC2 & AC5: 分支进行中重新启动 Yudao，分支继续，回答交回提问方，事项运行到放行
    import sys
    from harness.proposals import delivery
    from harness.tests import process_kill as killed

    data_dir = tmp_path / "data"
    # 脚本按会话给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [
            {"proposal": {"kind": "product_spec", "goal": "build an echo CLI",
                          "requirements": ["echo input"], "acceptance_criteria": ["prints arg"],
                          "requirement_mapping": [{"requirement": 1, "criteria": ["AC1"]}]}},
        ],
        "engineering": [
            {"output": [
                _call("ask-1", "ask", recipient="product", question="Is lowercase ok?",
                      background="Bg", expected="Exp"),
            ]},
        ],
        "quality": [{"proposal": {"kind": "quality_auto", "verdict": "release",
                                  "rationale": "checks passed on the current snapshot"}}],
    }
    checks = {"smoke": {"command": f"\"{sys.executable.replace(chr(92), chr(47))}\" -c \"print('smoke ok')\""}}
    tail = {
        "product:ask": [
            {"output": [
                _call("ans-1", "answer", answer="Yes, lowercase is ok."),
            ]},
        ],
        "engineering": [
            {"proposal": delivery(check_names=["smoke"]),
             "writes": {"src/echo.py": "import sys\nprint(sys.argv[1].lower())\n"},
             "checks": checks},
        ],
        "quality": [{"proposal": {"kind": "quality_auto", "verdict": "release",
                                  "rationale": "checks passed on the current snapshot"}}],
    }

    with killed.interrupted(data_dir, script, hold_after=EventType.ASK_STARTED, tail=tail) as run:
        events_after = run.after.store.list_events(run.run_id)
        assert len([e for e in events_after if e.type == EventType.TOOL_STARTED and (e.payload or {}).get("id") == "ask-1"]) == 1
        ask_started_events = [e for e in events_after if e.type == EventType.ASK_STARTED]
        assert len(ask_started_events) == 1
        ask_answered_events = [e for e in events_after if e.type == EventType.ASK_ANSWERED]
        assert len(ask_answered_events) == 1
        assert ask_started_events[0].payload["branch_session_id"] == ask_answered_events[0].session_id
        assert ask_answered_events[0].payload["status"] == "answered"
        assert ask_answered_events[0].payload["answer"] == "Yes, lowercase is ok."
        assert run.after.project(run.run_id).status == "done"


def test_ask_branch_finished_restart_retains_accumulated_elapsed_time(tmp_path: Path):
    # 分支结束 → 重启 → run 已用时间恢复包含分支时段，各激活结束事件 elapsed_ms 单调不减
    import sys
    from harness.tests import process_kill as killed
    from harness.proposals import delivery

    data_dir = tmp_path / "data"
    # 脚本按会话给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [
            {"proposal": {"kind": "product_spec", "goal": "build echo", "requirements": ["echo"],
                          "acceptance_criteria": ["ok"],
                          "requirement_mapping": [{"requirement": 1, "criteria": ["AC1"]}]}},
        ],
        "engineering": [
            {"output": [_call("ask-1", "ask", recipient="product", question="q?", background="b", expected="e")]},
        ],
        "quality": [{"proposal": {"kind": "quality_auto", "verdict": "release", "rationale": "ok"}}],
    }
    tail = {
        "product:ask": [
            {"output": [_call("ans-1", "answer", answer="ans")]},
        ],
        "engineering": [
            {"proposal": delivery(check_names=["smoke"]),
             "writes": {"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
             "checks": {"smoke": {"command": f"\"{sys.executable.replace(chr(92), chr(47))}\" -c \"print('smoke ok')\""}}},
        ],
        "quality": [{"proposal": {"kind": "quality_auto", "verdict": "release", "rationale": "ok"}}],
    }

    with killed.interrupted(data_dir, script, hold_after="tool_called", hold_action="ask-1", tail=tail) as run:
        branch_finished = [
            e for e in run.before_events
            if e.type == EventType.ACTIVATION_FINISHED and (e.session_id or "").startswith("ses_ask_")
        ]
        assert len(branch_finished) == 1
        branch_elapsed = branch_finished[0].payload.get("elapsed_ms", 0)
        assert branch_elapsed > 0

        after_events = run.after.store.list_events(run.run_id)
        # 重启恢复后的 run 已用时间包含分支时段：已用时间读最小投影里已结算的那一部分（S1e 工单 #1015）
        assert fold_events(after_events).used.settled_ms >= branch_elapsed
        elapsed_list = [e.payload["elapsed_ms"] for e in after_events if e.type == EventType.ACTIVATION_FINISHED]
        # 各激活结束事件记下的已用时间单调不减：同时运行的会话各自记下自己结束时刻的累计值（工单 #557）
        assert all(x <= y for x, y in zip(elapsed_list, elapsed_list[1:]))
        assert {event.department for event in after_events
                if event.type == EventType.ACTIVATION_FINISHED} == {"product", "engineering", "quality"}
        assert run.after.project(run.run_id).status == "done"


def test_ask_branch_no_tool_call_ends_with_unable(tmp_path: Path):
    # AC1 & AC2: 模型反复不提交回答（连续只回复文字），分支以 unable 结束，提问方接着工作
    from harness.definitions import DEFINITIONS
    limit = DEFINITIONS.rule_value("tool_call_required_limit")

    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Clarify something?",
                      background="Bg", expected="Exp"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [
            ModelResponse(output=[{"id": f"msg-{i}", "type": "message", "role": "assistant",
                                  "content": [{"type": "output_text", "text": "Just plain text."}]}])
            for i in range(limit + 1)
        ],
        "quality": quality_turns("release", "ok"),
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    payload = ask_answered_events[0].payload
    assert payload["status"] == "unable"
    assert "without calling a tool" in payload["reason"]

    tool_calls = [e for e in events if e.type == EventType.TOOL_CALLED and e.payload.get("name") == "ask"]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["ok"] is False
    assert "without calling a tool" in (tool_calls[0].payload.get("error") or "")
    assert system.project(run_id).status == "done"


def test_ask_branch_exhausted_by_department_time_limit_ends_with_unable(tmp_path: Path):
    # 分支声明时间耗尽：以 unable 结束，写明时间上限原因，提问方接着工作
    import time
    from harness.engine import StepLimits

    def product_branch_slow(call):
        time.sleep(0.4)
        return ModelResponse(output=[_call("ans-1", "answer", answer="too late")])

    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Clarify something?",
                      background="Bg", expected="Exp"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [product_branch_slow],
        "quality": quality_turns("release", "ok"),
    }
    adapter = FakeAdapter(scripts)
    step_limits = StepLimits(department_max_time_sec={"product": 0.2})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=step_limits)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    payload = ask_answered_events[0].payload
    assert payload["status"] == "unable"
    assert "time limit" in payload["reason"].lower()

    tool_calls = [e for e in events if e.type == EventType.TOOL_CALLED and e.payload.get("name") == "ask"]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["ok"] is False
    assert "time limit" in (tool_calls[0].payload.get("error") or "").lower()
    assert system.project(run_id).status == "done"


def test_ask_branch_exhausted_by_run_time_limit_ends_with_unable(tmp_path: Path):
    # 事项运行时间在分支进行中用完：声明值（45s）大于剩余量（~10s），事项运行时间用完而以 unable 结束
    # 上限与分支的等待都要比运行机上准备这一段时间长（准备里有一次 Git 提交），否则上限在分支开始前就用完，
    # 询问没有被回答（工单 #557 以后同时运行，准备这一段更慢）
    import time
    from harness.engine import StepLimits

    def product_branch_slow(call):
        time.sleep(12)
        return ModelResponse(output=[_call("ans-1", "answer", answer="too late")])

    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Clarify something?",
                      background="Bg", expected="Exp"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [product_branch_slow],
        "quality": quality_turns("release", "ok"),
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(
        tmp_path,
        adapter,
        step_limits=StepLimits(department_max_time_sec={"product": 45.0}),
    )
    run_id = system.create_run("build echo", run_time_limit_sec=10)
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    payload = ask_answered_events[0].payload
    assert payload["status"] == "unable"
    assert "time limit" in payload["reason"].lower()
    assert system.project(run_id).stop_reason == "time_limit"



def test_two_branches_revise_the_prd_and_the_stale_one_sees_the_new_version(tmp_path: Path):
    # 验收第 5 条（工单 #559）：两个分支同时修订 PRD，后提交的一个因依据的版本过期被拒绝，并看到新版本。
    # 两条分支都开在产品上：一条由工程的询问开出，一条由质检的询问开出。后提交的那条按它开始时
    # 看到的版本提交，被拒绝以后按请求里的当前版本重新提交，PRD 的两个新版本因此各来自一条分支。
    state: dict[str, Any] = {}
    holder: dict[str, Any] = {}
    acceptance = ["running the program with a word prints that word in uppercase"]

    def current_spec(call: Any) -> dict[str, Any]:
        return json.loads(prompt_part(call, "current_product_spec"))

    def revision(call: Any, criteria: list[str], basis: str) -> Any:
        return answer_turn(
            answer="按澄清修订 PRD。",
            requirements=["print the given argument in uppercase to stdout"],
            acceptance=criteria,
            change_record={"changed": [criteria[-1]], "retained": [], "retired": [],
                           "rationale": "询问里澄清了要求。"},
            basis_product_spec_hash=basis)(call)

    def own_question(call: Any) -> str:
        # 这条分支回答的那一次询问：一个部门可以同时有几个分支，每条分支看自己的问题（工单 #559）
        for event in holder["system"].store.list_events(holder["run_id"]):
            if (event.type == EventType.ASK_STARTED
                    and (event.payload or {}).get("branch_session_id") == call.session_id):
                return str((event.payload or {}).get("question") or "")
        raise AssertionError("the branch has no ask of its own")

    def product_branch(call: Any) -> Any:
        state.setdefault("asked", {})[call.session_id] = json.loads(
            prompt_part(call, "pending_ask"))["question"]
        if "大写" in own_question(call):
            def engineering_branch(call: Any):
                # 先等另一条分支读到 PRD 的第 1 版：两个分支的读取同时进行
                for _ in range(600):
                    if state.get("quality_saw"):
                        break
                    yield ModelStreamEvent(kind="stream_event", id="evt-wait-engineering")
                return revision(call, acceptance, current_spec(call)["content_hash"])
            return engineering_branch(call)

        def quality_branch(call: Any):
            state["quality_attempts"] = state.get("quality_attempts", 0) + 1
            if state["quality_attempts"] == 1:
                state["quality_saw"] = current_spec(call)["content_hash"]
                # 等另一条分支的修订落地：这条分支依据的版本在这期间过期
                for _ in range(600):
                    projection = holder["system"].project(holder["run_id"])
                    if projection.product_spec is not None and projection.product_spec.revision >= 2:
                        break
                    yield ModelStreamEvent(kind="stream_event", id="evt-wait-quality")
                return revision(call, acceptance + ["empty input prints a blank line"], state["quality_saw"])
            # 被拒绝以后看到新版本：按请求里的当前版本重新提交
            holder["resubmitted_at"] = current_spec(call)["revision"]
            return revision(call, acceptance + ["empty input prints a blank line"],
                            current_spec(call)["content_hash"])
        return quality_branch(call)

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [ask_turn("product", "输出要不要大写？", call_id="ask-eng-1"),
                        delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"},
                                      checks={"smoke": {"command": "python -c \"print('smoke ok')\""}}),
                        delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"},
                                      checks={"smoke": {"command": "python -c \"print('smoke ok')\""}}),
                        delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"},
                                      checks={"smoke": {"command": "python -c \"print('smoke ok')\""}})],
        "quality": [ask_turn("product", "验收标准要补上空输入吗？", call_id="ask-qua-1"),
                    *quality_turns("release", "checks passed on the current snapshot",
                                   checks={"smoke": {"command": "python -c \"print('smoke ok')\""}})],
        "product:ask": [product_branch] * 20,
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    holder["system"] = system
    holder["run_id"] = run_id
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    # 两条分支各自看到自己的问题：一个部门同时有几个分支时，分支不串到别的询问上
    assert sorted(state["asked"].values()) == ["输出要不要大写？", "验收标准要补上空输入吗？"]
    # 产品的历史增加两条记录：两条分支各自结束，都得到回答
    answered = [event for event in events if event.type == EventType.ASK_ANSWERED]
    assert len(answered) == 2
    assert [event.payload["status"] for event in answered] == ["answered", "answered"]
    # 两条分支同时进行：两条分支的激活都在任何一条结束之前开始
    branch_starts = [event for event in events
                     if event.type == EventType.DEPARTMENT_ACTIVATED
                     and event.session_id.startswith("ses_ask_pro_")]
    branch_finishes = [event for event in events
                       if event.type == EventType.ACTIVATION_FINISHED
                       and event.session_id.startswith("ses_ask_pro_")]
    assert len(branch_starts) == 2
    assert max(event.position for event in branch_starts) < min(event.position for event in branch_finishes)
    # 两个分支各带来一个新版本：先提交的是第 2 版
    revisions = [event.payload["revision"] for event in events if event.type == EventType.SPEC_ACCEPTED]
    assert revisions == [1, 2, 3]
    # 后提交的一条按开始时看到的版本提交，被拒绝，原因写明依据的版本不是当前版本
    rejected = [event for event in events
                if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("name") == "answer"
                and not (event.payload or {}).get("ok")]
    assert len(rejected) == 1
    error = rejected[0].payload.get("error") or ""
    # 拒绝的原因写明它依据的版本与当前版本：依据的版本已经不是当前版本，当前版本一并给出
    assert state["quality_saw"] in error and "current version is" in error, error
    # 被拒绝以后它看到新版本，并按新版本重新提交（第 3 版）
    assert holder["resubmitted_at"] == 2

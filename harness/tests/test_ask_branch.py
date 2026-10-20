import json
from pathlib import Path
from typing import Any

import pytest

from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem


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
        "quality": [review_turn("release", "valid uppercase implementation")],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.outcome == "done"
    assert projection.phase == "DONE"
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
        "quality": [review_turn("release", "ok")],
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
        phase="ENGINEERING",
        active_ask={"requester": "product", "recipient": "engineering", "branch_session_id": "ses_ask_eng"},
    )
    basis = WorkBasis.current(projection, "engineering")

    # 工程分支试图写入
    perm_write = tool_permission(
        projection,
        {"name": "write_file", "args": {"path": "src/new.py", "content": "x"}},
        department="engineering",
        guidance_only=False,
        basis=basis,
        aborted=False,
        facts=WorkspaceFacts(),
    )
    assert not perm_write.allowed

    # 工程分支试图提交交付
    perm_del = tool_permission(
        projection,
        {"name": "submit_delivery", "args": {"summary": "done", "files": ["src/new.py"], "check_names": []}},
        department="engineering",
        guidance_only=False,
        basis=basis,
        aborted=False,
        facts=WorkspaceFacts(),
    )
    assert not perm_del.allowed

    # 质检分支试图提交放行或缺陷记录
    qa_projection = RunProjection(
        run_id="run_test",
        phase="QUALITY",
        active_ask={"requester": "engineering", "recipient": "quality", "branch_session_id": "ses_ask_qa"},
    )
    qa_basis = WorkBasis.current(qa_projection, "quality")
    perm_rev = tool_permission(
        qa_projection,
        {"name": "submit_review", "args": {"verdict": "release", "rationale": "ok", "checks": []}},
        department="quality",
        guidance_only=False,
        basis=qa_basis,
        aborted=False,
        facts=WorkspaceFacts(),
    )
    assert not perm_rev.allowed

    # 产品分支试图执行除 answer 之外的工具被拒绝
    prod_projection = RunProjection(
        run_id="run_test",
        phase="ENGINEERING",
        active_ask={"requester": "engineering", "recipient": "product", "branch_session_id": "ses_ask_pro"},
    )
    prod_basis = WorkBasis.current(prod_projection, "product")
    perm_prod_read = tool_permission(
        prod_projection,
        {"name": "read_file", "args": {"path": "src/echo.py"}},
        department="product",
        guidance_only=False,
        basis=prod_basis,
        aborted=False,
        facts=WorkspaceFacts(),
    )
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
        "quality": [review_turn("release", "valid uppercase implementation")],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.outcome == "done"
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
        "quality": [review_turn("release", "valid echo implementation")],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.outcome == "done"
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
        "quality": [review_turn("release", "ok")],
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
        "quality": [review_turn("release", "ok")],
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

    # 提问方投影的已用量包含分支的步骤
    finished_events = [e for e in events if e.type == EventType.ACTIVATION_FINISHED and e.department == "engineering"]
    assert finished_events[0].payload["model_steps"] == 4
    assert system.project(run_id).outcome == "done"


def test_ask_branch_resumes_across_system_restart(tmp_path: Path):
    # AC2 & AC5: 分支进行中重新启动 Yudao，分支继续，回答交回提问方，事项运行到放行
    import sys
    from harness.tests import process_kill as killed
    from harness.proposals import delivery, review

    data_dir = tmp_path / "data"
    script = [
        {"proposal": {"kind": "product_spec", "goal": "build an echo CLI",
                      "requirements": ["echo input"], "acceptance_criteria": ["prints arg"]}},
        {"output": [
            _call("ask-1", "ask", recipient="product", question="Is lowercase ok?",
                  background="Bg", expected="Exp"),
        ]},
    ]
    checks = {"smoke": {"command": f"\"{sys.executable.replace(chr(92), chr(47))}\" -c \"print('smoke ok')\""}}
    tail = [
        {"output": [
            _call("ans-1", "answer", answer="Yes, lowercase is ok."),
        ]},
        {"proposal": delivery(check_names=["smoke"]),
         "writes": {"src/echo.py": "import sys\nprint(sys.argv[1].lower())\n"},
         "checks": checks},
        {"proposal": review("release", "checks passed on the current snapshot"),
         "checks": checks},
    ]

    with killed.interrupted(data_dir, script, hold_after=EventType.ASK_STARTED, tail=tail) as run:
        events_after = run.after.store.list_events(run.run_id)
        ask_answered_events = [e for e in events_after if e.type == EventType.ASK_ANSWERED]
        assert len(ask_answered_events) == 1
        assert ask_answered_events[0].payload["status"] == "answered"
        assert ask_answered_events[0].payload["answer"] == "Yes, lowercase is ok."
        assert run.after.project(run.run_id).phase == "DONE"


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
        "quality": [review_turn("release", "ok")],
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
    assert system.project(run_id).outcome == "done"


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
        "quality": [review_turn("release", "ok")],
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
    assert system.project(run_id).outcome == "done"


def test_ask_branch_exhausted_by_run_time_limit_ends_with_unable(tmp_path: Path):
    # 事项整条 run 的时间上限耗尽：分支在 unable 结束时写明时间上限原因（而非通用兜底）
    import time

    def product_branch_slow(call):
        time.sleep(1.5)
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
        "quality": [review_turn("release", "ok")],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo", run_time_limit_sec=1)
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    payload = ask_answered_events[0].payload
    assert payload["status"] == "unable"
    assert "time limit" in payload["reason"].lower()
    assert system.project(run_id).stop_reason == "time_limit"


def test_ask_branch_zero_remaining_time_does_not_open_branch(tmp_path: Path):
    # 剩余或声明时间 <= 0 时不开启分支，直接以 unable 结束并写明时间上限
    from harness.engine import StepLimits

    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="Clarify something?",
                      background="Bg", expected="Exp"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [ModelResponse(output=[_call("ans-1", "answer", answer="Clarified.")])],
        "quality": [review_turn("release", "ok")],
    }
    adapter = FakeAdapter(scripts)
    step_limits = StepLimits(department_max_time_sec={"product": 0.0})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=step_limits)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    ask_answered_events = [e for e in events if e.type == EventType.ASK_ANSWERED]
    assert len(ask_answered_events) == 1
    payload = ask_answered_events[0].payload
    assert payload["status"] == "unable"
    assert "time limit" in payload["reason"].lower()

    # 不开启分支：没有分支 session 的激活与请求
    branch_activations = len([
        e for e in events
        if e.type == EventType.DEPARTMENT_ACTIVATED and (e.session_id or "").startswith("ses_ask")
    ])
    branch_steps = len([
        e for e in events
        if e.type == EventType.MODEL_REQUESTED and (e.session_id or "").startswith("ses_ask")
    ])
    assert branch_activations == 0
    assert branch_steps == 0

    tool_calls = [e for e in events if e.type == EventType.TOOL_CALLED and e.payload.get("name") == "ask"]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["ok"] is False
    assert "time limit" in (tool_calls[0].payload.get("error") or "").lower()
    assert system.project(run_id).outcome == "done"

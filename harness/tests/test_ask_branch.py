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

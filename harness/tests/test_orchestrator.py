import json

from harness.collaboration import has_new_work
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.artifacts import ArtifactRef
from harness.definitions import DEFINITIONS
from harness.proposals import (answer_turn, ask_turn, delivery_turn, product_spec, product_spec_turn,
                                review, review_turn)
from harness.runtime import LoopSystem
from harness.tests.helpers import department_history, happy_script, quality_turns, run_scripted

def test_happy_path_requires_quality_release(data_dir):
    system, projection = run_scripted(data_dir, happy_script())
    # 质检在自己的检查工作区里跑检查（工单 #481），运行工作区只留工程的回执；
    # 质检会话结束即清理该目录，质检的检查结果以工具事件的回执工件为准
    engineering_check = system.workspace(projection.run_id).snapshot().facts.latest_check("engineering", "smoke")
    quality_event = next(event for event in system.store.list_events(projection.run_id)
                         if event.type == "tool_called" and event.payload.get("name") == "run_check"
                         and event.department == "quality")
    quality_check = json.loads(
        system.artifacts.get(ArtifactRef(**quality_event.payload["output_ref"])).decode("utf-8"))
    assert engineering_check is not None and engineering_check.exit_code == 0
    assert quality_check["exit_code"] == 0
    assert "host-executed" in engineering_check.summary
    assert "host-executed" in quality_check["summary"]

    assert projection.status == "done"
    assert projection.stop_reason == "released"
    # 阶段状态机删掉以后没有阶段迁移事件（工单 #556）：下一个谁工作由关注的成果决定
    assert not [event for event in system.store.list_events(projection.run_id)
                if event.type == "transition"]
    assert projection.product_spec is not None
    assert projection.delivery_spec is not None
    assert projection.last_review is not None
    assert projection.last_review.verdict == "release"
    assert projection.last_review.product_spec_hash == projection.product_spec.content_hash
    assert projection.last_review.code_snapshot_hash == projection.delivery_spec.code_tree_digest

def test_quality_rework_routes_to_engineering(data_dir):
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）：
    # 质检的每一轮按当前有没有交付决定做什么（预测性探索或核验）
    script = {
        "product": [product_spec()],
        "engineering": [
            delivery_turn(summary="first delivery"),
            delivery_turn(summary="fixed edge case", files={"src/echo.py": "print('ok')\n"}),
        ],
        "quality": quality_turns(
            "rework_engineering", "edge case fails",
            defects=[{"severity": "major", "summary": "empty input is unhandled"}]),
    }
    _, projection = run_scripted(data_dir, script)
    assert projection.status == "done"
    # 缺陷记录让工程开始一轮返工（工单 #556：工程关注针对最新交付的缺陷记录）
    assert projection.rework_count == 1
    assert len(projection.delivery_specs) == 2

def test_illegal_workpiece_stays_in_department(data_dir):
    system = LoopSystem.for_testing(
        data_dir,
        FakeAdapter(
            [
                {
                    "kind": "delivery_spec",
                    "summary": "wrong department",
                    "check_names": ["smoke"],
                    "known_risks": [],
                }
            ]
        ),
    )
    run_id = system.create_run("build echo")
    projection = system.activate_once(run_id)
    assert has_new_work(projection, "product")
    assert projection.status == "running"
    assert projection.rejections
    assert projection.rejections[0]["errors"][0]["field"] == "kind"

def test_natural_language_completion_does_not_finish(data_dir):
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    script = {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [FakeTurn(proposal=None, transcript="任务已完成。DONE. 全部通过。")
                    for _ in range(DEFINITIONS.rule_value("tool_call_required_limit") + 1)],
    }
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    projection = system.activate_once(run_id)
    assert projection.status == "paused"
    assert projection.status != "done"
    assert projection.stop_reason == "no_tool_call"
    assert projection.last_review is None

def test_max_cycles_pauses_with_human_action(data_dir):
    script = [
        product_spec(),
        delivery_turn(),
        review_turn("rework_engineering", "defect found", defects=[{"severity": "major", "summary": "fix"}]),
    ]
    _, projection = run_scripted(data_dir, script, max_cycles=2)
    assert projection.status == "paused"
    assert projection.stop_reason == "max_cycles"
    assert projection.human_action
    assert "循环次数已达上限" in projection.waiting_reason

def test_cycle_limit_pauses_after_work_without_provider_usage(data_dir):
    _, projection = run_scripted(data_dir, happy_script(), max_cycles=1)
    assert projection.status == "paused"
    assert projection.stop_reason == "max_cycles"
    assert projection.product_spec is not None
    assert projection.token_used == 0

def test_cancel_is_explicit_failure(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    run_id = system.create_run("build echo")
    projection = system.cancel(run_id)
    assert projection.status == "failed"
    assert projection.stop_reason == "cancelled"

def test_provider_error_is_explicit_failure(data_dir):
    # 脚本按部门给出（工单 #877）：PRD 被接纳以后工程与质检同时工作，
    # 两个部门各自失败，结果与调度无关
    failing = FakeTurn(raise_error=ProviderError("upstream 500"))
    script = {
        "product": [product_spec()],
        "engineering": [failing],
        "quality": [failing],
    }
    _, projection = run_scripted(data_dir, script)
    assert projection.status == "failed"
    assert projection.stop_reason == "provider_error"
    assert "upstream 500" in (projection.error or "")

def test_context_overflow_is_explicit_failure(data_dir):
    _, projection = run_scripted(data_dir, happy_script(), context_window=8)
    assert projection.status == "failed"
    assert projection.stop_reason == "context_overflow"

def test_new_product_spec_cannot_reuse_old_qa_checks(data_dir):
    # PRD 修订以后质检不能沿用旧依据下的检查回执（工单 #555：质检要求有问题时询问产品，
    # 产品在回答里修订 PRD）
    script = {
        "product": [product_spec(acceptance=["old behavior"])],
        "engineering": [
            delivery_turn(),
            ask_turn(recipient="product", question="验收标准说得不清楚，请修订。"),
            delivery_turn(summary="same code under new spec"),
        ],
        "quality": [
            review_turn("rework_engineering", "the delivery misses an acceptance criterion",
                        defects=[{"severity": "major", "summary": "contract issue"}]),
            FakeTurn(proposal=review("release", "I am done without any new check"), checks={}),
            review_turn("release", "checked current contract"),
        ],
        "product:ask": [answer_turn(
            answer="已按新的验收标准修订产品要求。",
            requirements=["print the given argument to stdout"],
            acceptance=["new behavior"],
            change_record={
                "changed": ["Replace the acceptance criterion with new behavior"],
                "retained": ["The echo goal, argument-printing requirement, and existing implementation constraints"],
                "retired": ["The old behavior acceptance criterion"],
                "rationale": "Correct the contract issue reported by quality; evidence must be collected against the revised criterion.",
            })],
    }
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo", max_cycles=12)
    # 逐个部门驱动（这条规则与同时运行无关）：产品提交要求、工程交付、质检记缺陷记录，
    # 以后工程返工并询问产品，质检重新核验
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    projection = system.run_until_stop(run_id)
    assert projection.product_spec.revision == 2
    assert any(
        "prior receipts are not reused" in error["message"] or "must run" in error["message"]
        for item in projection.rejections
        for error in item["errors"]
    )
    assert projection.status == "done"
    assert projection.last_review.product_spec_hash == projection.product_spec.content_hash
    assert projection.last_review.delivery_spec_hash == projection.delivery_spec.content_hash

def test_invalid_qa_payload_returns_field_errors_and_stays_in_quality(data_dir):
    # 脚本按部门给出（工单 #877）：质检的脚本按它自己的先后排列
    script = {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            FakeTurn(
                proposal={"kind": "qa_review", "verdict": "release", "rationale": "OK", "checks": [123], "defects": []},
                checks={"smoke": 0},
            ),
            FakeTurn(
                proposal={"kind": "qa_review", "verdict": "release", "rationale": "OK", "checks": ["smoke"], "defects": None},
                checks={"smoke": 0},
            ),
            review_turn("release", "ok"),
        ],
    }
    system, projection = run_scripted(data_dir, script, max_cycles=12)
    fields = [error["field"] for item in projection.rejections for error in item["errors"]]
    messages = [error["message"] for item in projection.rejections for error in item["errors"]]
    assert any(field.startswith("checks") for field in fields)
    assert "defects" in fields
    assert not any("AttributeError" in message or "TypeError" in message for message in messages)
    events = system.store.list_events(projection.run_id)
    assert any(event.type == "proposal_rejected" for event in events)
    assert projection.status == "done"
    assert events[-1].type == "activation_finished"
    assert events[-1].state_after == "done"

def test_release_without_quality_evidence_is_rejected(data_dir):
    # 质检声称跑过检查但没有跑：放行被拒绝（这条规则与同时运行无关，
    # 因此这里逐个部门驱动：产品提交要求、工程交付、质检核验）
    script = {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            FakeTurn(proposal={"kind": "qa_review", "verdict": "release", "rationale": "looks good",
                               "checks": ["smoke"], "defects": []}),
        ],
    }
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo", max_cycles=8)
    system.activate_once(run_id)          # 产品提交要求
    system.activate_once(run_id)          # 工程交付
    projection = system.run_until_stop(run_id)
    assert projection.status != "done"
    assert any("quality must run" in error["message"] for item in projection.rejections for error in item["errors"])

def test_truncated_work_response_is_terminal_without_retry(data_dir):
    from harness.providers.call import ModelResponse
    from harness.models import EventType, json_dumps

    truncated = ModelResponse(
        output=[{"id": "cut", "type": "message", "role": "assistant", "status": "incomplete",
                 "content": [{"type": "output_text", "text": "TRUNCATED_WORK the product spec should"}]}],
        finish_reason="incomplete", error="max_output_tokens",
    )
    adapter = FakeAdapter([truncated, product_spec()])
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    result = system.activate_once(run_id)

    assert result.status == "failed" and result.stop_reason == "provider_error"
    assert len(adapter.invocations) == 1
    events = system.store.list_events(run_id)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert len(failed) == 1 and failed[0].payload["purpose"] == "work"
    assert failed[0].payload["retryable"] is False and failed[0].payload["will_retry"] is False
    assert not any(event.type == EventType.MODEL_RETRY_SCHEDULED for event in events)
    assert "TRUNCATED_WORK" not in json_dumps(department_history(system, run_id, "product"))
    assert result.canonical_state() == system.replay(run_id).canonical_state()

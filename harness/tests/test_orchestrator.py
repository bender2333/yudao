import json

from harness.watched_outputs import has_new_work
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.artifacts import ArtifactRef
from harness.proposals import (
    answer_turn,
    ask_turn,
    delivery_turn,
    judgement_turn,
    product_spec,
    review,
    review_turn,
)
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, run_scripted

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


def test_new_product_spec_cannot_reuse_old_qa_checks(data_dir):
    # PRD 修订以后质检不能沿用旧依据下的检查回执（工单 #555：质检要求有问题时询问产品，
    # 产品在回答里修订 PRD）。质检先交独立判断再下结论（先判断后看解释的门，工单 #358）
    script = {
        "product": [product_spec(acceptance=["old behavior"])],
        "engineering": [
            delivery_turn(),
            ask_turn(recipient="product", question="验收标准说得不清楚，请修订。"),
            delivery_turn(summary="same code under new spec"),
        ],
        "quality": [
            judgement_turn(),
            review_turn("rework_engineering", "the delivery misses an acceptance criterion",
                        defects=[{"severity": "major", "summary": "contract issue"}]),
            FakeTurn(proposal=review("release", "I am done without any new check"), checks={}),
            judgement_turn(),
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
    # 脚本按部门给出（工单 #877）：质检的脚本按它自己的先后排列。
    # 结论前先交独立判断（先判断后看解释的门，工单 #358）
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
            judgement_turn(),
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

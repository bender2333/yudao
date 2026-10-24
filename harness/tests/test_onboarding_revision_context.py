import uuid
from pathlib import Path

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.event_store import Command
from harness.models import ArtifactRef, EventType, ProjectEventType
from harness.projection import saved_decisions
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import recorded_context
from harness.tests.onboarding_project import (
    ONBOARDING_GOAL as GOAL,
    ONBOARDING_REQUIREMENT as REQUIREMENT,
    onboarding_source as _source,
)

NOTE = "现有 CLI 还没有 --help，初始 PRD 要把这个用法说明写进去"
NEW_REQUIREMENT = "the CLI explains its usage when started with --help"


def _product_turn(round_number: int, requirements: list[str]) -> FakeTurn:
    return FakeTurn(proposal=product_spec(goal=f"{GOAL}（第 {round_number} 轮）", requirements=requirements,
                                          acceptance=["run the CLI with a word"]))


def _structure_turn(round_number: int, requirements: list[str]) -> FakeTurn:
    return structure_turn(
        requirement_locations=[{"requirement": item, "locations": ["src/echo.py"]} for item in requirements],
        overall=f"第 {round_number} 轮的结构说明：一个包加一个命令行入口")


def _review_turn(requirements: list[str]) -> FakeTurn:
    return baseline_review_turn(conclusions=[{"requirement": item, "status": "verified", "evidence": "smoke"}
                                             for item in requirements])


def _round_turns(captured: dict, holder: dict, round_number: int, requirements: list[str]) -> dict:
    # 一轮建档的三个部门回答；每个部门第一次被激活时把它收到的上下文材料记下来。
    # 脚本按部门给出（工单 #557、#879）：PRD 被接纳以后工程与质检同时开始一轮工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化
    def remember(department: str, call, turn: FakeTurn) -> FakeTurn:
        captured[f"round{round_number}_{department}"] = recorded_context(holder["system"], call)
        return turn

    return {
        "product": [lambda call: remember("product", call, _product_turn(round_number, requirements))],
        "engineering": [lambda call: remember("engineering", call, _structure_turn(round_number, requirements))],
        "quality": [lambda call: remember("quality", call, _review_turn(requirements))],
    }


def _two_round_onboarding(tmp_path: Path) -> dict:
    # 真实流程走完两轮建档：接入已有项目、第一轮跑到基线核验通过、结算出初始 PRD 的候选、
    # 用户回答「提出修改」并附修改意见、第二轮三个部门照常进行
    captured: dict[str, object] = {}
    holder: dict[str, LoopSystem] = {}
    rounds = [_round_turns(captured, holder, 1, [REQUIREMENT]),
              _round_turns(captured, holder, 2, [REQUIREMENT, NEW_REQUIREMENT])]
    script = {department: [turn for round_script in rounds for turn in round_script[department]]
              for department in rounds[0]}
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter(script))
    holder["system"] = system
    project_id, work_item_id, first_run_id = system.projects.onboard(
        "已有项目", GOAL, "src", str(_source(tmp_path / "source")))
    first = system.run_until_stop(first_run_id)
    assert first.status == "done", first.error
    assert first.stop_reason == "baseline_verified"
    assert system.projects.settle(first_run_id) is not None

    _position, open_decisions = saved_decisions(system.store, statuses=("open",))
    [decision] = open_decisions
    assert decision.kind == "initial_prd"
    command = Command(str(uuid.uuid4()), "decision.answer", f"sha256:revise:{decision.version}", "user:local")
    revision_run_id = system.orchestrator.answer_decision(
        decision.decision_id, "revise", NOTE, base_version=decision.version, command=command)
    assert revision_run_id is not None

    revision = next(event for event in system.store.list_project_events(project_id)
                    if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED)
    second_run_id = revision.payload["run_id"]
    second = system.run_until_stop(second_run_id)
    assert second.status == "done", second.error
    assert second.round == 2

    return {
        "system": system, "captured": captured, "first": first, "second": second,
        "first_run_id": first_run_id, "second_run_id": second_run_id,
        "prior_prd": system.artifacts.get_for_run(
            first_run_id, first.effective_contract.prd_ref).decode("utf-8"),
        "prior_structure": system.artifacts.get_for_run(
            first_run_id, ArtifactRef(**first.structure["structure_ref"])).decode("utf-8"),
    }


def test_revision_round_product_gets_prior_prd_and_note(tmp_path):
    # 建档修改轮的常驻材料（docs/design/existing-project-onboarding.md 第 4.7 节最后一段）：
    # 产品拿到上一轮的初始 PRD 原文与这一轮用户的修改意见
    fixture = _two_round_onboarding(tmp_path)
    captured = fixture["captured"]
    sources = {key: [part.source for part in value.parts] for key, value in captured.items()}
    texts = {(key, part.source): part.text for key, value in captured.items() for part in value.parts}

    assert "prior_initial_prd" not in sources["round1_product"]
    product_sources = sources["round2_product"]
    assert "prior_initial_prd" in product_sources
    assert "revision_note" in product_sources
    assert fixture["prior_prd"] in texts[("round2_product", "prior_initial_prd")]
    assert "第 1 轮" in texts[("round2_product", "prior_initial_prd")]
    assert texts[("round2_product", "revision_note")] == NOTE
    # 修改意见同时是这一轮的第一项用户输入，按已有的输入处理规则由这一轮新的 ProductSpec 处理
    assert NOTE in texts[("round2_product", "pending_inputs")]
    assert "existing_overview" in product_sources


def test_revision_round_engineering_gets_prior_structure(tmp_path):
    # 工程的常驻材料是上一轮的 STRUCTURE.md 原文；上一轮的初始 PRD 与修改意见都不给它
    fixture = _two_round_onboarding(tmp_path)
    captured = fixture["captured"]
    sources = {key: [part.source for part in value.parts] for key, value in captured.items()}
    texts = {(key, part.source): part.text for key, value in captured.items() for part in value.parts}

    assert "prior_structure" not in sources["round1_engineering"]
    engineering_sources = sources["round2_engineering"]
    assert "prior_structure" in engineering_sources
    assert fixture["prior_structure"] in texts[("round2_engineering", "prior_structure")]
    assert "第 1 轮的结构说明" in texts[("round2_engineering", "prior_structure")]
    assert "prior_initial_prd" not in engineering_sources
    assert "revision_note" not in engineering_sources


def test_revision_round_quality_reviews_the_new_prd_only(tmp_path):
    # 质检只看这一轮新写出的初始 PRD：基线核验重新进行，上一轮的任何原文都不作为材料注入。
    # 修改意见仍然出现在这一轮的工作请求里（它就是这一轮的用户输入），但不是质检的常驻材料
    fixture = _two_round_onboarding(tmp_path)
    captured, second = fixture["captured"], fixture["second"]
    sources = {key: [part.source for part in value.parts] for key, value in captured.items()}

    assert not {"prior_initial_prd", "prior_structure", "revision_note"} & set(sources["round1_quality"])
    quality_sources = sources["round2_quality"]
    assert not {"prior_initial_prd", "prior_structure", "revision_note"} & set(quality_sources)
    quality_text = "".join(part.text for part in captured["round2_quality"].parts)
    assert fixture["prior_prd"] not in quality_text
    assert fixture["prior_structure"] not in quality_text
    assert "（第 2 轮）" in quality_text and "（第 1 轮）" not in quality_text
    assert NEW_REQUIREMENT in next(part.text for part in captured["round2_quality"].parts
                                   if part.source == "current_product_spec")
    # 基线核验在这一轮重新进行：新的核验结论绑定这一轮的初始 PRD，与第一轮的核验是两条记录
    assert second.baseline_review["product_spec_hash"] == second.product_spec.content_hash
    assert second.baseline_review["product_spec_hash"] != fixture["first"].baseline_review["product_spec_hash"]
    accepted = [event.type for event in fixture["system"].store.list_events(fixture["second_run_id"])]
    assert accepted.count(EventType.BASELINE_REVIEW_ACCEPTED) == 1

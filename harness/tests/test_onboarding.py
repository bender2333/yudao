from pathlib import Path

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import ArtifactRef, DEPARTMENTS, EventType
from harness.proposals import baseline_review_turn, product_spec, product_spec_turn, structure_turn
from harness.runtime import LoopSystem
from harness.snapshot import ingest_snapshot
from harness.tools import tools_for

from harness.tests.onboarding_project import (
    ONBOARDING_GOAL as GOAL,
    ONBOARDING_REQUIREMENT as REQUIREMENT,
    onboarding_source as _source,
)


def _onboarding_run(tmp_path: Path, script, *, source: Path | None = None) -> tuple[LoopSystem, str]:
    # 建档 run 由控制系统从快照创建：没有采纳成果，工作区从快照建立。
    # 项目归属参数按事项创建时的做法给出（工单 #135 登记应用层命令以后由命令提供）
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter(script))
    tree, snapshot = ingest_snapshot(source or _source(tmp_path / "source"), system.artifacts, "run_onboarding")
    run_id = system.create_run(
        GOAL, run_id="run_onboarding", kind="onboarding", initial_tree=tree, code_snapshot=snapshot,
        project_id="proj_onboarding", work_item_id="wi_onboarding", project_context="项目：已有项目接入",
        prompt_config_versions={department: 0 for department in DEPARTMENTS},
    )
    return system, run_id

def _product_turn() -> FakeTurn:
    return FakeTurn(proposal=product_spec(requirements=[REQUIREMENT], acceptance=["run the CLI with a word"]))

def _structure_turn(**kwargs) -> FakeTurn:
    return structure_turn(requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}], **kwargs)

def _review_turn(**kwargs) -> FakeTurn:
    return baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
                                **kwargs)

def _happy_script() -> dict:
    # 脚本按部门给出（工单 #557、#879）：PRD 被接纳以后工程与质检同时开始一轮工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化（工单 #879）
    return {
        "product": [_product_turn()],
        "engineering": [_structure_turn()],
        "quality": [_review_turn()],
    }

def test_onboarding_run_reaches_baseline_verified(tmp_path):
    system, run_id = _onboarding_run(tmp_path, _happy_script())
    result = system.run_until_stop(run_id)
    assert result.status == "done", result.error
    assert result.kind == "onboarding"
    assert result.stop_reason == "baseline_verified"
    kinds = [event.type for event in system.store.list_events(run_id)]
    assert EventType.STRUCTURE_ACCEPTED in kinds
    assert EventType.BASELINE_REVIEW_ACCEPTED in kinds
    assert result.structure is not None and result.baseline_review is not None
    structure_md = system.artifacts.get_for_run(run_id, ArtifactRef(**result.structure["structure_ref"])).decode("utf-8")
    assert "现有结构说明" in structure_md
    assert (tmp_path / "loop" / "materials" / run_id / "STRUCTURE.md").read_text(encoding="utf-8") == structure_md
    assert result.workspace_digest == result.snapshot["tree_digest"]

def test_onboarding_workspace_tree_equals_snapshot_throughout(tmp_path):
    system, run_id = _onboarding_run(tmp_path, _happy_script())
    result = system.run_until_stop(run_id)
    assert result.status == "done", result.error
    assert result.workspace_digest == result.snapshot["tree_digest"]
    assert result.structure["code_tree_digest"] == result.snapshot["tree_digest"]
    assert result.baseline_review["code_snapshot_hash"] == result.snapshot["tree_digest"]
    assert system.replay(run_id).canonical_state() == result.canonical_state()

def test_onboarding_departments_have_no_write_tools(tmp_path):
    write_tools = {"write_file", "edit_range", "delete_file", "move_file"}
    for department in ("product", "engineering", "quality"):
        tools = set(tools_for(department, "onboarding"))
        assert not (tools & write_tools), department
    engineering = set(tools_for("engineering", "onboarding"))
    assert "submit_plan" not in engineering
    assert "submit_delivery" not in engineering
    assert "submit_structure" in engineering
    assert "submit_baseline_review" in set(tools_for("quality", "onboarding"))


def test_quality_cannot_see_existing_structure(tmp_path):
    # 第一轮工程提交结构说明；退回产品以后，新一轮里工程能看到上一轮的结构说明，产品与质检看不到
    captured: dict[str, object] = {}
    holder: dict[str, LoopSystem] = {}

    # 提交依据的版本由工厂从请求里的当前版本取（工单 #471）
    def product_rework_turn(call):
        return FakeTurn(proposal=product_spec_turn(
            requirements=[REQUIREMENT], acceptance=["run the CLI with a word"],
            change_record={"changed": ["clarified the requirement"], "retained": [],
                           "retired": [], "rationale": "rework"})(call))

    def engineering_turn(call):
        from harness.tests.helpers import recorded_context
        captured["engineering"] = recorded_context(holder["system"], call)
        return _structure_turn()

    def quality_turn(call):
        from harness.tests.helpers import recorded_context
        captured["quality"] = recorded_context(holder["system"], call)
        return baseline_review_turn(
            verdict="rework_product" if not captured.get("reworked") else "consistent",
            conclusions=[{"requirement": REQUIREMENT, "status": "unsupported" if not captured.get("reworked")
                          else "verified", "evidence": "the README says nothing about this" if not captured.get("reworked")
                          else "smoke"}],
            checks={"smoke": 0})

    def product_then_mark(call):
        captured["reworked"] = True
        return product_rework_turn(call)

    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879）：每一轮三个部门各一轮。
        # 第一轮质检要求产品修改，第二轮产品改完以后质检核验通过
        "product": [_product_turn(), product_then_mark],
        "engineering": [engineering_turn, engineering_turn],
        "quality": [quality_turn, quality_turn],
    })
    holder["system"] = system
    result = system.run_until_stop(run_id)
    assert result.status == "done", result.error
    engineering_sources = [part.source for part in captured["engineering"].parts]
    quality_sources = [part.source for part in captured["quality"].parts]
    assert "existing_overview" in engineering_sources
    assert "existing_overview" in quality_sources
    assert "existing_structure" in engineering_sources
    assert "existing_structure" not in quality_sources
    # 读取与搜索工具取不到 STRUCTURE.md：它不在工作区的公开树中
    assert "STRUCTURE.md" not in system.workspace(run_id).list_files()

def test_consistent_with_unsupported_is_rejected(tmp_path):
    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879）
        "product": [_product_turn()],
        "engineering": [_structure_turn()],
        "quality": [baseline_review_turn(verdict="consistent",
                                         conclusions=[{"requirement": REQUIREMENT, "status": "unsupported", "evidence": "no test covers this"}],
                                         checks={"smoke": 0})],
    })
    result = system.run_until_stop(run_id)
    assert result.status != "done"
    assert EventType.BASELINE_REVIEW_ACCEPTED not in [event.type for event in system.store.list_events(run_id)]

def test_rework_product_returns_to_product(tmp_path):
    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879）
        "product": [_product_turn()],
        "engineering": [_structure_turn()],
        "quality": [baseline_review_turn(verdict="rework_product",
                                         conclusions=[{"requirement": REQUIREMENT, "status": "unsupported", "evidence": "the README says nothing about this"}],
                                         checks={"smoke": 0})],
    })
    result = system.run_until_stop(run_id)
    assert result.baseline_review["verdict"] == "rework_product"
    # 核验要求产品修改以后，产品开始一轮工作（工单 #556：关注的成果有了新东西，部门在等待工作时开始工作）
    activated = [event.department for event in system.store.list_events(run_id)
                 if event.type == EventType.DEPARTMENT_ACTIVATED]
    assert activated == ["product", "engineering", "quality", "product"]
    assert EventType.BASELINE_REVIEW_ACCEPTED in [event.type for event in system.store.list_events(run_id)]

def test_rework_product_requires_unsupported_or_omission(tmp_path):
    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879）
        "product": [_product_turn()],
        "engineering": [_structure_turn()],
        "quality": [baseline_review_turn(verdict="rework_product",
                                         conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
                                         checks={"smoke": 0})],
    })
    result = system.run_until_stop(run_id)
    assert result.active_department != "product"
    assert EventType.BASELINE_REVIEW_ACCEPTED not in [event.type for event in system.store.list_events(run_id)]

def test_failing_existing_test_can_still_be_consistent(tmp_path):
    def source(root: Path) -> Path:
        _source(root)
        (root / "tests" / "test_failing.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
        return root
    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879）
        "product": [_product_turn()],
        "engineering": [_structure_turn()],
        "quality": [baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "existing_defect", "evidence": "failing"}],
                                         checks={"smoke": 0, "failing": 1})],
    }, source=source(tmp_path / "source"))
    result = system.run_until_stop(run_id)
    assert result.status == "done", result.error
    assert result.baseline_review["verdict"] == "consistent"
    referenced = {item["evidence"] for item in result.baseline_review["conclusions"] if item["status"] == "existing_defect"}
    assert "failing" in referenced

def test_unexplained_failing_check_is_rejected(tmp_path):
    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879）
        "product": [_product_turn()],
        "engineering": [_structure_turn()],
        "quality": [baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
                                         checks={"smoke": 0, "failing": 1})],
    })
    result = system.run_until_stop(run_id)
    assert result.status != "done"
    assert EventType.BASELINE_REVIEW_ACCEPTED not in [event.type for event in system.store.list_events(run_id)]

def test_a_timed_out_check_is_treated_like_a_failing_check(tmp_path):
    # 超时的检查（主机记录的退出状态为 TIMEOUT_EXIT_CODE，124）与失败检查同样处理：
    # 没有被 existing_defect 引用或写进「其他失败」时被拒绝，被引用时可以以 consistent 结束。
    # 检查本身在检查副本中运行，真实的 600 秒超时不在单元层重复（test_tools.py 已核对超时的退出状态）。
    from harness.environment import TIMEOUT_EXIT_CODE
    from harness.models import CheckReceipt
    from harness.validation import evaluate_proposal

    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879），三个部门都写上（工单 #943）：
        # 质检在这些用例里不工作，给它的是空脚本——脚本里没有它的名字时，
        # 假模型在它真的发请求时报「脚本用尽」，整个 run 以 provider_error 提前结束
        "product": [_product_turn()],
        "engineering": [_structure_turn()],
        "quality": [],
    })
    system.activate_once(run_id)
    result = system.activate_once(run_id)
    assert has_new_work(result, "quality"), result.status
    projection = system.project(run_id)
    workspace = system.workspace(run_id)
    facts = workspace.snapshot().facts
    spec = projection.product_spec
    structure = projection.structure
    receipt = CheckReceipt(name="slow", department="quality", exit_code=TIMEOUT_EXIT_CODE,
                           summary="check timed out after 600s", snapshot_hash=facts.digest,
                           product_spec_hash=spec.content_hash, activation_id=projection.last_activations.get("quality"))
    facts = facts.model_copy(update={"checks": (*facts.checks, receipt)})
    unexplained = {
        "kind": "baseline_review", "verdict": "consistent",
        "conclusions": [{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
        "omissions": [], "checks": ["slow"], "other_failures": [],
    }
    decision = evaluate_proposal(department="quality", proposal=unexplained,
                                 projection=projection, facts=facts)
    assert not decision.accepted
    assert any("failing check" in error.message for error in decision.errors)
    explained = {**unexplained,
                 "conclusions": [{"requirement": REQUIREMENT, "status": "existing_defect", "evidence": "slow"}]}
    decision = evaluate_proposal(department="quality", proposal=explained,
                                 projection=projection, facts=facts)
    assert decision.accepted, [error.message for error in decision.errors]
    assert decision.artifact["checks"][0]["exit_code"] == TIMEOUT_EXIT_CODE
    assert structure is not None

def test_structure_requires_activation_receipt(tmp_path):
    # build_and_test 的名称没有对应的本次激活 run_check 回执时被拒绝
    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879）
        "product": [_product_turn()],
        "engineering": [
            structure_turn(requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}],
                           checks={}, build_and_test=[{"name": "smoke", "command": "python src/echo.py", "purpose": "run the CLI"}]),
        ],
        # 质检与工程同时开始一轮工作（工单 #557）：结构说明被拒绝，这一轮提交的结论也被拒绝
        "quality": [_review_turn()],
    })
    result = system.run_until_stop(run_id)
    assert result.active_department != "quality"
    assert EventType.STRUCTURE_ACCEPTED not in [event.type for event in system.store.list_events(run_id)]

def test_structure_rejects_requirement_coverage_mismatch(tmp_path):
    # requirement_locations 必须恰好覆盖当前初始 PRD 的每条要求
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    system, run_id = _onboarding_run(tmp_path, {
        "product": [_product_turn()],
        "engineering": [
            structure_turn(requirement_locations=[{"requirement": "a requirement that is not in the PRD",
                                                   "locations": ["src/echo.py"]}]),
        ],
        # 质检在 PRD 被接纳以后与工程同时开始一轮工作（工单 #557）：结构说明还没有被接纳，这一轮提交的结论被拒绝
        "quality": [_review_turn()],
    })
    system.run_until_stop(run_id)
    events = [event.type for event in system.store.list_events(run_id)]
    assert EventType.STRUCTURE_ACCEPTED not in events
    rejected = [event for event in system.store.list_events(run_id) if event.type == EventType.PROPOSAL_REJECTED]
    assert any("requirement_locations" in error["field"] for event in rejected for error in event.payload["errors"])

def test_structure_acceptance_refuses_a_changed_workspace_tree(tmp_path):
    # 接纳时核对工作区的树摘要等于快照摘要，不相等时拒绝（设计第 4.1 节）
    from harness.validation import evaluate_proposal

    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879），三个部门都写上（工单 #943）：
        # 质检在这些用例里不工作，给它的是空脚本——脚本里没有它的名字时，
        # 假模型在它真的发请求时报「脚本用尽」，整个 run 以 provider_error 提前结束
        "product": [_product_turn()],
        "engineering": [_structure_turn()],
        "quality": [],
    })
    result = system.activate_once(run_id)
    assert has_new_work(result, "engineering"), result.status
    projection = system.project(run_id)
    facts = system.workspace(run_id).snapshot().facts
    proposal = {
        "kind": "structure", "overall": "text",
        "modules": [{"path": "src/", "responsibility": "implementation"}],
        "entry_points": [{"kind": "command_line", "path": "src/echo.py", "how_to_run": "python src/echo.py"}],
        "build_and_test": [{"name": "smoke", "command": "python src/echo.py", "purpose": "run the CLI"}],
        "requirement_locations": [{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}],
        "conventions": [],
    }
    changed = facts.model_copy(update={"digest": "sha256:" + "0" * 64})
    decision = evaluate_proposal(department="engineering", proposal=proposal,
                                 projection=projection, facts=changed)
    assert not decision.accepted
    assert any("no longer matches the snapshot" in error.message for error in decision.errors)

DESIGN_CAPABILITY = "导出 PDF 报告"
MARKED_BOUNDARY = "导出 PDF 报告（设计中，未实施）：docs/design/export.md 描述，代码尚未实现"


def test_existing_defect_must_not_cover_a_marked_boundary_entry(tmp_path):
    # 工单 #346：带标记的边界条目不记为现有缺陷，基线核验按此核对
    from harness.models import CheckReceipt
    from harness.validation import evaluate_proposal

    marked = "导出 PDF 报告（设计中，未实施）：设计文档描述，代码尚未实现"
    system, run_id = _onboarding_run(tmp_path, {
        # 脚本按部门给出（工单 #557、#879），三个部门都写上（工单 #943）
        "product": [FakeTurn(proposal=product_spec(requirements=[DESIGN_CAPABILITY], acceptance=["run the CLI with a word"],
                                      boundaries=[marked]))],
        "engineering": [structure_turn(requirement_locations=[{"requirement": DESIGN_CAPABILITY, "locations": ["src/echo.py"]}])],
        "quality": [],
    })
    system.activate_once(run_id)
    result = system.activate_once(run_id)
    assert has_new_work(result, "quality"), result.status
    projection = system.project(run_id)
    facts = system.workspace(run_id).snapshot().facts
    spec = projection.product_spec
    receipt = CheckReceipt(name="smoke", department="quality", exit_code=1,
                           summary="not implemented", snapshot_hash=facts.digest,
                           product_spec_hash=spec.content_hash, activation_id=projection.last_activations.get("quality"))
    facts = facts.model_copy(update={"checks": (*facts.checks, receipt)})
    proposal = {
        "kind": "baseline_review", "verdict": "consistent",
        "conclusions": [{"requirement": DESIGN_CAPABILITY, "status": "existing_defect", "evidence": "smoke"}],
        "omissions": [], "checks": ["smoke"], "other_failures": [],
    }
    decision = evaluate_proposal(department="quality", proposal=proposal,
                                 projection=projection, facts=facts)
    assert not decision.accepted
    assert any("设计中，未实施" in error.message for error in decision.errors)

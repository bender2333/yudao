from pathlib import Path

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import DEFINITIONS
from harness.models import ArtifactRef, DEPARTMENTS, EventType
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.runtime import LoopSystem
from harness.snapshot import ingest_snapshot
from harness.tools import tools_for

GOAL = "把已有项目接入 Yudao，写出初始 PRD 并核验现有行为"
REQUIREMENT = "print the given argument to stdout"

def _source(root: Path) -> Path:
    # 一份最小的已有项目：一个可运行的脚本、一个说明文件与一个通过的测试
    (root / "src").mkdir(parents=True)
    (root / "src" / "echo.py").write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    (root / "README.md").write_text("# Echo\n\nPrint the given argument.\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_echo.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    return root

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

def _happy_script() -> list:
    return [_product_turn(), _structure_turn(), _review_turn()]

def test_onboarding_run_reaches_baseline_verified(tmp_path):
    system, run_id = _onboarding_run(tmp_path, _happy_script())
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
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
    assert result.phase == "DONE", result.error
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

def test_repository_overview_is_generated(tmp_path):
    system, run_id = _onboarding_run(tmp_path, _happy_script())
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    overview = system.artifacts.get_for_run(run_id, ArtifactRef(**result.overview_ref)).decode("utf-8")
    assert "仓库概况" in overview
    assert "src/" in overview
    assert "README.md" in overview
    assert "tests/test_echo.py" in overview
    # 概况只列路径与数量，不含文件内容
    assert "print(sys.argv[1])" not in overview

def test_check_timeout_is_six_hundred():
    # 登记里的现值与 bounds 一致；由 rules.registry 读出
    rule = DEFINITIONS.rule("check_timeout_sec")
    assert rule.value == 600 and list(rule.bounds) == [1, 86400]
    assert DEFINITIONS.rule_value("command_timeout_max_sec") == 600

def test_quality_cannot_see_existing_structure(tmp_path):
    # 第一轮工程提交结构说明；退回产品以后，新一轮里工程能看到上一轮的结构说明，产品与质检看不到
    captured: dict[str, object] = {}
    holder: dict[str, LoopSystem] = {}

    def product_rework_turn():
        return FakeTurn(proposal=product_spec(requirements=[REQUIREMENT], acceptance=["run the CLI with a word"],
                                              change_record={"changed": ["clarified the requirement"], "retained": [],
                                                             "retired": [], "rationale": "rework"}))

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
        return product_rework_turn()

    system, run_id = _onboarding_run(tmp_path, [
        _product_turn(), engineering_turn, quality_turn, product_then_mark, engineering_turn, quality_turn,
    ])
    holder["system"] = system
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    engineering_sources = [part.source for part in captured["engineering"].parts]
    quality_sources = [part.source for part in captured["quality"].parts]
    assert "existing_overview" in engineering_sources
    assert "existing_overview" in quality_sources
    assert "existing_structure" in engineering_sources
    assert "existing_structure" not in quality_sources
    # 读取与搜索工具取不到 STRUCTURE.md：它不在工作区的公开树中
    assert "STRUCTURE.md" not in system.workspace(run_id).list_files()

def test_consistent_with_unsupported_is_rejected(tmp_path):
    system, run_id = _onboarding_run(tmp_path, [
        _product_turn(), _structure_turn(),
        baseline_review_turn(verdict="consistent",
                             conclusions=[{"requirement": REQUIREMENT, "status": "unsupported", "evidence": "no test covers this"}],
                             checks={"smoke": 0}),
    ])
    result = system.run_until_stop(run_id)
    assert result.phase != "DONE"
    assert EventType.BASELINE_REVIEW_ACCEPTED not in [event.type for event in system.store.list_events(run_id)]

def test_rework_product_returns_to_product(tmp_path):
    system, run_id = _onboarding_run(tmp_path, [
        _product_turn(), _structure_turn(),
        baseline_review_turn(verdict="rework_product",
                             conclusions=[{"requirement": REQUIREMENT, "status": "unsupported", "evidence": "the README says nothing about this"}],
                             checks={"smoke": 0}),
    ])
    result = system.run_until_stop(run_id)
    assert result.baseline_review["verdict"] == "rework_product"
    routes = [event.payload["route"] for event in system.store.list_events(run_id) if event.type == EventType.TRANSITION]
    assert "QUALITY->REWORK_PRODUCT" in routes
    assert "REWORK_PRODUCT->PRODUCT_SPEC" in routes
    assert EventType.BASELINE_REVIEW_ACCEPTED in [event.type for event in system.store.list_events(run_id)]

def test_rework_product_requires_unsupported_or_omission(tmp_path):
    system, run_id = _onboarding_run(tmp_path, [
        _product_turn(), _structure_turn(),
        baseline_review_turn(verdict="rework_product",
                             conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
                             checks={"smoke": 0}),
    ])
    result = system.run_until_stop(run_id)
    assert result.phase != "REWORK_PRODUCT"
    assert EventType.BASELINE_REVIEW_ACCEPTED not in [event.type for event in system.store.list_events(run_id)]

def test_failing_existing_test_can_still_be_consistent(tmp_path):
    def source(root: Path) -> Path:
        _source(root)
        (root / "tests" / "test_failing.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
        return root
    system, run_id = _onboarding_run(tmp_path, [
        _product_turn(), _structure_turn(),
        baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "existing_defect", "evidence": "failing"}],
                             checks={"smoke": 0, "failing": 1}),
    ], source=source(tmp_path / "source"))
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    assert result.baseline_review["verdict"] == "consistent"
    referenced = {item["evidence"] for item in result.baseline_review["conclusions"] if item["status"] == "existing_defect"}
    assert "failing" in referenced

def test_unexplained_failing_check_is_rejected(tmp_path):
    system, run_id = _onboarding_run(tmp_path, [
        _product_turn(), _structure_turn(),
        baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
                             checks={"smoke": 0, "failing": 1}),
    ])
    result = system.run_until_stop(run_id)
    assert result.phase != "DONE"
    assert EventType.BASELINE_REVIEW_ACCEPTED not in [event.type for event in system.store.list_events(run_id)]

def test_a_timed_out_check_is_treated_like_a_failing_check(tmp_path):
    # 超时的检查（主机记录的退出状态为 TIMEOUT_EXIT_CODE，124）与失败检查同样处理：
    # 没有被 existing_defect 引用或写进「其他失败」时被拒绝，被引用时可以以 consistent 结束。
    # 检查本身在检查副本中运行，真实的 600 秒超时不在单元层重复（test_tools.py 已核对超时的退出状态）。
    from harness.environment import TIMEOUT_EXIT_CODE
    from harness.models import CheckReceipt
    from harness.validation import evaluate_proposal

    system, run_id = _onboarding_run(tmp_path, [_product_turn(), _structure_turn()])
    system.activate_once(run_id)
    result = system.activate_once(run_id)
    assert result.phase == "QUALITY", result.phase
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
    decision = evaluate_proposal(phase="QUALITY", department="quality", proposal=unexplained,
                                 projection=projection, facts=facts)
    assert not decision.accepted
    assert any("failing check" in error.message for error in decision.errors)
    explained = {**unexplained,
                 "conclusions": [{"requirement": REQUIREMENT, "status": "existing_defect", "evidence": "slow"}]}
    decision = evaluate_proposal(phase="QUALITY", department="quality", proposal=explained,
                                 projection=projection, facts=facts)
    assert decision.accepted, [error.message for error in decision.errors]
    assert decision.artifact["checks"][0]["exit_code"] == TIMEOUT_EXIT_CODE
    assert structure is not None

def test_structure_requires_activation_receipt(tmp_path):
    # build_and_test 的名称没有对应的本次激活 run_check 回执时被拒绝
    system, run_id = _onboarding_run(tmp_path, [
        _product_turn(),
        structure_turn(requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}],
                       checks={}, build_and_test=[{"name": "smoke", "argv": ["python", "src/echo.py"], "purpose": "run the CLI"}]),
    ])
    result = system.run_until_stop(run_id)
    assert result.phase != "QUALITY"
    assert EventType.STRUCTURE_ACCEPTED not in [event.type for event in system.store.list_events(run_id)]

def test_structure_rejects_requirement_coverage_mismatch(tmp_path):
    # requirement_locations 必须恰好覆盖当前初始 PRD 的每条要求
    system, run_id = _onboarding_run(tmp_path, [
        _product_turn(),
        structure_turn(requirement_locations=[{"requirement": "a requirement that is not in the PRD",
                                               "locations": ["src/echo.py"]}]),
    ])
    system.run_until_stop(run_id)
    events = [event.type for event in system.store.list_events(run_id)]
    assert EventType.STRUCTURE_ACCEPTED not in events
    rejected = [event for event in system.store.list_events(run_id) if event.type == EventType.PROPOSAL_REJECTED]
    assert any("requirement_locations" in error["field"] for event in rejected for error in event.payload["errors"])

def test_structure_acceptance_refuses_a_changed_workspace_tree(tmp_path):
    # 接纳时核对工作区的树摘要等于快照摘要，不相等时拒绝（设计第 4.1 节）
    from harness.validation import evaluate_proposal

    system, run_id = _onboarding_run(tmp_path, [_product_turn()])
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING", result.phase
    projection = system.project(run_id)
    facts = system.workspace(run_id).snapshot().facts
    proposal = {
        "kind": "structure", "overall": "text",
        "modules": [{"path": "src/", "responsibility": "implementation"}],
        "entry_points": [{"kind": "command_line", "path": "src/echo.py", "how_to_run": "python src/echo.py"}],
        "build_and_test": [{"name": "smoke", "argv": ["python", "src/echo.py"], "purpose": "run the CLI"}],
        "requirement_locations": [{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}],
        "conventions": [],
    }
    changed = facts.model_copy(update={"digest": "sha256:" + "0" * 64})
    decision = evaluate_proposal(phase="ENGINEERING", department="engineering", proposal=proposal,
                                 projection=projection, facts=changed)
    assert not decision.accepted
    assert any("no longer matches the snapshot" in error.message for error in decision.errors)

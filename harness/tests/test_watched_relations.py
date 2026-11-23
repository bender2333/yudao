"""工单 #556 验收第 5 条：关注关系来自组织定义。

在组织定义里去掉工程对「缺陷记录」的关注以后，缺陷记录提交后工程不开始返工：
规则只看定义里写明的关注关系，代码里不写死。
"""
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

from harness import watched_outputs
from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.app.application import Application
from harness.app.home import AwayReportRequest
from harness.app.project_queries import ProjectFlow, ProjectOverview
from harness.definitions import (
    DEFAULT_FORM, DEFINITIONS_DIR, load_definitions,
)
from harness.models import (
    ArtifactRef, DeliverySpec, EffectiveContract, EventType, ProductSpec, QAReview, RunProjection, SessionRecord,
)
from harness.path_rules import QA_TESTS_DIR
from harness.proposals import default_criteria, delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.verification_definitions import INSPECTOR, with_second_delivery_verifier
from harness.tightening import WATCHED_OUTPUTS
from harness.watched_outputs import has_new_work


def _work(department: str) -> RunProjection:
    """一份带有效要求、有效合同与交付的投影：工程交付过一次，质检还没有结论。"""
    projection = RunProjection(run_id="run", task="Build a CLI.")
    projection.sessions[department] = SessionRecord(
        session_id=f"ses_{department}", department=department, status="active")
    projection.product_spec = ProductSpec(
        "spec", "run", 1, None, "spec-hash", "product", "active", "spec-event",
        "CLI", ["Print text"], [], [], ["Text appears"], [], [], [],
        change_record=None, input_version=0,
    )
    projection.effective_contract = EffectiveContract(
        "contract-hash", 1, "spec-hash", 0, [], "contract-event", ArtifactRef("prd", "prd-hash", "PRD.md"),
    )
    projection.delivery_spec = DeliverySpec(
        "delivery", "run", 1, None, "delivery-hash", "engineering", "active", "delivery-event",
        "spec-hash", "contract-hash", "CLI", ["cli.py"], [], [], [],
        "tree-hash", ArtifactRef("tree", "tree-ref", "tree.json"),
    )
    return projection


def _definitions_without_defect_watch(directory: Path) -> object:
    """一份去掉工程对「缺陷记录」关注的组织定义。"""
    shutil.copytree(DEFINITIONS_DIR, directory)
    path = directory / "organization.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    for department in document["departments"]:
        if department["id"] == "engineering":
            department["watched"] = [item for item in department["watched"] if item != "defect_record"]
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def _with_defect_record():
    """一份带交付与缺陷记录的投影：质检对最新交付记了缺陷记录。"""
    projection = _work("quality")
    delivery = projection.delivery_spec
    projection.reviews.append(QAReview(
        id="review", run_id="run", revision=1, parent_hash=None, content_hash="review-hash",
        issuer="quality", status="active", created_event_id="review-event",
        product_spec_hash="spec-hash", effective_contract_hash="contract-hash",
        delivery_spec_hash=delivery.content_hash, code_snapshot_hash="tree-hash",
        verdict="rework_engineering", rationale="命名不符要求", checks=[], defects=[],
        evidence_refs=[],
    ))
    return projection


def test_the_engineering_starts_a_rework_when_the_defect_record_is_watched():
    projection = _with_defect_record()
    assert has_new_work(projection, "engineering")


def test_removing_the_watch_in_the_definition_stops_the_rework(tmp_path, monkeypatch):
    definitions = _definitions_without_defect_watch(tmp_path / "definitions")
    monkeypatch.setattr(watched_outputs, "DEFINITIONS", definitions)
    projection = _with_defect_record()
    assert not has_new_work(projection, "engineering")
    # 只少了这一条关注关系：其它部门的关注关系照旧
    assert definitions.watched_outputs("engineering") == ("product_spec", "guidance")
    assert definitions.watched_outputs("quality") == ("delivery", "guidance", "structure", "product_spec")


def test_a_release_only_consumes_the_watch_of_the_verifier_who_submitted_it():
    # R3：两个核验角色独立关注同一交付；一份结论不能消耗另一条关注关系。
    definition = with_second_delivery_verifier()
    projection = _with_defect_record()
    projection.department_bases = dict.fromkeys(("quality", INSPECTOR), projection.effective_contract.content_hash)
    projection.sessions.clear()
    projection.reviews[0] = replace(projection.reviews[0], verdict="release")

    assert not has_new_work(projection, "quality", definition)
    assert has_new_work(projection, INSPECTOR, definition)

    projection.reviews.append(replace(projection.reviews[0], issuer=INSPECTOR, verdict="rework_engineering"))
    assert has_new_work(projection, "engineering", definition)
    assert not has_new_work(projection, INSPECTOR, definition)


def test_the_complete_feedback_path_rechecks_each_revision_before_reporting_release(tmp_path):
    # R3：两位核验者各用主机运行的真实断言；初版部分通过后打回，新版必须重新获得两份结论。
    executable = sys.executable.replace("\\", "/")
    program = "import runpy; message = runpy.run_path('message.py')['MESSAGE']"
    smoke = {"prints": {"command": f'"{executable}" -c "{program}; assert message"'}}
    uppercase = {"uppercase": {"command": f'"{executable}" -c "{program}; assert message == \'HELLO\'"'}}
    failed = default_criteria(1, list(uppercase), result="failed")

    def first_independent_judgement(call):
        delivery = json.loads(prompt_part(call, "current_delivery_spec"))
        assert "summary" not in delivery and "known_risks" not in delivery
        return judgement_turn(checks=uppercase, criteria=failed)(call)

    script = {
        "product": [product_spec(requirements=["The message is HELLO"], acceptance=["message.py exposes HELLO"])],
        "engineering": [
            delivery_turn("第一版", files={"message.py": "MESSAGE = 'hello'\n"}, checks=smoke),
            delivery_turn("第二版", files={"message.py": "MESSAGE = 'HELLO'\n"}, checks=uppercase),
        ],
        "quality": [judgement_turn(checks=smoke), review_turn("release", "非空", checks=smoke),
                    judgement_turn(checks=uppercase), review_turn("release", "大写正确", checks=uppercase)],
        INSPECTOR: [
            first_independent_judgement,
            review_turn("rework_engineering", "消息不符合大写要求", checks=uppercase, criteria=failed,
                        defects=[{"severity": "major", "summary": "message.py 必须提供 HELLO"}]),
            judgement_turn(checks=uppercase), review_turn("release", "正确", checks=uppercase),
        ],
    }
    definitions = with_second_delivery_verifier()
    system = LoopSystem.for_testing(tmp_path / "feedback", FakeAdapter(script), resume_on_startup=False,
                                    forms={DEFAULT_FORM: (definitions, WATCHED_OUTPUTS)})
    try:
        application = Application(system)
        project_id = system.projects.register("核验反馈", "从命令行检查输出")
        item_id, run_id = system.projects.start_work_item(project_id, "消息必须写成 HELLO")

        def events(kind):
            return [event for event in system.store.list_events(run_id) if event.type == kind]

        def progress():
            query = ProjectOverview(project_id=project_id, work_item=item_id)
            return application.query("project.overview", query).data.work_items[0].progress

        def flow():
            return application.query("project.flow", ProjectFlow(project_id=project_id, work_item=item_id)).data.records

        system.activate_once(run_id)  # 产品合同
        system.activate_once(run_id)  # 交付
        system.activate_once(run_id)  # 质检独立判断
        partial = system.activate_once(run_id)  # 质检结论
        assert partial.status == "running" and partial.last_review.issuer == "quality"
        assert not events(EventType.RUN_DONE)
        assert progress().conclusion is None
        assert not any(row.kind == "放行" for row in flow())
        assert any(row.kind == "核验通过" for row in flow())
        report = application.query("home.away_report", AwayReportRequest(range="24h")).data
        assert "released" not in {item.id for item in report.summary}
        assert all(fact.kind != "release" for fact in report.facts)

        result = system.run_until_stop(run_id)
        assert (result.status, result.stop_reason) == ("done", "released"), result.error
        [first, second] = result.delivery_specs
        reviews = events(EventType.QA_SUBMITTED)
        assert [(event.payload["delivery_spec_hash"], event.department, event.payload["verdict"])
                for event in reviews[:2]] == [(first.content_hash, "quality", "release"),
                                               (first.content_hash, INSPECTOR, "rework_engineering")]
        assert len(reviews) == 4 and {event.department for event in reviews[2:]} == {"quality", INSPECTOR}
        assert reviews[1].payload["checks"][0]["exit_code"] != 0
        assert all(event.payload["checks"][0]["exit_code"] == 0 for event in reviews[2:])
        assert all(event.payload["delivery_spec_hash"] == second.content_hash
                   and event.payload["verdict"] == "release" for event in reviews[2:])
        assert events(EventType.RUN_DONE)[0].position > max(event.position for event in reviews)
        judgements = {event.event_id: event for event in events(EventType.INDEPENDENT_JUDGEMENT_COMMITTED)}
        assert len(judgements) == 4
        assert all(judgements[event.payload["judgement_event"]].department == event.department for event in reviews)
        for event in reviews:
            [check] = event.payload["checks"]
            [observed] = [tool for tool in events(EventType.TOOL_CALLED) if tool.department == event.department
                          and tool.payload.get("activation_id") == check["activation_id"]
                          and tool.payload.get("name") == "run_check"]
            assert observed.payload["output_ref"] in event.payload["evidence_refs"]
        assert result.canonical_state() == system.replay(run_id).canonical_state()
        assert progress().conclusion == "release"
        [released] = [row for row in flow() if row.kind == "放行"]
        assert released.event_id == reviews[-1].event_id
    finally:
        system.close()


def test_a_second_verifier_starts_with_its_own_check_materials(tmp_path):
    # R3：核验者的副本只装配它自己的检查材料，未保存本职能材料时不装配他人的脚本。
    path = f"{QA_TESTS_DIR}/probe.py"
    executable = sys.executable.replace("\\", "/")
    smoke = {"probe": {"command": f'"{executable}" {path}'}}
    first_material = "from pathlib import Path\nassert Path('src/echo.py').is_file()\n"
    no_other_materials = {"isolation": {"command": (
        f'"{executable}" -c "from pathlib import Path; assert not Path(\'{path}\').exists()"')}}

    def first_check(call):
        turn = judgement_turn(checks=smoke)(call)
        return FakeTurn(proposal=turn.proposal, checks=turn.checks, writes={path: first_material})

    script = {"product": [product_spec()], "engineering": [delivery_turn()],
              "quality": [first_check, review_turn("release", "检查通过", checks=smoke)],
              INSPECTOR: [judgement_turn(checks=no_other_materials),
                          review_turn("release", "没有借用其他角色的检查材料", checks=no_other_materials)]}
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(script), resume_on_startup=False,
                                    forms={DEFAULT_FORM: (with_second_delivery_verifier(), WATCHED_OUTPUTS)})
    try:
        run_id = system.create_run("echo")
        system.activate_once(run_id)  # 合同
        system.activate_once(run_id)  # 交付
        system.activate_once(run_id)  # 第一位核验者保存自己的脚本
        system.activate_once(run_id)  # 第一位核验者完成核验
        result = system.run_until_stop(run_id)
        assert (result.status, result.stop_reason) == ("done", "released"), result.error
        [isolation] = [review for review in result.reviews if review.issuer == INSPECTOR]
        assert all(check["exit_code"] == 0 for check in isolation.checks)
        replayed = system.replay(run_id)
        assert result.check_materials_index == replayed.check_materials_index
        assert replayed.check_materials_index and set(replayed.check_materials_index) == {"quality"}
        assert result.canonical_state() == replayed.canonical_state()
    finally:
        system.close()

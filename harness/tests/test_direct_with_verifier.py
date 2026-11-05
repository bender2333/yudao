"""工单 #1396：直做加一个核验角色（形态与核验角色设计说明「直做」第 3 条、「核验角色」、「定义的校验」
最后一段、「验收」第 6、7 条；总图第一节「轮转方式」、第三节「返工」）。

直做路由（`harness/direct.py`）在定义里有核验角色时：指定角色交了完成以后事项**不结束**，等核验角色对
**当前这一版**的结论——放行，事项以放行结束；打回，被核验的角色再开始一轮，它交出的新一版让旧结论失效。
几个核验角色核验同一份时，每一个都放行才算放行，任何一个打回就返工；结论绑定被核验的那一版（内容摘要），
新的一版要重新取得每一个的结论。被核验的角色给自己下结论被拒绝（基础规则 3）。核验本身用三部门质检同一套
（写入范围是检查材料、独立副本、结论绑定当前版本）：路由只问结论，不自己写核验。

测试用的「直做加一个核验角色」定义在 `harness/tests/direct_with_verifier_definitions/`：由发布的那份单角色
直做形态（`harness/definitions/forms/single_role_direct/`）复制，加一个质检部门做核验角色、加一种核验结论的
成果与它的提交工具、把核验声明与写入范围写进组织定义。产品的那份形态一行不改。

层：集成层（有完整循环的用例开真实事件库与真实工作区，模型回答由假模型按部门给出；也有不经循环、只看路由
与收紧检查判断的用例。按分层设计说明第 2 节「一个文件中的测试用到不同层级的资源时，整个文件登记为其中最高
的一层」一起登记为集成层）。

守 R2（合同只增：路由实现用契约第三版已有的可选方法 `use_facts` 读事件，定义一个字段都不加；核验结论是定义
里的一种成果，按现有的通用成果接纳事件写下）与 R3（形态与核验角色：直做加核验角色以后交完成等放行、打回再做
一轮，核验结论绑定当前这一版；没有核验角色的形态仍以开环完成结束）。

先后由事件决定，不用时长赌（测试分层设计说明第 10 节第 7 条）：事项跑完再断言事件；脚本按部门给出。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from harness import direct
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import (DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR, DefinitionError,
                                 VerifiedOutcomes, VerificationDeclaration, VerifierRole, load_definitions)
from harness.direct import (RELEASE_VERDICT, REVIEW_KIND, REWORK_VERDICT, SINGLE_ROLE_DIRECT,
                            check_definition, ready_departments, verification_of_current)
from harness.event_store import project_stream
from harness.models import EventType, ProjectEventType, RunProjection
from harness.proposals import completion_turn
from harness.providers.call import ModelResponse
from harness.routing_contract import InvalidRoutingDefinition
from harness.runtime import LoopSystem
from harness.tightening import WATCHED_OUTPUTS
from harness.validation import TightenRequest
from harness.write_path import NewProjectEvent

GOAL = "做一个可以长期演进的逐行文本处理工具。"
WORK_ITEM = "补一份用法说明"

# 测试用的形态：直做加一个核验角色（名字由这个用例文件给，实例里同时加载的产品形态仍是默认那一份）
FORM = "direct_with_verifier"
FORM_DIRECTORY = Path(__file__).parent / "direct_with_verifier_definitions"
WITH_VERIFIER = load_definitions(FORM_DIRECTORY)
FORMS = {
    DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS),
    FORM: (WITH_VERIFIER, direct.DIRECT_TIGHTENING),
}

ENGINEERING = "engineering"
QUALITY = "quality"
COMPLETION_KIND = "completion"
SUBMIT_REVIEW = "submit_completion_review"
WRITTEN = {"src/echo.py": "import sys\nprint(sys.argv[1])\n"}


# ---------------------------------------------------------------------------
# 夹具：一次事项（项目换成这一份形态以后建事项，写成 #1392 的那条项目事件）
# ---------------------------------------------------------------------------


def _system(data_dir, script: dict[str, list], forms: dict | None = None) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(script), forms=forms or FORMS,
                                  resume_on_startup=False)


def _started(data_dir, script: dict[str, list], *, form: str = FORM,
             forms: dict | None = None) -> tuple[LoopSystem, str, str]:
    system = _system(data_dir, script, forms)
    project_id = system.projects.register("直做加一个核验角色", GOAL)
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET,
        {"previous_form": DEFAULT_FORM, "form": form, "reason": ""}, actor="user:local"))
    work_item_id, run_id = system.projects.start_work_item(project_id, WORK_ITEM)
    return system, work_item_id, run_id


def review_turn(verdict: str, rationale: str):
    # 核验角色的一轮：用直做加核验角色这份定义里的提交工具交结论（假模型的全局对照表认不出这一种成果，
    # 与交完成的那一轮同一个写法）
    proposal = {"verdict": verdict, "rationale": rationale}

    def factory(call):
        identity = f"review-{call.activation_id}-{call.step_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": SUBMIT_REVIEW, "arguments": json.dumps(proposal),
        }])

    return factory


def _events(system: LoopSystem, run_id: str) -> list:
    return list(system.store.list_events(run_id))


def _accepted(system: LoopSystem, run_id: str, kind: str) -> list[dict]:
    return [event.payload for event in _events(system, run_id)
            if event.type == EventType.ARTIFACT_ACCEPTED and event.payload.get("artifact_kind") == kind]


def _run_created(system: LoopSystem, run_id: str) -> dict:
    return next(event.payload for event in _events(system, run_id) if event.type == EventType.RUN_CREATED)


def _run_done(system: LoopSystem, run_id: str):
    return next(event for event in _events(system, run_id) if event.type == EventType.RUN_DONE)


def _departments(system: LoopSystem, run_id: str) -> list[str]:
    return [event.department for event in _events(system, run_id)
            if event.type == EventType.DEPARTMENT_ACTIVATED]


def _positions(system: LoopSystem, run_id: str, wanted: str) -> list[int]:
    return [index for index, event in enumerate(_events(system, run_id)) if event.type == wanted]


# ---------------------------------------------------------------------------
# 验收第 1 条：交完成以后事项不结束；核验角色放行以后以放行结束
# ---------------------------------------------------------------------------


def test_a_completion_does_not_end_the_item_until_the_verifier_releases(tmp_path):
    system, work_item_id, run_id = _started(tmp_path / "release", {
        ENGINEERING: [FakeTurn(writes=WRITTEN, checks={}), completion_turn("补了用法一节")],
        QUALITY: [review_turn(RELEASE_VERDICT, "看过了用法与退出码，可以放行")],
    })
    created = _run_created(system, run_id)
    # 有核验角色核验交完成的那一份：创建时不是开环
    assert (created["form"], created["open_loop"], created["work_item_id"]) == (FORM, False, work_item_id)

    ended = system.run_until_stop(run_id)

    # 事项以放行结束，不写成开环完成
    assert (ended.status, ended.stop_reason) == ("done", "released")
    done = _run_done(system, run_id)
    assert (done.stop_reason, done.payload["stop_reason"], done.department) == (
        "released", "released", QUALITY)
    # 交完成的那一次提交没有结束事项：放行的事件写在它后面，结束事件在放行以后
    completions = _accepted(system, run_id, COMPLETION_KIND)
    reviews = _accepted(system, run_id, REVIEW_KIND)
    assert len(completions) == 1 and len(reviews) == 1
    completion, review = completions[0], reviews[0]
    assert (completion["artifact_issuer"], completion["artifact_version"], completion["summary"]) == (
        ENGINEERING, 1, "补了用法一节")
    assert (review["artifact_issuer"], review["verdict"], review["completion"]) == (
        QUALITY, RELEASE_VERDICT, completion["content_hash"])
    assert review["completion_version"] == completion["artifact_version"]
    # 结束事件在放行那一次接纳之后：交完成那一次没有结束它
    assert _positions(system, run_id, EventType.RUN_DONE)[0] > _positions(system, run_id, EventType.ARTIFACT_ACCEPTED)[-1]
    # 两个角色各一轮：工程交完成、质检给结论
    assert _departments(system, run_id) == [ENGINEERING, QUALITY]


def test_a_rework_sends_the_author_back_and_the_new_version_makes_the_old_conclusion_stale(tmp_path):
    # 打回以后工程再做一轮，交出新的一版；新的一版让上一版的结论不再作数，质检要对新的这一版重新下结论，
    # 全部放行以后事项才结束
    system, _work_item_id, run_id = _started(tmp_path / "rework", {
        ENGINEERING: [FakeTurn(writes=WRITTEN, checks={}), completion_turn("第一版"),
                      FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else '')\n"},
                               checks={}),
                      completion_turn("第二版：退出码补齐了")],
        QUALITY: [review_turn(REWORK_VERDICT, "参数缺省时的退出码没有写"), review_turn(RELEASE_VERDICT, "补齐了")],
    })

    ended = system.run_until_stop(run_id)

    assert (ended.status, ended.stop_reason) == ("done", "released")
    completions = _accepted(system, run_id, COMPLETION_KIND)
    reviews = _accepted(system, run_id, REVIEW_KIND)
    assert [item["summary"] for item in completions] == ["第一版", "第二版：退出码补齐了"]
    assert [item["artifact_version"] for item in completions] == [1, 2]
    first, second = completions
    assert first["content_hash"] != second["content_hash"]
    # 两条结论各自绑定它核验的那一版：第一条对第一版打回，第二条对第二版放行
    assert [(item["verdict"], item["completion"]) for item in reviews] == [
        (REWORK_VERDICT, first["content_hash"]), (RELEASE_VERDICT, second["content_hash"])]
    # 工程被放回来再做一轮：工程、质检、工程、质检四轮
    assert _departments(system, run_id) == [ENGINEERING, QUALITY, ENGINEERING, QUALITY]
    # 新的一版交出去以后，当前这一版的结论只有第二条；第一条对应的是上一版，不再算数
    current = verification_of_current(direct.fold(_events(system, run_id)), WITH_VERIFIER)
    assert [(role, verdict["verdict"], verdict["completion"]) for role, verdict in current] == [
        (QUALITY, RELEASE_VERDICT, second["content_hash"])]


# ---------------------------------------------------------------------------
# 验收第 2 条：两个核验角色核验同一份，一个放行一个打回——事项不结束，进入返工
# ---------------------------------------------------------------------------


# 第二个核验角色：从测试用的那份定义复制一份，加一个复核部门（同一个核验结论工具与合同）
INSPECTOR = "inspector"


def _two_verifier_form(tmp_path) -> object:
    directory = tmp_path / "two_verifiers"
    shutil.copytree(FORM_DIRECTORY, directory)

    def load(name: str) -> dict:
        return json.loads((directory / name).read_text(encoding="utf-8"))

    def save(name: str, data: dict) -> None:
        (directory / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    organization = load("organization.json")
    organization["departments"].append({"id": INSPECTOR, "label": "复核", "roles": [INSPECTOR], "watched": []})
    organization["verification"]["verifiers"].append(
        {"role": INSPECTOR, "verifies": [{"role": ENGINEERING, "outcomes": [COMPLETION_KIND]}]})
    save("organization.json", organization)

    roles = load("roles.json")
    roles[INSPECTOR] = {**roles[QUALITY], "prompt": roles[QUALITY]["prompt"].replace("质检部门", "复核部门")}
    save("roles.json", roles)

    contracts = load("proposal_contracts.json")
    contracts["roles"][INSPECTOR] = contracts["roles"][QUALITY]
    save("proposal_contracts.json", contracts)

    work_items = load("work_items.json")
    work_items["kinds"]["change"]["departments"][INSPECTOR] = work_items["kinds"]["change"]["departments"][QUALITY]
    save("work_items.json", work_items)

    routings = load("routings.json")
    routings["routings"][0]["departments"] = [ENGINEERING, QUALITY, INSPECTOR]
    save("routings.json", routings)
    return load_definitions(directory)


def test_one_release_and_one_rework_keep_the_item_open_and_send_it_back(tmp_path):
    two_verifiers = _two_verifier_form(tmp_path)
    forms = {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), FORM: (two_verifiers, direct.DIRECT_TIGHTENING)}
    system, _work_item_id, run_id = _started(tmp_path / "two", {
        ENGINEERING: [FakeTurn(writes=WRITTEN, checks={}), completion_turn("第一版"),
                      FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else '')\n"},
                               checks={}),
                      completion_turn("第二版")],
        QUALITY: [review_turn(RELEASE_VERDICT, "可以放行"), review_turn(RELEASE_VERDICT, "这一版可以")],
        INSPECTOR: [review_turn(REWORK_VERDICT, "缺省参数的退出码没有写"), review_turn(RELEASE_VERDICT, "补齐了")],
    }, forms=forms)

    ended = system.run_until_stop(run_id)

    # 一个放行一个打回：事项不结束，进入返工——工程再做一轮，交出新的一版
    assert (ended.status, ended.stop_reason) == ("done", "released")
    assert _departments(system, run_id).count(ENGINEERING) == 2
    completions = _accepted(system, run_id, COMPLETION_KIND)
    reviews = _accepted(system, run_id, REVIEW_KIND)
    first, second = completions
    # 第一版上两个人的结论不一样：一个放行、一个打回，谁也没有让事项结束
    on_first = {(item["artifact_issuer"], item["verdict"]) for item in reviews
                if item["completion"] == first["content_hash"]}
    assert on_first == {(QUALITY, RELEASE_VERDICT), (INSPECTOR, REWORK_VERDICT)}
    # 第二版要重新取得每一个的结论：两条都是对第二版的放行
    on_second = [(item["artifact_issuer"], item["verdict"]) for item in reviews
                 if item["completion"] == second["content_hash"]]
    assert sorted(on_second) == [(INSPECTOR, RELEASE_VERDICT), (QUALITY, RELEASE_VERDICT)]
    # 结束发生在两个人的放行都到齐以后
    assert _positions(system, run_id, EventType.RUN_DONE)[0] > _positions(system, run_id, EventType.ARTIFACT_ACCEPTED)[-1]
    assert reviews[-1]["completion"] == second["content_hash"] and reviews[-1]["verdict"] == RELEASE_VERDICT


def test_the_route_waits_for_every_verifier_and_does_not_end_while_one_is_pending(tmp_path):
    # 路由自己的判断（不经完整循环）：两个核验角色里只有一个放了行时还没有结束，两个都放行才结束
    two_verifiers = _two_verifier_form(tmp_path)
    assert two_verifiers.verifiers_of(ENGINEERING, COMPLETION_KIND) == (QUALITY, INSPECTOR)
    completion = _artifact(COMPLETION_KIND, "sha256:completion-1", ENGINEERING)
    release = _artifact(REVIEW_KIND, "sha256:review-1", QUALITY, verdict=RELEASE_VERDICT,
                        completion=completion["content_hash"])
    outcomes = direct.fold([_accepted_event(completion), _accepted_event(release)])
    view = _view()

    # 还有一个没给结论：等它，事项不结束；交完成的角色这时不再开工，等的那个核验角色开工
    assert direct.awaiting_verdict(outcomes, two_verifiers) is True
    assert direct.waiting_verifiers(outcomes, two_verifiers) == {INSPECTOR}
    assert direct.completing_departments(two_verifiers) == (ENGINEERING,)
    assert ready_departments(view, {ENGINEERING, QUALITY, INSPECTOR}, two_verifiers, outcomes) == [INSPECTOR]
    assert direct.item_end(view, two_verifiers, outcomes) is None

    # 第二个打回：不再等结论（交完成的角色再做一轮），事项仍不结束——它有工作要做，所以不走到「以路由
    # 声明的原因结束」那一步
    rework = _artifact(REVIEW_KIND, "sha256:review-2", INSPECTOR, verdict=REWORK_VERDICT,
                       completion=completion["content_hash"])
    reworked = direct.fold([_accepted_event(completion), _accepted_event(release), _accepted_event(rework)])
    assert direct.awaiting_verdict(reworked, two_verifiers) is False
    assert direct.rework_requested(reworked, two_verifiers) is True
    assert ready_departments(view, {ENGINEERING, QUALITY, INSPECTOR}, two_verifiers, reworked) == [ENGINEERING]

    # 两个都放行：结束（放行那一次提交结束事项，路由不再让谁开工）
    inspector_release = _artifact(REVIEW_KIND, "sha256:review-3", INSPECTOR, verdict=RELEASE_VERDICT,
                                  completion=completion["content_hash"])
    released = direct.fold([_accepted_event(completion), _accepted_event(release),
                            _accepted_event(inspector_release)])
    assert direct.awaiting_verdict(released, two_verifiers) is False
    assert ready_departments(view, {ENGINEERING, QUALITY, INSPECTOR}, two_verifiers, released) == []


# ---------------------------------------------------------------------------
# 验收第 3 条：被核验的角色给自己下结论被拒绝
# ---------------------------------------------------------------------------


def test_the_verifier_cannot_verify_itself_and_the_definition_is_rejected_at_load(tmp_path):
    # 核验自己是一条长度为一的环：定义的加载就拒绝（设计说明「定义的校验」第 2 条）
    directory = tmp_path / "self_verifying"
    shutil.copytree(FORM_DIRECTORY, directory)
    organization = json.loads((directory / "organization.json").read_text(encoding="utf-8"))
    organization["verification"]["verifiers"] = [
        {"role": QUALITY, "verifies": [{"role": QUALITY, "outcomes": [REVIEW_KIND]}]},
    ]
    (directory / "organization.json").write_text(
        json.dumps(organization, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        load_definitions(directory)
    except DefinitionError as rejected:  # 逐项写明是哪一项
        assert "角色核验自己" in str(rejected)
    else:  # pragma: no cover - 走不到时让用例失败
        raise AssertionError("a verifier that verifies itself must be rejected")


def test_the_author_of_the_completion_cannot_conclude_on_it():
    # 路由自己判（基础规则 3）：被核验的角色给自己下结论，收紧检查拒绝，并写明原因。
    # 这一条不靠提案合同——那是定义的数据，合同写错的形态也要挡住
    completion = _artifact(COMPLETION_KIND, "sha256:completion-1", ENGINEERING)
    events = (_accepted_event(completion),)
    tightening = direct.DIRECT_TIGHTENING
    request = TightenRequest(
        department=ENGINEERING, state=_view(),
        proposal={"kind": REVIEW_KIND, "verdict": RELEASE_VERDICT, "rationale": "我自己觉得可以"},
        events=events, definitions=WITH_VERIFIER)
    judged = tightening.submission(request)
    assert judged.reason is not None and "handed in this completion" in judged.reason
    # 核验角色给结论就走得通，并且放行结束事项
    allowed = tightening.submission(TightenRequest(
        department=QUALITY, state=_view(),
        proposal={"kind": REVIEW_KIND, "verdict": RELEASE_VERDICT, "rationale": "看过了"},
        events=events, definitions=WITH_VERIFIER))
    assert (allowed.reason, allowed.errors, allowed.ends_run) == (None, (), True)
    assert allowed.content["completion"] == completion["content_hash"]


# ---------------------------------------------------------------------------
# 缝上的另几处：结论只对提交时当前的那一版有效、结论的形状、等结论时交不了新的完成
# ---------------------------------------------------------------------------


def test_a_verdict_binds_the_version_that_is_current_when_it_is_submitted():
    # 同一版不能下两次结论（要等作者交出新的一版）；作者交出新的一版以后，对上一版的结论不再作数
    first = _artifact(COMPLETION_KIND, "sha256:completion-1", ENGINEERING)
    second = _artifact(COMPLETION_KIND, "sha256:completion-2", ENGINEERING, version=2)
    early = _artifact(REVIEW_KIND, "sha256:review-1", QUALITY, verdict=REWORK_VERDICT,
                      completion=first["content_hash"])
    outcomes = direct.fold([_accepted_event(first), _accepted_event(early), _accepted_event(second)])
    # 新的一版交上来以后，质检要重新下结论；对上一版的结论不算在当前这一版上
    assert direct.awaiting_verdict(outcomes, WITH_VERIFIER) is True
    assert direct.waiting_verifiers(outcomes, WITH_VERIFIER) == {QUALITY}
    assert direct.rework_requested(outcomes, WITH_VERIFIER) is False
    # 同一版再交一次结论被拒绝（写明要等新的一版）
    repeated = direct.DIRECT_TIGHTENING.submission(TightenRequest(
        department=QUALITY, state=_view(),
        proposal={"kind": REVIEW_KIND, "verdict": RELEASE_VERDICT, "rationale": "再看一遍"},
        events=(_accepted_event(first), _accepted_event(early)),
        definitions=WITH_VERIFIER))
    assert repeated.reason is not None and "a new version" in repeated.reason


def test_a_verdict_needs_a_known_verdict_value_and_a_reason():
    completion = _artifact(COMPLETION_KIND, "sha256:completion-1", ENGINEERING)
    events = (_accepted_event(completion),)
    for proposal, field_name in (
        ({"kind": REVIEW_KIND, "verdict": "maybe", "rationale": "像是不错"}, "verdict"),
        ({"kind": REVIEW_KIND, "verdict": RELEASE_VERDICT, "rationale": "  "}, "rationale"),
    ):
        judged = direct.DIRECT_TIGHTENING.submission(TightenRequest(
            department=QUALITY, state=_view(), proposal=proposal,
            events=events, definitions=WITH_VERIFIER))
        assert [error.field for error in judged.errors] == [field_name]


def test_the_author_cannot_hand_in_another_version_while_the_conclusion_is_pending():
    completion = _artifact(COMPLETION_KIND, "sha256:completion-1", ENGINEERING)
    events = (_accepted_event(completion),)
    judged = direct.DIRECT_TIGHTENING.submission(TightenRequest(
        department=ENGINEERING, state=_view(),
        proposal={"kind": COMPLETION_KIND, "summary": "又改了一版"},
        events=events, definitions=WITH_VERIFIER))
    assert judged.reason is not None and "waiting for the verifier" in judged.reason


# ---------------------------------------------------------------------------
# 定义：这一份形态的形状与加载校验；没有核验角色的形态照旧以开环完成结束
# ---------------------------------------------------------------------------


def test_the_form_declares_one_verifier_with_the_check_material_write_scope():
    organization = WITH_VERIFIER.organization
    assert WITH_VERIFIER.departments == (ENGINEERING, QUALITY)
    assert WITH_VERIFIER.verifiers_of(ENGINEERING, COMPLETION_KIND) == (QUALITY,)
    assert WITH_VERIFIER.verifier_roles() == (QUALITY,)
    # 写入范围是检查材料：它写的东西只进检查材料，不让被核验方的成果失效（设计说明第 4.2 节第 1 条）
    scope = organization.verification.write_scopes[QUALITY]
    assert (scope.scope, scope.paths) == ("check_materials", (".yudao-qa-tests",))
    # 核验结论是这份路由认得的一种成果，由核验角色的提交工具提交
    assert REVIEW_KIND in WITH_VERIFIER.outcomes_of("direct")
    assert direct.proposal_kinds_for(QUALITY, "change", WITH_VERIFIER) == {REVIEW_KIND}
    assert direct.completing_departments(WITH_VERIFIER) == (ENGINEERING,)
    # 有核验角色核验最后采纳的那一份：事项不是开环
    assert WITH_VERIFIER.is_open_loop(COMPLETION_KIND) is False
    check_definition(WITH_VERIFIER)


def test_a_verifier_that_cannot_submit_a_conclusion_is_rejected_at_load():
    # 核验角色交不了结论时事项交完成以后等不到放行：加载时整份拒绝，不等到运行到上限才发现
    without = WITH_VERIFIER.model_copy(update={
        "proposal_contracts": WITH_VERIFIER.proposal_contracts.model_copy(update={
            "roles": {**WITH_VERIFIER.proposal_contracts.roles,
                      QUALITY: WITH_VERIFIER.proposal_contracts.roles[QUALITY].model_copy(
                          update={"kinds": {}})},
        }),
    })
    try:
        check_definition(without)
    except InvalidRoutingDefinition as rejected:
        assert any(REVIEW_KIND in issue for issue in rejected.issues)
    else:  # pragma: no cover
        raise AssertionError("a verifier that cannot hand in a conclusion must be rejected")


def test_a_verifier_of_a_role_that_cannot_hand_in_the_completion_is_rejected_at_load():
    # 核验的对象交不了那一份完成：这个核验角色永远没有可以核验的那一版
    broken = WITH_VERIFIER.model_copy(update={
        "organization": WITH_VERIFIER.organization.model_copy(update={
            "verification": VerificationDeclaration(verifiers=(
                VerifierRole(role=QUALITY, verifies=(
                    VerifiedOutcomes(role=QUALITY, outcomes=(COMPLETION_KIND,)),)),),
                write_scopes=WITH_VERIFIER.organization.verification.write_scopes),
        }),
    })
    try:
        check_definition(broken)
    except InvalidRoutingDefinition as rejected:
        assert any("交不了" in issue for issue in rejected.issues)
    else:  # pragma: no cover
        raise AssertionError("a verifier of a role that cannot hand in the completion must be rejected")


def test_the_single_role_direct_form_still_ends_open_loop_without_a_verifier():
    # 没有核验角色的那一份形态不受影响：交完成以开环完成结束（工单 #1395 的行为照旧）
    single = load_definitions(DEFINITIONS_DIR / "forms" / SINGLE_ROLE_DIRECT)
    assert single.verifier_roles() == ()
    assert single.is_open_loop(COMPLETION_KIND) is True
    assert direct.awaiting_verdict(direct.NO_OUTCOMES, single) is False
    assert direct.verified_outcome(ENGINEERING, single) is False


# ---------------------------------------------------------------------------
# 小工具：手工造事件与视图（不经完整循环的用例用）
# ---------------------------------------------------------------------------


def _artifact(kind: str, content_hash: str, issuer: str, **extra) -> dict:
    return {"artifact_kind": kind, "content_hash": content_hash, "artifact_issuer": issuer,
            "artifact_version": extra.pop("version", 1), **extra}


def _accepted_event(payload: dict):
    return SimpleNamespace(type=EventType.ARTIFACT_ACCEPTED, payload=payload)


def _view():
    # 一条已经处理过的输入：没有新的输入，开工名单只看「等结论」这一条（角色的会话状态由 waiting 参数给出）
    view = RunProjection(run_id="run", task=WORK_ITEM)
    view.input_version = 1
    view.processed_input_version = 1
    return view

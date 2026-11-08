"""工单 #1454：几个角色直做——工程接输入并交完成，产品只回答询问，可加回质检做核验角色。

依据：docs/design/forms-and-verifier-role.md「直做」「开环完成」「形态随事项冻结」「验收」第 6 条；
总图第一节「轮转方式」、第四节「路由」「定义」缝。形态在 harness/definitions/forms/several_roles_direct/：
产品与工程两个自有角色，用这两个部门的名字、工具与模型设置（模型按部门设置解析，定义里不另加模型设置）；
你的输入与建档都由工程接，工程交完成，产品只在收到询问时开始工作、回答需求的边界与取舍；没有核验角色，
事项以开环完成结束。同一份定义加回质检做核验角色（测试里按本项目的改动那样补上质检的角色材料）时，
工程交完成以后等结论：放行才结束，打回则工程再做一轮。

层：集成层（每一条都开真实事件库与真实工作区，跑完整的部门循环；模型的回答由假模型按部门给出）。
守 R3（直做与开环完成、询问、形态随事项冻结：两个角色一份定义，产品只在收到询问时开始工作，加核验角色
以后等结论）与 R2（定义的格式只增：新形态只新增一份定义目录，发布的三部门定义与它的事件序列不动）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness import direct
from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.definitions import (DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR, Department, OutcomeKind,
                                 VerificationDeclaration, VerifiedOutcomes, VerifierRole, WriteScope,
                                 load_definitions)
from harness.direct import (COMPLETION_KIND, DIRECT_TIGHTENING, REVIEW_KIND, RELEASE_VERDICT,
                            REWORK_VERDICT, SINGLE_ROLE_DIRECT)
from harness.event_store import project_stream
from harness.models import EventType, ProjectEventType
from harness.path_rules import CHECK_MATERIALS_DIR
from harness.proposals import answer_turn, ask_turn, completion_turn
from harness.providers.call import ModelResponse
from harness.runtime import FORM_REGISTRY, SEVERAL_ROLES_DIRECT, LoopSystem
from harness.tests.helpers import happy_script
from harness.tightening import WATCHED_OUTPUTS
from harness.write_path import NewProjectEvent

GOAL = "做一个可以长期演进的逐行文本处理工具。"
WORK_ITEM = "补一份用法说明"

PRODUCT = "product"
ENGINEERING = "engineering"
QUALITY = "quality"

# 形态的定义目录（与 runtime.FORM_REGISTRY 登记的那一份同一个来源）
FORM_DIRECTORY = DEFINITIONS_DIR / "forms" / SEVERAL_ROLES_DIRECT
SEVERAL_ROLES = load_definitions(FORM_DIRECTORY)
FORMS = {
    DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS),
    SEVERAL_ROLES_DIRECT: (SEVERAL_ROLES, DIRECT_TIGHTENING),
}

WRITTEN = {"src/echo.py": "import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else '')\n"}

# 质检的角色材料与核验结论工具取自 #1396 建的测试形态（与发布的三部门质检同一套）：
# 这份形态发布时不带质检；加回它做核验角色时，除部门与核验声明以外用的就是这一份材料
WITH_VERIFIER_FIXTURE = load_definitions(Path(__file__).parent / "direct_with_verifier_definitions")
QUALITY_ROLE = WITH_VERIFIER_FIXTURE.roles[QUALITY]
SUBMIT_REVIEW = "submit_completion_review"
REVIEW_TOOL = WITH_VERIFIER_FIXTURE.tools[SUBMIT_REVIEW]
REVIEW_CONTRACT = WITH_VERIFIER_FIXTURE.proposal_contracts.roles[QUALITY]


def _with_quality_verifier() -> Any:
    """同一份定义加回质检做核验角色：只补部门、核验声明与核验结论那一样。

    本项目的改动（project-organization 设计说明）还没有合成这一层实现，这里按它以后的样子从发布的那一份
    定义复制一份：部门加质检，核验声明写质检核验工程交完成的那一份，路由的部门清单与提议方式跟着多一样，
    成果种类多出核验结论。其余内容（产品与工程的角色材料、工具、文档、路由）一个字不改。
    """
    declared = SEVERAL_ROLES.routing_definition()
    several_departments = {department.id for department in SEVERAL_ROLES.organization.departments}
    quality = Department(id=QUALITY, label=DEFINITIONS.department_labels[QUALITY], roles=(QUALITY,), watched=())
    organization = SEVERAL_ROLES.organization.model_copy(update={
        "departments": (*SEVERAL_ROLES.organization.departments, quality),
        "verification": VerificationDeclaration(
            verifiers=(VerifierRole(role=QUALITY, verifies=(
                VerifiedOutcomes(role=ENGINEERING, outcomes=(COMPLETION_KIND,)),)),),
            write_scopes={QUALITY: WriteScope(scope="check_materials", paths=(CHECK_MATERIALS_DIR,))}),
    })
    routing = declared.model_copy(update={
        "departments": (*declared.departments, QUALITY),
        "proposal_methods": (*declared.proposal_methods, SUBMIT_REVIEW),
    })
    review_kind = OutcomeKind(id=REVIEW_KIND, label="核验结论",
                              why="核验角色对工程交完成的当前这一版的结论：放行或打回")
    group = SEVERAL_ROLES.outcome_kinds.groups[0].model_copy(
        update={"kinds": (*SEVERAL_ROLES.outcome_kinds.groups[0].kinds, REVIEW_KIND)})
    outcome_kinds = SEVERAL_ROLES.outcome_kinds.model_copy(
        update={"kinds": (*SEVERAL_ROLES.outcome_kinds.kinds, review_kind), "groups": (group,)})
    assert several_departments == {PRODUCT, ENGINEERING}
    return SEVERAL_ROLES.model_copy(update={
        "version": "sha256:several-roles-direct-with-quality",
        "organization": organization,
        "roles": {**SEVERAL_ROLES.roles, QUALITY: QUALITY_ROLE},
        "tools": {**SEVERAL_ROLES.tools, SUBMIT_REVIEW: REVIEW_TOOL},
        "proposal_contracts": SEVERAL_ROLES.proposal_contracts.model_copy(
            update={"roles": {**SEVERAL_ROLES.proposal_contracts.roles, QUALITY: REVIEW_CONTRACT}}),
        "routings": SEVERAL_ROLES.routings.model_copy(update={"routings": (routing,)}),
        "outcome_kinds": outcome_kinds,
    })


WITH_VERIFIER = _with_quality_verifier()


# ---------------------------------------------------------------------------
# 夹具：项目换成几个角色直做以后建一个事项（#1392 的那条项目事件，与 #1402 的命令同一个落点）
# ---------------------------------------------------------------------------


def _system(data_dir: Path, script: dict[str, list[Any]], forms: dict[str, Any] | None = None) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(script), forms=forms or FORMS,
                                  resume_on_startup=False)


def _switched_to(data_dir: Path, script: dict[str, list[Any]], *, form: str = SEVERAL_ROLES_DIRECT,
                 forms: dict[str, Any] | None = None) -> tuple[LoopSystem, str, str]:
    system = _system(data_dir, script, forms)
    project_id = system.projects.register("几个角色直做", GOAL)
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET,
        {"previous_form": DEFAULT_FORM, "form": form, "reason": ""}, actor="user:local"))
    work_item_id, run_id = system.projects.start_work_item(project_id, WORK_ITEM)
    return system, work_item_id, run_id


def _events(system: LoopSystem, run_id: str) -> list[Any]:
    return list(system.store.list_events(run_id))


def _of_type(system: LoopSystem, run_id: str, *types: str) -> list[Any]:
    wanted = set(types)
    return [event for event in _events(system, run_id) if event.type in wanted]


def _run_created(system: LoopSystem, run_id: str) -> dict[str, Any]:
    return next(event.payload for event in _events(system, run_id) if event.type == EventType.RUN_CREATED)


def _run_done(system: LoopSystem, run_id: str) -> Any:
    return next(event for event in _events(system, run_id) if event.type == EventType.RUN_DONE)


def _activations(system: LoopSystem, run_id: str) -> list[str]:
    return [event.department for event in _of_type(system, run_id, EventType.DEPARTMENT_ACTIVATED)]


def _accepted(system: LoopSystem, run_id: str, kind: str) -> list[dict[str, Any]]:
    return [event.payload for event in _of_type(system, run_id, EventType.ARTIFACT_ACCEPTED)
            if event.payload.get("artifact_kind") == kind]


def _positions(system: LoopSystem, run_id: str, wanted: str) -> list[int]:
    return [index for index, event in enumerate(_events(system, run_id)) if event.type == wanted]


def _engineering_asks_then_completes() -> dict[str, list[Any]]:
    # 工程的一轮里先问产品，回答回来以后写文件、交完成；产品的一轮只有回答
    return {
        ENGINEERING: [
            ask_turn(PRODUCT, "输出要不要固定为一行？", background="用户原文只说了逐行处理。",
                     expected="固定取舍与理由", call_id="ask-eng-1"),
            FakeTurn(writes=WRITTEN, checks={}),
            completion_turn("按产品回答固定了一行输出", uncertain=["退出码没有写全"]),
        ],
        PRODUCT: [answer_turn("固定为一行：逐行处理，去掉每行末尾的空白。", call_id="ans-1")],
    }


# ---------------------------------------------------------------------------
# 验收第 1 条：工程先开工，询问产品得到回答，交完成；以开环完成结束，没有质检结论、没有决定请求
# ---------------------------------------------------------------------------


def test_engineering_asks_product_and_the_item_ends_open_loop(tmp_path):
    system, work_item_id, run_id = _switched_to(tmp_path / "open_loop", _engineering_asks_then_completes())
    created = _run_created(system, run_id)
    # 创建时按冻结的定义标为开环：最后采纳交完成那一份，没有核验角色核验它（#1394）
    assert (created["form"], created["open_loop"], created["work_item_id"]) == (
        SEVERAL_ROLES_DIRECT, True, work_item_id)

    ended = system.run_until_stop(run_id)

    # 结果是完成，结束原因是开环完成，不写成放行
    assert (ended.status, ended.stop_reason) == ("done", "open_loop")
    done = _run_done(system, run_id)
    assert (done.stop_reason, done.payload["stop_reason"], done.state_after) == (
        "open_loop", "open_loop", "done")
    # 交上来的完成被采纳：作者是工程，说明与拿不准的地方留在内容里；产品没有提交任何成果
    completions = _accepted(system, run_id, COMPLETION_KIND)
    assert len(completions) == 1
    completion = completions[0]
    assert (completion["artifact_issuer"], completion["summary"], completion["uncertain"]) == (
        ENGINEERING, "按产品回答固定了一行输出", ["退出码没有写全"])
    assert _accepted(system, run_id, REVIEW_KIND) == []
    # 询问确实发生：工程问、产品答，回答写在事实里
    asked = _of_type(system, run_id, EventType.ASK_STARTED)
    assert [(event.payload["requester"], event.payload["recipient"]) for event in asked] == [
        (ENGINEERING, PRODUCT)]
    answered = _of_type(system, run_id, EventType.ASK_ANSWERED)
    assert [(event.payload["status"], event.payload["recipient"], event.payload["answer"]) for event in answered] == [
        ("answered", PRODUCT, "固定为一行：逐行处理，去掉每行末尾的空白。")]
    # 开环完成不发决定请求；事件里没有质检结论，也没有质检这个部门的任何事件
    assert _of_type(system, run_id, EventType.DECISION_REQUESTED) == []
    assert _of_type(system, run_id, EventType.QA_SUBMITTED) == []
    assert {event.department for event in _events(system, run_id)} <= {PRODUCT, ENGINEERING, None}


def test_the_product_works_only_when_engineering_asks(tmp_path):
    # 验收第 3 条：产品没有待处理的输入，也不关注任何成果；它开始工作只能是因为工程问了它
    system, _work_item_id, run_id = _switched_to(tmp_path / "only_on_ask", _engineering_asks_then_completes())
    system.run_until_stop(run_id)
    events = _events(system, run_id)
    ask_at = _positions(system, run_id, EventType.ASK_STARTED)[0]
    product_events = [index for index, event in enumerate(events) if event.department == PRODUCT]
    # 询问以前没有产品的任何事件；产品被激活的一次在询问之后，而且正好是询问分支的那一轮
    assert product_events and min(product_events) > ask_at
    assert _activations(system, run_id) == [ENGINEERING, PRODUCT]
    assert _positions(system, run_id, EventType.DEPARTMENT_ACTIVATED)[1] > ask_at
    # 回答以后工程接着工作，完成在回答之后
    assert _positions(system, run_id, EventType.ASK_ANSWERED)[0] < _positions(
        system, run_id, EventType.ARTIFACT_ACCEPTED)[-1]


# ---------------------------------------------------------------------------
# 验收第 2 条：同一份定义加回质检做核验角色，交完成以后等结论；放行才结束，打回则工程再做一轮
# ---------------------------------------------------------------------------


def review_turn(verdict: str, rationale: str) -> Any:
    # 核验角色的一轮：用核验结论的提交工具交结论（与 #1396 的用例同一个写法）
    def factory(call: Any) -> ModelResponse:
        identity = f"review-{call.activation_id}-{call.step_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": SUBMIT_REVIEW, "arguments": json.dumps({"verdict": verdict, "rationale": rationale}),
        }])

    return factory


def test_the_same_definition_with_quality_added_is_a_valid_direct_definition():
    # 加回质检以后仍是一份合法的直做定义：质检核验工程交完成的那一份，最后采纳的那一份因此不再是开环；
    # 发布的那一份（没有核验角色）照旧是开环，两个判断都由同一份定义的核验声明得出
    direct.check_definition(WITH_VERIFIER)
    assert WITH_VERIFIER.verifiers_of(ENGINEERING, COMPLETION_KIND) == (QUALITY,)
    assert WITH_VERIFIER.is_open_loop(COMPLETION_KIND) is False
    assert SEVERAL_ROLES.verifier_roles() == ()
    assert SEVERAL_ROLES.is_open_loop(COMPLETION_KIND) is True
    assert WITH_VERIFIER.roles[PRODUCT] == SEVERAL_ROLES.roles[PRODUCT]
    assert WITH_VERIFIER.roles[ENGINEERING] == SEVERAL_ROLES.roles[ENGINEERING]


def test_with_quality_as_verifier_the_item_waits_for_a_release(tmp_path):
    forms = {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), SEVERAL_ROLES_DIRECT: (WITH_VERIFIER, DIRECT_TIGHTENING)}
    system, _work_item_id, run_id = _switched_to(tmp_path / "release", {
        ENGINEERING: [FakeTurn(writes=WRITTEN, checks={}), completion_turn("补了用法一节")],
        QUALITY: [review_turn(RELEASE_VERDICT, "看过了用法与退出码，可以放行")],
    }, forms=forms)
    created = _run_created(system, run_id)
    # 有核验角色核验交完成的那一份：创建时不是开环
    assert (created["form"], created["open_loop"]) == (SEVERAL_ROLES_DIRECT, False)

    ended = system.run_until_stop(run_id)

    # 事项以放行结束；交完成那一次没有结束它，结束事件在结论之后
    assert (ended.status, ended.stop_reason) == ("done", "released")
    assert _run_done(system, run_id).stop_reason == "released"
    completions = _accepted(system, run_id, COMPLETION_KIND)
    reviews = _accepted(system, run_id, REVIEW_KIND)
    assert len(completions) == 1 and len(reviews) == 1
    assert (reviews[0]["artifact_issuer"], reviews[0]["verdict"]) == (QUALITY, RELEASE_VERDICT)
    assert reviews[0]["completion"] == completions[0]["content_hash"]
    assert _positions(system, run_id, EventType.RUN_DONE)[0] > _positions(
        system, run_id, EventType.ARTIFACT_ACCEPTED)[-1]
    assert _activations(system, run_id) == [ENGINEERING, QUALITY]


def test_a_rework_makes_engineering_do_another_round(tmp_path):
    forms = {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), SEVERAL_ROLES_DIRECT: (WITH_VERIFIER, DIRECT_TIGHTENING)}
    system, _work_item_id, run_id = _switched_to(tmp_path / "rework", {
        ENGINEERING: [FakeTurn(writes=WRITTEN, checks={}), completion_turn("第一版"),
                      FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}, checks={}),
                      completion_turn("第二版：退出码补齐了")],
        QUALITY: [review_turn(REWORK_VERDICT, "参数缺省时的退出码没有写"),
                  review_turn(RELEASE_VERDICT, "补齐了")],
    }, forms=forms)

    ended = system.run_until_stop(run_id)

    # 打回以后工程再做一轮，交出新的一版；新的一版让旧结论不再作数，质检重新下结论，放行才结束
    assert (ended.status, ended.stop_reason) == ("done", "released")
    completions = _accepted(system, run_id, COMPLETION_KIND)
    reviews = _accepted(system, run_id, REVIEW_KIND)
    assert [(item["summary"], item["artifact_version"]) for item in completions] == [
        ("第一版", 1), ("第二版：退出码补齐了", 2)]
    assert [(item["completion"], item["verdict"]) for item in reviews] == [
        (completions[0]["content_hash"], REWORK_VERDICT), (completions[1]["content_hash"], RELEASE_VERDICT)]
    assert _activations(system, run_id) == [ENGINEERING, QUALITY, ENGINEERING, QUALITY]


def test_with_quality_as_verifier_the_copy_is_the_sealed_completion_and_facts_come_first(tmp_path):
    # 工单 #1579：几个角色直做加回质检，质检的检查副本从交完成封存的那一版建立，
    # 材料里有那一版的树与回执，没有工程写的说明与拿不准的地方（下结论以前）
    seen: list[Any] = []
    box: dict[str, Any] = {}

    def observing(call: Any) -> ModelResponse:
        system, run_id = box["system"], box["run_id"]
        system.workspace(run_id).write_file("src/echo.py", "print('after completion')\n")
        tree = system.orchestrator._workspaces.source_tree(QUALITY, system.project(run_id))
        seen.append(({item.path: item.data.decode() for item in tree.files},
                     json.loads(prompt_part(call, "verified_outcome") or "null")))
        return review_turn(RELEASE_VERDICT, "可以放行")(call)

    forms = {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), SEVERAL_ROLES_DIRECT: (WITH_VERIFIER, DIRECT_TIGHTENING)}
    system, _work_item_id, run_id = _switched_to(tmp_path / "sealed", {
        ENGINEERING: [FakeTurn(writes=WRITTEN, checks={}), completion_turn("补了用法一节", uncertain=["退出码"])],
        QUALITY: [observing],
    }, forms=forms)
    box.update(system=system, run_id=run_id)

    assert system.run_until_stop(run_id).stop_reason == "released"
    ((tree, outcome),) = seen
    completion = _accepted(system, run_id, COMPLETION_KIND)[0]
    assert tree == WRITTEN
    assert outcome["tree_digest"] == completion["artifact_tree_digest"]
    assert "explanation" not in outcome and "uncertain" not in outcome


# ---------------------------------------------------------------------------
# 形态本身：两个自有角色、没有核验角色、用这两个部门的工具与内核表、两种来源都由工程接
# ---------------------------------------------------------------------------


def test_the_form_declares_product_and_engineering_and_no_verifier():
    organization = SEVERAL_ROLES.organization
    assert SEVERAL_ROLES.departments == (PRODUCT, ENGINEERING)
    assert SEVERAL_ROLES.department_labels[PRODUCT] == DEFINITIONS.department_labels[PRODUCT]
    assert SEVERAL_ROLES.department_labels[ENGINEERING] == DEFINITIONS.department_labels[ENGINEERING]
    # 「你的输入」与「建档」都由工程接（来源的写法见 #1455）
    assert dict(organization.sources) == {"user_input": ENGINEERING, "onboarding": ENGINEERING}
    # 没有核验角色：事项最后采纳的成果没有人核验，创建时标为开环；路由的最后采纳是交完成
    assert SEVERAL_ROLES.verifier_roles() == ()
    assert SEVERAL_ROLES.is_open_loop(COMPLETION_KIND) is True
    declared = SEVERAL_ROLES.routing_definition()
    assert (declared.id, declared.final_outcome) == (direct.ROUTING_NAME, COMPLETION_KIND)
    assert declared.departments == (PRODUCT, ENGINEERING)


def test_the_form_uses_the_roles_and_tools_of_those_departments():
    # 工程：发布的工程工具去掉交交付（这一份以交完成结束），加上交完成；产品：去掉两种提交工具，
    # 其余读、查、问的工具照旧。工具定义逐项与发布的那一份相同，问的工具只把收件人改成本形态的部门
    product = DEFINITIONS.roles[PRODUCT]
    engineering = DEFINITIONS.roles[ENGINEERING]
    assert set(SEVERAL_ROLES.roles[PRODUCT].tools) == set(product.tools) - {
        "submit_product_spec", "submit_product_decision"}
    assert set(SEVERAL_ROLES.roles[ENGINEERING].tools) == (set(engineering.tools) - {"submit_delivery"}) | {
        "submit_completion"}
    granted = set(SEVERAL_ROLES.roles[PRODUCT].tools) | set(SEVERAL_ROLES.roles[ENGINEERING].tools)
    for name in granted:
        if name == "ask" or name not in DEFINITIONS.tools:
            continue
        assert SEVERAL_ROLES.tools[name] == DEFINITIONS.tools[name]
    assert SEVERAL_ROLES.tools["ask"].parameters["properties"]["recipient"]["enum"] == (PRODUCT, ENGINEERING)
    # 浏览器工具是单独一份生成的定义：两份逐字节相同，不各写一份
    assert (FORM_DIRECTORY / "browser_tools.json").read_bytes() == (
        DEFINITIONS_DIR / "browser_tools.json").read_bytes()
    # 可见范围与发布的那份相同；模型按各自部门的设置解析（定义里不另加模型设置）
    assert SEVERAL_ROLES.roles[PRODUCT].visibility == product.visibility
    assert SEVERAL_ROLES.roles[ENGINEERING].visibility == engineering.visibility


def test_the_form_carries_the_kernel_tables_unchanged():
    # 停止原因是内核的封闭清单、事件来源按事件种类给出：两份定义里这两张表相同（形态不另写一份）
    assert SEVERAL_ROLES.stop_reasons == DEFINITIONS.stop_reasons
    assert SEVERAL_ROLES.event_sources == DEFINITIONS.event_sources


def test_the_role_materials_say_who_starts_and_who_answers():
    # 角色材料按「开环完成」第 3 条写倾向：工程能补全的就继续，拿不准的列进交完成的说明；
    # 产品写明自己不主动开工，只在工程询问时回答需求的边界与取舍
    engineering = SEVERAL_ROLES.roles[ENGINEERING].prompt
    for phrase in ("能按项目约定与常见做法补全的就继续", "拿不准的地方列进交完成的说明",
                   "只有目标本身读不通", "开环完成"):
        assert phrase in engineering
    product = SEVERAL_ROLES.roles[PRODUCT].prompt
    assert "不主动开工" in product and "询问" in product and "边界与取舍" in product


# ---------------------------------------------------------------------------
# 验收第 4 条：同一个实例里三部门事项照旧；发布带的形态清单多一份，默认仍是三部门
# ---------------------------------------------------------------------------


class _NoEvents:
    # 接形态时要交的事件库：登记处这一条用例只接上路由，不读事件（直做声明了 use_facts，工单 #1396）
    def list_events(self, run_id: str) -> list[Any]:
        return []


def test_all_three_forms_are_registered_and_the_release_keeps_the_default():
    from harness.runtime import load_forms

    assert set(FORM_REGISTRY) == {DEFAULT_FORM, SINGLE_ROLE_DIRECT, SEVERAL_ROLES_DIRECT}
    forms = load_forms(FORM_REGISTRY, store=_NoEvents())
    assert forms[DEFAULT_FORM].definitions.routing == "watched_outputs"
    several = forms[SEVERAL_ROLES_DIRECT]
    assert several.definitions.routing == direct.ROUTING_NAME
    assert type(several.routing).__name__ == "Direct"
    assert type(several.tightening).__name__ == "DirectTightening"
    # 默认那份定义的成果种类与提议方式不变：几个角色直做没有往发布的那一份定义里加东西
    assert [tool.proposal for tool in DEFINITIONS.tools.values() if tool.proposal] == [
        "product_spec", "product_decision", "delivery_spec", "qa_review", "structure", "baseline_review",
        "independent_judgement"]


def test_the_three_departments_still_end_with_a_release_in_the_same_instance(tmp_path):
    # 同一份实例里两份形态都在：三部门的事项照旧以放行结束（默认定义、默认路由与默认收紧检查一行不改；
    # 事件序列基准由 test_event_sequence.py 守住，这里核对它没有被新形态带走）
    system = _system(tmp_path / "default_form", happy_script())
    project_id = system.projects.register("三部门", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, WORK_ITEM)

    ended = system.run_until_stop(run_id)

    created = _run_created(system, run_id)
    assert (created["form"], created["open_loop"]) == (DEFAULT_FORM, False)
    assert (ended.status, ended.stop_reason) == ("done", "released")
    assert _run_done(system, run_id).stop_reason == "released"
    accepted_kinds = {event.payload.get("artifact_kind")
                      for event in _of_type(system, run_id, EventType.ARTIFACT_ACCEPTED)}
    assert COMPLETION_KIND not in accepted_kinds

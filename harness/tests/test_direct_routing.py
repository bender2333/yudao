"""工单 #1395：直做路由与单角色直做形态（形态与核验角色设计说明「直做」「开环完成」「形态随事项冻结」；
骨架与应用设计说明「路由契约」「第二种路由：骨架要满足的条件」；总图第一节「轮转方式」、第四节「路由」缝）。

两件事：

- 直做路由（`harness/direct.py`）：有用户输入或指导时没有在工作的角色开始一轮；角色之间的询问照现有规矩；
  定义里指定的角色交了完成，事项结束。没有核验角色核验它时结束原因是开环完成——路由按事项创建事件里记下的
  开环标记给出（#1394 的做法），薄驱动只把它写进事实。交完成以前能交完成的角色可以一轮接一轮地工作，
  到内核的上限会停（停止原因来自封闭清单）。路由按骨架的七条接上，骨架文件一行不改。
- 单角色直做形态（`harness/definitions/forms/single_role_direct/`，在 `harness/runtime.py` 的形态登记处登记）：
  一个工程角色，用工程这个部门的名字、工具与模型设置（模型按部门的设置解析，定义里不另加），你的输入与建档
  都由它接，带一个交完成的提议方式，没有核验角色；角色材料按「开环完成」第 3 条写倾向：能按项目约定补全的
  就继续，拿不准的列进交完成的说明。

层：集成层（有完整循环的用例开真实事件库与真实工作区，模型回答由假模型按部门给出；也有不经循环、只看路由
判断的用例。按分层 docs/design/test-pyramid.md「三层的定义」「一个文件中的测试用到不同层级的资源时，整个文件登记为其中最高的一层」
一起登记为集成层）。

守 R2（路由契约与定义格式只增：新的路由实现按名称登记，形态是又一份完整的定义，骨架事件与停止原因不变；
发布的那份定义的成果种类与提议方式一行不改）与 R3（形态随事项冻结：换成单角色直做以后建的事项按那一份运行；
开环完成与放行分开记，交完成写在成果接纳事件里、结束原因是开环完成）。

先后由事件决定，不用时长赌（测试分层 docs/design/test-pyramid.md「测试的写法」）：事项跑完再断言事件；脚本按部门给出。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from harness import proposals, routing_contract
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import (DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR, VerifiedOutcomes, VerifierRole,
                                 VerificationDeclaration, load_definitions)
from harness.direct import (COMPLETION_KIND, DIRECT_TIGHTENING, ITEM_END_REASON, ROUTING_NAME,
                            SINGLE_ROLE_DIRECT, completing_departments, check_definition,
                            ready_departments, routing_departments, waiting_departments)
from harness.event_store import project_stream
from harness.models import ArtifactRef, DepartmentGuidance, EventType, ProjectEventType, RunProjection
from harness.proposals import completion_turn
from harness.runtime import FORM_REGISTRY, SEVERAL_ROLES_DIRECT, LoopSystem
from harness.tests.helpers import happy_script
from harness.tightening import WATCHED_OUTPUTS
from harness.write_path import NewProjectEvent

GOAL = "做一个可以长期演进的逐行文本处理工具。"

# 形态的定义目录（与 runtime.FORM_REGISTRY 登记的那一份同一个来源）
FORM_DIRECTORY = DEFINITIONS_DIR / "forms" / SINGLE_ROLE_DIRECT
SINGLE_ROLE_DIRECT_DEFINITIONS = load_definitions(FORM_DIRECTORY)

FORMS = {
    DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS),
    SINGLE_ROLE_DIRECT: (SINGLE_ROLE_DIRECT_DEFINITIONS, DIRECT_TIGHTENING),
}

# 直做形态从这个部门取名字、工具与模型设置；它不授予的提交工具是交交付与交结构（这一份形态以交完成结束），
# 也不授予 ask（只有一个角色，没有可问的部门）
ENGINEERING = "engineering"
NOT_GRANTED = {"submit_delivery", "submit_structure", "ask"}


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _system(data_dir: Path, script: dict[str, list[Any]]) -> LoopSystem:
    # 两种形态都交给实例；装配与执行用产品的那一份，部门、工具与提案合同按事项冻结的那一份取
    return LoopSystem.for_testing(data_dir, FakeAdapter(script), forms=FORMS, resume_on_startup=False)


def _switched_to(data_dir: Path, script: dict[str, list[Any]], **kwargs: Any) -> tuple[LoopSystem, str, str]:
    # 项目的形态换成单角色直做以后建一个事项（写成 #1392 的那条项目事件，与 #1402 的命令同一个落点）
    system = _system(data_dir, script)
    project_id = system.projects.register("一个角色直做", GOAL)
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET,
        {"previous_form": DEFAULT_FORM, "form": SINGLE_ROLE_DIRECT, "reason": ""}, actor="user:local"))
    work_item_id, run_id = system.projects.start_work_item(project_id, "补一份用法说明", **kwargs)
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


def _activations(system: LoopSystem, run_id: str) -> int:
    return len(_of_type(system, run_id, EventType.DEPARTMENT_ACTIVATED))


# 一轮按顺序给出：先写文件、再交完成（同一次激活的两步）；或者只交完成
def _single_role_script(*turns: Any) -> dict[str, list[Any]]:
    return {ENGINEERING: list(turns)}


# ---------------------------------------------------------------------------
# 验收第 1 条：一个角色交完成，以开环完成结束
# ---------------------------------------------------------------------------


def test_a_single_role_direct_item_ends_open_loop_with_the_completion_accepted(tmp_path):
    # 项目换成单角色直做以后建事项：假模型改一个文件、交完成——事项以开环完成结束，交上来的完成被采纳，
    # 没有决定请求，事件里没有质检结论（这个事项只有工程一个角色）
    system, work_item_id, run_id = _switched_to(
        tmp_path / "direct",
        _single_role_script(
            FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}, checks={}),
            completion_turn("补了用法一节", uncertain=["退出码没有写全"]),
        ),
    )
    created = _run_created(system, run_id)
    # 创建时按冻结的定义标为开环：最后采纳交完成那一份，没有核验角色核验它（#1394）
    assert (created["form"], created["open_loop"], created["work_item_id"]) == (SINGLE_ROLE_DIRECT, True,
                                                                                work_item_id)

    ended = system.run_until_stop(run_id)

    # 结果是完成，结束原因是开环完成：运行结束事件上写明了它，不写成放行
    assert (ended.status, ended.stop_reason) == ("done", "open_loop")
    done = _run_done(system, run_id)
    assert (done.stop_reason, done.payload["stop_reason"], done.state_after) == ("open_loop", "open_loop", "done")
    # 交上来的完成被采纳：通用的成果接纳事件，作者是工程，记下了工作区的树，拿不准的地方留在内容里
    accepted = [event for event in _of_type(system, run_id, EventType.ARTIFACT_ACCEPTED)
                if event.payload.get("artifact_kind") == COMPLETION_KIND]
    assert len(accepted) == 1
    payload = accepted[0].payload
    assert payload["artifact_issuer"] == ENGINEERING
    assert payload["artifact_version"] == 1
    assert payload["uncertain"] == ["退出码没有写全"]
    assert payload["summary"] == "补了用法一节"
    assert payload["artifact_tree_digest"].startswith("sha256:")
    # 开环完成不发决定请求；事件里没有质检结论，也没有质检这个部门的任何事件
    assert _of_type(system, run_id, EventType.DECISION_REQUESTED) == []
    assert _of_type(system, run_id, EventType.QA_SUBMITTED) == []
    assert {event.department for event in _events(system, run_id)} <= {ENGINEERING, None}


def test_the_completion_must_explain_what_was_done(tmp_path):
    # 交完成的形状：说明必填。空说明被拒绝，这一轮按被拒绝结束，下一轮再交（这也是交完成以前可以多轮的样子）
    system, _work_item_id, run_id = _switched_to(
        tmp_path / "reject",
        _single_role_script(completion_turn("   "), completion_turn("补了用法一节")),
    )

    ended = system.run_until_stop(run_id)

    rejected = _of_type(system, run_id, EventType.PROPOSAL_REJECTED)
    assert [event.payload["errors"][0]["field"] for event in rejected] == ["summary"]
    assert (ended.status, ended.stop_reason) == ("done", "open_loop")
    assert len(_of_type(system, run_id, EventType.ARTIFACT_ACCEPTED)) == 1
    assert _activations(system, run_id) == 2


# ---------------------------------------------------------------------------
# 验收第 2 条：交完成以前可以多轮工作；到上限会停，停止原因来自封闭清单
# ---------------------------------------------------------------------------


def test_the_role_works_round_after_round_until_the_activation_limit_stops_it(tmp_path):
    # 一直交不出合格的完成：每一轮以被拒绝结束，能交完成的角色再开始一轮；轮次到上限时停下，
    # 停止原因是内核封闭清单里的一条（max_cycles），不是路由自己编的名字
    system, _work_item_id, run_id = _switched_to(
        tmp_path / "limit",
        _single_role_script(*[completion_turn("")] * 4),
        max_cycles=2,
    )

    ended = system.run_until_stop(run_id)

    assert (ended.status, ended.stop_reason) == ("paused", "max_cycles")
    assert _activations(system, run_id) == 2
    assert ended.stop_reason in DEFINITIONS.stop_reasons
    assert len(_of_type(system, run_id, EventType.PROPOSAL_REJECTED)) == 2
    assert _of_type(system, run_id, EventType.RUN_DONE) == []


# ---------------------------------------------------------------------------
# 路由自己的判断（不经完整循环的用例）
# ---------------------------------------------------------------------------


def _new_input_view() -> RunProjection:
    # 一条还没有任何角色处理过的新输入：接这种来源的部门是唯一有新的工作、并且能交完成的那一个
    view = RunProjection(run_id="run", task="补一份用法说明")
    view.input_version = 1
    return view


def test_the_routing_lets_the_completing_role_start_until_it_hands_in_completion():
    # 能交完成的角色交完成以前一直可以开始下一轮；名单按这份形态的定义取，发布的三部门不在里面
    view = _new_input_view()
    assert completing_departments(SINGLE_ROLE_DIRECT_DEFINITIONS) == (ENGINEERING,)
    assert routing_departments(SINGLE_ROLE_DIRECT_DEFINITIONS) == (ENGINEERING,)
    assert ready_departments(view, {ENGINEERING}, SINGLE_ROLE_DIRECT_DEFINITIONS) == [ENGINEERING]
    # 正在工作的角色不再开一轮（同时运行，一个角色同一时刻最多一轮）
    assert ready_departments(view, set(), SINGLE_ROLE_DIRECT_DEFINITIONS) == []
    # 到了终态谁也不开工
    finished = _new_input_view()
    finished.status = "done"
    assert ready_departments(finished, {ENGINEERING}, SINGLE_ROLE_DIRECT_DEFINITIONS) == []
    # 在等待工作的角色按会话状态取：进程里没有正在工作的会话的都算（工单 #16 的恢复口径）
    assert waiting_departments({ENGINEERING: None}, SINGLE_ROLE_DIRECT_DEFINITIONS) == {ENGINEERING}
    assert waiting_departments({ENGINEERING: "active"}, SINGLE_ROLE_DIRECT_DEFINITIONS) == set()


def test_a_role_with_pending_guidance_starts_a_round():
    # 有指导时没有在工作的角色开始一轮（工单正文的第一句）：指导是这份形态的部门关注的那一项
    guidance = DepartmentGuidance(id="gd_1", run_id="run", department=ENGINEERING, version=1,
                                  text="用法一节写清楚",
                                  guidance_ref=ArtifactRef(kind="department_guidance",
                                                           content_hash="sha256:0",
                                                           path="materials/run/guidance.md"),
                                  created_event_id="evt_1", status="received")
    # 一条已经处理过的输入（没有新的输入）+ 一段待处理的指导：这一轮只有指导是新的工作
    view = RunProjection(run_id="run", task="补一份用法说明", department_guidance=[guidance])
    view.input_version = 1
    view.processed_input_version = 1
    assert ready_departments(view, {ENGINEERING}, SINGLE_ROLE_DIRECT_DEFINITIONS) == [ENGINEERING]
    # 这段指导已经进入过模型输入（in_input）时它不再触发新一轮；能交完成的角色照旧开工
    view.department_guidance[0] = replace(guidance, status="in_input")
    assert ready_departments(view, {ENGINEERING}, SINGLE_ROLE_DIRECT_DEFINITIONS) == [ENGINEERING]
    # 开工名单只看这份形态的部门：别的部门有指导也不在直做的名单里
    view.department_guidance[0] = replace(guidance, department="quality")
    assert ready_departments(view, {"quality"}, SINGLE_ROLE_DIRECT_DEFINITIONS) == []


def test_the_item_end_reason_is_the_one_the_definition_declares():
    # 没有角色可以开始一轮工作时，事项以路由定义里声明的原因结束；它与内核的停止原因分开，是这份定义的封闭清单
    declared = routing_contract.definition_of(SINGLE_ROLE_DIRECT_DEFINITIONS, ROUTING_NAME)
    assert ITEM_END_REASON in declared.end_reasons
    assert ITEM_END_REASON not in DEFINITIONS.stop_reasons
    assert SINGLE_ROLE_DIRECT_DEFINITIONS.stop_reason(ITEM_END_REASON).outcome == "failed"


def test_the_completion_reason_comes_from_the_open_loop_flag_recorded_at_creation():
    # 结束原因由路由按创建事件里的开环标记给（#1394 的做法）：标了开环给开环完成，没标的不给、薄驱动按事项
    # 种类取。两种情况都由这一份直做的路由实现给出，不看进程加载的那份定义
    from harness import direct

    open_loop_run = _run_created_event({"open_loop": True})
    assert direct.completion_reason(None, [open_loop_run]).stop_reason == "open_loop"
    assert direct.completion_reason(None, [_run_created_event({"open_loop": False})]) is None
    # 旧事件没有这一项时读作不是开环
    assert direct.completion_reason(None, [_run_created_event({})]) is None


def _run_created_event(payload: dict[str, Any]) -> Any:
    # 只带路由读的两样：事件种类与载荷（结束原因只看创建事件里的开环标记）
    return SimpleNamespace(type=EventType.RUN_CREATED, payload=payload)


class _NoEvents:
    # 接形态时要交的事件库：登记处这一条用例只接上路由，不读事件（直做声明了 use_facts，工单 #1396）
    def list_events(self, run_id: str) -> list[Any]:
        return []


def test_a_direct_definition_whose_verifier_cannot_conclude_is_rejected_at_load():
    # #1396 起直做可以带核验角色（交完成以后等它的结论），所以 #1395 的「核验交完成的那一份就整份拒绝」
    # 这条临时限制换成了两条：核验的双方都要交得出自己的那一样。这一份的核验角色交不了核验结论
    # （completion_review），事项交完成以后等不到放行——加载时整份拒绝，原因写明是哪一项
    verified = SINGLE_ROLE_DIRECT_DEFINITIONS.model_copy(update={
        "organization": SINGLE_ROLE_DIRECT_DEFINITIONS.organization.model_copy(update={
            "verification": VerificationDeclaration(verifiers=(
                VerifierRole(role=ENGINEERING, verifies=(
                    VerifiedOutcomes(role=ENGINEERING, outcomes=(COMPLETION_KIND,)),)),)),
        }),
    })
    try:
        check_definition(verified)
    except routing_contract.InvalidRoutingDefinition as rejected:
        assert any("verification" in issue for issue in rejected.issues)
    else:  # pragma: no cover - 走不到时让用例失败
        raise AssertionError("a direct definition whose verifier cannot conclude must be rejected")


def test_a_direct_definition_without_a_role_that_can_hand_in_completion_is_rejected():
    # 没有角色能交完成时事项交不了完成：加载时拒绝，不等到运行到上限才发现
    contract = SINGLE_ROLE_DIRECT_DEFINITIONS.proposal_contracts
    without = SINGLE_ROLE_DIRECT_DEFINITIONS.model_copy(update={
        "proposal_contracts": contract.model_copy(update={
            "roles": {ENGINEERING: contract.roles[ENGINEERING].model_copy(update={"kinds": {}})},
        }),
    })
    try:
        check_definition(without)
    except routing_contract.InvalidRoutingDefinition as rejected:
        assert any("final_outcome" in issue for issue in rejected.issues)
    else:  # pragma: no cover
        raise AssertionError("a direct definition without a role that can hand in completion must be rejected")


def test_the_forms_are_registered_and_the_release_keeps_the_default():
    # 登记处（工单 #1392 的形态机制）：发布带三份形态（#1395 的单角色直做，#1454 的几个角色直做），
    # 默认仍是三部门；新的一份按它的组织定义接上直做。
    # 直做声明了 use_facts（工单 #1396 读交完成与核验结论），所以接上时要有事件库，这里给一个没有事件的
    assert set(FORM_REGISTRY) == {DEFAULT_FORM, SINGLE_ROLE_DIRECT, SEVERAL_ROLES_DIRECT}
    forms = __import__("harness.runtime", fromlist=["load_forms"]).load_forms(FORM_REGISTRY, store=_NoEvents())
    assert forms[DEFAULT_FORM].definitions.routing == "watched_outputs"
    direct_form = forms[SINGLE_ROLE_DIRECT]
    assert direct_form.definitions.routing == ROUTING_NAME
    assert type(direct_form.routing).__name__ == "Direct"
    assert type(direct_form.tightening).__name__ == "DirectTightening"
    # 默认那份定义的成果种类与提议方式不变：单角色直做没有往发布的那一份定义里加东西
    assert [tool.proposal for tool in DEFINITIONS.tools.values() if tool.proposal] == [
        "product_spec", "product_decision", "delivery_spec", "qa_review", "structure", "baseline_review",
        "independent_judgement"]


# ---------------------------------------------------------------------------
# 形态用工程这个部门的名字、工具与模型设置（守卫：发布的那一份变了，这一份跟着发现）
# ---------------------------------------------------------------------------


def test_the_single_role_direct_form_uses_the_engineering_role_and_its_tools():
    form = SINGLE_ROLE_DIRECT_DEFINITIONS
    product = DEFINITIONS.roles[ENGINEERING]
    expected = (set(product.tools) - NOT_GRANTED) | {proposals.SUBMIT_COMPLETION}
    assert set(form.roles[ENGINEERING].tools) == expected
    # 工具定义逐项与发布的那一份相同（名称、说明、参数都不另写一份）
    for name in expected - {proposals.SUBMIT_COMPLETION}:
        assert form.tools[name] == DEFINITIONS.tools[name]
    # 浏览器工具是单独一份生成的定义：两份逐字节相同，不各写一份
    assert (FORM_DIRECTORY / "browser_tools.json").read_bytes() \
        == (DEFINITIONS_DIR / "browser_tools.json").read_bytes()
    # 可见范围与发布的那份相同；形态是工程这个部门，模型按部门的设置解析（定义里不另加模型设置）
    assert form.roles[ENGINEERING].visibility == product.visibility
    assert form.departments == (ENGINEERING,)
    assert form.department_labels[ENGINEERING] == DEFINITIONS.department_labels[ENGINEERING]


def test_the_single_role_direct_form_carries_the_kernel_tables_unchanged():
    # 停止原因是内核的封闭清单、事件来源按事件种类给出：两份定义里这两张表相同（形态不另写一份）
    form = SINGLE_ROLE_DIRECT_DEFINITIONS
    assert form.stop_reasons == DEFINITIONS.stop_reasons
    assert form.event_sources == DEFINITIONS.event_sources


def test_the_single_role_direct_form_declares_both_sources_and_no_verifier():
    organization = SINGLE_ROLE_DIRECT_DEFINITIONS.organization
    # 「你的输入」与「建档」都由工程接（来源的写法见 #1455）
    assert dict(organization.sources) == {"user_input": ENGINEERING, "onboarding": ENGINEERING}
    # 没有核验角色：事项最后采纳的成果没有人核验，创建时标为开环
    assert SINGLE_ROLE_DIRECT_DEFINITIONS.verifier_roles() == ()
    assert SINGLE_ROLE_DIRECT_DEFINITIONS.is_open_loop(COMPLETION_KIND) is True
    assert SINGLE_ROLE_DIRECT_DEFINITIONS.routing_definition().final_outcome == COMPLETION_KIND


def test_the_role_material_says_to_continue_and_list_what_is_uncertain():
    # 角色材料按「开环完成」第 3 条写倾向（结构上不规定去向）：能按项目约定补全的就继续，拿不准的列进交完成的
    # 说明，只有目标本身读不通时才问
    prompt = SINGLE_ROLE_DIRECT_DEFINITIONS.roles[ENGINEERING].prompt
    for phrase in ("能按项目约定与常见做法补全的就继续", "拿不准的地方列进交完成的说明", "只有目标本身读不通"):
        assert phrase in prompt
    assert "开环完成" in prompt


# ---------------------------------------------------------------------------
# 询问照现有规矩（角色之间靠询问交流，单角色时没有可问的人）
# ---------------------------------------------------------------------------


def _limits() -> routing_contract.AskLimits:
    return routing_contract.AskLimits(max_model_steps=5)


def test_asks_follow_the_existing_rules():
    from harness import direct

    view = _new_input_view()
    # 收件人不在这个路由的部门清单里、或者就是提问方自己：这次调用不合法，不运行、不写事件
    assert isinstance(direct.ask_branch(view, [], requester=ENGINEERING, session_id="ses_1",
                                        call={"args": {"recipient": "quality", "question": "q"}},
                                        limits=_limits(), definitions=SINGLE_ROLE_DIRECT_DEFINITIONS),
                      routing_contract.AskRejection)
    assert isinstance(direct.ask_branch(view, [], requester=ENGINEERING, session_id="ses_1",
                                        call={"args": {"recipient": ENGINEERING, "question": "q"}},
                                        limits=_limits(), definitions=SINGLE_ROLE_DIRECT_DEFINITIONS),
                      routing_contract.AskRejection)
    # 问题为空时同样不合法
    assert isinstance(direct.ask_branch(view, [], requester=ENGINEERING, session_id="ses_1",
                                        call={"args": {"recipient": ENGINEERING}},
                                        limits=_limits(), definitions=SINGLE_ROLE_DIRECT_DEFINITIONS),
                      routing_contract.AskRejection)


def test_a_branch_that_cannot_answer_says_so_with_the_shape_the_caller_expects():
    # 分支这一轮没交上回答：结果写明没能回答与原因（这一版直做只有自己的那一轮能交完成，回答不附成果）
    from harness import direct

    view = _new_input_view()
    branch = routing_contract.AskBranch(recipient=ENGINEERING, session_id="ses_ask_eng", max_model_steps=1,
                                        max_time_sec=1.0)
    outcome = direct.ask_outcome(view, branch=branch, result=routing_contract.AskRoundResult(steps_left=0),
                                 definitions=SINGLE_ROLE_DIRECT_DEFINITIONS)
    assert (outcome.status, outcome.session_id, bool(outcome.reason)) == ("unable", "ses_ask_eng", True)
    answered = direct.ask_outcome(view, branch=branch, definitions=SINGLE_ROLE_DIRECT_DEFINITIONS,
                                  result=routing_contract.AskRoundResult(submission={"answer": "用不上"}))
    assert (answered.status, answered.answer, answered.revises) == ("answered", "用不上", None)


def test_the_three_departments_still_end_with_a_release_in_the_same_instance(tmp_path):
    # 同一个实例里两份形态都在：三部门的事项照旧以放行结束（默认定义、默认路由与默认收紧检查一行不改；
    # 事件序列基准由 test_event_sequence.py 守住，这里核对它没有被新形态带走）
    system = _system(tmp_path / "release", happy_script())
    project_id = system.projects.register("三部门", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "补一份用法说明")

    ended = system.run_until_stop(run_id)

    assert _run_created(system, run_id)["form"] == DEFAULT_FORM
    assert (ended.status, ended.stop_reason) == ("done", "released")
    assert _run_done(system, run_id).stop_reason == "released"
    accepted = {event.payload.get("artifact_kind") for event in _of_type(system, run_id, EventType.ARTIFACT_ACCEPTED)}
    assert COMPLETION_KIND not in accepted

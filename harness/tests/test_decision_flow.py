# 工单 #827（S4a）：决定请求的处理与建档的流转在应用层，薄驱动只转交
# （骨架与应用 docs/design/skeleton-and-application.md「薄驱动」；总图第二节「薄驱动」，第三节外环「等用户」）。
#
# 守 R1（第三环的不变式）与 R3（路线图阶段一写明的行为）：
# - R1：回答只在写入口的一个事务里写成事实——回答与它解除的阻塞同一批写入，命令身份绑在这两条事件上；
#   核对不通过时一个事件都不写、命令不登记。
# - R3：决定请求得到回答以后 run 继续执行（应用层给出要继续执行的 run，由调用方开始）；
#   这些处理在应用层，薄驱动里不再有（docs/design/skeleton-and-application.md「薄驱动」「薄驱动只连接」）。
#
# 一次部门激活、SQLite 事件库与数据目录，属于模块层（docs/design/test-pyramid.md「三层的定义」）。
# 事项级的决定、基线采纳与建档修改轮的行为由 test_projects.py、test_onboarding_confirmation_round.py、
# test_onboarding_revision_context.py 守着（集成层），这里不重复。

import ast
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from harness import decision_flow
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.decision_flow import DECISION_FLOW
from harness.decisions import (
    DECISION_KINDS, InvalidOption, ROLE_CHOICE, StaleDecision,
    blocks_run, resolve_role_choice_answers, validate_role_choice_questions,
)
from harness.event_store import Command, run_stream
from harness.models import DecisionRequest, EventType
from harness.projection import replay_decisions, saved_decision, saved_decisions
from harness.runtime import LoopSystem
from harness.tests.helpers import TOOL_CALL_REQUIRED_LIMIT as LIMIT
from harness.write_path import NewEvent

HARNESS = Path(__file__).resolve().parents[1]
# 从薄驱动搬到应用层的处理：两种决定请求的解答、建档的采纳与修改轮、修改轮 run 的建立、继续暂停的 run，
# 以及建档摘要那句话
MOVED_METHODS = (
    "_answer_run_decision",
    "_answer_project_decision",
    "_settle_kernel_modification",
    "_adopt_baseline",
    "_start_onboarding_revision",
    "_create_missing_revision_run",
    "_continue_paused_run",
)
MOVED_FUNCTIONS = ("_onboarding_summary",)


def _plain_reply():
    # 部门回复文字、没有调用工具：连续若干次以后主机要求调用工具，这一轮以 no_tool_call 暂停
    return lambda _call: FakeTurn(transcript="先整理一下思路，稍后提交。")


def _paused_on_a_decision(data_dir):
    # 一次部门激活就停在一个待回答的决定请求上，不跑完整的三部门循环
    script = {"product": [_plain_reply() for _ in range(LIMIT + 1)], "engineering": [], "quality": []}
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo")
    paused = system.activate_once(run_id)
    assert (paused.status, paused.stop_reason) == ("paused", "no_tool_call"), paused.status
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    [decision] = [item for item in decisions if item.run_id == run_id]
    return system, run_id, decision


def _command(option: str, base_version: int) -> Command:
    return Command(str(uuid.uuid4()), "decision.answer", f"sha256:{option}:{base_version}", "user:local")


def _driver_source() -> str:
    return (HARNESS / "orchestrator.py").read_text(encoding="utf-8")


def _method_source(name: str) -> str:
    # 薄驱动里 Orchestrator 的一个方法的源码，按语法树取原文
    source = _driver_source()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"薄驱动里没有 {name}")


def _imported(relative: str) -> set[str]:
    # 模块里的相对导入，按 harness 下的模块名给出（from . import x 记成 x）
    found: set[str] = set()
    for node in ast.walk(ast.parse((HARNESS / relative).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module is None:
                found.update(alias.name for alias in node.names)
            else:
                found.add(node.module)
    return found


def test_the_application_module_answers_a_run_decision_and_gives_back_the_run_to_continue(tmp_path):
    # R1、R3：应用层的这一份直接回答一个 run 级的决定请求，回答与继续写在同一个事务里，
    # 并给出要继续执行的 run（薄驱动的转交入口只把它交给调用方）
    system, run_id, decision = _paused_on_a_decision(tmp_path / "data")
    try:
        # 组装时接上的是应用层这一份，薄驱动转交的就是它
        assert system.orchestrator.decision_flow is DECISION_FLOW
        command = _command("continue", decision.version)
        returned = DECISION_FLOW.answer_decision(
            system.orchestrator, decision.decision_id, "continue", "已经处理", base_version=decision.version,
            command=command)
        # 返回要让调用方开始的 run
        assert returned == run_id
        events = system.store.list_events(run_id)
        assert [event.type for event in events[-2:]] == [EventType.DECISION_ANSWERED, EventType.RUN_CONTINUED]
        # 回答解除阻塞：回答事件带选项与说明，继续事件指向同一个决定请求
        assert events[-2].payload == {"decision_id": decision.decision_id, "option": "continue",
                                      "note": "已经处理", "base_version": decision.version}
        assert events[-1].payload["decision_id"] == decision.decision_id
        assert events[-1].payload["stop_reason"] == "no_tool_call"
        # 两条事实是同一批写入：同一条命令身份绑在它们上，命令只登记一次
        assert events[-2].command_id == events[-1].command_id == command.command_id
        assert [event.event_id for event in system.store.command_events(command.command_id)] == [
            events[-2].event_id, events[-1].event_id]
        answered = saved_decision(system.store, decision.decision_id)
        assert (answered.status, answered.answer["option"]) == ("answered", "continue")
    finally:
        system.close()


def test_the_thin_driver_forwards_the_answer_without_deciding_anything_itself(tmp_path):
    # R1：核对不通过时一个事件都不写、命令不登记；薄驱动的转交与直接问应用层是同一个结果
    system, run_id, decision = _paused_on_a_decision(tmp_path / "data")
    try:
        end = system.store.end_position()
        stale = decision.version + 1
        with pytest.raises(StaleDecision):
            system.orchestrator.answer_decision(decision.decision_id, "continue", None, base_version=stale,
                                                command=_command("continued", stale))
        forwarded = _command("continue", stale)
        with pytest.raises(StaleDecision):
            DECISION_FLOW.answer_decision(system.orchestrator, decision.decision_id, "continue", None,
                                          base_version=stale, command=forwarded)
        assert system.store.end_position() == end
        assert system.store.command(forwarded.command_id) is None
        assert saved_decision(system.store, decision.decision_id).status == "open"
    finally:
        system.close()


def test_the_thin_driver_only_forwards_the_decision_and_onboarding_flow():
    # R3、docs/design/skeleton-and-application.md「薄驱动」「薄驱动只连接」：这些处理在应用层；薄驱动里只剩两个转交，一处写事件都没有
    driver = _driver_source()
    for name in MOVED_METHODS + MOVED_FUNCTIONS:
        assert f"def {name}(" not in driver, name
    forwarded = _method_source("answer_decision") + _method_source("create_revision_run")
    for written in ("transaction.append", "on_commit", "NewProjectEvent", "NewCatalogEvent", "NewEvent"):
        assert written not in forwarded, written
    # 应用层这一份持有这些处理
    assert isinstance(DECISION_FLOW, decision_flow.DecisionFlow)
    for name in MOVED_METHODS:
        assert hasattr(DECISION_FLOW, name), name
    assert hasattr(DECISION_FLOW, "create_revision_run")
    for name in MOVED_FUNCTIONS:
        assert hasattr(decision_flow, name), name


def test_the_application_module_does_not_import_the_thin_driver():
    # R2：薄驱动调用应用层这一份，它不导入薄驱动（薄驱动在调用时把自己交进来）；写事实只经写入口
    imports = _imported("decision_flow.py")
    assert "orchestrator" not in imports
    assert "write_path" in imports


def _sample_questions() -> list[dict[str, object]]:
    return [
        {
            "id": "q1",
            "question": "日志输出格式采用哪一种？",
            "options": [
                {"id": "json", "label": "JSON 结构化", "description": "便于脚本解析"},
                {"id": "text", "label": "纯文本行"},
            ],
            "recommended": "json",
            "rationale": "便于后续工具消费",
        },
        {
            "id": "q2",
            "question": "错误是否输出到标准错误流？",
            "options": [
                {"id": "stderr", "label": "输出到 stderr"},
                {"id": "stdout", "label": "输出到 stdout"},
            ],
            "recommended": "stderr",
            "rationale": "遵循命令行约定",
        },
    ]


def test_role_choice_kind_is_round_scoped_and_validates_question_batches():
    # 守护 R1 与 R2：ROLE_CHOICE 登记在 DECISION_KINDS 且阻塞范围为 round（不阻塞整次运行）；
    # 多题结构校验对空列表、空或重复题号、空题干、少于两项或重复选项、推荐项越界及空推荐理由均拒绝
    assert DECISION_KINDS["role_choice"] is ROLE_CHOICE
    assert ROLE_CHOICE.blocks == "round"
    assert [opt.id for opt in ROLE_CHOICE.options] == ["submit", "recommended"]
    open_round = DecisionRequest(
        decision_id="evt_round", stream="run:r1", run_id="r1", project_id=None, work_item_id=None,
        requested_at="2026-11-16T00:00:00+00:00",
        request={"kind": "role_choice", "blocks": "round", "questions": _sample_questions()},
    )
    assert blocks_run([open_round]) is False

    normalized = validate_role_choice_questions(_sample_questions())
    assert [q["id"] for q in normalized] == ["q1", "q2"]

    bad_batches = [
        [],
        [{**_sample_questions()[0], "id": " "}],
        _sample_questions() + [{**_sample_questions()[0], "question": "重复题号"}],
        [{**_sample_questions()[0], "question": ""}],
        [{**_sample_questions()[0], "options": [{"id": "only", "label": "只有一项"}]}],
        [{**_sample_questions()[0], "options": [{"id": "dup", "label": "A"}, {"id": "dup", "label": "B"}]}],
        [{**_sample_questions()[0], "options": [{"id": "a", "label": ""}, {"id": "b", "label": "B"}]}],
        [{**_sample_questions()[0], "recommended": "missing"}],
        [{**_sample_questions()[0], "rationale": "  "}],
    ]
    for batch in bad_batches:
        with pytest.raises(ValueError):
            validate_role_choice_questions(batch)


def _write_role_choice_decision(system: LoopSystem, run_id: str) -> DecisionRequest:
    questions = _sample_questions()
    system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
        EventType.DECISION_REQUESTED, actor="system", department="product",
        state_before=transaction.projection.status, state_after=transaction.projection.status,
        payload={
            "kind": "role_choice",
            "blocks": "round",
            "options": [{"id": opt.id, "label": opt.label} for opt in ROLE_CHOICE.options],
            "description": "产品有两道前置分叉问题等待用户选择",
            "facts": [],
            "department": "product",
            "questions": questions,
            "input_version": 1,
            "round": 1,
        },
    )))
    [decision] = [item for item in saved_decisions(system.store, statuses=("open",))[1] if item.run_id == run_id]
    return decision


def test_role_choice_answer_resolution_validation_and_non_role_choice_rejection(tmp_path):
    # 守护 R1 与 R2：role_choice 支持完整 answers、部分 answers 自动按 recommended 补齐及
    # option="recommended" 无 answers 全推荐补齐；未知题号、未知选项与对非 role_choice 传 answers
    # 均抛出 InvalidOption 且不写事件与命令，回答落盘后与事件重放保持一致
    questions = _sample_questions()
    assert resolve_role_choice_answers(questions, "submit", {"q1": "text", "q2": "stdout"}) == {
        "q1": "text", "q2": "stdout",
    }
    assert resolve_role_choice_answers(questions, "submit", {"q1": "text"}) == {
        "q1": "text", "q2": "stderr",
    }
    assert resolve_role_choice_answers(questions, "recommended", None) == {
        "q1": "json", "q2": "stderr",
    }
    with pytest.raises(InvalidOption):
        resolve_role_choice_answers(questions, "submit", {"q_unknown": "json"})
    with pytest.raises(InvalidOption):
        resolve_role_choice_answers(questions, "submit", {"q1": "yaml"})

    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter([]))
    try:
        run_a = system.create_run("role choice partial")
        dec_a = _write_role_choice_decision(system, run_a)
        end_before = system.store.end_position()
        bad_cmd = _command("submit", dec_a.version)
        with pytest.raises(InvalidOption):
            system.orchestrator.answer_decision(
                dec_a.decision_id, "submit", None, base_version=dec_a.version,
                command=bad_cmd, answers={"q1": "invalid"},
            )
        assert system.store.end_position() == end_before
        assert system.store.command(bad_cmd.command_id) is None

        returned = system.orchestrator.answer_decision(
            dec_a.decision_id, "submit", "第二题沿用推荐", base_version=dec_a.version,
            command=_command("submit", dec_a.version), answers={"q1": "text"},
        )
        assert returned == run_a
        saved_a = saved_decision(system.store, dec_a.decision_id)
        assert saved_a.status == "answered"
        assert saved_a.answer["answers"] == {"q1": "text", "q2": "stderr"}
        replayed_a = replay_decisions(system.store.list_events(run_a))[dec_a.decision_id]
        assert replayed_a.answer == saved_a.answer
    finally:
        system.close()

    paused_system, paused_run, paused_dec = _paused_on_a_decision(tmp_path / "paused")
    try:
        end_before = paused_system.store.end_position()
        rejected_cmd = _command("continue", paused_dec.version)
        with pytest.raises(InvalidOption):
            paused_system.orchestrator.answer_decision(
                paused_dec.decision_id, "continue", None, base_version=paused_dec.version,
                command=rejected_cmd, answers={"q1": "a"},
            )
        assert paused_system.store.end_position() == end_before
        assert paused_system.store.command(rejected_cmd.command_id) is None
    finally:
        paused_system.close()


def _ask_user_call(call_id: str, questions: list[dict[str, object]], note: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"questions": questions}
    if note is not None:
        payload["note"] = note
    return {
        "id": call_id,
        "call_id": call_id,
        "type": "function_call",
        "name": "ask_user",
        "arguments": json.dumps(payload, ensure_ascii=False),
    }


def _called_results(system: LoopSystem, run_id: str, name: str) -> list[dict[str, Any]]:
    return [
        {"event": event, **json.loads(event.payload["input_item"]["output"])}
        for event in system.store.list_events(run_id)
        if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("name") == name
    ]


def _definitions_with_ask_user(target: Path) -> Any:
    import shutil
    from harness.definitions import DEFINITIONS_DIR, load_definitions

    if not target.exists():
        shutil.copytree(DEFINITIONS_DIR, target)
    roles_path = target / "roles.json"
    roles_doc = json.loads(roles_path.read_text(encoding="utf-8"))
    for role in ("product", "engineering", "quality"):
        if "ask_user" not in roles_doc[role]["tools"]:
            roles_doc[role]["tools"].append("ask_user")
    roles_path.write_text(json.dumps(roles_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    work_items_path = target / "work_items.json"
    work_items_doc = json.loads(work_items_path.read_text(encoding="utf-8"))
    departments = work_items_doc["kinds"]["change"]["departments"]
    for role in ("product", "engineering", "quality"):
        dept_cfg = departments.get(role)
        if isinstance(dept_cfg, dict) and "tools" in dept_cfg and "ask_user" not in dept_cfg["tools"]:
            dept_cfg["tools"].append("ask_user")
    work_items_path.write_text(json.dumps(work_items_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(target)


def _wait_and_answer(
    system: LoopSystem,
    run_id: str,
    *,
    expected_round: int,
    expected_input_version: int = 1,
    option: str = "submit",
    answers: dict[str, str] | None = None,
    note: str | None = None,
    hold_event: Any = None,
) -> list[str]:
    # 订阅 DECISIONS 事件：一旦目标轮次的 role_choice 提交即触发回答，不靠睡眠碰运气
    import threading
    from harness.projection import saved_decisions

    answered_ids: list[str] = []
    lock = threading.Lock()

    def on_events(events: list[Any]) -> None:
        for event in events:
            if event.type != EventType.DECISION_REQUESTED or event.run_id != run_id:
                continue
            payload = event.payload or {}
            if (payload.get("kind") != "role_choice"
                    or payload.get("round") != expected_round
                    or payload.get("input_version") != expected_input_version):
                continue

            def respond() -> None:
                if hold_event is not None:
                    hold_event.wait(timeout=5.0)
                with lock:
                    dec = saved_decision(system.store, event.event_id)
                    if dec is None or dec.status != "open":
                        return
                    system.orchestrator.answer_decision(
                        dec.decision_id,
                        option,
                        note,
                        base_version=dec.version,
                        command=_command(option, dec.version),
                        answers=answers,
                    )
                    answered_ids.append(dec.decision_id)

            threading.Thread(target=respond, daemon=True).start()

    system.store.subscribe(on_events)
    return answered_ids


def test_ask_user_validation_bounds_zero_limit_branch_and_new_input_version(tmp_path):
    # 守 R1 与 R2：题数超过 ask_user.max_questions_per_round、同次输入轮数达到上限（含设为 0）、
    # 问题结构无效与 ask 分支调用时均不生成 DECISION_REQUESTED 并返回明确中文错误；
    # 用户追加新输入推进 input_version 后，追问额度按新输入版本重新起算
    import asyncio
    from harness.definitions import DEFAULT_FORM
    from harness.models import new_id
    from harness.proposals import delivery_turn, product_spec
    from harness.providers.call import ModelResponse
    from harness.recording import ActivationScope
    from harness.tests.helpers import work_basis
    from harness.thin_driver import RoundWork
    from harness.tightening import WATCHED_OUTPUTS

    q1, q2 = _sample_questions()
    q3 = {**q1, "id": "q3", "question": "第三个问题？"}
    defs = _definitions_with_ask_user(tmp_path / "defs")

    # 1) 设 max_rounds_per_input=0 与 max_questions_per_round=1，验证立即拒绝与参数冻结；
    # 再设 max_rounds_per_input=1 验证第 1 轮成功、第 2 轮拒绝，以及无效参数与未知键拒绝
    system = LoopSystem.for_testing(
        tmp_path / "bounds",
        FakeAdapter({
            "product": [
                # invalid extra key
                ModelResponse(output=[{
                    "id": "call-extra", "call_id": "call-extra", "type": "function_call",
                    "name": "ask_user",
                    "arguments": json.dumps({"questions": [q1], "extra": 1}, ensure_ascii=False),
                }]),
                # too many questions (> max_questions_per_round=1)
                ModelResponse(output=[_ask_user_call("call-too-many", [q1, q2])]),
                # invalid structure (empty questions)
                ModelResponse(output=[_ask_user_call("call-empty", [])]),
                # valid round 1 under max_rounds=1
                ModelResponse(output=[_ask_user_call("call-r1", [q1], note="先定格式")]),
                # exceeded round 2 under same input_version=1
                ModelResponse(output=[_ask_user_call("call-r2-over", [q2])]),
                product_spec(),
            ],
        }),
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        zero_sys = LoopSystem.for_testing(
            tmp_path / "zero",
            FakeAdapter({
                "product": [
                    ModelResponse(output=[_ask_user_call("call-zero", [q1])]),
                    product_spec(),
                ],
            }),
            forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
        )
        try:
            zero_sys.set_parameter("ask_user.max_rounds_per_input", 0,
                                   reason="关闭提问", modified_by="user:test")
            zero_run = zero_sys.create_run("禁用提问")
            zero_sys.activate_once(zero_run)
            assert [e for e in zero_sys.store.list_events(zero_run)
                    if e.type == EventType.DECISION_REQUESTED and (e.payload or {}).get("kind") == "role_choice"] == []
            [zero_call] = _called_results(zero_sys, zero_run, "ask_user")
            assert zero_call["ok"] is False
            assert "0" in (zero_call["error"] or "")
        finally:
            zero_sys.close()

        system.set_parameter("ask_user.max_questions_per_round", 1, reason="限题数", modified_by="user:test")
        system.set_parameter("ask_user.max_rounds_per_input", 1, reason="限轮数", modified_by="user:test")

        run_id = system.create_run("边界校验与新输入起算")
        answered = _wait_and_answer(system, run_id, expected_round=1, option="recommended")
        system.activate_once(run_id)

        role_reqs = [e for e in system.store.list_events(run_id)
                     if e.type == EventType.DECISION_REQUESTED and (e.payload or {}).get("kind") == "role_choice"]
        assert len(role_reqs) == 1
        assert len(answered) == 1

        calls = _called_results(system, run_id, "ask_user")
        assert [c["ok"] for c in calls] == [False, False, False, True, False]
        assert "extra" in (calls[0]["error"] or "")
        assert "上限 1 题" in (calls[1]["error"] or "")
        assert "不能为空" in (calls[2]["error"] or "")
        assert "第 1 版" in (calls[4]["error"] or "") and "上限 1 轮" in (calls[4]["error"] or "")

        # 追加新用户输入推进 input_version=2，并确认同一分支会话直接调用 _execute_ask_user 也被拒绝且不产生决定请求
        proj = system.project(run_id)
        system.orchestrator.add_input(run_id, "新增要求：支持逗号分隔输出", base_version=proj.input_version)
        assert system.project(run_id).input_version == 2

        # 构造询问分支会话与直接测试参数入参异常：验证 ask 分支即使绕过收紧检查也由编排层拒绝
        branch_id = "ses_ask_branch_check"
        system.writes.transact(run_stream(run_id), lambda tx: tx.append(NewEvent(
            EventType.ASK_STARTED, actor="department:engineering", department="engineering",
            session_id=tx.projection.sessions["engineering"].session_id,
            state_before=tx.projection.status, state_after=tx.projection.status,
            payload={
                "requester": "engineering", "recipient": "product",
                "question": "请确认边界", "origin_session_id": tx.projection.sessions["engineering"].session_id,
                "branch_session_id": branch_id,
            },
        )))
        from threading import Event as ThreadEvent
        branch_scope = ActivationScope(
            run_id, "product", branch_id, new_id("act"), "evt_p",
            prompt_version=1, prompt_hash="sha256:p", guidance_ids=(),
            basis=work_basis(system.project(run_id), "product"), provider="fake",
        )
        branch_round = RoundWork(branch_scope, None, ThreadEvent(), None, None)
        br_ok, _br_out, br_err, br_stopped = asyncio.run(
            system.orchestrator._execute_ask_user(branch_round, "call-branch", {"questions": [q1]})
        )
        assert (br_ok, br_stopped) == (False, False)
        assert "answer" in (br_err or "")
        assert len([e for e in system.store.list_events(run_id)
                    if e.type == EventType.DECISION_REQUESTED and (e.payload or {}).get("kind") == "role_choice"]) == 1

        # 用主线新轮次验证 input_version=2 下的新配额可再次提问
        main_session = system.project(run_id).sessions["product"].session_id
        main_scope = ActivationScope(
            run_id, "product", main_session, new_id("act"), "evt_p2",
            prompt_version=1, prompt_hash="sha256:p2", guidance_ids=(),
            basis=work_basis(system.project(run_id), "product"), provider="fake",
        )
        main_round = RoundWork(main_scope, None, ThreadEvent(), None, None)
        answered_v2 = _wait_and_answer(
            system, run_id, expected_round=1, expected_input_version=2, option="recommended")
        v2_ok, v2_out, v2_err, v2_stopped = asyncio.run(
            system.orchestrator._execute_ask_user(main_round, "call-v2-r1", {"questions": [q3]})
        )
        assert (v2_ok, v2_err, v2_stopped) == (True, None, False)
        assert v2_out["input_version"] == 2
        assert v2_out["round"] == 1
        assert len(answered_v2) == 1
    finally:
        system.close()


def test_ask_user_multi_round_structured_answer_and_idempotent_recovery_after_restart(tmp_path):
    # 守 R1 与 R2：首轮回答按结构化逐题详情交回后同轮继续发起第二轮追问并交出提案；
    # 模拟服务进程在 open 或已 answered 但未写 tool_called 时中断重启恢复，按 (session_id, call_id)
    # 幂等复用原决定请求、不写入第二条 DECISION_REQUESTED 或错误 HANDED_BACK 并顺利完成本轮
    import threading
    from harness.definitions import DEFAULT_FORM
    from harness.models import json_dumps
    from harness.proposals import delivery_turn, product_spec
    from harness.providers.call import ModelResponse
    from harness.projection import saved_decisions
    from harness.tightening import WATCHED_OUTPUTS

    q1, q2 = _sample_questions()
    defs = _definitions_with_ask_user(tmp_path / "defs_multi")
    followup = [{
        "id": "q_follow",
        "question": "JSON 字段名使用 snake_case 还是 camelCase？",
        "options": [
            {"id": "snake", "label": "snake_case"},
            {"id": "camel", "label": "camelCase"},
        ],
        "recommended": "snake",
        "rationale": "与现有接口字段一致",
    }]

    # 1) 同轮连续两轮提问并校验结构化返回
    multi_sys = LoopSystem.for_testing(
        tmp_path / "multi",
        FakeAdapter({
            "product": [
                ModelResponse(output=[_ask_user_call("call-m1", [q1, q2], note="先确认基本格式")]),
                ModelResponse(output=[_ask_user_call("call-m2", followup)]),
                product_spec(),
            ],
        }),
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        run_id = multi_sys.create_run("多轮提问结构化结果")
        _wait_and_answer(
            multi_sys, run_id, expected_round=1, option="submit",
            answers={"q1": "text"}, note="第一题选纯文本，第二题采用推荐",
        )
        _wait_and_answer(multi_sys, run_id, expected_round=2, option="recommended")
        multi_sys.activate_once(run_id)
        calls = _called_results(multi_sys, run_id, "ask_user")
        assert len(calls) == 2
        first_out = calls[0]["output"]
        assert first_out["option"] == "submit"
        assert first_out["note"] == "第一题选纯文本，第二题采用推荐"
        assert first_out["input_version"] == 1
        assert first_out["round"] == 1
        assert first_out["answers"] == [
            {
                "id": "q1",
                "question": "日志输出格式采用哪一种？",
                "selected_option_id": "text",
                "selected_option_label": "纯文本行",
                "recommended": "json",
                "from_recommended": False,
            },
            {
                "id": "q2",
                "question": "错误是否输出到标准错误流？",
                "selected_option_id": "stderr",
                "selected_option_label": "输出到 stderr",
                "recommended": "stderr",
                "from_recommended": True,
            },
        ]
        second_out = calls[1]["output"]
        assert second_out["round"] == 2
        assert second_out["answers"][0]["from_recommended"] is True
        assert multi_sys.project(run_id).product_spec is not None
    finally:
        multi_sys.close()

    # 2) 模拟进程在 role_choice 处于 open 时中断（写入了 tool_started 与 DECISION_REQUESTED，但未写 tool_called）
    from dataclasses import asdict
    crash_dir = tmp_path / "crash_open"
    crash_sys = LoopSystem.for_testing(
        crash_dir,
        FakeAdapter({"product": [ModelResponse(output=[_ask_user_call("call-crash", [q1, q2])])]}),
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    dec_box: list[str] = []
    try:
        # 即使单次输入上限设为 1 轮，重启按 (session_id, call_id) 复用既有请求时仍不得误拒
        crash_sys.set_parameter("ask_user.max_rounds_per_input", 1, reason="核对满额重启恢复", modified_by="user:test")
        run_id = crash_sys.create_run("崩溃幂等恢复")
        # 构造中断现场：直接用一次带 MODEL_MESSAGE + TOOL_STARTED + DECISION_REQUESTED 的未收尾事件序列
        session_id = crash_sys.project(run_id).sessions["product"].session_id
        act_id = "act_crashed_1"
        msg_item = _ask_user_call("call-crash", [q1, q2])
        msg_ref = crash_sys.artifacts.put(run_id, "model/msg", json_dumps(msg_item), media_type="application/json")

        def write_crash_scene(tx):
            parent = tx.append(NewEvent(
                EventType.DEPARTMENT_ACTIVATED, actor="system", department="product",
                session_id=session_id, state_before="running", state_after="running",
                payload={"activation_id": act_id, "cycle": 1, "input_version": 1, "guidance_version": 0,
                         "prompt_version": 1, "prompt_hash": "sha256:p", "guidance_ids": []},
            ))[0]
            tx.append(NewEvent(
                EventType.MODEL_MESSAGE, actor="department:product", department="product",
                parent_event_id=parent.event_id, session_id=session_id,
                state_before="running", state_after="running",
                payload={"activation_id": act_id, "step_id": 1, "purpose": "work",
                         "message_ref": asdict(msg_ref)},
            ))
            tx.append(NewEvent(
                EventType.TOOL_STARTED, actor="department:product", department="product",
                parent_event_id=parent.event_id, session_id=session_id,
                state_before="running", state_after="running",
                payload={"id": "call-crash", "name": "ask_user",
                         "args": {"questions": [q1, q2]}, "step_id": 1, "activation_id": act_id, "purpose": "work"},
            ))
            req = tx.append(NewEvent(
                EventType.DECISION_REQUESTED, actor="system", department="product",
                parent_event_id=parent.event_id, session_id=session_id,
                state_before="running", state_after="running",
                payload={
                    "kind": "role_choice", "blocks": "round",
                    "options": [{"id": opt.id, "label": opt.label} for opt in ROLE_CHOICE.options],
                    "description": "崩溃前发出的提问", "facts": [q1["question"], q2["question"]],
                    "department": "product", "questions": [q1, q2],
                    "session_id": session_id, "call_id": "call-crash", "input_version": 1, "round": 1, "note": None,
                },
            ))[0]
            dec_box.append(req.event_id)

        crash_sys.writes.transact(run_stream(run_id), write_crash_scene)
    finally:
        crash_sys.close()

    # 重启并恢复：不重复写 DECISION_REQUESTED，也不写 ACTION_VERIFIED handed_back；等待原 open 请求被回答后继续交出提案
    reopened = LoopSystem.for_testing(
        crash_dir,
        FakeAdapter({"product": [product_spec()]}),
        resume_on_startup=False,
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        reopened.orchestrator.resume_incomplete_run(run_id)
        assert [e for e in reopened.store.list_events(run_id) if e.type == EventType.ACTION_VERIFIED] == []
        entered_wait = threading.Event()
        reopened.store.subscribe(lambda evs: [
            entered_wait.set() for ev in evs
            if ev.type == EventType.DEPARTMENT_ACTIVATED and ev.department == "product"
        ])

        def answer_original():
            entered_wait.wait(timeout=5.0)
            dec = saved_decision(reopened.store, dec_box[0])
            reopened.orchestrator.answer_decision(
                dec.decision_id, "recommended", "重启后补答", base_version=dec.version,
                command=_command("recommended", dec.version),
            )

        t = threading.Thread(target=answer_original, daemon=True)
        t.start()
        reopened.activate_once(run_id)
        t.join(timeout=5.0)

        reqs = [e for e in reopened.store.list_events(run_id)
                if e.type == EventType.DECISION_REQUESTED and (e.payload or {}).get("kind") == "role_choice"]
        assert len(reqs) == 1
        [call_done] = _called_results(reopened, run_id, "ask_user")
        assert call_done["event"].payload["id"] == "call-crash"
        assert call_done["output"]["decision_id"] == dec_box[0]
        assert call_done["output"]["note"] == "重启后补答"
        assert reopened.project(run_id).product_spec is not None
    finally:
        reopened.close()

    # 3) 若在停机期间用户已提前回答该 role_choice，再重启时直接取已答结果继续，不阻塞
    pre_dir = tmp_path / "crash_answered"
    pre_sys = LoopSystem.for_testing(
        pre_dir,
        FakeAdapter([]),
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    dec2_box: list[str] = []
    try:
        run2 = pre_sys.create_run("停机期已回答的幂等恢复")
        ses2 = pre_sys.project(run2).sessions["product"].session_id
        act2 = "act_crashed_2"
        msg_item2 = _ask_user_call("call-pre", [q1])
        msg_ref2 = pre_sys.artifacts.put(run2, "model/msg", json_dumps(msg_item2), media_type="application/json")

        def write_pre_scene(tx):
            p = tx.append(NewEvent(
                EventType.DEPARTMENT_ACTIVATED, actor="system", department="product",
                session_id=ses2, state_before="running", state_after="running",
                payload={"activation_id": act2, "cycle": 1, "input_version": 1, "guidance_version": 0,
                         "prompt_version": 1, "prompt_hash": "sha256:p2", "guidance_ids": []},
            ))[0]
            tx.append(NewEvent(
                EventType.MODEL_MESSAGE, actor="department:product", department="product",
                parent_event_id=p.event_id, session_id=ses2,
                state_before="running", state_after="running",
                payload={"activation_id": act2, "step_id": 1, "purpose": "work",
                         "message_ref": asdict(msg_ref2)},
            ))
            tx.append(NewEvent(
                EventType.TOOL_STARTED, actor="department:product", department="product",
                parent_event_id=p.event_id, session_id=ses2,
                state_before="running", state_after="running",
                payload={"id": "call-pre", "name": "ask_user",
                         "args": {"questions": [q1]}, "step_id": 1, "activation_id": act2, "purpose": "work"},
            ))
            req = tx.append(NewEvent(
                EventType.DECISION_REQUESTED, actor="system", department="product",
                parent_event_id=p.event_id, session_id=ses2,
                state_before="running", state_after="running",
                payload={
                    "kind": "role_choice", "blocks": "round",
                    "options": [{"id": opt.id, "label": opt.label} for opt in ROLE_CHOICE.options],
                    "description": "待答", "facts": [q1["question"]],
                    "department": "product", "questions": [q1],
                    "session_id": ses2, "call_id": "call-pre", "input_version": 1, "round": 1, "note": None,
                },
            ))[0]
            dec2_box.append(req.event_id)

        pre_sys.writes.transact(run_stream(run2), write_pre_scene)
        dec2 = saved_decision(pre_sys.store, dec2_box[0])
        pre_sys.orchestrator.answer_decision(
            dec2.decision_id, "submit", "提前答复", base_version=dec2.version,
            command=_command("submit", dec2.version), answers={"q1": "text"},
        )
    finally:
        pre_sys.close()

    pre_reopened = LoopSystem.for_testing(
        pre_dir,
        FakeAdapter({"product": [product_spec()]}),
        resume_on_startup=False,
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        pre_reopened.orchestrator.resume_incomplete_run(run2)
        pre_reopened.activate_once(run2)
        reqs2 = [e for e in pre_reopened.store.list_events(run2)
                 if e.type == EventType.DECISION_REQUESTED and (e.payload or {}).get("kind") == "role_choice"]
        assert len(reqs2) == 1
        [call2] = _called_results(pre_reopened, run2, "ask_user")
        assert call2["output"]["selections"] == {"q1": "text"}
        assert call2["output"]["note"] == "提前答复"
        assert pre_reopened.project(run2).product_spec is not None
    finally:
        pre_reopened.close()


def test_role_choice_withdrawn_and_handed_back_on_add_input(tmp_path):
    # 守 R1 与 R2：role_choice 处于 open 且阻塞等待时追加新用户输入，旧请求按
    # superseded_by_hand_back 撤销、等待中的轮次立即醒来并记录 ask_user 的 TOOL_CALLED(ok=False)；
    # 后续步骤与崩溃重启恢复均不重放已撤销的 ask_user，并结合新 input_version 正常完成
    import threading
    import time
    from dataclasses import asdict
    from harness.definitions import DEFAULT_FORM
    from harness.models import json_dumps
    from harness.proposals import product_spec
    from harness.providers.call import ModelResponse
    from harness.tightening import WATCHED_OUTPUTS

    q1, _ = _sample_questions()
    defs = _definitions_with_ask_user(tmp_path / "defs_superseded")

    # 1) 在线等待期间调用 add_input：撤回旧 role_choice、立即唤醒当前轮并继续结合新输入完成
    live_sys = LoopSystem.for_testing(
        tmp_path / "live_superseded",
        FakeAdapter({
            "product": [
                ModelResponse(output=[_ask_user_call("call-hb-live", [q1])]),
                product_spec(),
            ],
        }),
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        run_id = live_sys.create_run("等待回答时追加新输入")
        entered = threading.Event()
        woke_done = threading.Event()
        live_errors: list[BaseException] = []

        def on_events(events: list[Any]) -> None:
            for event in events:
                if (event.type == EventType.DECISION_REQUESTED
                        and event.run_id == run_id
                        and (event.payload or {}).get("kind") == "role_choice"):
                    entered.set()

                    def push_new_input() -> None:
                        try:
                            deadline = time.monotonic() + 5.0
                            while (run_id not in live_sys.orchestrator._thin_driver._waiters
                                   and time.monotonic() < deadline):
                                time.sleep(0.005)
                            live_sys.orchestrator.add_input(run_id, "改按补充要求直接出稿", base_version=1)
                        except BaseException as exc:  # pragma: no cover - 仅失败诊断
                            live_errors.append(exc)
                        finally:
                            woke_done.set()

                    threading.Thread(target=push_new_input, daemon=True).start()

        live_sys.store.subscribe(on_events)
        live_sys.activate_once(run_id)
        assert entered.wait(timeout=5.0)
        assert woke_done.wait(timeout=5.0)
        assert not live_errors

        reqs = [e for e in live_sys.store.list_events(run_id)
                if e.type == EventType.DECISION_REQUESTED and (e.payload or {}).get("kind") == "role_choice"]
        assert len(reqs) == 1
        dec = saved_decision(live_sys.store, reqs[0].event_id)
        assert dec is not None
        assert dec.status == "withdrawn"
        assert (dec.withdrawal or {}).get("reason") == "superseded_by_hand_back"

        calls = _called_results(live_sys, run_id, "ask_user")
        assert len(calls) == 1
        assert calls[0]["event"].payload["id"] == "call-hb-live"
        assert calls[0]["ok"] is False
        assert "新的用户输入" in (calls[0]["error"] or "")

        proj = live_sys.project(run_id)
        assert proj.input_version == 2
        assert proj.product_work_input_version == 2
        assert proj.product_spec is not None
    finally:
        live_sys.close()

    # 2) 中断后等待期已被 add_input 撤回：重启恢复不重放已撤销的 ask_user，以 TOOL_CALLED(ok=False) 交还模型继续
    crash_dir = tmp_path / "crash_superseded"
    crash_sys = LoopSystem.for_testing(
        crash_dir,
        FakeAdapter([]),
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    dec_box: list[str] = []
    try:
        run2 = crash_sys.create_run("中断期间追加新输入后恢复")
        ses2 = crash_sys.project(run2).sessions["product"].session_id
        act2 = "act_crashed_superseded"
        msg_item = _ask_user_call("call-hb-crash", [q1])
        msg_ref = crash_sys.artifacts.put(run2, "model/msg", json_dumps(msg_item), media_type="application/json")

        def write_scene(tx: Any) -> None:
            p = tx.append(NewEvent(
                EventType.DEPARTMENT_ACTIVATED, actor="system", department="product",
                session_id=ses2, state_before="running", state_after="running",
                payload={"activation_id": act2, "cycle": 1, "input_version": 1, "guidance_version": 0,
                         "prompt_version": 1, "prompt_hash": "sha256:p3", "guidance_ids": []},
            ))[0]
            tx.append(NewEvent(
                EventType.MODEL_MESSAGE, actor="department:product", department="product",
                parent_event_id=p.event_id, session_id=ses2,
                state_before="running", state_after="running",
                payload={"activation_id": act2, "step_id": 1, "purpose": "work",
                         "message_ref": asdict(msg_ref)},
            ))
            tx.append(NewEvent(
                EventType.TOOL_STARTED, actor="department:product", department="product",
                parent_event_id=p.event_id, session_id=ses2,
                state_before="running", state_after="running",
                payload={"id": "call-hb-crash", "name": "ask_user",
                         "args": {"questions": [q1]}, "step_id": 1, "activation_id": act2, "purpose": "work"},
            ))
            req = tx.append(NewEvent(
                EventType.DECISION_REQUESTED, actor="system", department="product",
                parent_event_id=p.event_id, session_id=ses2,
                state_before="running", state_after="running",
                payload={
                    "kind": "role_choice", "blocks": "round",
                    "options": [{"id": opt.id, "label": opt.label} for opt in ROLE_CHOICE.options],
                    "description": "中断前提问", "facts": [q1["question"]],
                    "department": "product", "questions": [q1],
                    "session_id": ses2, "call_id": "call-hb-crash", "input_version": 1, "round": 1, "note": None,
                },
            ))[0]
            dec_box.append(req.event_id)

        crash_sys.writes.transact(run_stream(run2), write_scene)
        crash_sys.orchestrator.add_input(run2, "停机后补发的新输入", base_version=1)
        dec2 = saved_decision(crash_sys.store, dec_box[0])
        assert dec2 is not None
        assert dec2.status == "withdrawn"
        assert (dec2.withdrawal or {}).get("reason") == "superseded_by_hand_back"
    finally:
        crash_sys.close()

    reopened = LoopSystem.for_testing(
        crash_dir,
        FakeAdapter({"product": [product_spec()]}),
        resume_on_startup=False,
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        reopened.orchestrator.resume_incomplete_run(run2)
        reopened.activate_once(run2)
        reqs2 = [e for e in reopened.store.list_events(run2)
                 if e.type == EventType.DECISION_REQUESTED and (e.payload or {}).get("kind") == "role_choice"]
        assert len(reqs2) == 1
        calls2 = _called_results(reopened, run2, "ask_user")
        assert len(calls2) == 1
        assert calls2[0]["event"].payload["id"] == "call-hb-crash"
        assert calls2[0]["ok"] is False
        assert "新的用户输入" in (calls2[0]["error"] or "")
        proj2 = reopened.project(run2)
        assert proj2.input_version == 2
        assert proj2.product_work_input_version == 2
        assert proj2.product_spec is not None
    finally:
        reopened.close()


def test_start_after_work_item_role_choice_answer_waits_without_concurrent_loop(tmp_path):
    # 守 R1 与 R2：经 orchestrator.start_work_item 启动的 run 在职能触发 role_choice 等待期间，
    # 回答决定后紧接调用 orchestrator.start(run_id) 时统一感知 _work_item_tasks 里的活跃任务并等待其收尾，
    # 不会并发启动第二个 run_until_stop 或因 no_new_work 误报失败，最终收敛至 done 并完成采纳
    import asyncio
    from harness.definitions import DEFAULT_FORM
    from harness.models import ProjectEventType
    from harness.proposals import delivery_turn, product_spec
    from harness.providers.call import ModelResponse
    from harness.tests.helpers import quality_turns
    from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
    from harness.tightening import WATCHED_OUTPUTS

    q1, _ = _sample_questions()
    defs = _definitions_with_ask_user(tmp_path / "defs_coord")
    system = LoopSystem.for_testing(
        tmp_path / "run_coord",
        FakeAdapter({
            "product": [
                ModelResponse(output=[_ask_user_call("call-coord", [q1])]),
                product_spec(),
            ],
            "engineering": [delivery_turn()],
            "quality": quality_turns("release", "checks passed on the current snapshot"),
        }),
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        project_id = system.projects.register("任务协同防并发", "核对 start_work_item 与 start 不并发重入")
        _work_item_id, run_id = system.projects.start_work_item(project_id, "回答提问后继续并采纳")

        observed_calls: list[str] = []
        in_flight = 0
        max_in_flight = 0
        orig_run_until_stop = system.orchestrator.run_until_stop

        async def tracked_run_until_stop(target_run_id: str) -> Any:
            nonlocal in_flight, max_in_flight
            observed_calls.append(target_run_id)
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            try:
                return await orig_run_until_stop(target_run_id)
            finally:
                in_flight -= 1

        system.orchestrator.run_until_stop = tracked_run_until_stop  # type: ignore[method-assign]

        async def drive() -> None:
            loop = asyncio.get_running_loop()
            opened = asyncio.Event()
            dec_box: list[str] = []

            def on_events(events: list[Any]) -> None:
                for ev in events:
                    if (ev.type == EventType.DECISION_REQUESTED
                            and ev.run_id == run_id
                            and (ev.payload or {}).get("kind") == "role_choice"):
                        dec_box.append(ev.event_id)
                        loop.call_soon_threadsafe(opened.set)

            system.store.subscribe(on_events)
            work_task = system.orchestrator.start_work_item(run_id)
            await asyncio.wait_for(opened.wait(), timeout=WAIT_FOR_HOST_WORK_SEC)
            assert system.orchestrator.work_item_execution(run_id) is work_task
            assert not work_task.done()

            dec = saved_decision(system.store, dec_box[0])
            assert dec is not None
            system.orchestrator.answer_decision(
                dec.decision_id, "submit", "选定纯文本格式",
                base_version=dec.version, command=_command("submit", dec.version), answers={"q1": "text"},
            )
            resume_task = system.orchestrator.start(run_id)
            await asyncio.wait_for(asyncio.gather(work_task, resume_task), timeout=WAIT_FOR_HOST_WORK_SEC)

        asyncio.run(drive())

        assert observed_calls == [run_id]
        assert max_in_flight == 1
        assert [e for e in system.store.list_events(run_id) if e.type == EventType.RUN_FAILED] == []
        final_proj = system.project(run_id)
        assert final_proj.status == "done"
        assert final_proj.stop_reason == "released"
        adopted = [
            e for e in system.store.list_project_events(project_id)
            if e.type == ProjectEventType.DELIVERABLE_ADOPTED and (e.payload or {}).get("run_id") == run_id
        ]
        assert len(adopted) == 1
        assert system.orchestrator.execution(run_id) is None
        assert system.orchestrator.work_item_execution(run_id) is None
    finally:
        system.close()

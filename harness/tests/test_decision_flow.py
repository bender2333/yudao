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
import uuid
from pathlib import Path

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

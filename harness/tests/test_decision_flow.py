# 工单 #827（S4a）：决定请求的处理与建档的流转在应用层，薄驱动只转交
# （骨架与应用设计说明第 6、12 节；总图第二节「薄驱动」，第三节外环「等用户」）。
#
# 守 R1（第三环的不变式）与 R3（路线图阶段一写明的行为）：
# - R1：回答只在写入口的一个事务里写成事实——回答与它解除的阻塞同一批写入，命令身份绑在这两条事件上；
#   核对不通过时一个事件都不写、命令不登记。
# - R3：决定请求得到回答以后 run 继续执行（应用层给出要继续执行的 run，由调用方开始）；
#   这些处理在应用层，薄驱动里不再有（设计说明第 6 节「薄驱动只连接」）。
#
# 一次部门激活、SQLite 事件库与数据目录，属于模块层（test-pyramid 第 2 节）。
# 事项级的决定、基线采纳与建档修改轮的行为由 test_projects.py、test_onboarding_confirmation_round.py、
# test_onboarding_revision_context.py 守着（集成层），这里不重复。

import ast
import uuid
from pathlib import Path

import pytest

from harness import decision_flow
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.decision_flow import DECISION_FLOW
from harness.decisions import StaleDecision
from harness.event_store import Command
from harness.models import EventType
from harness.projection import saved_decision, saved_decisions
from harness.runtime import LoopSystem
from harness.tests.helpers import TOOL_CALL_REQUIRED_LIMIT as LIMIT

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
    # R3、第 6 节「薄驱动只连接」：这些处理在应用层；薄驱动里只剩两个转交，一处写事件都没有
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

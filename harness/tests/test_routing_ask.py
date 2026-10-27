# 询问分支按路由请求运行（工单 #862；骨架与应用设计说明第 5.1、5.3、5.4 节、三部门的循环结构；
# 总图第四节「路由」缝）。
#
# 守的是 R2：路由契约给询问分支的输出——询问的开始、这一轮的上限、回答与没能回答——按定义取部门与上限；
# 以及 R3：询问的开始、回问、回问深度与分支步数的上限、答没答出来由路由判断，薄驱动不再自己写这些判断，
# 分支的一轮照常经执行契约运行、已用掉的量由薄驱动从最小投影扣。询问、回问、上限、没能回答与重启以后
# 接着同一次询问的行为由 test_ask_branch.py、test_ask_chain.py、test_issue_475.py 与事件序列基准守住，
# 这里只补契约与那几条搬家。
#
# 读源码文件与投影对象，不起服务、不写文件，属于单元层。

import ast
from pathlib import Path
from types import SimpleNamespace

from harness import routing_contract
from harness.definitions import DEFINITIONS
from harness.models import EventType, RunProjection
from harness.watched_outputs import ROUTING

HARNESS = Path(__file__).resolve().parents[1]


def _running() -> RunProjection:
    return RunProjection(run_id="run", task="Build a CLI.")


def _limits(**kwargs) -> routing_contract.AskLimits:
    return routing_contract.AskLimits(max_model_steps=20, **kwargs)


def _ask_call(**args) -> dict[str, object]:
    # 提问方这一次的工具调用：参数，以及这一步还剩几步（执行契约给出，工单 #826）
    return {"name": "ask", "args": args, "remaining_steps": 8}


def _branch(recipient: str = "product", session_id: str = "ses_ask_pro_1") -> routing_contract.AskBranch:
    return routing_contract.AskBranch(recipient=recipient, session_id=session_id,
                                      max_model_steps=4, max_time_sec=60.0)


def _pending(projection: RunProjection, branch_session_id: str = "ses_ask_pro_1",
             origin: str = "ses_eng") -> None:
    projection.ask_stack.append({"requester": "engineering", "recipient": "product",
                                 "question": "first?", "branch_session_id": branch_session_id,
                                 "origin_session_id": origin})


def _answered_event(payload: dict[str, str], session_id: str = "ses_ask_pro_1") -> object:
    return SimpleNamespace(type=EventType.ASK_ANSWERED, session_id=session_id, payload=payload)


def test_a_new_ask_asks_the_route_for_one_round_of_the_recipient_department():
    # R2 & R3：询问的开始归路由——回复的部门、分支会话与要写下的那一层都由路由组好，
    # 这一轮的上限取被问部门声明的量，工作引用指向这次询问（设计说明第 5.1 节输出、第 5.4 节第 4 条）
    requested = ROUTING.ask_branch(
        _running(), [], requester="engineering", session_id="ses_eng",
        call=_ask_call(recipient="product", question="Is lowercase ok?", background="bg", expected="yes/no"),
        limits=_limits(department_max_model_steps={"product": 4}, department_max_time_sec={"product": 90.0}),
    )
    assert isinstance(requested, routing_contract.AskBranch)
    assert requested.recipient == "product"
    assert requested.session_id.startswith("ses_ask_")
    assert requested.start is not None
    assert requested.start["requester"] == "engineering"
    assert requested.start["recipient"] == "product"
    assert requested.start["question"] == "Is lowercase ok?"
    assert requested.start["background"] == "bg"
    assert requested.start["expected"] == "yes/no"
    assert requested.start["branch_session_id"] == requested.session_id
    assert requested.max_model_steps == 4
    assert requested.max_time_sec == 90.0
    assert requested.work_ref["ask"]["branch_session_id"] == requested.session_id
    assert requested.work_ref["ask"]["recipient"] == "product"


def test_the_branch_limit_is_the_smaller_of_the_department_and_what_the_asker_has_left():
    # R3：分支步数的上限归路由，按被问部门声明的量与提问方这一步剩下的量取小的；
    # 没有声明的量时按运行配置里的全局上限，时间按事项的运行时间上限
    projection = _running()
    requested = ROUTING.ask_branch(
        projection, [], requester="engineering", session_id="ses_eng",
        call={"name": "ask", "args": {"recipient": "product", "question": "q"}, "remaining_steps": 2},
        limits=_limits(department_max_model_steps={"product": 9}),
    )
    assert requested.max_model_steps == 2
    requested = ROUTING.ask_branch(
        projection, [], requester="engineering", session_id="ses_eng",
        call=_ask_call(recipient="quality", question="q"), limits=_limits(),
    )
    # 提问方这一步还剩 8 步，全局上限 20 步
    assert requested.max_model_steps == 8
    assert requested.max_time_sec == float(projection.run_time_limit_sec)


def test_an_ask_that_cannot_start_is_refused_with_the_reason_the_tool_result_shows():
    # R3：调用不合法时不运行、不写事件，原因作为这次工具调用的错误交回提问方。部门取自路由的定义：
    # 不在清单里的、提问方自己的都不行；问题与事实两部分都没有时不算一次询问（工单 #554）
    projection = _running()
    refused = ROUTING.ask_branch(projection, [], requester="engineering", session_id="ses_eng",
                                 call=_ask_call(recipient="engineering", question="q"), limits=_limits())
    assert isinstance(refused, routing_contract.AskRejection)
    assert "invalid recipient" in refused.message
    refused = ROUTING.ask_branch(projection, [], requester="engineering", session_id="ses_eng",
                                 call=_ask_call(recipient="ops", question="q"), limits=_limits())
    assert "invalid recipient ops" in refused.message
    refused = ROUTING.ask_branch(projection, [], requester="engineering", session_id="ses_eng",
                                 call=_ask_call(recipient="quality", question="  "), limits=_limits())
    assert refused.message == "question must be a non-empty string"
    # 工程询问质检时问题写在事实那一部分里（工单 #554）
    requested = ROUTING.ask_branch(projection, [], requester="engineering", session_id="ses_eng",
                                   call=_ask_call(recipient="quality", facts="the snapshot is X"),
                                   limits=_limits())
    assert isinstance(requested, routing_contract.AskBranch)
    assert requested.start["facts"] == "the snapshot is X"


def test_a_pending_ask_continues_its_own_layer_instead_of_opening_a_new_one():
    # R3：这个会话自己那次没结束的询问接着那一层，不新开一层（工单 #473 的嵌套询问）；回问由同一套
    # 判断处理，层数上限按路由自己的定义算（tightening 一侧）
    projection = _running()
    _pending(projection)
    requested = ROUTING.ask_branch(projection, [], requester="engineering", session_id="ses_eng",
                                   call=_ask_call(recipient="quality", question="second?"), limits=_limits())
    assert isinstance(requested, routing_contract.AskBranch)
    assert requested.session_id == "ses_ask_pro_1"
    assert requested.recipient == "product"
    assert requested.start is None


def test_an_ask_that_was_already_answered_is_reported_without_another_round():
    # R3：这一层已经答过（重新启动以后接着同一次询问）：结果照原样交回，不再跑一轮、不再写事件
    projection = _running()
    _pending(projection)
    events = [_answered_event({"status": "answered", "answer": "Yes."})]
    reported = ROUTING.ask_branch(projection, events, requester="engineering", session_id="ses_eng",
                                  call=_ask_call(recipient="product", question="first?"), limits=_limits())
    assert isinstance(reported, routing_contract.AskOutcome)
    assert reported.recorded is True
    assert (reported.status, reported.answer) == ("answered", "Yes.")
    assert reported.session_id == "ses_ask_pro_1"
    events = [_answered_event({"status": "unable", "reason": "branch failed to answer"})]
    reported = ROUTING.ask_branch(projection, events, requester="engineering", session_id="ses_eng",
                                  call=_ask_call(recipient="product", question="first?"), limits=_limits())
    assert (reported.status, reported.reason) == ("unable", "branch failed to answer")


def test_the_answer_the_branch_submitted_is_what_the_route_hands_back():
    # R3：分支这一轮交上来的回答由路由整理（工程回答质检时回答分两部分，工单 #554）
    outcome = ROUTING.ask_outcome(_running(), branch=_branch(),
                                  result=routing_contract.AskRoundResult(submission={"answer": "Yes, lowercase is ok."}))
    assert (outcome.status, outcome.answer, outcome.revises) == ("answered", "Yes, lowercase is ok.", None)
    outcome = ROUTING.ask_outcome(
        _running(), branch=_branch(recipient="quality"),
        result=routing_contract.AskRoundResult(submission={"facts": "it is X", "explanation": "because Y"}))
    assert (outcome.status, outcome.answer) == ("answered", "it is X")
    assert (outcome.facts, outcome.explanation) == ("it is X", "because Y")


def test_a_product_answer_that_revises_the_prd_hands_the_proposal_to_the_driver():
    # R3：回答同时交上的成果由路由组装（循环结构第 4.3 节、设计说明第 5.5 节）：产品在回答一次询问时
    # 可以修订 PRD，提案参数随结果交给薄驱动，由薄驱动经写入口提交
    outcome = ROUTING.ask_outcome(
        _running(), branch=_branch(),
        result=routing_contract.AskRoundResult(submission={
            "answer": "按澄清修订 PRD。", "goal": "echo", "requirements": ["prints the argument"],
            "acceptance_criteria": ["prints"]}))
    assert outcome.revises["kind"] == "product_spec"
    assert outcome.revises["issuer"] == "product"
    assert outcome.revises["requirements"] == ["prints the argument"]
    assert "answer" not in outcome.revises
    # 只有产品的回答带这一份成果：别的部门回答时即便带了同样的参数也不是提案
    outcome = ROUTING.ask_outcome(
        _running(), branch=_branch(recipient="quality"),
        result=routing_contract.AskRoundResult(submission={"facts": "f", "requirements": ["r"]}))
    assert outcome.revises is None


def test_a_branch_that_did_not_answer_says_why():
    # R3：没能回答的原因由路由按这一轮的实际情形取（验收「没能回答」一条）
    projection = _running()
    outcome = ROUTING.ask_outcome(projection, branch=_branch(),
                                  result=routing_contract.AskRoundResult(steps_left=0))
    assert outcome.status == "unable"
    assert "step limit" in outcome.reason
    outcome = ROUTING.ask_outcome(projection, branch=_branch(),
                                  result=routing_contract.AskRoundResult(time_exhausted=True))
    assert "time limit" in outcome.reason
    outcome = ROUTING.ask_outcome(
        projection, branch=_branch(),
        result=routing_contract.AskRoundResult(message="department stopped without calling a tool"))
    assert outcome.reason == "department stopped without calling a tool"
    outcome = ROUTING.ask_outcome(projection, branch=_branch(),
                                  result=routing_contract.AskRoundResult(stop_reason="cancel"))
    assert outcome.reason == "cancel"
    outcome = ROUTING.ask_outcome(projection, branch=_branch(),
                                  result=routing_contract.AskRoundResult(steps_left=3))
    assert outcome.reason == "branch failed to answer"


def _function_source(text: str, name: str) -> str:
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"orchestrator.py 里没有 {name}")


def test_the_thin_driver_only_connects_the_ask_branch():
    # R3：薄驱动里没有询问的判断（验收第 2 条）：这些判断与它们的说明只住在路由实现里；
    # 薄驱动向路由要这一轮、要结果，分支的一轮照常交给执行契约，工作引用来自路由的请求
    driver = (HARNESS / "orchestrator.py").read_text(encoding="utf-8")
    route = (HARNESS / "watched_outputs.py").read_text(encoding="utf-8")
    for judgment in ("invalid recipient",
                     "question must be a non-empty string",
                     "department reached the model step limit without submitting a proposal",
                     "department reached the time limit without submitting an answer",
                     "branch failed to answer"):
        assert judgment not in driver, judgment
        assert judgment in route, judgment
    assert "self._routing.ask_branch(" in driver
    assert "self._routing.ask_outcome(" in driver
    assert "branch.work_ref" in driver
    # 询问这一段不按部门写死：部门取自路由的判断与它组好的成果（`issuer`）
    for name in ("_execute_ask", "_run_ask_branch", "_commit_answer_revision", "_branch_steps"):
        source = _function_source(driver, name)
        for department in DEFINITIONS.departments:
            assert f'"{department}"' not in source, (name, department)

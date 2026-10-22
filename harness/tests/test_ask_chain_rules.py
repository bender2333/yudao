# 询问链的规则判定（工单 #473，ADR-0039）：
# 询问链的层数上限从规则登记 organization.ask_chain_max_depth 读，不写死在代码里；
# 纯函数按会话在链上的位置给出能不能再问一层；超过上限时给出原因：
# 链已有几层、上限是多少，并提示把要问的内容写进回答。
#
# 单元层：只用内存里的投影与纯函数，不起目录、不起进程。

from harness.actions import WorkspaceFacts
from harness.adjudication import ask_chain_decision, ask_chain_max_depth, tool_permission
from harness.definitions import DEFINITIONS
from harness.models import RunProjection
from harness.recording import WorkBasis


def _chain(depth: int) -> RunProjection:
    # 链上 depth 层：第 i 层由上一层的分支发起（i 为 0 时由主线发起），
    # 分支会话是 ses_ask_i，层号从 1 数
    stack = [
        {
            "requester": "product" if index % 2 == 0 else "engineering",
            "recipient": "engineering" if index % 2 == 0 else "product",
            "question": "问题",
            "branch_session_id": f"ses_ask_{index}",
            "origin_session_id": f"ses_ask_{index - 1}" if index else "ses_main",
        }
        for index in range(depth)
    ]
    return RunProjection(run_id="run_test", phase="ENGINEERING", ask_stack=stack)


def _permission(projection: RunProjection, session_id: str):
    return tool_permission(
        projection,
        {"name": "ask", "args": {"recipient": "quality", "question": "还能问吗？"}},
        department="engineering",
        session_id=session_id,
        guidance_only=False,
        basis=WorkBasis.current(projection, "engineering"),
        aborted=False,
        facts=WorkspaceFacts(),
    )


def test_the_chain_limit_comes_from_the_rule_registry():
    # 层数上限从规则登记读，不写死在代码里
    assert ask_chain_max_depth() == DEFINITIONS.rule_value("organization.ask_chain_max_depth")
    assert ask_chain_max_depth() == 3


def test_the_chain_decision_covers_the_combinations():
    # 链上的位置在上限之内：可以再问一层
    assert ask_chain_decision(0, 3) == (True, None)
    assert ask_chain_decision(1, 3) == (True, None)
    assert ask_chain_decision(2, 3) == (True, None)
    # 超过上限：被拒绝，原因写明链已有几层、上限是多少，并提示把要问的内容写进回答
    allowed, reason = ask_chain_decision(3, 3)
    assert allowed is False
    assert reason is not None
    assert "已有 3 层" in reason
    assert "上限是 3 层" in reason
    assert "写进回答" in reason
    # 上限是 2 时第三层被拒绝，第四层同样被拒绝
    assert ask_chain_decision(1, 2) == (True, None)
    allowed, reason = ask_chain_decision(2, 2)
    assert allowed is False
    assert reason is not None and "上限是 2 层" in reason
    assert ask_chain_decision(3, 2)[0] is False


def test_the_branch_may_ask_again_within_the_limit():
    # 链上两层时，最内层的分支还能再问一层（第三层）
    projection = _chain(2)
    assert _permission(projection, "ses_ask_1").allowed


def test_the_branch_is_denied_beyond_the_chain_limit():
    # 链上三层时，最内层的分支再问一层被工具许可拒绝，原因写明层数与上限
    projection = _chain(3)
    denied = _permission(projection, "ses_ask_2")
    assert denied.allowed is False
    assert denied.reason is not None
    assert "已有 3 层" in denied.reason
    assert "上限是 3 层" in denied.reason


def test_the_main_session_keeps_its_own_tools_while_a_branch_is_open():
    # 分支的约束只作用在分支会话上：主线会话不受分支的约束
    projection = _chain(1)
    write = tool_permission(
        projection,
        {"name": "write_file", "args": {"path": "src/echo.py", "content": "print(1)\n"}},
        department="engineering",
        session_id="ses_main",
        guidance_only=False,
        basis=WorkBasis.current(projection, "engineering"),
        aborted=False,
        facts=WorkspaceFacts(),
    )
    assert write.allowed
    # 分支会话不能改运行工作区
    branch_write = tool_permission(
        projection,
        {"name": "write_file", "args": {"path": "src/echo.py", "content": "print(1)\n"}},
        department="engineering",
        session_id="ses_ask_0",
        guidance_only=False,
        basis=WorkBasis.current(projection, "engineering"),
        aborted=False,
        facts=WorkspaceFacts(),
    )
    assert branch_write.allowed is False

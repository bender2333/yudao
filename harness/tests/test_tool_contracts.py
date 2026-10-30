# 工具定义本身的规则：工具种类与动作类别、工具说明写明的证据要求、回执的显示方式、唯一的可重复判断入口，
# 以及按输入方式提供工具的机制。这些结论只读取仓库内的定义与纯函数，登记为单元层。
#
# 动作合同的两项元数据（工单 #1170；恢复契约第 4 节；网络取回与 MCP 设计说明第 18 节；总图第四节「动作」缝）：
# 类别只增、每类有自己的既定合同，定义与动作请求写明这两项，写错立刻拒绝，旧合同与旧定义照旧读得进来。

from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from harness.actions import (ADDED_KINDS, ESTABLISHED_CONTRACTS, Action, ActionKind, ActionReceipt,
                             established_cancellable, established_verification)
from harness.definitions import DEFINITIONS, Identifier, Tool
from harness.tools import (tool_action, tool_cancellable, tool_kind, tool_verification, tools_for)

TOOLS = DEFINITIONS.tools


def test_tools_are_host_tools_or_environment_actions():
    # 主机工具由控制核心处理（提交类工具与询问/回答工具）；其余工具是环境工具，各有动作类别
    assert {name for name, tool in TOOLS.items() if tool.kind == "host"} == {
        *{name for name in TOOLS if name.startswith("submit_")}, "ask", "answer"}
    assert {name: tool.action for name, tool in TOOLS.items() if tool.kind == "environment"} == {
        "read_file": "read", "list_files": "read", "search": "read", "read_range": "read",
        "write_file": "write", "edit_range": "write", "delete_file": "write", "move_file": "write",
        "run_check": "check", "bash": "command", "read_output": "command", "stop_job": "command",
    }

def test_answer_prd_revision_parameter_definitions_match_submit_product_spec():
    # answer 中附带的 PRD 修订参数定义必须与 submit_product_spec 对应参数完全一致
    answer_props = TOOLS["answer"].parameters["properties"]
    spec_props = TOOLS["submit_product_spec"].parameters["properties"]
    for param_name, spec_def in spec_props.items():
        assert param_name in answer_props, f"{param_name} missing from answer parameters"
        assert answer_props[param_name] == spec_def, f"{param_name} definition mismatch"


def test_write_tools_belong_to_engineering_and_quality():
    # 工程写交付、质检写测试材料（工单 #645）：两个部门都有写入与区间编辑，产品没有；
    # 质检能写到哪里由工具许可核对（只能写 .yudao-qa-tests/，见 test_qa_test_materials.py）
    assert tool_kind("edit_range") == "environment" and tool_action("edit_range") == "write"
    assert {"write_file", "edit_range"} <= set(tools_for("engineering"))
    assert {"write_file", "edit_range"} <= set(tools_for("quality"))
    assert "edit_range" not in tools_for("product") and "write_file" not in tools_for("product")


def test_the_action_kinds_add_the_four_network_and_trial_categories():
    # 类别只增：原来的四类还在，新增的四类可用；每一类都在既定合同里有自己的一行
    assert set(get_args(ActionKind)) == {
        "read", "write", "check", "command", "fetch", "mcp", "trial", "browser"}
    assert set(ESTABLISHED_CONTRACTS) == set(get_args(ActionKind))
    assert set(ADDED_KINDS) == {"fetch", "mcp", "trial", "browser"}


def test_each_action_kind_follows_the_recovery_contract():
    # 恢复契约第 4 节：读取与命令没有可以查询的外部结果，写入以树快照核实，检查的结果是检查回执、经查询取得；
    # 取回与 MCP 没有可以验证的查询；试用会话与浏览器按动作记录与会话记录查询，取消能否确认停止随工具不同
    assert {kind: (established_verification(kind), established_cancellable(kind))
            for kind in get_args(ActionKind)} == {
        "read": ("none", True),
        "write": ("snapshot", True),
        "check": ("query", True),
        "command": ("none", True),
        "fetch": ("none", True),
        "mcp": ("none", None),
        "trial": (None, True),
        "browser": (None, True),
    }


def test_every_environment_tool_declares_the_action_metadata():
    # 新发布的静态环境工具定义显式给出新增元数据；主机工具没有动作，也没有这两项
    for name, tool in TOOLS.items():
        if tool.kind != "environment":
            assert tool.verification is None and tool.cancellable is None, name
            continue
        assert tool.verification is not None and tool.cancellable is not None, f"{name} 没有写明动作合同的元数据"
        assert tool.verification == established_verification(tool.action), name
        fixed = established_cancellable(tool.action)
        assert fixed is None or tool.cancellable == fixed, name


def test_the_tools_module_reads_the_metadata_from_the_definitions():
    assert tool_verification("write_file") == "snapshot"
    assert tool_cancellable("run_check") is True
    assert tool_verification("submit_delivery") is None
    assert tool_cancellable("submit_delivery") is None
    assert tool_verification("not_a_tool") is None and tool_cancellable("not_a_tool") is None


def test_an_old_definition_entry_without_the_new_fields_is_still_read():
    # 旧定义文件缺少这两项：照样读得进来，动作按类别的既定值解释
    tool = Tool.model_validate({"kind": "environment", "action": "write", "description": "write a file",
                                "parameters": {"type": "object"}})
    assert tool.verification is None and tool.cancellable is None


def test_a_definition_with_wrong_action_metadata_is_rejected_naming_the_tool():
    adapter = TypeAdapter(dict[Identifier, Tool])
    entry = {"kind": "environment", "action": "write", "description": "write a file",
             "parameters": {"type": "object"}}
    with pytest.raises(ValidationError) as wrong_value:
        adapter.validate_python({"write_matter_note": {**entry, "verification": "none", "cancellable": True}})
    problem = wrong_value.value.errors()[0]
    assert problem["loc"] == ("write_matter_note",) and "verified by 'snapshot'" in problem["msg"]
    with pytest.raises(ValidationError) as wrong_type:
        adapter.validate_python({"write_matter_note": {**entry, "verification": "snapshot", "cancellable": "yes"}})
    problem = wrong_type.value.errors()[0]
    assert problem["loc"] == ("write_matter_note", "cancellable"), "错误的元数据类型没有定位到工具与字段"
    with pytest.raises(ValidationError) as wrong_kind:
        adapter.validate_python({"write_matter_note": {**entry, "action": "fetchh"}})
    assert wrong_kind.value.errors()[0]["loc"] == ("write_matter_note", "action")


def test_a_new_kind_tool_must_declare_the_metadata():
    # 新增的类别必须写明这两项；取消能否确认停止随传输不同（MCP 的 HTTP 与 stdio）时同样必须写明
    trial = {"kind": "environment", "action": "trial", "description": "开始试用会话",
             "parameters": {"type": "object"}}
    with pytest.raises(ValidationError, match="requires verification and cancellable"):
        Tool.model_validate(trial)
    assert Tool.model_validate({**trial, "verification": "query", "cancellable": True}).verification == "query"
    with pytest.raises(ValidationError, match="requires verification and cancellable"):
        Tool.model_validate({"kind": "environment", "action": "mcp", "description": "调用 MCP 工具",
                             "parameters": {"type": "object"}, "verification": "none"})


def test_a_host_tool_cannot_declare_an_action_or_its_metadata():
    # 主机工具由控制核心执行，没有动作类别，也没有这两项
    with pytest.raises(ValidationError, match="has no action"):
        Tool.model_validate({"kind": "host", "proposal": "product_spec", "action": "read",
                             "description": "提交需求", "parameters": {"type": "object"}})
    with pytest.raises(ValidationError, match="has no action metadata"):
        Tool.model_validate({"kind": "host", "proposal": "product_spec", "description": "提交需求",
                             "parameters": {"type": "object"}, "verification": "none"})


def test_an_old_contract_request_and_receipt_are_still_read():
    # 旧合同里没有这三项：读得进来，按原来的字段与动作类别的既定值解释
    action = Action.model_validate({"action_id": "act:1", "kind": "write", "tool": "write_file",
                                    "department": "engineering", "input": {"path": "a.txt"}})
    assert action.verification is None and action.cancellable is None
    receipt = ActionReceipt.model_validate({"action_id": "act:1", "status": "completed", "output": "a.txt"})
    assert receipt.refused is False and receipt.refused_reason is None and receipt.ok


def test_a_request_with_wrong_or_missing_metadata_is_rejected():
    with pytest.raises(ValidationError, match="verified by 'snapshot'"):
        Action(action_id="act:1", kind="write", tool="write_file", department="engineering",
               input={}, verification="none")
    with pytest.raises(ValidationError, match="can be confirmed"):
        Action(action_id="act:1", kind="read", tool="read_file", department="engineering",
               input={}, cancellable=False)
    with pytest.raises(ValidationError, match="requires verification and cancellable"):
        Action(action_id="act:1", kind="fetch", tool="fetch_url", department="engineering", input={})
    declared = Action(action_id="act:1", kind="fetch", tool="fetch_url", department="engineering", input={},
                      verification="none", cancellable=True)
    assert declared.verification == "none" and declared.cancellable is True


def test_a_refusal_receipt_marks_the_refusal_and_keeps_the_old_fields():
    reason = "engineering cannot use write_file"
    receipt = ActionReceipt.refusal("act:1", reason)
    assert (receipt.refused, receipt.refused_reason) == (True, reason)
    assert receipt.error == reason and receipt.ok is False
    assert (receipt.action_id, receipt.status, receipt.output) == ("act:1", "failed", None)



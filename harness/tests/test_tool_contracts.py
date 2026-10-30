# 工具定义本身的规则：工具种类与动作类别、工具说明写明的证据要求、回执的显示方式、唯一的可重复判断入口，
# 以及按输入方式提供工具的机制。这些结论只读取仓库内的定义与纯函数，登记为单元层。


from harness.definitions import DEFINITIONS
from harness.tools import tool_action, tool_kind, tools_for

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



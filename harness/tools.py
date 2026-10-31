# 工具：工具的类别、动作类别、提交的提案种类、描述与参数取自定义（definitions/tools.json），各部门可以使用的工具
# 取自定义的角色（definitions/roles.json）与事项种类（definitions/work_items.json）；这里是读取它们的函数，
# 主机工具由步骤驱动执行，环境工具的动作由执行环境（environment.py）执行。
#
# 读的是交给它的那份定义（工单 #1098，设计说明第 5.4 节第 3 条）：工具许可与提案校验把事项所用的定义
# （组织定义与它引用的路由定义所在的那个定义版本）交进来；没有交的时候是当前加载的那一份。
# 装配、显示与其他读取当前定义的调用方不交，交给它们的是哪一份定义不改变它们看到的东西。

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .definitions import DEFINITIONS, Definitions, Verification, thaw

# 浏览器工具（浏览器与 computer use 设计说明第 4.2 节，工单 #147）：由 scripts/extract_browser_tools.py 从
# Playwright MCP 0.0.83 的 tools/list 生成定义，按这张表筛选。browser_drop 能把本机路径的文件投给页面，
# 路径规则与 browser_file_upload 相同（限试用副本内）。
BROWSER_TOOL_NAMES: tuple[str, ...] = (
    "browser_navigate", "browser_navigate_back",
    "browser_click", "browser_hover", "browser_drag", "browser_type", "browser_fill_form",
    "browser_select_option", "browser_press_key", "browser_file_upload", "browser_handle_dialog",
    "browser_drop",
    "browser_wait_for", "browser_tabs", "browser_resize", "browser_emulate_media", "browser_close",
    "browser_snapshot", "browser_find", "browser_console_messages", "browser_network_requests",
    "browser_network_request",
    "browser_verify_element_visible", "browser_verify_text_visible", "browser_verify_list_visible",
    "browser_verify_value",
    "browser_generate_locator",
    "browser_take_screenshot",
)
# 不提供的工具（设计说明第 4.2 节）：脚本能绕过界面直接改页面状态，这样得到的结论不能说明用户能完成这项操作
EXCLUDED_BROWSER_TOOLS: tuple[str, ...] = ("browser_evaluate", "browser_run_code_unsafe")
# 需要图像输入的工具（设计说明第 6.1 节）：调用目标不含图像时它不出现在请求里
IMAGE_INPUT_BROWSER_TOOLS: tuple[str, ...] = ("browser_take_screenshot",)


def browser_tool_definitions(response: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    # 从 Playwright MCP 的 tools/list 响应生成浏览器工具的定义（设计说明第 4.1、4.2 节与第 9 节）：
    # 名称、说明与参数原样取用；动作类别是 browser；只读标注为是的工具按「无需查询」核对，
    # 其余按动作记录查询；都可以取消；截图需要图像输入。清单以外的工具（含不提供的两个）不进来
    listed = {str(tool.get("name")): tool for tool in response.get("result", {}).get("tools", [])}
    definitions: dict[str, dict[str, Any]] = {}
    for name in BROWSER_TOOL_NAMES:
        tool = listed.get(name)
        if tool is None:
            raise ValueError(f"Playwright MCP tools/list has no {name}")
        read_only = bool((tool.get("annotations") or {}).get("readOnlyHint"))
        definitions[name] = {
            "kind": "environment",
            "action": "browser",
            "verification": "none" if read_only else "query",
            "cancellable": True,
            "requires_image_input": name in IMAGE_INPUT_BROWSER_TOOLS,
            "description": tool["description"],
            "parameters": tool["inputSchema"],
        }
    return definitions


def in_force(definitions: Definitions | None) -> Definitions:
    # 这次判断所用的定义：事项所用的那一份由调用方交进来，没有交时是当前加载的那一份
    # （#861 的路由定义接上以后，由路由把那一份交进来）
    return DEFINITIONS if definitions is None else definitions


def tools_for(department: str, kind: str = "change", *,
              definitions: Definitions | None = None) -> list[str]:
    # 部门在这种事项种类中可以使用的工具：普通事项按角色定义中的顺序，建档事项按事项种类中的清单
    return list(in_force(definitions).tools_for(department, kind))


def has_tool(department: str, name: str, kind: str = "change", *,
             definitions: Definitions | None = None) -> bool:
    return name in in_force(definitions).tools_for(department, kind)


def proposal_kinds(department: str, kind: str = "change", *,
                   definitions: Definitions | None = None) -> set[str]:
    # 部门在这种事项种类中可以提交的提案种类，由该种类给出的工具里的提交类工具得出
    definition = in_force(definitions)
    return {definition.tools[name].proposal for name in definition.tools_for(department, kind)
            if name in definition.tools and definition.tools[name].proposal is not None}


def proposal_kinds_of(*, definitions: Definitions | None = None) -> frozenset[str]:
    # 这份定义里的全部提案种类：提案校验判断「种类认不认识」用它，不读模块加载时算好的常量（工单 #1098）
    return frozenset(tool.proposal for tool in in_force(definitions).tools.values() if tool.proposal is not None)


def tool_kind(name: str, *, definitions: Definitions | None = None) -> str | None:
    # host：主机工具；environment：环境工具；没有定义的工具为 None
    tool = in_force(definitions).tools.get(name)
    return None if tool is None else tool.kind


def tool_action(name: str, *, definitions: Definitions | None = None) -> str | None:
    # 环境工具的动作类别（read、write、check、command，以及新增的 fetch、mcp、trial、browser）；
    # 主机工具与没有定义的工具为 None
    tool = in_force(definitions).tools.get(name)
    return None if tool is None else tool.action


def tool_verification(name: str, *, definitions: Definitions | None = None) -> Verification | None:
    # 环境工具的核实方法；主机工具、没有定义的工具与省略了这项的旧定义为 None（按动作类别的既定值解释）
    tool = in_force(definitions).tools.get(name)
    return None if tool is None else tool.verification


def tool_cancellable(name: str, *, definitions: Definitions | None = None) -> bool | None:
    # 环境工具的取消能否确认停止；主机工具、没有定义的工具与省略了这项的旧定义为 None
    tool = in_force(definitions).tools.get(name)
    return None if tool is None else tool.cancellable


def proposal_kind(name: str, *, definitions: Definitions | None = None) -> str | None:
    # 提交类工具提交的提案种类；其他工具为 None
    tool = in_force(definitions).tools.get(name)
    return None if tool is None else tool.proposal


def submit_tool(kind: str, *, definitions: Definitions | None = None) -> str | None:
    # 提交这种提案的工具
    definition = in_force(definitions)
    return next((name for name, tool in definition.tools.items() if tool.proposal == kind), None)


def offers_with_input(tool_names: list[str], input_modalities: tuple[str, ...], *,
                      definitions: Definitions | None = None) -> list[str]:
    # 这次请求提供的工具：按调用目标的输入方式去掉声明需要图像输入而调用目标不含图像的工具
    # （设计说明第 5.6 节「请求时」；浏览器设计第 6.1 节的屏幕工具与 browser_take_screenshot 属于这一类）
    if "image" in input_modalities:
        return list(tool_names)
    tools = in_force(definitions).tools
    return [name for name in tool_names
            if not (name in tools and tools[name].requires_image_input)]


def tool_definitions(tool_names: list[str], *,
                     definitions: Definitions | None = None) -> list[dict[str, Any]]:
    # 请求中提供给模型的工具：名称、描述与参数（参数是普通的 JSON 结构，按定义中的键顺序）
    tools = in_force(definitions).tools
    return [{"name": name, "description": tools[name].description,
             "parameters": thaw(tools[name].parameters)} for name in tool_names]

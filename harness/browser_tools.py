# 浏览器工具的定义（浏览器与 computer use 设计说明第 4.1、4.2、6.1 与第 9 节，工单 #147）：
# 由 scripts/extract_browser_tools.py 从 Playwright MCP 固定版本的 tools/list 生成定义，按这张表筛选；
# 顶层工具清单在 harness/tools.py（内核），这里只放提取用的筛选与映射，不参与裁决（工单 #1452 移来）。

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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

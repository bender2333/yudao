# 试用与浏览器工具的定义（浏览器与 computer use 设计说明第 4.1、4.2、6.1、9 节，工单 #147）。
#
# 浏览器工具由 scripts/extract_browser_tools.py 从 Playwright MCP 0.0.83 的 tools/list 生成；记下的真实回复在
# harness/tests/data/playwright_mcp_tools_list.json，测试读它核对提交的 harness/definitions/browser_tools.json，
# 不 mock 也不起进程。试用工具的参数按部门分开：工程用 trial_start（一个启动方式），质检用 trial_open
# （当前交付说明里的启动方式名称）——同一个工具名不能在两个部门有不同参数。
# 读静态定义与数据、调纯函数，属于单元层。

import json
from pathlib import Path

import pytest

from harness.definitions import DEFINITIONS
from harness.tools import (BROWSER_TOOL_NAMES, EXCLUDED_BROWSER_TOOLS, IMAGE_INPUT_BROWSER_TOOLS,
                           browser_tool_definitions, offers_with_input, tool_definitions)

DATA = Path(__file__).resolve().parent / "data" / "playwright_mcp_tools_list.json"
COMMITTED = Path(__file__).resolve().parents[1] / "definitions" / "browser_tools.json"
TOOLS = DEFINITIONS.tools
TRIAL_TOOLS = ("trial_start", "trial_open", "trial_output", "trial_stop")


def _recorded() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_the_committed_browser_definitions_come_from_the_recorded_tools_list():
    # 提交的定义与按记下的真实回复生成的一致：升级 Playwright MCP 时两边一起更新（守 R2：工具定义是合同）
    definitions = browser_tool_definitions(_recorded())
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert committed == definitions
    assert list(committed) == list(BROWSER_TOOL_NAMES)


def test_the_recorded_reply_is_the_real_playwright_mcp_tools_list():
    # 记下的是 0.0.83 的真实回复：设计第 4.2 节的清单加 browser_drop 都在，不提供的两个也在回复里，
    # 回复里没有既没提供也没排除的工具
    listed = {tool["name"] for tool in _recorded()["result"]["tools"]}
    assert set(BROWSER_TOOL_NAMES) <= listed
    assert set(EXCLUDED_BROWSER_TOOLS) <= listed
    assert listed == set(BROWSER_TOOL_NAMES) | set(EXCLUDED_BROWSER_TOOLS)
    assert "browser_drop" in BROWSER_TOOL_NAMES


def test_every_trial_and_browser_tool_declares_action_recovery_and_images():
    # 每个试用与浏览器工具都写明动作类别、恢复契约与是否需要图像输入（第 6.1、9 节）
    for name in (*BROWSER_TOOL_NAMES, *TRIAL_TOOLS):
        tool = TOOLS[name]
        assert tool.kind == "environment", name
        assert tool.action in {"browser", "trial"}, name
        assert tool.verification in {"none", "query"}, name
        assert tool.cancellable is True, name
        assert isinstance(tool.requires_image_input, bool), name
    # 需要图像输入的只有浏览器截图（第 6.1 节）
    assert [name for name in BROWSER_TOOL_NAMES if TOOLS[name].requires_image_input] == list(IMAGE_INPUT_BROWSER_TOOLS)
    assert not any(TOOLS[name].requires_image_input for name in TRIAL_TOOLS)


def test_read_only_browser_tools_are_verified_without_a_query():
    # 第 9 节：只读标注为是的工具无需查询；其余按动作记录查询
    recorded = {tool["name"]: tool for tool in _recorded()["result"]["tools"]}
    for name in BROWSER_TOOL_NAMES:
        read_only = bool((recorded[name].get("annotations") or {}).get("readOnlyHint"))
        assert TOOLS[name].verification == ("none" if read_only else "query"), name


def test_trial_open_and_trial_start_take_different_parameters():
    # 同一个工具名不能在两个部门有不同参数：质检的 trial_open 只收名称，工程的 trial_start 收完整的启动方式
    assert set(TOOLS["trial_open"].parameters["properties"]) == {"launch_name"}
    assert set(TOOLS["trial_start"].parameters["properties"]) == {"launch"}
    assert list(TOOLS["trial_open"].parameters["required"]) == ["launch_name"]
    assert list(TOOLS["trial_start"].parameters["required"]) == ["launch"]
    launch = TOOLS["trial_start"].parameters["properties"]["launch"]
    assert set(launch["properties"]) == {"name", "kind", "commands", "ready_url", "ready_timeout_sec"}
    assert list(launch["required"]) == ["name", "kind", "commands"]


def test_offering_drops_image_tools_when_the_call_target_cannot_take_images():
    # 按调用目标的输入方式提供工具（第 6.1、6.3 节）：只有文本时声明需要图像输入的工具不出现，
    # 每次请求重新选一次（同一角色任务中途换模型时，下一次请求按新的输入方式选出）
    names = ["browser_snapshot", "browser_take_screenshot", "trial_open"]
    assert offers_with_input(names, ("text", "image")) == names
    assert offers_with_input(names, ("text",)) == ["browser_snapshot", "trial_open"]
    # 请求里的工具定义同样按选出的名单取：含图像时截图在，只有文本时不在
    with_image = tool_definitions(offers_with_input(names, ("text", "image")))
    without_image = tool_definitions(offers_with_input(names, ("text",)))
    assert "browser_take_screenshot" in [item["name"] for item in with_image]
    assert "browser_take_screenshot" not in [item["name"] for item in without_image]
    # 产品的工具清单里没有试用与浏览器工具（第 6.3 节）
    product_tools = set(DEFINITIONS.tools_for("product"))
    assert not product_tools & {*BROWSER_TOOL_NAMES, *TRIAL_TOOLS}

def test_a_recorded_reply_without_a_listed_tool_is_an_error():
    # 记下的回复里少了清单里的工具时生成直接失败并写明缺哪个：升级 Playwright MCP 时能看出清单要跟着改
    response = _recorded()
    response["result"]["tools"] = [tool for tool in response["result"]["tools"]
                                   if tool["name"] != "browser_drop"]
    with pytest.raises(ValueError, match="browser_drop"):
        browser_tool_definitions(response)

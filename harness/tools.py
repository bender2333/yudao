# 工具：工具的类别、动作类别、提交的提案种类、描述与参数取自定义（definitions/tools.json），各部门可以使用的工具
# 取自定义的角色（definitions/roles.json）与事项种类（definitions/work_items.json）；这里是读取它们的函数，
# 主机工具由步骤驱动执行，环境工具的动作由执行环境（environment.py）执行。

from __future__ import annotations

from typing import Any

from .definitions import DEFINITIONS, thaw


def tools_for(department: str, kind: str = "change") -> list[str]:
    # 部门在这种事项种类中可以使用的工具：普通事项按角色定义中的顺序，建档事项按事项种类中的清单
    return DEFINITIONS.tools_for(department, kind)


def has_tool(department: str, name: str, kind: str = "change") -> bool:
    return name in DEFINITIONS.tools_for(department, kind)


def proposal_kinds(department: str, kind: str = "change") -> set[str]:
    # 部门在这种事项种类中可以提交的提案种类，由该种类给出的工具里的提交类工具得出
    return {DEFINITIONS.tools[name].proposal for name in DEFINITIONS.tools_for(department, kind)
            if name in DEFINITIONS.tools and DEFINITIONS.tools[name].proposal is not None}


def tool_kind(name: str) -> str | None:
    # host：主机工具；environment：环境工具；没有定义的工具为 None
    tool = DEFINITIONS.tools.get(name)
    return None if tool is None else tool.kind


def tool_action(name: str) -> str | None:
    # 环境工具的动作类别（read、write、check、command）；主机工具与没有定义的工具为 None
    tool = DEFINITIONS.tools.get(name)
    return None if tool is None else tool.action


def proposal_kind(name: str) -> str | None:
    # 提交类工具提交的提案种类；其他工具为 None
    tool = DEFINITIONS.tools.get(name)
    return None if tool is None else tool.proposal


def submit_tool(kind: str) -> str | None:
    # 提交这种提案的工具
    return next((name for name, tool in DEFINITIONS.tools.items() if tool.proposal == kind), None)


def offers_with_input(tool_names: list[str], input_modalities: tuple[str, ...]) -> list[str]:
    # 这次请求提供的工具：按调用目标的输入方式去掉声明需要图像输入而调用目标不含图像的工具
    # （设计说明第 5.6 节「请求时」；浏览器设计第 6.1 节的屏幕工具与 browser_take_screenshot 属于这一类）
    if "image" in input_modalities:
        return list(tool_names)
    return [name for name in tool_names
            if not (name in DEFINITIONS.tools and DEFINITIONS.tools[name].requires_image_input)]


def tool_definitions(tool_names: list[str]) -> list[dict[str, Any]]:
    # 请求中提供给模型的工具：名称、描述与参数（参数是普通的 JSON 结构，按定义中的键顺序）
    return [{"name": name, "description": DEFINITIONS.tools[name].description,
             "parameters": thaw(DEFINITIONS.tools[name].parameters)} for name in tool_names]

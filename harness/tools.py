# 工具：工具的类别、动作类别、提交的提案种类、描述与参数取自定义（definitions/tools.json），各部门可以使用的工具
# 取自定义的角色（definitions/roles.json）与事项种类（definitions/work_items.json）；这里是读取它们的函数，
# 以及项目登记命令的校验。
# 主机工具由步骤驱动执行，环境工具的动作由执行环境（environment.py）执行。

from __future__ import annotations

import re
from typing import Any

from .definitions import DEFINITIONS, thaw

# 登记命令名只允许简单标识，避免路径与 shell 元字符进入注册表
_COMMAND_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def validate_registered_command(name: str, config: dict[str, Any]) -> dict[str, Any]:
    # 校验一条项目登记命令，返回冻结用的规范形态；任一非法直接报错。时限与输出上限的默认值、时限的最大值取自定义
    limits = DEFINITIONS.limits
    if not isinstance(name, str) or not _COMMAND_NAME_PATTERN.fullmatch(name):
        raise ValueError("command name must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    if not isinstance(config, dict):
        raise ValueError(f"registered command {name} must be an object")
    argv = config.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ValueError(f"registered command {name} requires a non-empty argv list of strings")
    extra_args = config.get("args", [])
    if not isinstance(extra_args, list) or any(not isinstance(item, str) or not item for item in extra_args):
        raise ValueError(f"registered command {name} allowlist args must be a list of non-empty strings")
    timeout_sec = config.get("timeout_sec", limits.check_timeout_sec)
    if type(timeout_sec) is not int or not 1 <= timeout_sec <= limits.command_timeout_max_sec:
        raise ValueError(f"registered command {name} timeout_sec must be an integer in 1..{limits.command_timeout_max_sec}")
    output_limit = config.get("output_limit", limits.tool_output_limit)
    if type(output_limit) is not int or output_limit < 1:
        raise ValueError(f"registered command {name} output_limit must be an integer >= 1")
    return {"argv": list(argv), "args": list(extra_args), "timeout_sec": timeout_sec, "output_limit": output_limit}


def normalize_registered_commands(registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    # 冻结注册表逐条校验并规范化；空注册表表示本轮没有可用命令
    if registry is None:
        return {}
    if not isinstance(registry, dict):
        raise ValueError("registered_commands must be an object")
    return {name: validate_registered_command(name, config) for name, config in registry.items()}


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


def usable_when_guidance_only(name: str) -> bool:
    # 因待处理指导被提前安排、只能回应指导的激活可以使用的工具
    tool = DEFINITIONS.tools.get(name)
    return tool is not None and tool.guidance_only


def tool_definitions(tool_names: list[str]) -> list[dict[str, Any]]:
    # 请求中提供给模型的工具：名称、描述与参数（参数是普通的 JSON 结构，按定义中的键顺序）
    return [{"name": name, "description": DEFINITIONS.tools[name].description,
             "parameters": thaw(DEFINITIONS.tools[name].parameters)} for name in tool_names]

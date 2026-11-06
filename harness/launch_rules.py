# 试用启动方式的核对（浏览器与 computer use 设计说明「启动方式」「试用工具」，工单 #1497）：工具许可
# （adjudication.py）与执行侧（environment.py、trial_sessions.py）共用这一份规则。它只读调用给出的启动方式、
# 当前交付说明与执行位置的系统，不做进程探测、不做 I/O，也不导入裁决模块；执行侧在执行之前用同一套核对。
# 放在这里而不放在执行侧，是因为裁决要导入它，而裁决不导入含进程与端口的模块。

from __future__ import annotations

import sys
from typing import Any

from .definitions import DEFINITIONS

# 建立试用会话的两个工具：工程用 trial_start（给出启动方式），质检用 trial_open（给出交付说明中的名称）
TRIAL_TOOLS = frozenset({"trial_start", "trial_open"})

# 本机进程是控制主机：系统按 Python 的 sys.platform 取值。其他系统没有启动命令的约定
_PLATFORM_SYSTEMS = {"win32": "windows", "linux": "linux"}

# 就绪时限的默认值取自规则登记
READINESS_TIMEOUT_SEC = int(DEFINITIONS.rule_value("execution.readiness_timeout_sec"))


def current_system() -> str | None:
    # 执行位置的系统：本机是控制主机，取引擎进程的 sys.platform。其他系统返回 None
    return _PLATFORM_SYSTEMS.get(sys.platform)


def resolve_trial_launch(name: str, args: dict[str, Any], methods: list[dict[str, Any]],
                         system: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """交回这次调用要用的启动方式，或者拒绝的原因（工具许可与执行之前是同一套核对）。

    工程的 trial_start 用这次调用给出的启动方式；质检的 trial_open 只接受当前交付说明里的名称（`methods`
    是当前交付说明的启动方式），名称不存在时原因写明交付说明中已有的名称，没有启动方式时写明交付说明
    没有写启动方式。两者都按执行位置的系统选用命令：没有这个系统的命令时拒绝，原因写明缺少哪个系统
    的命令。桌面试用会话在本机版还没有接上（屏幕工具属于 computer use 专题），先拒绝并写明原因。
    """
    if name == "trial_start":
        launch = args.get("launch")
        if not isinstance(launch, dict):
            return None, "trial_start requires a launch method object"
    elif name == "trial_open":
        if not methods:
            return None, "the DeliverySpec has no launch method"
        wanted = args.get("launch_name")
        matches = [item for item in methods if item.get("name") == wanted]
        if not matches:
            names = ", ".join(str(item.get("name")) for item in methods)
            return None, (f"the DeliverySpec has no launch method named {wanted!r}; "
                          f"it carries: {names}")
        launch = matches[0]
    else:
        return None, f"{name} does not start a trial session"
    problem = _launch_shape_problem(launch)
    if problem is not None:
        return None, problem
    system = system or current_system()
    commands = launch.get("commands") or {}
    if system is None:
        return None, (f"this execution location runs {sys.platform}; "
                      f"launch commands are defined for windows and linux only")
    if system not in commands:
        covered = ", ".join(sorted(commands)) or "nothing"
        return None, f"the launch method has no command for {system}; commands cover: {covered}"
    if launch.get("kind") == "desktop":
        return None, "desktop trial sessions are not available in this build"
    return dict(launch), None


def normalize_launch(raw: Any) -> dict[str, Any]:
    # 一个启动方式的形状（docs/design/browser-and-computer-use.md「启动方式」）。交付说明由提案校验核对过；这里再核一次，
    # 因为 trial_start 的启动方式是模型在这次调用里给出的。形状的核对与工具许可共用 _launch_shape_problem
    if not isinstance(raw, dict):
        raise ValueError("a launch method must be an object")
    problem = _launch_shape_problem(raw)
    if problem is not None:
        raise ValueError(problem)
    kind = raw["kind"]
    ready_url = raw.get("ready_url")
    if kind == "desktop" and ready_url is not None:
        raise ValueError("a desktop program has no ready_url")
    timeout = raw.get("ready_timeout_sec")
    if timeout is None:
        timeout = READINESS_TIMEOUT_SEC
    low, high = DEFINITIONS.rule("execution.readiness_timeout_sec").bounds
    if type(timeout) is not int or not low <= timeout <= high:
        raise ValueError(f"ready_timeout_sec must be an integer between {int(low)} and {int(high)}")
    return {"name": str(raw["name"]).strip(), "kind": kind,
            "commands": {str(system): list(argv) for system, argv in raw["commands"].items()},
            "ready_url": ready_url, "ready_timeout_sec": timeout}


def select_command(launch: dict[str, Any], system: str | None) -> list[str]:
    # 按执行位置的系统选用命令（docs/design/browser-and-computer-use.md「启动方式」）：没有这个系统的命令时按缺少启动方式处理
    commands = launch.get("commands") or {}
    if system is None:
        raise ValueError("this execution location has no system from which to choose a launch command")
    if system not in commands:
        raise ValueError(f"the launch method has no command for {system}; "
                         f"commands cover: {', '.join(sorted(commands)) or 'nothing'}")
    return list(commands[system])


def _launch_shape_problem(launch: dict[str, Any]) -> str | None:
    # 启动方式的形状（docs/design/browser-and-computer-use.md「启动方式」）：交付说明由提案校验，trial_start 的启动方式由这里核对
    kind = launch.get("kind")
    if kind not in {"web", "desktop"}:
        return "kind must be web or desktop"
    name = launch.get("name")
    if not isinstance(name, str) or not name.strip():
        return "name must be a non-empty string"
    commands = launch.get("commands")
    if not isinstance(commands, dict) or not commands:
        return "commands must map at least one system to an argv list"
    for system, argv in commands.items():
        if system not in {"windows", "linux"}:
            return f"commands keys must be windows or linux, not {system!r}"
        if not isinstance(argv, list) or not argv or any(
                not isinstance(part, str) or not part for part in argv):
            return f"commands.{system} must be a non-empty list of non-empty strings"
    if kind == "web":
        ready_url = launch.get("ready_url")
        if not isinstance(ready_url, str) or "{port}" not in ready_url:
            return "a web app requires a ready_url containing {port}"
    return None

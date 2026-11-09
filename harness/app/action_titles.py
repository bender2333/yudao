# 动作标记与动作标题（工作过程的任务与动作标题设计说明「动作标记」「动作标题」，工单 #1657）：
# 系统按工具定义、动作的参数与回执算出一个动作的一行标题与标记，从事实重算，不保存。
#
# 只有一处：run.steps 的动作行与事件流里工具开始、工具结果两种事件的文字都调用这里的函数，
# 所以两处逐字相同（设计说明「接口」「谁来读」）。标记只由系统给：种类取工具定义里已有的 kind、action、
# proposal（定义不加新栏），系统量到的事实取回执；角色写的话改变不了标记。
#
# 标题的写法按设计说明「动作标题」的那张表；表里没有的工具写工具名（与「不认识的工具」同一条），
# 页面因此不会因为一个没见过的工具报错。浏览器动作的写法留给页面的翻译层（试用记录页已有中文写法），
# 这里同样写工具名，不另抄一份。

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from ..definitions import DEFINITIONS, DEFINITIONS_DIR, Definitions, load_definitions
from ..redact import redact_text

# 标题的显示上限（设计说明「本说明的常量」）：60 字符，含超出时加的省略号——一行放得下标记、标题与用时，
# 原文在原始数据里
TITLE_LIMIT = 60
ELLIPSIS = "…"

# 五种动作标记（设计说明「动作标记」）：只由工具定义得出，角色写不了
MARK_READ = "读"
MARK_WRITE = "写"
MARK_RUN = "运行"
MARK_ASK = "询问"
MARK_SUBMIT = "提交"
Mark = Literal["读", "写", "运行", "询问", "提交"]

# 系统量到的事实（设计说明「动作标记」）：只由回执得出
FACT_FAILED = "失败"
FACT_TIMED_OUT = "超时"
FACT_UNKNOWN = "结果未知"
FACT_REFUSED = "被拒绝"
FACT_FILES_CHANGED = "改了文件"
Fact = Literal["失败", "超时", "结果未知", "被拒绝", "改了文件"]

# 标题的来源（设计说明「动作标题」）：系统算的，或者角色写的（运行命令那一句，工单 #1659 接上）
SOURCE_SYSTEM = "系统"
SOURCE_AUTHOR = "作者"
Source = Literal["系统", "作者"]

# 超时的退出状态：与执行层（harness/environment.py 的 TIMEOUT_EXIT_CODE）相同，检查类工具的回执里
# 没有 status 一栏，按退出状态认出超时。两处取值相同由 test_action_titles.py 的一条用例守着
TIMEOUT_EXIT_CODE = 124

# MCP 工具的名字：mcp__服务器__工具（设计说明「动作标题」的 MCP 一行）
MCP_PREFIX = "mcp__"


@dataclass(frozen=True)
class ToolDefinition:
    """标题与标记要用到的工具定义那几栏：种类由已有的 kind、action、proposal 得出，定义不加新栏。"""

    name: str
    kind: str
    action: str | None
    proposal: str | None
    # 提交类工具的成果名：这份定义里成果种类的中文名（outcome_kinds.json 的 label）
    outcome: str | None = None


@dataclass(frozen=True)
class ReceiptFacts:
    """回执里能拿到的几项事实：工具是否报错、退出状态与超时、被拒绝、动作前后的公开树摘要、结果未知。"""

    ok: bool = True
    error: str | None = None
    exit_code: int | None = None
    status: str | None = None
    refused: bool = False
    # 动作前后快照引用的 content_hash：两个引用都在、摘要不同时标「改了文件」。
    # 不比较整个引用：两个引用的 kind 不同
    before_hash: str | None = None
    after_hash: str | None = None
    unknown: bool = False


@dataclass(frozen=True)
class ActionLine:
    """一个动作的一行：种类标记（没有种类时为空）、标题、标题来源与系统量到的事实。"""

    mark: Mark | None
    title: str
    source: Source
    facts: tuple[Fact, ...] = field(default_factory=tuple)


def limit_title(text: str) -> str:
    """标题的显示上限：超过 60 字符时截断并加省略号，上限含省略号本身。"""
    if len(text) <= TITLE_LIMIT:
        return text
    return text[:TITLE_LIMIT - 1].rstrip() + ELLIPSIS


def one_line(text: Any) -> str:
    """一段文字合成一行：换行与连续的空白合成一个空格（角色写的话与命令原文同一条规则）。"""
    return " ".join(str(text or "").split())


def text_title(text: Any) -> str:
    """只有文字、没有动作的一步：这段文字的开头作一行，不带种类标记，来源记作者。"""
    return limit_title(one_line(text))


def _releases() -> list[Definitions]:
    """发布带的几份定义：默认形态一份，加上 forms/ 下每一个形态各自的一份完整定义。

    `harness/runtime.py` 的 FORM_REGISTRY 登记的就是这几份（默认形态另有一份收紧检查），
    这里按同一个来源取，不另抄一份名字：形态目录多一份，这里的查找就多认得一份。
    """
    forms = DEFINITIONS_DIR / "forms"
    return [DEFINITIONS] + [load_definitions(path) for path in sorted(forms.iterdir())
                            if (path / "tools.json").is_file()]


@lru_cache(maxsize=1)
def _tool_definitions() -> dict[str, ToolDefinition]:
    """发布带的每一份定义（默认与各形态）里的工具：名字 → 标题与标记要用的那几栏。

    直做形态的提交工具只在形态自己的工具定义里，所以这一份查找把每一份定义都收进来：
    查询与事件流用同一份查找，都认得这些工具。默认形态在前，同一个名字先出现的那一份说了算。

    只读定义文件，不导入运行时：这条查找在事件流渲染每个工具事件时都要用，拉进整个运行时太贵
    （单元层每条用例五秒的上限）。
    """
    definitions: dict[str, ToolDefinition] = {}
    for release in _releases():
        outcomes = {kind.id: kind.label for kind in release.outcome_kinds.kinds}
        for name, tool in release.tools.items():
            if name in definitions:
                continue
            definitions[name] = ToolDefinition(
                name=name, kind=tool.kind, action=tool.action, proposal=tool.proposal,
                outcome=None if tool.proposal is None else outcomes.get(tool.proposal, tool.proposal),
            )
    return definitions


def tool_definition(name: Any) -> ToolDefinition | None:
    """一个工具的标题与标记要用的那几栏；定义里没有这个工具时为空（写工具名，不报错）。"""
    return _tool_definitions().get(str(name or ""))


def mcp_tool_parts(name: str) -> tuple[str, str] | None:
    """MCP 工具的名字分成服务器与工具：mcp__服务器__工具。不是这个写法时为空。"""
    if not name.startswith(MCP_PREFIX):
        return None
    parts = name.split("__")
    if len(parts) < 3:
        return None
    server, tool = parts[1], "__".join(parts[2:])
    return (server, tool) if server and tool else None


def _text(args: Mapping[str, Any], key: str) -> str | None:
    # 参数里的一项文字：不是字符串或者只有空白时为空（标题退到工具名，不写出空的对象）
    value = args.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _lines(args: Mapping[str, Any]) -> str:
    # 带行范围时写第几行：两端都有写「第 3–5 行」，只有起点写「第 3 行起」
    start, end = args.get("start_line"), args.get("end_line")
    start = start if isinstance(start, int) and not isinstance(start, bool) else None
    end = end if isinstance(end, int) and not isinstance(end, bool) else None
    if start is not None and end is not None:
        return f" 第 {start}–{end} 行"
    if start is not None:
        return f" 第 {start} 行起"
    return ""


def _department(value: Any) -> str:
    # 职能的显示名：定义里的中文名后面加「部门」，没有登记的原样写
    text = str(value or "")
    return f"{DEFINITIONS.department_labels.get(text, text)}部门"


def _known_title(tool: ToolDefinition, args: Mapping[str, Any]) -> str | None:
    """设计说明「动作标题」那张表里的写法；这个工具不在表里（或者参数缺了对象）时为空。"""
    name = tool.name
    if name == "read_file":
        path = _text(args, "path")
        return None if path is None else f"读取 {path}"
    if name == "read_range":
        path = _text(args, "path")
        return None if path is None else f"读取 {path}{_lines(args)}"
    if name == "list_files":
        prefix = _text(args, "prefix")
        return "列出文件" if prefix is None else f"列出 {prefix} 下的文件"
    if name == "search":
        pattern = _text(args, "pattern")
        return None if pattern is None else f"搜索「{pattern}」"
    if name == "fetch_url":
        url = _text(args, "url")
        return None if url is None else f"取回 {url}"
    if name == "write_file":
        path = _text(args, "path")
        return None if path is None else f"写入 {path}"
    if name == "edit_range":
        path = _text(args, "path")
        return None if path is None else f"修改 {path}"
    if name == "delete_file":
        path = _text(args, "path")
        if path is None:
            return None
        reason = _text(args, "reason")
        return f"删除 {path}" + ("" if reason is None else f"：{reason}")
    if name == "move_file":
        source, destination = _text(args, "source"), _text(args, "destination")
        if source is None or destination is None:
            return None
        reason = _text(args, "reason")
        return f"移动 {source} 到 {destination}" + ("" if reason is None else f"：{reason}")
    if name == "bash":
        # 这一张单里运行命令一律由系统写「运行命令：<命令开头>」；角色写的那一句由 #1659 接上，
        # 接手时只改这里：有那句话时标题是那句话、来源记作者
        command = _text(args, "command")
        return None if command is None else f"运行命令：{redact_text(one_line(command))}"
    if name == "run_check":
        check = _text(args, "name")
        return None if check is None else f"运行检查 {check}"
    if name == "run_baseline_check":
        check = _text(args, "name")
        return None if check is None else f"在基线上运行检查 {check}"
    if name == "ask":
        question = _text(args, "question")
        return f"问{_department(args.get('recipient'))}" + ("" if question is None else f"：{one_line(question)}")
    if name == "answer":
        return "回答询问"
    if name == "trial_start":
        launch = args.get("launch")
        launch_name = launch.get("name") if isinstance(launch, Mapping) else None
        if isinstance(launch_name, str) and launch_name.strip():
            return f"开始试用 {launch_name.strip()}"
        return "开始试用"
    if name == "trial_stop":
        return "结束试用"
    if name == "trial_case_begin":
        title = _text(args, "title")
        return "开始用例" + ("" if title is None else f"：{title}")
    if name == "trial_case_end":
        result = _text(args, "result")
        return "结束用例" + ("" if result is None else f"：{result}")
    # 表里没有、但已知的几类工具：按同类工具的写法写一句，对象取参数里的那一项
    if name == "read_external_source":
        source = _text(args, "source")
        return None if source is None else f"读取外部来源 {source}{_lines(args)}"
    if name == "read_output":
        return "读取后台命令的输出"
    if name == "stop_job":
        return "停止后台命令"
    if name == "trial_open":
        launch_name = _text(args, "launch_name")
        return "打开试用页面" + ("" if launch_name is None else f" {launch_name}")
    if name == "trial_output":
        return "读取试用的输出"
    return None


def _title(tool: ToolDefinition | None, name: str, args: Mapping[str, Any]) -> str:
    # 一行标题：工具不在定义里、参数不是合法 JSON（执行层记成 {"invalid_arguments": 原文}）时写工具名
    if tool is None:
        parts = mcp_tool_parts(name)
        if parts is not None:
            return limit_title(f"调用 {parts[0]} 的 {parts[1]}")
        return limit_title(name)
    if "invalid_arguments" in args:
        return limit_title(name)
    known = _known_title(tool, args)
    if known is not None:
        return limit_title(known)
    if tool.proposal is not None:
        return limit_title(f"提交{tool.outcome or tool.proposal}")
    return limit_title(name)


def _mark(tool: ToolDefinition | None, name: str) -> Mark | None:
    # 种类标记：只由工具定义得出。四种环境动作按设计说明「动作标记」归类，主机工具里提交成果的算提交、
    # 询问与回答算询问，其余主机工具算运行
    if tool is None:
        return MARK_RUN if mcp_tool_parts(name) is not None else None
    if tool.kind == "host":
        if tool.proposal is not None:
            return MARK_SUBMIT
        return MARK_ASK if tool.name in ("ask", "answer") else MARK_RUN
    if tool.action in ("read", "fetch"):
        return MARK_READ
    if tool.action == "write":
        return MARK_WRITE
    return MARK_RUN


def _facts(receipt: ReceiptFacts | None) -> tuple[Fact, ...]:
    # 系统量到的事实：失败（退出状态非零或工具报错）、超时、结果未知、被拒绝、改了文件
    if receipt is None:
        return ()
    facts: list[Fact] = []
    if receipt.status == "timeout" or receipt.exit_code == TIMEOUT_EXIT_CODE:
        facts.append(FACT_TIMED_OUT)
    if not receipt.ok or (receipt.exit_code is not None and receipt.exit_code != 0):
        facts.append(FACT_FAILED)
    if receipt.unknown:
        facts.append(FACT_UNKNOWN)
    if receipt.refused:
        facts.append(FACT_REFUSED)
    if (receipt.before_hash is not None and receipt.after_hash is not None
            and receipt.before_hash != receipt.after_hash):
        facts.append(FACT_FILES_CHANGED)
    return tuple(facts)


def action_line(tool: ToolDefinition | None, name: str, args: Any, receipt: ReceiptFacts | None = None) -> ActionLine:
    """一个动作的一行：标记（五种种类加系统量到的事实）、标题（上限 60 字符）与标题来源。

    纯函数：只看工具定义、动作的参数与回执，不读事件日志、不写任何事实。工具定义不在发布带的定义里时
    传空，标题写工具名。参数与回执可以是任意输入（不是合法 JSON、缺字段、工具已经不存在），不抛异常。
    """
    arguments: Mapping[str, Any] = args if isinstance(args, Mapping) else {}
    text = "" if name is None else str(name)
    return ActionLine(mark=_mark(tool, text), title=_title(tool, text, arguments),
                      source=SOURCE_SYSTEM, facts=_facts(receipt))


def action_title(name: Any, args: Any) -> str:
    """工具事件文字与 run.steps 的标题共用的那一个结果：事件流里工具开始、工具结果两种事件写它。

    与 action_line 同一个函数算，所以两处逐字相同；事件的那条文字只要标题，不要标记。
    """
    text = "" if name is None else str(name)
    return action_line(tool_definition(text), text, args).title

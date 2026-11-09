# 任务分组（工作过程的任务与动作标题设计说明「任务」「任务分组」「老事件」，工单 #1661）：
# 一个纯函数，输入一轮工作（一次激活或一个询问分支）的工具调用记录，输出任务列表与每个动作的归属，
# 从事实重算，不保存。更新计划是普通的工具调用记录（工单 #1660）：这里只读它写下的整份计划与它在
# 事件里的位置，不新增事件种类，也不写回任何事实。
#
# 规则按设计说明「任务分组」：
# - 一个动作归它开始时最新一份计划里排在最前的进行中条目（按事件位置算，同一步里先发更新计划、
#   后发动作时归新计划）；
# - 同一句话算同一条任务，一条任务可以有几段动作；改了措辞的算新的一条；
# - 任务按第一次进行中的时间排，编号 1、2、3；状态取最后一次写的；后来的计划里没有了的写
#   「已从计划里去掉」；从没进行过的排在最后；
# - 没有进行中条目时的动作不编号，按时间留在两段任务之间（分组只给出「不归属」，先后由页面按行排）；
# - 更新计划自己不单独成行——它只参与分组，不是动作；
# - 范围是一轮工作或一个询问分支：调用方只把这一轮的记录交进来，别的轮次的计划不影响这一轮；
# - 一轮没有计划时任务列表为空，动作不带所属任务（页面平铺）。
#
# 设计说明没写到的边界（工单 #1661 的交付说明「自定的边界」）：
# - 工具结果报错的更新计划（空条目、未知状态）不当成计划，分组仍按上一份已接受的计划；
# - 认不出的状态按「待做」显示（防御性；正常的调用已经被主机拒绝）；
# - 同一句话按原样比较（去掉首尾空白），改了措辞就是新的一条。

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

# 更新计划这个主机工具的名字：与 harness/engine.py 的 PLAN_TOOL、harness/loops.py 的同名常量是同一个工具
PLAN_TOOL = "update_plan"

# 任务的状态（设计说明「任务」「任务分组」）：待做、进行中、完成，以及后来从计划里去掉了的
TASK_PENDING = "待做"
TASK_IN_PROGRESS = "进行中"
TASK_COMPLETED = "完成"
TASK_REMOVED = "已从计划里去掉"
TaskStatus = Literal["待做", "进行中", "完成", "已从计划里去掉"]

# 更新计划里那三种状态（工具定义的枚举）对到显示用的词
PLAN_STATUS = {"pending": TASK_PENDING, "in_progress": TASK_IN_PROGRESS, "completed": TASK_COMPLETED}


@dataclass(frozen=True)
class ToolRecord:
    """一条工具调用记录，任务分组只看这几项。

    `position` 是这条工具调用开始时的事件位置，记录按它排先后；`accepted` 是工具结果里这条调用
    是否被接受（更新计划格式错误时是假，那一份不当成计划）。动作记录只看 `action_id` 与位置。
    """

    position: int
    action_id: str
    name: str
    args: Mapping[str, Any] = field(default_factory=dict)
    accepted: bool = True


@dataclass(frozen=True)
class Task:
    """一条任务：编号（1、2、3）、角色写的那句话、状态。"""

    number: int
    content: str
    status: TaskStatus


@dataclass(frozen=True)
class Grouping:
    """一次分组的结论：任务列表（按编号）与动作的所属任务（动作身份 → 编号）。"""

    tasks: tuple[Task, ...]
    # 没有进行中条目时的动作不在这里：页面按时间把它们留在两段任务之间
    owners: Mapping[str, int]


def group_tasks(records: Iterable[ToolRecord]) -> Grouping:
    """一轮工作的工具调用记录 → 任务列表与每个动作的所属任务。

    纯函数：同一个输入给同一个结论，不读别的东西。记录可以按任意顺序给出，按事件位置排。
    """
    ordered = sorted(records, key=lambda record: record.position)
    plans: list[tuple[int, tuple[tuple[str, str], ...]]] = []
    actions: list[tuple[int, str]] = []
    for record in ordered:
        if record.name == PLAN_TOOL:
            if record.accepted:
                plans.append((record.position, _entries(record.args)))
            continue
        actions.append((record.position, record.action_id))
    if not plans:
        return Grouping(tasks=(), owners={})
    # 每条任务：第一次写下的位置（没进行过的按它排），第一次进行中的位置（进行过的按它排）
    first_seen: dict[str, tuple[int, int]] = {}
    first_in_progress: dict[str, tuple[int, int]] = {}
    for position, entries in plans:
        for index, (content, status) in enumerate(entries):
            first_seen.setdefault(content, (position, index))
            if status == TASK_IN_PROGRESS:
                first_in_progress.setdefault(content, (position, index))
    # 状态取最后一次写的：最后一份计划里还在的按那里的状态，不在的写「已从计划里去掉」。
    # 同一句话在一份计划里出现两次时，后一条算最后一次写的
    final_status = {content: status for content, status in plans[-1][1]}
    tasks = tuple(
        Task(number=number, content=content, status=final_status.get(content, TASK_REMOVED))
        for number, content in enumerate(sorted(first_seen, key=lambda content: _order_key(
            content, first_seen, first_in_progress)), start=1))
    numbers = {task.content: task.number for task in tasks}
    owners: dict[str, int] = {}
    current: tuple[tuple[str, str], ...] = ()
    index = 0
    for position, action_id in actions:
        while index < len(plans) and plans[index][0] < position:
            current = plans[index][1]
            index += 1
        owner = next((content for content, status in current if status == TASK_IN_PROGRESS), None)
        if owner is not None:
            owners[action_id] = numbers[owner]
    return Grouping(tasks=tasks, owners=owners)


def _order_key(content: str, first_seen: Mapping[str, tuple[int, int]],
               first_in_progress: Mapping[str, tuple[int, int]]) -> tuple[int, int, int]:
    # 进行过的按第一次进行中的时间排，从没进行过的排在最后（各自按第一次写下的先后）
    if content in first_in_progress:
        position, index = first_in_progress[content]
        return 0, position, index
    position, index = first_seen[content]
    return 1, position, index


def _entries(args: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    # 一次更新计划调用写下的整份计划：一句话加状态。取不出条目的按空计划（清空）处理
    raw = args.get("plan") if isinstance(args, Mapping) else None
    if not isinstance(raw, list):
        return ()
    entries: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        status = item.get("status")
        label = PLAN_STATUS.get(status, TASK_PENDING) if isinstance(status, str) else TASK_PENDING
        # 首尾空白不改变这句话：同一句话带不带首尾空白都是同一条任务，显示去掉首尾空白以后的那句
        entries.append((content.strip(), label))
    return tuple(entries)

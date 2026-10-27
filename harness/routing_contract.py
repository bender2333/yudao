# 路由契约第二版（工单 #825 建、#861 第二版；骨架与应用设计说明第 3.2、5.1、5.4 节；总图第四节「路由」缝）。
#
# 回答三个问题：现在让哪些部门（会话）开始一轮工作；一轮工作以什么结束；事项以什么结束。
#
# 输入：只读的事实（运行流的投影，从事件日志折叠而来）与事项创建时冻结的定义。路由自己从事件折叠要用的状态，
# 不保存事件之外的状态，不读最小投影，最小投影不为任何路由加字段（ADR-0042 的 2026-10-25 修订）。
# 输出：开始一轮工作的部门与它自己的工作引用；一轮工作以什么结束；事项结束的判断与停止原因。
#
# 不做：不写事件（结果经薄驱动交给写入口）、不调模型、不核对边界、不执行工具。
#
# 本模块只导入内核（kernel_events、definitions）与标准库，以及契约圈的 contract_versions；实现（这一版是
# harness/watched_outputs.py）声明它实现的版本，薄驱动在一个发布里接受当前版与上一版。第二种路由是同一副
# 骨架上的另一个实现：它自己登记名称与一份定义，不改这个模块（设计说明第 5.4 节）。
#
# 第二版（#861）：组织定义的 routing 指向路由自己的一份定义（部门、成果种类、提议方式、路由自己的上限与
# 结束原因，routings.json），由路由实现自己校验、内核只核对名称与结构；一轮的结束由路由按事件判断，
# 执行契约的结果不再写死「提交了正式成果」「回答了询问」这类种类；开始一轮工作的请求带路由自己的工作引用。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from . import contract_versions
from .definitions import DEFINITIONS
# 事件信封从内核事件模块导入。运行流的投影与部门 Prompt 是应用侧的类（harness/models.py），
# 契约模块不导入应用（harness/tests/test_contract_modules.py 的导入方向），所以这两处按 Any 标注，
# 具体的类型由实现（这一版是 orchestrator.py 与 assembly.py）给出。
from .kernel_events import Event

# 这一版契约的版本号；上一版是第一版（结果的种类还写在执行契约里，工单 #826）
CURRENT_VERSION = 2
PREVIOUS_VERSION: int | None = 1


class UnavailableRouting(RuntimeError):
    # 组织定义里的路由名称没有实现接上它：这条缝接不起来时在开始一轮工作之前失败，不带着空的实现在跑
    pass


class InvalidRoutingDefinition(RuntimeError):
    # 路由自己的一份定义的内容不对（名称指向的东西不存在、几种名称互相对不上）：由路由实现自己校验，
    # 说明里逐项写明是哪一项。内核只核对这份定义的结构，内容归路由
    def __init__(self, routing: str, issues: list[str]) -> None:
        super().__init__(f"routing {routing!r} rejects its own definition (routings.json):\n"
                         + "\n".join(f"  {issue}" for issue in issues))
        self.routing = routing
        self.issues = tuple(issues)


def accept(implementation: Any) -> int:
    # 薄驱动在开始一轮工作之前核对路由实现声明的契约版本
    return contract_versions.require_version(
        implementation, component="the routing implementation",
        current=CURRENT_VERSION, previous=PREVIOUS_VERSION,
    )


# 已接上的路由实现，键是它声明的名称：实现在自己的模块加载时登记，启动时按组织定义里的名称接上
# （ADR-0042 修订里的插件加载）。这个表没有别的内容，不是事件之外的应用状态
_REGISTRY: dict[str, Any] = {}


def register(implementation: Any) -> Any:
    # 一种路由实现登记自己的名称；名称重复时后登记的接上，与按名称选实现的含义一致
    name = getattr(implementation, "NAME", None)
    if not isinstance(name, str) or not name:
        raise UnavailableRouting(f"routing implementation {implementation!r} does not declare a NAME")
    _REGISTRY[name] = implementation
    return implementation


def select(name: str, definitions: Any = None) -> Any:
    # 启动时按组织定义里写明的名称接上路由实现，核对它声明的契约版本，再让它校验自己那份定义的内容
    # （设计说明第 5.4 节第 2 条：结构由内核核对，内容归路由）。名称没有实现时失败，说明里写明有哪些可用的名称
    implementation = _REGISTRY.get(name)
    if implementation is None:
        raise UnavailableRouting(
            f"no routing implementation is registered under {name!r}; "
            f"registered names: {sorted(_REGISTRY)}")
    accept(implementation)
    implementation.check_definition(DEFINITIONS if definitions is None else definitions)
    return implementation


def registered() -> tuple[str, ...]:
    # 已接上的路由名称（按字母序），给错误说明与测试用
    return tuple(sorted(_REGISTRY))


def definition_of(definitions: Any, name: str) -> Any:
    # 一种路由自己的一份定义（routings.json 的那一条）；名称不在里面时为空
    return next((item for item in definitions.routings.routings if item.id == name), None)


@dataclass(frozen=True)
class RoundEnd:
    # 一轮工作以什么结束（成果驱动这一版沿用现在的结果种类，设计说明第 5.3 节输出）：
    # 提交被接纳记 proposal_accepted，其余正常结束（含只有文字回答的一轮）记 text_reply
    outcome: str


@dataclass(frozen=True)
class ItemEnd:
    # 事项以什么结束：停止原因与写进暂停或失败事件的处理说明。停止原因来自内核的清单或路由自己声明的结束原因
    stop_reason: str
    message: str


class Routing(Protocol):
    # 路由契约的实现（这一版是 watched_outputs.py 的 WatchedOutputs）。
    # 三个问题各是方法名里的一件事：谁现在开始一轮工作、一轮以什么结束、事项以什么结束。
    NAME: str
    CONTRACT_VERSION: int

    def check_definition(self, definitions: Any) -> None:
        # 校验自己那份定义的内容（设计说明第 5.4 节第 2 条）：名称指向的部门、成果种类与提议方式都在定义里、
        # 几种名称互相对得上。不合格时抛出 InvalidRoutingDefinition，逐项写明是哪一项
        ...

    def ready_departments(self, view: Any, *, waiting: set[str] | None = None) -> list[str]:
        # 现在让哪些部门开始一轮工作（按定义里的部门顺序）
        ...

    def next_department(self, view: Any, *, waiting: set[str] | None = None) -> str | None:
        # 下一个开始一轮工作的部门（单步入口用一次一个；同一时刻一个部门最多一轮工作）
        ...

    def department_ready(self, view: Any, *, department: str,
                         waiting: set[str] | None = None) -> bool:
        # 这个部门现在能不能开始一轮工作：准备激活的事务里由薄驱动再问一次
        ...

    def work_reference(self, view: Any, *, department: str) -> Any:
        # 这一轮工作的路由自己的工作引用（例如任务池的任务），原样交给装配与执行（设计说明第 5.1 节输出、
        # 第 5.4 节第 4 条）；不用它时为空。任务池不在这里：成果驱动不用
        ...

    def round_end(self, view: Any, events: list[Event], *, department: str, session_id: str | None,
                  activation_id: str) -> RoundEnd | None:
        # 这一轮以什么结束；不是正常结束的一轮（暂停、失败）返回 None
        ...

    def item_end(self, view: Any) -> ItemEnd | None:
        # 事项以什么结束；还可以继续时返回 None
        ...

# 路由契约第二版（工单 #825 建、#861 第二版；骨架与应用设计说明第 3.2、5.1、5.4 节；总图第四节「路由」缝）。
#
# 回答三个问题：现在让哪些部门（会话）开始一轮工作；一轮工作以什么结束；事项以什么结束。
#
# 输入：只读的事实（运行流的投影，从事件日志折叠而来）与事项创建时冻结的定义。路由自己从事件折叠要用的状态，
# 不保存事件之外的状态，不读最小投影，最小投影不为任何路由加字段。
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
#
# 第二版的输出里补一件（#862）：询问分支也由路由请求一轮工作。路由判断这次询问要不要开一层分支、
# 接着上次没结束的那一层、回复给谁、这一轮的上限，以及分支这一轮答没答出来；分支的一轮由薄驱动按执行契约
# 照常运行，已用掉的步数与时间由薄驱动自己扣（路由不读最小投影）。
#
# 第三版（#1164）：输入那一条给了路由读事件的入口。契约新增可选方法 use_facts：声明了它的路由，组装处在
# select 接上它以后把事件库的**只读**读取器交给它（只有 list_events(run_id)，没有写事件的出路）；没有声明的
# 路由（成果驱动）不受影响，也不会被调用。第二版的路由实现照旧被接受（一版兼容，contract_versions）。
# 这样第二种路由按设计说明第 5.1 节的输入自己折事件，不必再把事件库从外面塞进路由。

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import contract_versions
from .definitions import DEFINITIONS
# 事件信封从内核事件模块导入。运行流的投影与部门 Prompt 是应用侧的类（harness/models.py），
# 契约模块不导入应用（harness/tests/test_contract_modules.py 的导入方向），所以这两处按 Any 标注，
# 具体的类型由实现（这一版是 orchestrator.py 与 assembly.py）给出。
from .kernel_events import Event

# 这一版契约的版本号；上一版是第二版（组织定义里的路由名称指向路由自己的一份定义，工单 #861）
CURRENT_VERSION = 3
PREVIOUS_VERSION: int | None = 2


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
# （骨架与应用设计说明第 5.1 节）。这个表没有别的内容，不是事件之外的应用状态
_REGISTRY: dict[str, Any] = {}


def register(implementation: Any) -> Any:
    # 一种路由实现登记自己的名称；名称重复时后登记的接上，与按名称选实现的含义一致
    name = getattr(implementation, "NAME", None)
    if not isinstance(name, str) or not name:
        raise UnavailableRouting(f"routing implementation {implementation!r} does not declare a NAME")
    _REGISTRY[name] = implementation
    return implementation


class _Facts:
    # 交给路由的只读事件读取器（第三版，工单 #1164）：只有 list_events，读哪个 run 的事件。
    # 事件库本身留在组装处，路由借看，不写事件（设计说明第 5.1 节「不做」）。不给写出路是这一版的用意：
    # 契约只给读的入口，写仍然只经薄驱动交给写入口
    __slots__ = ("_store",)

    def __init__(self, store: Any) -> None:
        self._store = store

    def list_events(self, run_id: str) -> list[Event]:
        return list(self._store.list_events(run_id))


def _hand_facts(name: str, implementation: Any, store: Any) -> bool:
    # 组装处把只读的事件读取器交给声明了 use_facts 的路由（第三版，工单 #1164）：没有声明的路由不调用它，
    # 声明了却没有事件库可交时在开始一轮工作之前失败，不让路由带着「读不到事件」的状态跑起来
    method = getattr(implementation, "use_facts", None)
    if method is None:
        return False
    if not callable(method):
        raise UnavailableRouting(
            f"routing implementation {name!r} declares use_facts, and it is not callable")
    if store is None:
        raise UnavailableRouting(
            f"routing implementation {name!r} reads events through use_facts, "
            "and the assembly has no event store to hand it a read-only reader")
    method(_Facts(store))
    return True


def select(name: str, definitions: Any = None, *, store: Any = None) -> Any:
    # 启动时按组织定义里写明的名称接上路由实现，核对它声明的契约版本，再让它校验自己那份定义的内容
    # （设计说明第 5.4 节第 2 条：结构由内核核对，内容归路由）。名称没有实现时失败，说明里写明有哪些可用的名称。
    # store 是组装处手里的事件库：声明了 use_facts 的路由在这里拿到它的只读读取器
    implementation = _REGISTRY.get(name)
    if implementation is None:
        raise UnavailableRouting(
            f"no routing implementation is registered under {name!r}; "
            f"registered names: {sorted(_REGISTRY)}")
    accept(implementation)
    implementation.check_definition(DEFINITIONS if definitions is None else definitions)
    _hand_facts(name, implementation, store)
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


# ---------------------------------------------------------------------------
# 询问分支（#862）：路由判断这一层询问，薄驱动照常运行这一轮
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AskLimits:
    # 薄驱动给的运行配置上限：路由按被问的部门与提问方这一步剩下的量算出这一次询问这一轮的上限
    # （设计说明第 5.1 节输出里的「这一轮的上限」）。已经用掉的步数与时间由薄驱动扣，路由不读最小投影
    max_model_steps: int
    department_max_model_steps: Mapping[str, int] = field(default_factory=dict)
    department_max_time_sec: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AskBranch:
    # 这一次询问要开的一轮分支工作：回复的部门、分支会话、这一轮的上限，以及路由自己的工作引用
    # （指向这次询问，原样交给装配与执行）。start 是要写下的询问开始事件的载荷；接着上次没结束的
    # 那一层时为空，那一层已经开始过了（设计说明第 5.1 节「询问的开始归路由」）
    recipient: str
    session_id: str
    max_model_steps: int
    max_time_sec: float
    start: dict[str, Any] | None = None
    work_ref: Any = None


@dataclass(frozen=True)
class AskRoundResult:
    # 分支这一轮的结果里路由要看的几样：交上来的回答（原样的工具参数）或为空、停止原因与说明，
    # 以及薄驱动按这一轮的上限算出的两件事——时间是否用完、还剩几步可走（0 表示这一轮没有跑）
    submission: dict[str, Any] | None = None
    stop_reason: str | None = None
    message: str = ""
    time_exhausted: bool = False
    steps_left: int = 1


@dataclass(frozen=True)
class AskOutcome:
    # 询问的结果：status 是 answered（回答交回提问方）或 unable（没能回答，原因写在 reason）；
    # revises 是这一回答同时交上的成果（路由组装的提案参数），薄驱动经写入口提交。
    # recorded 为真表示这条结果已经写在事件日志里（重新启动以后接着同一次询问），薄驱动不再写事件
    status: str
    session_id: str
    answer: str = ""
    reason: str = ""
    facts: str | None = None
    explanation: str | None = None
    revises: dict[str, Any] | None = None
    recorded: bool = False


@dataclass(frozen=True)
class AskRejection:
    # 这次询问的调用不合法（回复的部门不在路由的部门清单里、问题为空）：不运行、不写事件，
    # 原因作为这次工具调用的错误交回提问方
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

    def use_facts(self, reader: Any) -> None:
        # 可选（第三版，工单 #1164）：声明了这个方法的路由，在组装处 select 接上它以后拿到事件库的只读读取器
        # reader（只有 list_events(run_id)），据此按设计说明第 5.1 节的输入自己折事件。没有这个方法的路由实现
        # （第二版与成果驱动）照常被接受，也不会被调用
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

    def ask_branch(self, view: Any, events: list[Event], *, requester: str, session_id: str,
                   call: dict[str, Any], limits: AskLimits) -> AskBranch | AskOutcome | AskRejection:
        # 提问方这个会话的这次询问：要开一轮分支工作就给这一轮（AskBranch），已经答过或一步也走不了
        # 就给结果（AskOutcome），调用不合法就给原因（AskRejection）。询问的开始与回问都在这里判断，
        # 回问的层数上限按路由自己的定义算（设计说明第 5.1 节）
        ...

    def ask_outcome(self, view: Any, *, branch: AskBranch,
                    result: AskRoundResult) -> AskOutcome:
        # 分支这一轮以什么结束：把回答交回提问方（answered），还是没能回答与原因（unable）。
        # 回答的内容、回答同时交上的成果、没能回答的原因都由路由按自己的定义判断
        ...

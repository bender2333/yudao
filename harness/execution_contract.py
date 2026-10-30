# 执行契约第二版（骨架与应用设计说明第 3.2、5.3 节；总图第四节「执行」缝）：
# 输入一轮工作（部门、会话、提示、这一轮的上限、路由的工作引用；工作引用原样交给装配）；
# 每一步经安全节点问薄驱动继续或停止；工具调用经裁决入口；输出一轮工作的结果：这一轮写下的事件的范围与
# 停止原因。这一轮算不算结束、结束成什么，由路由按事件判断，契约不写死「提交了正式成果」「回答了询问」
# 这类结果种类（第二版：#861 从第一版改形状；阶段一首次发布以后按字段只增）。
# 本模块只导入内核与标准库，以及契约圈的 contract_versions；实现（engine.py 的 StepDriver）声明实现这一版，
# 薄驱动接受当前版与上一版。

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Event as CancelEvent
from typing import Any, Protocol

from . import contract_versions
from .adjudication import WorkBasis
from .definitions import DEFINITIONS
# 事件信封从内核事件模块导入。运行流的投影与部门 Prompt 是应用侧的类（harness/models.py），
# 契约模块不导入应用（harness/tests/test_contract_modules.py 的导入方向），所以这两处按 Any 标注，
# 具体的类型由实现（这一版是 orchestrator.py 与 assembly.py）给出。
from .kernel_events import Event
from .write_path import Transaction

# 这一版契约的版本号；上一版是第一版（结果的种类还写死成「提交了正式成果」与「回答了询问」，工单 #826）
CURRENT_VERSION = 2
PREVIOUS_VERSION: int | None = 1


def accept(implementation: Any) -> int:
    # 薄驱动在开始一轮工作之前核对执行实现声明的版本
    return contract_versions.require_version(
        implementation, component="the execution implementation",
        current=CURRENT_VERSION, previous=PREVIOUS_VERSION,
    )


@dataclass(frozen=True)
class Judgment:
    # 安全节点的回答：是否继续，以及作出判断时 run 流的版本；
    # blocked_by_other_session 说明别的会话已经写下待恢复的决定请求（模型管理设计说明第 5.5 节）：
    # 这个会话照常停下（事项的状态不变，工单 #856），它自己也被挡住时它要写下自己的那一条
    proceed: bool
    version: int
    blocked_by_other_session: bool = False


@dataclass(frozen=True)
class ActivationScope:
    # 记录所属的激活：身份、激活采用的版本与工作依据，以及激活开始时配置的提供方名称（解析发生在每次逻辑调用）。
    # 记录接口（recording.py）与步骤驱动共用这一份；询问带回新合同以后由步骤驱动替换它（工单 #840）
    run_id: str
    department: str
    session_id: str
    activation_id: str
    parent_event_id: str
    prompt_version: int
    prompt_hash: str | None
    guidance_ids: tuple[str, ...]
    basis: WorkBasis
    provider: str

    def versions(self) -> dict[str, Any]:
        return {"input_version": self.basis.input_version, "prompt_version": self.prompt_version,
                "prompt_hash": self.prompt_hash, "guidance_ids": list(self.guidance_ids)}

    def work_basis(self) -> dict[str, Any]:
        return {"effective_contract_hash": self.basis.effective_contract_hash}


@dataclass(frozen=True)
class StepLimits:
    # 步骤驱动的重试与步数参数；默认值取规则登记中的初始值，一次 run 里由流程编排换成这个 run 冻结的值
    # （工单 #1189：这 6 项与 compaction_stalled_limit 一起在 run_created 里冻结）
    retry_initial_delay_sec: float = DEFINITIONS.rule_value("retry_initial_delay_sec")
    retry_max_delay_sec: float = DEFINITIONS.rule_value("retry_max_delay_sec")
    max_provider_attempts: int = DEFINITIONS.rule_value("max_provider_attempts")
    max_model_steps: int = DEFINITIONS.rule_value("max_model_steps")
    tool_call_required_limit: int = DEFINITIONS.rule_value("tool_call_required_limit")
    compaction_stalled_limit: int = DEFINITIONS.rule_value("compaction.stalled_limit")
    department_max_model_steps: Mapping[str, int] = field(default_factory=dict)
    department_max_time_sec: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RoundRequest:
    # 开始一轮工作的请求（第 5.3 节输入）：部门、会话在 scope 里，prompt 是这一轮采用的提示，
    # limits 是这一轮的上限，work_ref 是路由自己的工作引用（例如任务池的任务）。
    # work_ref 原样交给装配（第 5.4 节第 4 条），骨架不解释它
    scope: ActivationScope
    prompt: Any
    limits: StepLimits
    work_ref: Any = None


class SafeNode(Protocol):
    # 安全节点接口：步骤驱动在安全节点调用它，流程编排在这里分派新输入、关闭因此过时的协作请求，回答继续还是停止。
    # 这是唯一一处由下层调用上层的接口，按依赖倒置处理：接口在步骤驱动一侧定义，流程编排实现并在开始时交给步骤驱动，
    # 步骤驱动不引用流程编排

    def proceed(self) -> Judgment:
        # 分派新输入，回答是否继续
        ...

    def settle(self, transaction: Transaction) -> Any:
        # 在调用方的事务中分派新输入并关闭过时的协作请求，返回事务中当前的运行状态；调用方随后判断并写入
        ...

    async def wait(self, seconds: float) -> Judgment:
        # 在安全节点等待至多 seconds 秒，其间有新输入、指导或取消时提前回答；回答是否继续
        ...

    def end(self, transaction: Transaction, reason: str, message: str) -> None:
        # 以停止原因结束运行：运行的结束与调用方在同一事务中刚写下的记录一起提交
        ...

    def department_selection(self, department: str) -> Any | None:
        # 设置来源（项目层）：本次请求该项目该部门的项目部门设置中的模型选择；
        # 不属于项目的运行时为空，全部使用部门默认（设计说明第 6 节）。返回的是实现自己的选择类型
        # （providers.selection.ModelSelection），契约原样交回实现
        ...

    def department_prompt(self, department: str) -> Any:
        # 部门 Prompt 每次请求从项目部门设置读取；没有写入时使用内置默认 Prompt（版本 0）
        ...

    async def ask(self, scope: ActivationScope, call: dict[str, Any]) -> tuple[bool, Any, str | None, str | None, int]:
        # 开一个询问分支，等待分支回答，返回 (ok, output, error, new_contract_hash, branch_steps)
        ...


@dataclass(frozen=True)
class RoundResult:
    # 一轮工作的结果（设计说明第 5.3 节输出）：这一轮写下的事件范围与停止原因。这一轮算不算正常结束、
    # 结束成什么，由路由按事件判断（第 5.4 节第 5 条；routing_contract.RoundEnd），契约里没有结果种类。
    # stop_reason 为空：在安全节点停止（中止、运行时间用完、终态、输入或依据改变），由薄驱动按当时的运行状态
    # 收尾；否则是停止原因的编号与说明，由薄驱动暂停或结束运行。version 是作出停止判断时 run 流的版本。
    # target 是这次失败对应的调用目标公开部分（不含密钥）；facts 是停止原因要带给决定请求的事实引用
    events: tuple[Event, ...] = ()
    version: int = 0
    stop_reason: str | None = None
    message: str = ""
    target: dict[str, Any] | None = None
    facts: tuple[str, ...] = ()
    # 整理连续没有推进达到 compaction.stalled_limit（stop_reason 为 compaction_failed，模型管理设计说明
    # 第 8.7 节最后一条，工单 #1238）：薄驱动让 run 进入待恢复、等用户回答，不结束运行。其余
    # compaction_failed（整理请求本身装不进窗口）照旧结束运行，所以由实现标明是哪一种
    stalled_compaction: bool = False
    # 这一轮里模型用提交类工具交上来的参数（原样的工具回执，或参数加上工具声明的种类），带来它的这次回答，
    # 以及这一轮的发言：薄驱动经写入口提交时用（转录存成工件）。是不是提交、是哪一种，由路由按它自己的定义判断；
    # response 是 Provider 的回答对象，原样交回实现，契约不解释它
    submission: dict[str, Any] | None = None
    response: Any = None
    transcript: str = ""


class StepDriver(Protocol):
    # 执行契约的实现（这一版是 engine.py 的 StepDriver）：一轮工作的步骤循环。
    # 薄驱动只调 start、cancel 与 result；结果是一轮工作写下的事件范围与停止原因（RoundResult）
    CONTRACT_VERSION: int

    @classmethod
    def start(cls, request: RoundRequest, *, nodes: SafeNode, cancelled: CancelEvent,
              **dependencies: Any) -> "StepDriver":
        # 在当前事件循环中开始这次激活的步骤循环；dependencies 由实现按自己的需要取用，不属于契约
        ...

    def cancel(self) -> None:
        # 取消这一轮：之后的核对都得到停止，正在进行的动作与调用尝试按身份取消
        ...

    async def result(self) -> RoundResult:
        # 等这一轮结束并交回结果
        ...

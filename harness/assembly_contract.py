# 装配契约第一版（骨架与应用设计说明第 3.2、5.2 节；总图第四节「装配」缝）：
# 输入事件日志里这个部门与会话的历史、定义、材料、调用目标的窗口与输出上限，以及路由的工作引用；
# 输出装配好的请求与上下文清单，两者都记进日志；不改事实。
# 本模块只导入内核（kernel_events、definitions）与标准库，以及契约圈的 contract_versions；实现（assembly.py 的 ContextAssembly）声明实现这一版，
# 薄驱动接受当前版与上一版。装配出来的请求与固定部分的形状是实现自己的，契约这一版只固定输入与不变量。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from . import contract_versions
# 事件信封从内核事件模块导入。运行流的投影与部门 Prompt 是应用侧的类（harness/models.py），
# 契约模块不导入应用（harness/tests/test_contract_modules.py 的导入方向），所以这两处按 Any 标注，
# 具体的类型由实现（这一版是 orchestrator.py 与 assembly.py）给出。
from .kernel_events import Event

# 这一版契约的版本号；上一版是第一版之前的空位，没有实现声明它
CURRENT_VERSION = 1
PREVIOUS_VERSION: int | None = None


def accept(implementation: Any) -> int:
    # 薄驱动在开始一轮工作之前核对装配实现声明的版本
    return contract_versions.require_version(
        implementation, component="the assembly implementation",
        current=CURRENT_VERSION, previous=PREVIOUS_VERSION,
    )


@dataclass(frozen=True)
class ModelLimits:
    # 按调用目标计算的有效窗口、模型声明的输出上限与为回复保留的空间；保留空间决定何时压缩历史
    context_window: int
    output_limit: int | None
    reserve: int


@dataclass(frozen=True)
class StepFrame:
    # 一次激活装配每一步所需的身份与激活时采用的版本；压缩检查点按这些版本选取。
    # work_ref 是路由自己的工作引用，从开始一轮工作的请求原样带到这里，供装配实现取用（第 5.4 节第 4 条）
    department: str
    session_id: str
    activation_id: str
    prompt: Any
    effective_contract_hash: str | None
    input_version: int
    work_ref: Any = None


class ContextAssembly(Protocol):
    # 装配契约的实现（这一版是 assembly.py 的 ContextAssembly）
    CONTRACT_VERSION: int

    def department_history(self, events: list[Event], department: str, *,
                           session_id: str | None = None) -> list[dict[str, Any]]:
        # 这个部门（与这个会话）的历史，按事件顺序排列
        ...

    def pin(self, projection: Any, frame: StepFrame, limits: ModelLimits, *, step_id: int,
            events: list[Event], snapshot_hash: str, call_target: dict[str, Any] | None = None,
            input_modalities: tuple[str, ...] = ("text",)) -> Any:
        # 这一步固定的部分：部门材料、工具定义与上下文清单的前一半
        ...

    def request(self, pinned: Any, history: list[dict[str, Any]], *,
                defer_compaction: bool = False) -> Any:
        # 在固定部分之后接上部门历史，得到装配好的请求与上下文清单。
        # defer_compaction 为真时，这一次不另发整理请求，按未压缩的历史交出工作请求（第 8.7 节，工单 #1155）
        ...

    def finish_compaction(self, step: Any, output: list[dict[str, Any]]) -> Any | None:
        # 压缩请求的回答生成的检查点；摘要为空或超过上限时为空，不记录这次压缩
        ...

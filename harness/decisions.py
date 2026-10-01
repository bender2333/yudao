# 用户决定（总体架构第 7.4 节）：凡是等待用户的事项，都由流程编排发出决定请求，用户经应用层的命令 decision.answer
# 回答；请求、回答与撤销都写成事件，决定请求另存一份投影（projection.py）。这里是决定的种类：每种请求的阻塞范围
# 与由它的合同给出的选项，以及回答被拒绝的原因。

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import DecisionRequest


@dataclass(frozen=True)
class Option:
    id: str
    label: str


@dataclass(frozen=True)
class DecisionKind:
    # blocks 是请求的阻塞范围：run 表示回答之前这个 run 不推进
    name: str
    blocks: str
    options: tuple[Option, ...]


# 模型引用无法使用时的待恢复（模型管理设计说明第 5.5 节）：用户修复配置以后继续执行，事项从这次请求接着进行，
# 已完成的工作与已用限额保留；或者停止事项
MODEL_UNAVAILABLE = DecisionKind("model_unavailable", "run", (Option("continue", "继续执行"), Option("stop", "停止事项")))

# 事项记录的定义版本与当前加载的版本不同（ADR-0014，工单 #16）：升级以后继续旧事项时由用户决定按新版本继续还是停止
DEFINITIONS_CHANGED = DecisionKind("definitions_changed", "run",
                                   (Option("continue", "按新版本继续"), Option("stop", "停止事项")))

# 结果未知的动作（工单 #17，恢复契约第 4 节）：工具已发出但结果未确认，由用户决定如何处理。
# 阻塞范围为动作（不是 run），其他合法动作可以继续；「重新执行」只在契约声明该动作可以重复时提供，
# 创建决定请求时按动作的 repeatable 属性过滤选项
UNKNOWN_ACTION = DecisionKind("unknown_action", "action",
                              (Option("reexecute", "重新执行"),
                               Option("continue", "按当前实际状态继续"),
                               Option("stop", "停止事项")))

DECISION_KINDS = {kind.name: kind for kind in (MODEL_UNAVAILABLE, DEFINITIONS_CHANGED, UNKNOWN_ACTION)}


def blocks_run(decisions: Iterable[DecisionRequest]) -> bool:
    # 有未回答、阻塞整个 run 的决定请求
    return any(decision.status == "open" and decision.blocks == "run" for decision in decisions)

def blocks_activation(decisions: Iterable[DecisionRequest]) -> bool:
    # 有未回答的「核实结果未知的动作」请求：在它得到回答以前，依赖这个动作的下一步不继续。
    # 动作级阻塞与 run 级阻塞一样不让流程编排开始新的激活，区别只在决定请求的阻塞范围标注为动作
    return any(decision.status == "open" and decision.kind == UNKNOWN_ACTION.name for decision in decisions)


class DecisionNotFound(KeyError):
    def __init__(self, decision_id: str) -> None:
        super().__init__(decision_id)
        self.decision_id = decision_id


class DecisionClosed(Exception):
    # 决定请求已经回答或已经撤销
    def __init__(self, decision: DecisionRequest) -> None:
        super().__init__(f"decision request {decision.decision_id} is {decision.status}")
        self.status = decision.status


class StaleDecision(Exception):
    # 回答所依据的请求版本不是请求的当前版本
    def __init__(self, decision: DecisionRequest, base_version: int) -> None:
        super().__init__(f"decision request {decision.decision_id} is at version {decision.version}, "
                         f"not the base version {base_version}")
        self.version = decision.version


class InvalidOption(Exception):
    # 所选的选项不是这个请求给出的选项
    def __init__(self, decision: DecisionRequest, option: str) -> None:
        super().__init__(f"option {option} is not offered by decision request {decision.decision_id}")
        self.options = [item["id"] for item in decision.request["options"]]

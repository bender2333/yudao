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
    # 说明必填（工单 #136，设计第 3.2 节）：为真时这个选项必须附说明，空说明的回答由服务端拒绝
    note_required: bool = False


@dataclass(frozen=True)
class DecisionKind:
    # blocks 是请求的阻塞范围：run 表示回答之前这个 run 不推进
    name: str
    blocks: str
    options: tuple[Option, ...]


# 模型引用无法使用时的待恢复（模型管理设计说明第 5.5 节）：用户修复配置以后继续执行，事项从这次请求接着进行，
# 已完成的工作与已用限额保留；或者停止事项
MODEL_UNAVAILABLE = DecisionKind("model_unavailable", "run", (Option("continue", "继续执行"), Option("stop", "停止事项")))

# 事项记录的定义版本与当前加载的版本不同（总体架构第 7.4 节，工单 #16）：升级以后继续旧事项时由用户决定按新版本继续还是停止
DEFINITIONS_CHANGED = DecisionKind("definitions_changed", "run",
                                   (Option("continue", "按新版本继续"), Option("stop", "停止事项")))

# 模型连续多次只回复文字、没有调用工具（D09，工单 #204）：用户处理以后从暂停位置继续，或者停止事项。
# 继续以前可以先在部门设置中更换模型，从下一次请求起生效
NO_TOOL_CALL = DecisionKind("no_tool_call", "run",
                            (Option("continue", "处理以后继续执行"), Option("stop", "停止事项")))

# 工作区出现公开树无法表示的条目（D09，工单 #204）：用户把条目加入忽略规则或者删除以后从暂停位置继续，或者停止事项
WORKSPACE_UNREPRESENTABLE = DecisionKind("workspace_unrepresentable", "run",
                                         (Option("continue", "处理以后继续执行"), Option("stop", "停止事项")))

# 暂停的 run 在回答以后继续的两种决定种类；由暂停的停止原因得到对应的种类
RESUMABLE_PAUSE_KINDS = {NO_TOOL_CALL.name: NO_TOOL_CALL, WORKSPACE_UNREPRESENTABLE.name: WORKSPACE_UNREPRESENTABLE}

# 确认接入已有项目的初始 PRD（工单 #136，接入已有项目设计说明第 3.2 节）：建档 run 已经结束，
# 请求写在项目流中，阻塞建档事项与同一项目中排在它后面的事项，不属于任何 run。
# 「提出修改」必须附说明：说明为空的回答由服务端以 not_allowed 拒绝
INITIAL_PRD = DecisionKind("initial_prd", "work_item",
                           (Option("confirm", "确认"), Option("revise", "提出修改", note_required=True)))
# 交付改动了内核清单里的路径（受控内核设计说明第 4.2 节，接口与应用层设计说明第 3.3 节，工单 #354）：
# 采纳之前由控制核心把交付相对基线的改动路径与运行实例的内核清单比较，有交集时不自动采纳，
# 请求用户批准；请求写在项目流中，阻塞整个 run（交付所属的 run 已经结束，阻塞范围按请求给出的范围标注）
KERNEL_MODIFICATION = DecisionKind("kernel_modification", "run",
                                   (Option("approve", "批准采纳"), Option("reject", "拒绝")))

# 实例升级（迭代底座 B7，工单 #355）：升级这台电脑上安装的那一份是一次用户决定，请求写在目录流中，
# 不属于任何 run 或项目，也不阻塞它们；发布检查的结果作为材料附在请求里
INSTANCE_UPGRADE = DecisionKind("instance_upgrade", "instance",
                                (Option("approve", "批准升级"), Option("reject", "拒绝")))

DECISION_KINDS = {kind.name: kind for kind in (MODEL_UNAVAILABLE, DEFINITIONS_CHANGED,
                                               NO_TOOL_CALL, WORKSPACE_UNREPRESENTABLE, INITIAL_PRD,
                                               INSTANCE_UPGRADE,
                                               KERNEL_MODIFICATION)}


def blocks_run(decisions: Iterable[DecisionRequest]) -> bool:
    # 有未回答、阻塞整个 run 的决定请求
    return any(decision.status == "open" and decision.blocks == "run" for decision in decisions)


def blocked_by_other_session(decisions: Iterable[DecisionRequest], department: str) -> bool:
    # 别的会话已经写下待恢复的决定请求（模型管理设计说明第 5.5 节：同一事项里同时有几个会话被挡住时，
    # 各发一条决定请求，各写明自己的部门、模型与问题，事项等这几条都回答以后再继续）。
    # 这个部门自己已经有一条时不重复：它写下以后就停在那里
    items = list(decisions)
    if not blocks_run(items):
        return False
    return not any(decision.status == "open" and decision.blocks == "run"
                   and decision.request.get("department") == department for decision in items)



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


class NoteRequired(Exception):
    # 所选的选项要求附说明而这次回答没有给说明（工单 #136）：请求不变，什么也不写
    def __init__(self, decision: DecisionRequest, option: str) -> None:
        super().__init__(f"option {option} of decision request {decision.decision_id} requires a note")
        self.decision_id = decision.decision_id
        self.option = option

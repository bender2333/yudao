# 用户决定（总体架构 docs/design/architecture/overall-architecture.md「用户决定」）：凡是等待用户的事项，都由流程编排发出决定请求，用户经应用层的命令 decision.answer
# 回答；请求、回答与撤销都写成事件，决定请求另存一份投影（projection.py）。这里是决定的种类：每种请求的阻塞范围
# 与由它的合同给出的选项，以及回答被拒绝的原因。

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .models import DecisionRequest


BlockingScope = Literal["run", "action", "round"]


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    # 说明必填（工单 #136）：为真时这个选项必须附说明，空说明的回答由服务端拒绝
    note_required: bool = False


@dataclass(frozen=True)
class DecisionKind:
    # blocks 是请求的阻塞范围：run 表示回答之前这个 run 不推进
    name: str
    blocks: str
    options: tuple[Option, ...]


# 模型引用无法使用时的待恢复（模型管理 docs/design/model-management.md「引用无法使用时」）：用户修复配置以后继续执行，事项从这次请求接着进行，
# 已完成的工作与已用限额保留；或者停止事项
MODEL_UNAVAILABLE = DecisionKind("model_unavailable", "run", (Option("continue", "继续执行"), Option("stop", "停止事项")))

# 事项记录的定义版本与当前加载的版本不同（总体架构 docs/design/architecture/overall-architecture.md「用户决定」，工单 #16）：升级以后继续旧事项时由用户决定按新版本继续还是停止
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

# 确认接入已有项目的初始 PRD（工单 #136，接入已有项目 docs/design/existing-project-onboarding.md「决定种类」）：建档 run 已经结束，
# 请求写在项目流中，阻塞建档事项与同一项目中排在它后面的事项，不属于任何 run。
# 「提出修改」必须附说明：说明为空的回答由服务端以 not_allowed 拒绝
INITIAL_PRD = DecisionKind("initial_prd", "work_item",
                           (Option("confirm", "确认"), Option("revise", "提出修改", note_required=True)))
# 交付改动了内核清单里的路径（受控内核 docs/design/trusted-kernel.md「路径守卫」，接口与应用层 docs/design/app-and-interface.md「用户决定的回答」，工单 #354）：
# 采纳之前由控制核心把交付相对基线的改动路径与运行实例的内核清单比较，有交集时不自动采纳，
# 请求用户批准；请求写在项目流中，阻塞整个 run（交付所属的 run 已经结束，阻塞范围按请求给出的范围标注）
KERNEL_MODIFICATION = DecisionKind("kernel_modification", "run",
                                   (Option("approve", "批准采纳"), Option("reject", "拒绝")))

# 质检无法核验（浏览器与 computer use docs/design/browser-and-computer-use.md「无法核验」，工单 #1179）：质检自己的条件不够
# （模型不支持图像输入而条目依赖外观、执行位置上缺少试用或运行交付需要的程序）时提交 cannot_verify，
# 流程编排发出这个请求，阻塞范围是这个 run，说明列出每条无法核验的验收条件与原因。
# 「重新核验」：用户修改设置或装好程序以后回答，质检以新的激活重新检查同一份交付；
# 「停止事项」：事项结束，交付不被采纳
QA_CANNOT_VERIFY = DecisionKind("qa_cannot_verify", "run",
                                (Option("re_verify", "重新核验"), Option("stop", "停止事项")))

# 实例升级（迭代底座 B7，工单 #355）：升级这台电脑上安装的那一份是一次用户决定，请求写在目录流中，
# 不属于任何 run 或项目，也不阻塞它们；发布检查的结果作为材料附在请求里
INSTANCE_UPGRADE = DecisionKind("instance_upgrade", "instance",
                                (Option("approve", "批准升级"), Option("reject", "拒绝")))

# 角色向用户提问的多题前沿决定（部门循环 docs/design/department-loop.md「向用户提问：多题前沿决定请求」）：
# 阻塞范围限定为 round，只暂停发出它的职能或角色这一轮；支持逐题回答或全部采用每题推荐选项
ROLE_CHOICE = DecisionKind("role_choice", "round",
                           (Option("submit", "提交回答"), Option("recommended", "全部采用推荐")))

DECISION_KINDS = {kind.name: kind for kind in (MODEL_UNAVAILABLE, DEFINITIONS_CHANGED,
                                               NO_TOOL_CALL, WORKSPACE_UNREPRESENTABLE, INITIAL_PRD,
                                               INSTANCE_UPGRADE, QA_CANNOT_VERIFY,
                                               KERNEL_MODIFICATION, ROLE_CHOICE)}


def _item_field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, Mapping) else getattr(item, name, None)


def _require_non_empty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    return value


def _validate_role_choice_option(q_id: str, opt_index: int, raw: Any, seen_ids: set[str]) -> dict[str, Any]:
    if isinstance(raw, (str, bytes, int, float, bool)) or raw is None:
        raise ValueError(f"题目 {q_id} 第 {opt_index} 个选项格式无效")
    opt_id = _require_non_empty_text(_item_field(raw, "id"), f"题目 {q_id} 第 {opt_index} 个选项标识 id")
    if opt_id in seen_ids:
        raise ValueError(f"题目 {q_id} 的选项标识 {opt_id} 重复")
    seen_ids.add(opt_id)
    label = _require_non_empty_text(_item_field(raw, "label"), f"题目 {q_id} 选项 {opt_id} 的标题 label")
    normalized: dict[str, Any] = {"id": opt_id, "label": label}
    description = _item_field(raw, "description")
    if description is not None:
        if not isinstance(description, str):
            raise ValueError(f"题目 {q_id} 选项 {opt_id} 的说明 description 必须是字符串")
        normalized["description"] = description
    return normalized


def _validate_role_choice_question(index: int, raw: Any, seen_ids: set[str]) -> dict[str, Any]:
    if isinstance(raw, (str, bytes, int, float, bool)) or raw is None:
        raise ValueError(f"第 {index} 道问题格式无效")
    q_id = _require_non_empty_text(_item_field(raw, "id"), f"第 {index} 题的题号 id")
    if q_id in seen_ids:
        raise ValueError(f"题目编号 {q_id} 在同一批问题中重复")
    seen_ids.add(q_id)
    question_text = _require_non_empty_text(_item_field(raw, "question"), f"题目 {q_id} 的题干 question")
    raw_options = _item_field(raw, "options")
    if not isinstance(raw_options, Sequence) or isinstance(raw_options, (str, bytes, bytearray)) or len(raw_options) < 2:
        raise ValueError(f"题目 {q_id} 至少需要两个互斥选项")
    seen_opt_ids: set[str] = set()
    options = [_validate_role_choice_option(q_id, opt_index, opt, seen_opt_ids)
               for opt_index, opt in enumerate(raw_options, start=1)]
    recommended = _require_non_empty_text(_item_field(raw, "recommended"), f"题目 {q_id} 的推荐选项 recommended")
    if recommended not in seen_opt_ids:
        raise ValueError(f"题目 {q_id} 的推荐选项 {recommended} 未出现在该题选项列表中")
    rationale = _require_non_empty_text(_item_field(raw, "rationale"), f"题目 {q_id} 的推荐理由 rationale")
    return {
        "id": q_id,
        "question": question_text,
        "options": options,
        "recommended": recommended,
        "rationale": rationale,
    }


def validate_role_choice_questions(questions: Sequence[Any]) -> list[dict[str, Any]]:
    # 校验 role_choice 问题列表结构并规范化返回副本：列表非空、题号批内唯一、每题至少两项互斥选项、
    # 推荐选项命中候选列表且推荐理由非空
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes, bytearray)) or not questions:
        raise ValueError("多题决定请求的问题列表不能为空")
    seen_ids: set[str] = set()
    return [_validate_role_choice_question(index, item, seen_ids)
            for index, item in enumerate(questions, start=1)]


def resolve_role_choice_answers(
    questions: Sequence[Any],
    option: str,
    answers: Mapping[str, str] | None,
    *,
    decision: DecisionRequest | None = None,
) -> dict[str, str]:
    # 解析并补齐多题决定请求的逐题回答：拒绝未知顶层选项、未知题号或某题未知选项标识，
    # 未指定回答的题目以及选用 recommended 且未传 answers 时自动按每题 recommended 补齐
    allowed_top = [item.id for item in ROLE_CHOICE.options]
    if option not in allowed_top:
        raise InvalidOption(decision, option, options=allowed_top)
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes, bytearray)) or not questions:
        raise ValueError("多题决定请求缺少有效的问题列表")
    by_id: dict[str, tuple[list[str], str]] = {}
    for index, item in enumerate(questions, start=1):
        q_id = _require_non_empty_text(_item_field(item, "id"), f"第 {index} 题的题号 id")
        if q_id in by_id:
            raise ValueError(f"题目编号 {q_id} 重复")
        raw_options = _item_field(item, "options") or ()
        opt_ids = [_require_non_empty_text(_item_field(opt, "id"), f"题目 {q_id} 选项 id") for opt in raw_options]
        recommended = _require_non_empty_text(_item_field(item, "recommended"), f"题目 {q_id} 的推荐选项 recommended")
        if recommended not in opt_ids:
            raise ValueError(f"题目 {q_id} 的推荐选项 {recommended} 未出现在候选选项中")
        by_id[q_id] = (opt_ids, recommended)
    if answers is not None:
        if not isinstance(answers, Mapping):
            raise InvalidOption(decision, str(answers), options=list(by_id),
                                detail="逐题回答 answers 必须是题号到选项标识的映射")
        for q_id, choice in answers.items():
            if q_id not in by_id:
                offered = "、".join(by_id)
                raise InvalidOption(decision, str(q_id), options=list(by_id),
                                    detail=f"逐题回答包含未知题号 {q_id}，当前题号：{offered}")
            valid_options, _rec = by_id[q_id]
            if not isinstance(choice, str) or choice not in valid_options:
                offered = "、".join(valid_options)
                raise InvalidOption(decision, str(choice), options=valid_options,
                                    detail=f"题目 {q_id} 不包含选项 {choice}，可选的选项：{offered}")
    if option == "recommended" and not answers:
        return {q_id: rec for q_id, (_opts, rec) in by_id.items()}
    provided = answers or {}
    return {q_id: provided.get(q_id, rec) for q_id, (_opts, rec) in by_id.items()}


def blocks_run(decisions: Iterable[DecisionRequest]) -> bool:
    # 有未回答、阻塞整个 run 的决定请求
    return any(decision.status == "open" and decision.blocks == "run" for decision in decisions)


def blocked_by_other_session(decisions: Iterable[DecisionRequest], department: str) -> bool:
    # 别的会话已经写下待恢复的决定请求（模型管理 docs/design/model-management.md「引用无法使用时」：同一事项里同时有几个会话被挡住时，
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
    # 所选的选项或逐题回答 answers 中的题号、选项不是这个请求给出的选项
    def __init__(self, decision: DecisionRequest | None, option: str, *,
                 options: Sequence[str] | None = None, detail: str | None = None) -> None:
        decision_id = "<unknown>" if decision is None else decision.decision_id
        message = detail or f"option {option} is not offered by decision request {decision_id}"
        super().__init__(message)
        self.detail = detail
        if options is not None:
            self.options = list(options)
        elif decision is not None:
            self.options = [item["id"] for item in decision.request["options"]]
        else:
            self.options = []


class NoteRequired(Exception):
    # 所选的选项要求附说明而这次回答没有给说明（工单 #136）：请求不变，什么也不写
    def __init__(self, decision: DecisionRequest, option: str) -> None:
        super().__init__(f"option {option} of decision request {decision.decision_id} requires a note")
        self.decision_id = decision.decision_id
        self.option = option


class AnswerNotAllowed(Exception):
    # 这条回答现在不能收（工单 #1392，项目的组织设计说明「冻结与升级」最后一条）：事项冻结的形态不在发布里，
    # 回答没有写入、决定请求仍在等待；换回带那一份形态的发布以后可以再回答。message 是给用户看的那句话
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

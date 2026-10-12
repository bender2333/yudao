# 事件标签（应用层与接口层设计说明第 5.2 节）：每条事件的一句中文说明，由应用层按事件种类生成。
# 客户端与命令行共用同一份标签，不在各处重复拼写。种类来自 payloads 中登记的全部事件种类，
# 出现未登记的种类时在这里失败（事件种类与载荷类型的联合同源）。模板里的占位只能取载荷里的字段：
# 载荷没有的字段让这里直接失败，说明里不出现空白的占位（工单 #319）。

from __future__ import annotations

from typing import Any

from ..definitions import DEFINITIONS
from ..models import (PHASES, STOP_REASON_LABELS, CatalogEventType, EventType, ProjectEventType,
                     stop_reason_name)


# 阶段的中文名（harness/models.py 的 PHASES 是同一份取值）：事件说明里的阶段按中文写
PHASE_NAMES: dict[str, str] = {
    "CREATED": "等待开始",
    "PRODUCT_SPEC": "产品处理中",
    "ENGINEERING": "工程处理中",
    "DELIVERY": "交付核验中",
    "QUALITY": "质检处理中",
    "REWORK_PRODUCT": "产品返工中",
    "REWORK_ENGINEERING": "工程返工中",
    "DONE": "已完成",
    "PAUSED": "已暂停",
    "FAILED": "执行失败",
}
if set(PHASE_NAMES) != set(PHASES):
    raise KeyError("阶段的中文名必须与控制核心的阶段取值相同：" + "、".join(PHASES))

STOP_REASON_NAMES = STOP_REASON_LABELS
DECISION_KIND_NAMES: dict[str, str] = {
    "model_unavailable": "模型引用无法使用，等待恢复",
    "no_tool_call": "已暂停（模型没有调用工具），等待继续",
    "workspace_unrepresentable": "已暂停（工作区无法表示），等待继续",
    "definitions_changed": "定义版本不同，等待选择",
    "unknown_action": "动作结果未知，等待核实",
    "initial_prd": "接入已有项目的初始需求文档等待确认",
    "instance_upgrade": "实例升级等待批准",
}


def phase_name(phase: Any) -> str:
    # 阶段的中文名；没有登记的取值原样返回，说明里不丢掉这个事实
    return PHASE_NAMES.get(str(phase or ""), str(phase or ""))

def decision_kind_name(kind: Any) -> str:
    # 决定种类的中文名；没有登记的取值原样返回，说明里不丢掉这个事实
    return DECISION_KIND_NAMES.get(str(kind or ""), str(kind or ""))


# 说明里出现的部门标识按中文写，机器标识不直接出现
def department_name(department: Any) -> str:
    value = str(department or "")
    return f"{DEFINITIONS.department_labels.get(value, value)}部门"


# 有两个字段的取值不在停止原因里（暂缓采纳、用户取消决定请求），单独给中文名
OTHER_VALUE_NAMES = {"baseline_changed": "基线已经变化", "user_cancelled": "用户已取消"}


def value_name(value: Any) -> str:
    text = str(value or "")
    return OTHER_VALUE_NAMES.get(text, stop_reason_name(text))


def item_count(items: Any) -> str:
    # 标识清单按数量写，说明里不出现一串机器标识
    return f"{len(items)} 个"


def event_label(event_type: str, payload: dict[str, Any]) -> str:
    # 一条事件的中文说明；载荷中的关键字段填进说明里，字段不在载荷里时直接报错，说明里不出现空白的占位
    template = _LABELS.get(event_type)
    if template is None:
        raise KeyError(f"no event label is defined for {event_type}")
    return template.format_map(_Translated(payload))


class _Translated(dict):
    # 阶段、停止原因与部门取中文名，标识清单取数量，其余字段原样
    _NAMES = {
        "from": phase_name, "to": phase_name, "resumed_at_phase": phase_name,
        "paused_at_phase": phase_name, "stop_reason": stop_reason_name, "reason": value_name,
        "department": department_name, "requester": department_name, "recipient": department_name,
        "guidance_ids": item_count, "candidate_ids": item_count, "running_runs": item_count,
        "stopped_runs": item_count, "restarted_work_items": item_count,
        "kind": decision_kind_name, "from_phase": phase_name, "to_phase": phase_name,
    }

    def __getitem__(self, key: str) -> Any:
        value = dict.__getitem__(self, key)
        translate = self._NAMES.get(key)
        return translate(value) if translate is not None else value


_LABELS: dict[str, str] = {
    EventType.RUN_CREATED: "建立了事项：{task}",
    EventType.USER_INPUT_RECEIVED: "收到用户输入（第 {version} 版）：{text}",
    EventType.PRODUCT_INPUT_ASSIGNED: "把用户输入分配给产品部门（到第 {through_version} 版）",
    EventType.DEPARTMENT_GUIDANCE_RECEIVED: "收到定向指导：{text}",
    EventType.DEPARTMENT_GUIDANCE_APPLIED: "定向指导已被采用：{guidance_ids}",
    EventType.DEPARTMENT_GUIDANCE_RESPONDED: "对定向指导作出回应：{status}",
    EventType.DEPARTMENT_ACTIVATED: "第 {cycle} 次激活部门",
    EventType.DEPARTMENT_INPUT: "把材料交给部门（第 {step_id} 步）",
    EventType.TOOL_CALL_REQUIRED: "部门没有调用工具，主机提示第 {count} 次",
    EventType.ACTIVATION_FINISHED: "结束这次激活：{stop_reason}",
    EventType.CONTEXT_ASSEMBLED: "装配了{department}的上下文（第 {step_id} 步，尝试 {attempt}）",
    EventType.MODEL_REQUEST_SERIALIZED: "记录了发往模型的请求（第 {step_id} 步，尝试 {attempt}）",
    EventType.MODEL_MESSAGE: "模型给出了一条回复（第 {step_id} 步）：{summary}",
    EventType.MODEL_REQUESTED: "向模型发出请求（第 {step_id} 步，尝试 {attempt}，目标 {requested_model}）",
    EventType.MODEL_STREAM_PROGRESS: "模型流式输出进入阶段 {stage}（第 {step_id} 步，尝试 {attempt}）",
    EventType.MODEL_ATTEMPT_FINISHED: "模型调用完成（第 {step_id} 步，尝试 {attempt}，用时 {duration_ms} 毫秒）",
    EventType.MODEL_ATTEMPT_FAILED: "模型调用失败（第 {step_id} 步，尝试 {attempt}）：{reason}",
    EventType.MODEL_RETRY_SCHEDULED: "安排第 {next_attempt} 次尝试，等待 {delay_sec} 秒：{reason}",
    EventType.COMPACTION_RECORDED: "记录了一次上下文压缩（第 {step_id} 步）",
    EventType.MODEL_REASONING: "记录了模型的思考内容（第 {step_id} 步）",
    EventType.TOOL_CALLED: "执行了工具 {name}：{ok}",
    EventType.TOOL_STARTED: "开始执行工具 {name}",
    EventType.ACTION_VERIFIED: "核实了动作 {name}：{resolution}",
    EventType.TOOL_SKIPPED: "跳过了工具 {name}：{error}",
    EventType.PROPOSAL_SUBMITTED: "提交了提案（{kind}）",
    EventType.PROPOSAL_REJECTED: "提案被拒绝（{kind}）",
    EventType.SPEC_ACCEPTED: "采纳了产品规格（第 {revision} 版）",
    EventType.SPEC_SUPERSEDED: "产品规格被新的版本取代（第 {revision} 版）",
    EventType.CONTRACT_ACCEPTED: "采纳了有效合同（第 {revision} 版）",
    EventType.PLAN_ACCEPTED: "采纳了工程方案（第 {revision} 版）",
    EventType.COLLABORATION_REQUESTED: "{requester}向{recipient}提出请求：{question}",
    EventType.COLLABORATION_RESPONDED: "{recipient}回应了协作请求：{status}",
    EventType.COLLABORATION_CLOSED: "关闭了协作请求：{status}",
    EventType.PRODUCT_DECISION_ACCEPTED: "采纳了产品决策（{kind}）",
    EventType.DELIVERY_ACCEPTED: "采纳了交付（第 {revision} 版）：{summary}",
    EventType.QA_SUBMITTED: "质检提交了结论：{verdict}",
    EventType.STRUCTURE_ACCEPTED: "采纳了现有结构说明（第 {revision} 版）",
    EventType.BASELINE_REVIEW_ACCEPTED: "质检提交了基线核验：{verdict}",
    EventType.LESSON_CANDIDATE_RECORDED: "记下了一条经验候选：{suggestion}",
    EventType.TRANSITION: "运行状态从 {from} 变为 {to}",
    EventType.RUN_DONE: "运行结束：{stop_reason}",
    EventType.RUN_PAUSED: "运行暂停，等待用户处理：{stop_reason}",
    EventType.RUN_CONTINUED: "运行从暂停位置继续：{resumed_at_phase}",
    EventType.RUN_RESUMED: "中断的运行自动继续（执行权第 {acquired_epoch} 号）",
    EventType.RUN_FAILED: "运行失败：{stop_reason}",
    EventType.DECISION_REQUESTED: "提出等待回答的决定（{kind}）：{description}",
    EventType.DECISION_ANSWERED: "回答了一个决定：{option}",
    EventType.DECISION_WITHDRAWN: "撤回了一个决定：{reason}",
    ProjectEventType.PROJECT_REGISTERED: "建立了项目：{name}",
    ProjectEventType.PROJECT_RENAMED: "项目改名为：{name}",
    ProjectEventType.PROJECT_GOAL_CHANGED: "修改了项目的长期目标",
    ProjectEventType.PROJECT_PINNED: "把项目固定到列表顶部",
    ProjectEventType.PROJECT_ARCHIVED: "归档了项目",
    ProjectEventType.PROJECT_RESTORED: "恢复了项目",
    ProjectEventType.WORK_ITEM_CREATED: "在项目中建立了事项：{title}",
    ProjectEventType.WORK_ITEM_START_FAILED: "事项未能开始：{error}",
    ProjectEventType.DELIVERABLE_ADOPTED: "采纳了交付物：{summary}",
    ProjectEventType.ADOPTION_HELD: "暂缓采纳：{reason}",
    ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED: "配置了{department}的设置（第 {version} 版）",
    ProjectEventType.COMMAND_CONFIGURED: "配置了登记命令 {name}",
    ProjectEventType.MATERIAL_RECORDED: "登记了材料：{text}",
    ProjectEventType.SOURCE_DIRECTORY_CONFIGURED: "登记了源目录：{path}",
    ProjectEventType.INITIAL_PRD_PROPOSED: "第 {round} 轮建档的初始 PRD 等待确认",
    ProjectEventType.PROJECT_DECISION_REQUESTED: "请用户决定：{description}",
    ProjectEventType.PROJECT_DECISION_ANSWERED: "回答了决定请求：{option}",
    ProjectEventType.PROJECT_DECISION_WITHDRAWN: "撤销了决定请求：{reason}",
    ProjectEventType.ONBOARDING_REVISION_STARTED: "开始第 {round} 轮建档",
    ProjectEventType.BASELINE_ADOPTED: "采纳了建档基线：{summary}",
    CatalogEventType.CATALOG_REVISED: "模型目录修订到第 {revision} 号（{operation}）",
    CatalogEventType.CATALOG_CANDIDATES_COLLECTED: "收集了模型候选：{candidate_ids} 个",
    CatalogEventType.CATALOG_TEST_FINISHED: "模型测试结束：{kind}，结果 {ok}",
    CatalogEventType.CREDENTIAL_CHANGED: "凭据发生变化：{action}",
    CatalogEventType.RUNTIME_DRAIN_STARTED: "开始排空运行（目录第 {version} 号）：还有 {running_runs} 个运行未结束",
    CatalogEventType.RUNTIME_FORCE_UPGRADE_REQUESTED: "请求强制升级（目录第 {version} 号）：停了 {stopped_runs} 个运行",
    CatalogEventType.HOME_SEEN: "记下用户查看的位置：{position}",
    CatalogEventType.PARAMETER_SET: "把参数 {name} 从 {old_value} 改为 {new_value}：{reason}",
}

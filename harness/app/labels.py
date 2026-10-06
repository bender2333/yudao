# 事件标签（应用层与接口层设计说明第 5.2 节）：每条事件的一句中文说明，由应用层按事件种类生成。
# 客户端与命令行共用同一份标签，不在各处重复拼写。种类来自 payloads 中登记的全部事件种类，
# 出现未登记的种类时在这里失败（事件种类与载荷类型的联合同源）。

from __future__ import annotations

from typing import Any

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


def phase_name(phase: Any) -> str:
    # 阶段的中文名；没有登记的取值原样返回，说明里不丢掉这个事实
    return PHASE_NAMES.get(str(phase or ""), str(phase or ""))


def event_label(event_type: str, payload: dict[str, Any]) -> str:
    # 一条事件的中文说明；载荷中的关键字段填进说明里，缺失时用空串
    template = _LABELS.get(event_type)
    if template is None:
        raise KeyError(f"no event label is defined for {event_type}")
    # 阶段与停止原因都取中文名，说明里不出现机器标识
    return template.format_map(_Translated(payload))


class _Translated(dict):
    # 载荷里的阶段与停止原因取中文名，其余字段原样；载荷没有的字段填入空串，说明仍然生成
    _NAMES = {
        "from_phase": phase_name, "to_phase": phase_name, "stop_reason": stop_reason_name,
        "resumed_at_phase": phase_name, "paused_at_phase": phase_name,
    }

    def __missing__(self, key: str) -> str:
        return ""

    def __getitem__(self, key: str) -> Any:
        translate = self._NAMES.get(key)
        return translate(dict.__getitem__(self, key)) if translate is not None else dict.__getitem__(self, key)

_LABELS: dict[str, str] = {
    EventType.RUN_CREATED: "建立了事项：{task}",
    EventType.USER_INPUT_RECEIVED: "收到用户输入（第 {input_version} 版）：{content}",
    EventType.PRODUCT_INPUT_ASSIGNED: "把用户输入分配给产品部门（第 {input_version} 版）",
    EventType.DEPARTMENT_GUIDANCE_RECEIVED: "收到定向指导：{text}",
    EventType.DEPARTMENT_GUIDANCE_APPLIED: "定向指导已被采用：{guidance_ids}",
    EventType.DEPARTMENT_GUIDANCE_RESPONDED: "对定向指导作出回应：{status}",
    EventType.DEPARTMENT_ACTIVATED: "激活{department}部门（第 {activation} 次激活）",
    EventType.DEPARTMENT_INPUT: "把{source}的材料交给{department}部门",
    EventType.TOOL_CALL_REQUIRED: "{department}部门没有调用工具，主机提示第 {count} 次",
    EventType.ACTIVATION_FINISHED: "结束这次激活：{outcome}",
    EventType.CONTEXT_ASSEMBLED: "装配了{department}部门的上下文（第 {step_id} 步，尝试 {attempt}）",
    EventType.MODEL_REQUEST_SERIALIZED: "记录了发往模型的请求（第 {step_id} 步，尝试 {attempt}）",
    EventType.MODEL_MESSAGE: "模型给出了一条回复（第 {step_id} 步）：{summary}",
    EventType.MODEL_REQUESTED: "向模型发出请求（第 {step_id} 步，尝试 {attempt}，目标 {requested_model}）",
    EventType.MODEL_STREAM_PROGRESS: "模型流式输出进入阶段 {stage}（第 {step_id} 步，尝试 {attempt}）",
    EventType.MODEL_ATTEMPT_FINISHED: "模型调用完成（第 {step_id} 步，尝试 {attempt}，用时 {duration_ms} 毫秒）",
    EventType.MODEL_ATTEMPT_FAILED: "模型调用失败（第 {step_id} 步，尝试 {attempt}）：{error}",
    EventType.MODEL_RETRY_SCHEDULED: "安排第 {next_attempt} 次尝试，等待 {delay_sec} 秒：{error}",
    EventType.COMPACTION_RECORDED: "记录了一次上下文压缩（第 {step_id} 步）",
    EventType.TOOL_CALLED: "执行了工具 {name}：{ok}",
    EventType.TOOL_STARTED: "开始执行工具 {name}",
    EventType.TOOL_SKIPPED: "跳过了工具 {name}：{reason}",
    EventType.PROPOSAL_SUBMITTED: "提交了提案（{kind}）",
    EventType.PROPOSAL_REJECTED: "提案被拒绝（{kind}）：{reason}",
    EventType.SPEC_ACCEPTED: "采纳了产品规格（第 {version} 版）",
    EventType.SPEC_SUPERSEDED: "产品规格被新的版本取代（第 {version} 版）",
    EventType.CONTRACT_ACCEPTED: "采纳了有效合同（第 {version} 版）",
    EventType.PLAN_ACCEPTED: "采纳了工程方案（第 {version} 版）",
    EventType.COLLABORATION_REQUESTED: "{from_department}部门向{to_department}部门提出请求：{question}",
    EventType.COLLABORATION_RESPONDED: "{department}部门回应了协作请求：{status}",
    EventType.COLLABORATION_CLOSED: "关闭了协作请求：{reason}",
    EventType.PRODUCT_DECISION_ACCEPTED: "采纳了产品决策（{kind}）",
    EventType.DELIVERY_ACCEPTED: "采纳了交付（第 {version} 版）",
    EventType.QA_SUBMITTED: "质检提交了结论：{verdict}",
    EventType.STRUCTURE_ACCEPTED: "采纳了现有结构说明（第 {revision} 版）",
    EventType.BASELINE_REVIEW_ACCEPTED: "质检提交了基线核验：{verdict}",
    EventType.LESSON_CANDIDATE_RECORDED: "记下了一条经验候选：{summary}",
    EventType.TRANSITION: "运行状态从 {from_phase} 变为 {to_phase}",
    EventType.RUN_DONE: "运行结束：{stop_reason}",
    EventType.RUN_PAUSED: "运行暂停，等待用户处理：{stop_reason}",
    EventType.RUN_CONTINUED: "运行从暂停位置继续：{resumed_at_phase}",
    EventType.RUN_FAILED: "运行失败：{stop_reason}",
    EventType.DECISION_REQUESTED: "提出等待回答的决定（{kind}）：{question}",
    EventType.DECISION_ANSWERED: "回答了一个决定（{kind}）",
    EventType.DECISION_WITHDRAWN: "撤回了一个决定（{kind}）",
    ProjectEventType.PROJECT_REGISTERED: "建立了项目：{name}",
    ProjectEventType.PROJECT_RENAMED: "项目改名为：{name}",
    ProjectEventType.PROJECT_GOAL_CHANGED: "修改了项目的长期目标",
    ProjectEventType.PROJECT_PINNED: "把项目固定到列表顶部",
    ProjectEventType.PROJECT_ARCHIVED: "归档了项目",
    ProjectEventType.PROJECT_RESTORED: "恢复了项目",
    ProjectEventType.WORK_ITEM_CREATED: "在项目中建立了事项：{title}",
    ProjectEventType.WORK_ITEM_START_FAILED: "事项未能开始：{reason}",
    ProjectEventType.DELIVERABLE_ADOPTED: "采纳了交付物（第 {version} 版）",
    ProjectEventType.ADOPTION_HELD: "暂缓采纳：{reason}",
    ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED: "配置了{department}部门的设置（第 {version} 版）",
    ProjectEventType.COMMAND_CONFIGURED: "配置了登记命令 {name}",
    ProjectEventType.MATERIAL_RECORDED: "登记了材料：{summary}",
    ProjectEventType.SOURCE_DIRECTORY_CONFIGURED: "登记了源目录：{path}",
    CatalogEventType.CATALOG_REVISED: "模型目录修订到第 {revision} 号（{operation}）",
    CatalogEventType.CATALOG_CANDIDATES_COLLECTED: "收集了模型候选：{count} 个",
    CatalogEventType.CATALOG_TEST_FINISHED: "模型测试结束：{status}",
    CatalogEventType.CREDENTIAL_CHANGED: "凭据发生变化：{operation}",
    CatalogEventType.HOME_SEEN: "记下用户查看的位置：{position}",
}

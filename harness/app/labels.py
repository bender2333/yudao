# 事件标签（应用层与接口层设计说明第 5.2 节）：每条事件的一句中文说明，由应用层按事件种类生成。
# 客户端与命令行共用同一份标签，不在各处重复拼写。种类来自 payloads 中登记的全部事件种类，
# 出现未登记的种类时在这里失败（事件种类与载荷类型的联合同源）。模板里的占位只能取载荷里的字段：
# 载荷没有的字段让这里直接失败，说明里不出现空白的占位（工单 #319）。

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..definitions import DEFINITIONS
from ..models import (RUN_STATUSES, CatalogEventType, EventType, ProjectEventType, stop_reason_name)


# run 状态的中文名（harness/models.py 的 RUN_STATUSES 是同一份取值）：事件说明里的状态按中文写
STATUS_NAMES: dict[str, str] = {
    "running": "进行中",
    "done": "已完成",
    "paused": "已暂停",
    "failed": "执行失败",
}
if set(STATUS_NAMES) != set(RUN_STATUSES):
    raise KeyError("状态的中文名必须与控制核心的状态取值相同：" + "、".join(RUN_STATUSES))

# 停止原因的中文名来自定义（stop_reasons.json 与路由自己的结束原因，工单 #861）
STOP_REASON_NAMES = {reason: definition.label for reason, definition in DEFINITIONS.stop_reasons.items()}
DECISION_KIND_NAMES: dict[str, str] = {
    "model_unavailable": "模型引用无法使用，等待恢复",
    "no_tool_call": "已暂停（模型没有调用工具），等待继续",
    "workspace_unrepresentable": "已暂停（工作区无法表示），等待继续",
    "definitions_changed": "定义版本不同，等待选择",
    "initial_prd": "接入已有项目的初始需求文档等待确认",
    "instance_upgrade": "实例升级等待批准",
    "kernel_modification": "交付改动了内核清单里的路径，等待批准",
    "qa_cannot_verify": "质检无法核验，等待回答",
}


def status_name(status: Any) -> str:
    # run 状态的中文名；没有登记的取值原样返回，说明里不丢掉这个事实
    return STATUS_NAMES.get(str(status or ""), str(status or ""))

def decision_kind_name(kind: Any) -> str:
    # 决定种类的中文名；没有登记的取值原样返回，说明里不丢掉这个事实
    return DECISION_KIND_NAMES.get(str(kind or ""), str(kind or ""))


# 收到指导的那一轮工作怎么结束的（部门指导设计说明第 3 节，工单 #1039）：提交被接纳，或者用文字回答
GUIDANCE_OUTCOME_NAMES: dict[str, str] = {
    "proposal_accepted": "提交被接纳",
    "text_reply": "用文字回答",
}


def guidance_outcome_name(outcome: Any) -> str:
    # 指导的回答方式的中文名；没有登记的取值原样返回，说明里不丢掉这个事实
    return GUIDANCE_OUTCOME_NAMES.get(str(outcome or ""), str(outcome or ""))


# 说明里出现的部门标识按中文写，机器标识不直接出现
def department_name(department: Any) -> str:
    value = str(department or "")
    return f"{DEFINITIONS.department_labels.get(value, value)}部门"


# 修改人：user:alice 这样的标识写成「用户 alice」，机器标识不直接出现
def modifier_name(value: Any) -> str:
    text = str(value or "")
    if text.startswith("user:"):
        return "用户 " + text[len("user:"):]
    return text


# 写回停止原因的中文名（工单 #347）：取值不在停止原因里，单独给中文名
WRITEBACK_REASON_NAMES = {
    "conflict": "合并出现冲突",
    "verification_failed": "最终树核验没有通过",
    "target_changed": "目标分支已经推进",
    "unrepresentable_path": "路径无法表示",
    "missing_source_reference": "缺少事项起点依据",
}
# 说明里出现的取值按中文写，机器标识不直接出现（暂缓采纳、用户取消决定请求、写回停止原因）
# user_cancelled 已经是停止原因，中文名在 models.py 的停止原因表里（工单 #707）
OTHER_VALUE_NAMES = {"baseline_changed": "基线已经变化",
                     "superseded_by_hand_back": "已交还模型",
                     # 成果失效的原因（骨架事件，S1b，工单 #858）
                     "workspace_changed": "工作区被改动",
                     "product_spec_changed": "产品规格换了版本",
                     "effective_contract_changed": "有效合同换了版本",
                     "replaced": "被新的交付取代",
                     "baseline_rework_product": "基线核验退回产品",
                     "qa_rework_engineering": "质检退回工程",
                     **WRITEBACK_REASON_NAMES}

# 成果失效事件里的成果种类：说明里写中文名（骨架事件，S1b）
ARTIFACT_KIND_NAMES = {"delivery_spec": "交付", "product_spec": "产品规格", "contract": "有效合同",
                       "qa_review": "质检结论", "structure": "现有结构说明",
                       "baseline_review": "基线核验", "product_decision": "产品决策"}


def artifact_kind_name(value: Any) -> str:
    # 成果种类：登记过的写中文名，没有登记的照原样写（第二种路由可以带自己的成果种类）
    text = str(value or "")
    return ARTIFACT_KIND_NAMES.get(text, text)


def value_name(value: Any) -> str:
    text = str(value or "")
    return OTHER_VALUE_NAMES.get(text, stop_reason_name(text))


def item_count(items: Any) -> str:
    # 标识清单按数量写，说明里不出现一串机器标识
    return f"{len(items)} 个"


# 一条没有登记说明的事件的通用说明（工单 #664）：一条事件不能把整条事件流断掉
GENERIC_EVENT_LABEL = "发生了一条事件"


def event_label(event_type: str, payload: dict[str, Any]) -> str:
    # 一条事件的中文说明；载荷中的关键字段填进说明里。
    # 没有登记说明的种类、或者载荷里缺了说明要的字段时，退回一句通用说明：
    # 事件流播到这一条就断掉，客户端会每秒重连一次，永远过不去（工单 #664）。
    # 标签表与事件种类清单的一致性由 test_event_classification.py 核对，
    # 说明里用的字段都在载荷里也由那一条核对。
    template = _LABELS.get(event_type)
    if template is None:
        return GENERIC_EVENT_LABEL
    try:
        return template.format_map(_Translated(payload))
    except (KeyError, IndexError, ValueError, TypeError):
        # TypeError：载荷里被当作清单翻译的字段其实是数字（例如开始排空事件的 running_runs），
        # 一种说明写不成不能把整条事件流断掉（工单 #1188 的端到端撞到）
        return GENERIC_EVENT_LABEL


class _Translated(dict):
    # 停止原因与部门取中文名，标识清单取数量，其余字段原样。
    # 数字与清单同名时以载荷里的类型为准：整数的 running_runs 不按清单翻译，标签里直接写数字
    _NAMES = {
        "stop_reason": stop_reason_name, "reason": value_name,
        "department": department_name, "requester": department_name, "recipient": department_name,
        "guidance_ids": item_count, "candidate_ids": item_count,
        "stopped_runs": item_count, "restarted_work_items": item_count,
        "kind": decision_kind_name,
        "artifact_kind": artifact_kind_name,
        "outcome": guidance_outcome_name,
        "modified_by": modifier_name,
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
    EventType.DEPARTMENT_GUIDANCE_RESPONDED: "这一轮结束，回答了定向指导：{outcome}",
    EventType.DEPARTMENT_ACTIVATED: "第 {cycle} 次激活部门",
    EventType.DEPARTMENT_INPUT: "把材料交给部门（第 {step_id} 步）",
    EventType.TOOL_CALL_REQUIRED: "部门没有调用工具，主机提示第 {count} 次",
    EventType.ACTIVATION_FINISHED: "结束这次激活：{stop_reason}",
    EventType.CONTEXT_ASSEMBLED: "装配了{department}的上下文（第 {step_id} 步，尝试 {attempt}）",
    EventType.MODEL_REQUEST_SERIALIZED: "记录了发往模型的请求（第 {step_id} 步，尝试 {attempt}）",
    EventType.MODEL_MESSAGE: "模型给出了一条回复（第 {step_id} 步）",
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
    EventType.ASK_STARTED: "{requester}向{recipient}发问：{question}",
    EventType.ASK_ANSWERED: "回答了询问",
    EventType.INDEPENDENT_JUDGEMENT_COMMITTED: "核验角色提交了独立判断（第 {criteria_count} 条，不含解释）",
    EventType.PRODUCT_DECISION_ACCEPTED: "采纳了产品决策（{kind}）",
    EventType.ARTIFACT_INVALIDATED: "成果失效：{artifact_kind}第 {artifact_version} 版（{reason}）",
    EventType.DELIVERY_ACCEPTED: "采纳了交付（第 {revision} 版）：{summary}",
    EventType.QA_SUBMITTED: "质检提交了结论：{verdict}",
    EventType.QA_TESTS_SAVED: "保存了质检的测试材料（第 {version} 版）",
    EventType.STRUCTURE_ACCEPTED: "采纳了现有结构说明（第 {revision} 版）",
    EventType.BASELINE_REVIEW_ACCEPTED: "质检提交了基线核验：{verdict}",
    EventType.ARTIFACT_ACCEPTED: "采纳了成果：{artifact_kind}（第 {artifact_version} 版）",
    EventType.LESSON_CANDIDATE_RECORDED: "记下了一条经验候选：{suggestion}",
    EventType.RUN_DONE: "运行结束：{stop_reason}",
    EventType.RUN_PAUSED: "运行暂停，等待用户处理：{stop_reason}",
    EventType.RUN_CONTINUED: "运行从暂停位置继续",
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
    ProjectEventType.MATERIAL_RECORDED: "登记了材料：{text}",
    ProjectEventType.SOURCE_DIRECTORY_CONFIGURED: "登记了源目录：{path}",
    ProjectEventType.INITIAL_PRD_PROPOSED: "第 {round} 轮建档的初始 PRD 等待确认",
    ProjectEventType.PROJECT_DECISION_REQUESTED: "请用户决定：{description}",
    ProjectEventType.PROJECT_DECISION_ANSWERED: "回答了决定请求：{option}",
    ProjectEventType.PROJECT_DECISION_WITHDRAWN: "撤销了决定请求：{reason}",
    ProjectEventType.ONBOARDING_REVISION_STARTED: "开始第 {round} 轮建档",
    ProjectEventType.BASELINE_ADOPTED: "采纳了建档基线：{summary}",
    ProjectEventType.PARAMETER_SET: "把项目参数 {name} 从 {old_value} 改为 {new_value}：{reason}（{modified_by} 修改）",
    ProjectEventType.WRITEBACK_COMPLETED: "写回了采纳成果：分支 {branch}，最终树 {final_tree_digest}",
    ProjectEventType.WRITEBACK_STOPPED: "写回停止：{reason}",
    ProjectEventType.WRITEBACK_NOT_NEEDED: "无需写回：本事项的变更已经在目标分支上",
    ProjectEventType.WRITEBACK_HELD: "写回等待前项合入：{previous_adoption_id}",
    ProjectEventType.WRITEBACK_VERIFIED: "核实了已发生的写回动作：分支 {branch}",
    ProjectEventType.MCP_SERVERS_CONFIGURED: "保存了 MCP 服务器设置（第 {version} 版）",
    ProjectEventType.TOOL_SERVER_PROBE_FINISHED: "探测 MCP 服务器 {server_name}：{status}",
    CatalogEventType.CATALOG_REVISED: "模型目录修订到第 {revision} 号（{operation}）",
    CatalogEventType.CATALOG_CANDIDATES_COLLECTED: "收集了模型候选：{candidate_ids} 个",
    CatalogEventType.CATALOG_TEST_FINISHED: "模型测试结束：{kind}，结果 {ok}",
    CatalogEventType.CREDENTIAL_CHANGED: "凭据发生变化：{action}",
    CatalogEventType.RUNTIME_DRAIN_STARTED: "开始排空运行（目录第 {version} 号）：还有 {running_runs} 个运行未结束",
    CatalogEventType.RUNTIME_DRAIN_FINISHED: "排空结束（目录第 {version} 号）：这个实例重新开始新事项",
    CatalogEventType.RUNTIME_FORCE_UPGRADE_REQUESTED: "请求强制升级（目录第 {version} 号）：停了 {stopped_runs} 个运行",
    CatalogEventType.HOME_SEEN: "记下用户查看的位置：{position}",
    CatalogEventType.PARAMETER_SET: "把参数 {name} 从 {old_value} 改为 {new_value}：{reason}",
    CatalogEventType.INSTANCE_UPGRADE_REQUESTED: "请用户决定是否升级实例（{kind}）：{description}",
    CatalogEventType.INSTANCE_UPGRADE_ANSWERED: "回答了实例升级的决定：{option}",
    CatalogEventType.INSTANCE_UPGRADE_WITHDRAWN: "撤销了实例升级的决定：{reason}",
}


# ---------------------------------------------------------------------------
# 请求体不符合合同时给页面的中文说明（工单 #740）
#
# 服务端按 422 拒绝一条命令时，响应体里有两样东西：pydantic 的字段错误明细（机器看）
# 与一句中文说明（页面直接显示）。这句说明写明是哪个字段、要求是什么：
# 字段写页面上的中文名，字段路径与错误类型这些机器标识不写进去。

# 命令请求字段的中文名：与页面上表单里那个名字一致
COMMAND_FIELD_NAMES: dict[str, str] = {
    "command_id": "命令身份",
    "project_id": "项目",
    "work_item_id": "事项",
    "department": "部门",
    "name": "名称",
    "goal": "长期目标",
    "title": "标题",
    "text": "内容",
    "path": "目录路径",
    "source_name": "源目录名称",
    "source_path": "源目录路径",
    "initial_directory": "起始文件夹",
    "department_prompt": "部门 Prompt",
    "provider_id": "服务提供方",
    "model_id": "模型",
    "requested_tier": "推理档位",
    "remote": "远程仓库",
    "target_branch": "目标分支",
    "check_commands": "检查命令",
    "credential_ref": "凭据引用",
    "ref": "凭据引用",
    "secret": "凭据",
    "position": "位置",
    "reason": "原因",
    "modified_by": "修改人",
    "decision_id": "决定请求",
    "option": "选项",
    "note": "说明",
    "models_url": "模型清单地址",
    "value": "取值",
}

# 校验错误的中文说法：键是 pydantic 的错误类型，named 是写明字段时的说法，
# unnamed 是没有登记字段名时的说法。string_too_short_min 是长度下限大于 1 的情形。
VALIDATION_REQUIREMENTS: dict[str, dict[str, str]] = {
    "string_too_short": {"named": "不能为空", "unnamed": "有一项内容不能为空"},
    "string_too_short_min": {"named": "太短了", "unnamed": "有一项内容太短了"},
    "string_too_long": {"named": "太长了", "unnamed": "有一项内容太长了"},
    "missing": {"named": "必须填写", "unnamed": "有一项内容必须填写"},
    "string_pattern_mismatch": {"named": "格式不对", "unnamed": "有一项内容格式不对"},
    "literal_error": {"named": "不是允许的取值", "unnamed": "有一项内容不是允许的取值"},
    "int_parsing": {"named": "必须是数字", "unnamed": "有一项内容必须是数字"},
    "float_parsing": {"named": "必须是数字", "unnamed": "有一项内容必须是数字"},
    # 合同里的空白检查（contracts.py 的 _not_blank）拒绝只有空白的文字
    "value_error": {"named": "不能只有空白字符", "unnamed": "有一项内容不能只有空白字符"},
    # 多余的字段不写字段名：那是服务端不认识的字段，页面上也没有对应的输入框
    "extra_forbidden": {"named": "不是这个命令要的填写项", "unnamed": "多填了一项服务端不认识的填写内容"},
}


def _error_field(location: Any) -> str:
    """字段错误明细里的字段名：位置的最后一段（body、字段、嵌套字段）。"""
    if not isinstance(location, Sequence) or isinstance(location, str):
        return ""
    parts = [str(part) for part in location if isinstance(part, (str, int))]
    return parts[-1] if parts else ""


def _error_kind(error: Mapping[str, Any]) -> str:
    """字段错误的种类：pydantic 的错误类型；长度下限大于 1 的另算一种。"""
    kind = str(error.get("type") or "")
    if kind == "string_too_short":
        context = error.get("ctx")
        minimum = context.get("min_length") if isinstance(context, Mapping) else None
        if isinstance(minimum, int) and minimum > 1:
            return "string_too_short_min"
    return kind


def validation_text(errors: Sequence[Mapping[str, Any]]) -> str:
    """请求体不符合合同时的一句话：写明这次请求被拒绝、是哪个字段、要求是什么。

    服务端给的每一条字段错误都写到这一句里，不丢一条。没有登记的字段名不写出来，
    只写要求（页面上不出现字段路径这样的机器标识）。
    """
    clauses: list[str] = []
    for error in errors:
        kind = _error_kind(error)
        requirement = VALIDATION_REQUIREMENTS.get(kind)
        if requirement is None:
            clauses.append("有一项填写的内容不符合要求")
            continue
        label = COMMAND_FIELD_NAMES.get(_error_field(error.get("loc")))
        if label is None or kind == "extra_forbidden":
            clauses.append(requirement["unnamed"])
        else:
            clauses.append(f"「{label}」{requirement['named']}")
    if not clauses:
        return "这次请求被拒绝：提交的内容没有通过服务端的检查，请修改以后再提交。"
    unique = list(dict.fromkeys(clauses))
    return f"这次请求被拒绝：{'；'.join(unique)}，请修改以后再提交。"

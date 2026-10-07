# 流的分类、run 事件版本与排空状态（ADR-0019，工单 #126）。
# 事件日志只有一份；按流的种类分为项目流与 run 流。项目流（与机器流）记录项目的长期事实，跨 Yudao 版本保存，
# 新版本只能增加种类或字段、已有字段的含义不变；run 流跟随应用版本，每个 Yudao 版本声明自己的 run 事件版本，
# 版本不同时先排空再升级。
# 分类的注册处在这里：每种事件以字面值声明属于哪一种流。models.py 的事件种类与这里的清单由测试互相比对，
# 新增的种类没有登记在清单中时测试失败——清单不从 models.py 派生，派生会把新种类自动归为一类，声明就失去作用。

from __future__ import annotations

from dataclasses import dataclass

from .event_store import EventStore
from .models import TERMINAL_PHASES

# 当前的 run 事件版本：run 事件的语义改变时提高这个版本。每个 run 在创建时把它记进 run_created 事件。
# 版本 2：删除事件种类 department_prompt_updated 与 run_created 的 department_prompts 字段（#89）
RUN_EVENT_VERSION = 2

# run 流：事项的进行过程（每次 run 的交接、询问、尝试与动作）
RUN_EVENT_TYPES = frozenset({
    "run_created",
    "user_input_received",
    "product_input_assigned",
    "department_guidance_received",
    "department_guidance_applied",
    "department_guidance_responded",
    "department_activated",
    "department_input",
    "tool_call_required",
    "activation_finished",
    "context_assembled",
    "model_request_serialized",
    "model_reasoning",
    "model_message",
    "model_requested",
    "model_stream_progress",
    "model_attempt_finished",
    "model_attempt_failed",
    "model_retry_scheduled",
    "compaction_recorded",
    "tool_called",
    "tool_started",
    "tool_skipped",
    "action_verified",
    "proposal_submitted",
    "proposal_rejected",
    "spec_accepted",
    "spec_superseded",
    "contract_accepted",
    "plan_accepted",
    "collaboration_requested",
    "collaboration_responded",
    "collaboration_closed",
    "product_decision_accepted",
    "delivery_accepted",
    "qa_submitted",
    "lesson_candidate_recorded",
    "structure_accepted",
    "baseline_review_accepted",
    "transition",
    "run_resumed",
    "run_continued",
    "run_done",
    "run_paused",
    "run_failed",
    "decision_requested",
    "decision_answered",
    "decision_withdrawn",
})

# 项目流：项目的长期事实（项目、当前 PRD 与采纳成果、事项的存在、队列位置与最终结果、项目部门设置、登记命令）
PROJECT_EVENT_TYPES = frozenset({
    "project_registered",
    "project_renamed",
    "project_goal_changed",
    "project_pinned",
    "project_archived",
    "project_restored",
    "work_item_created",
    "work_item_start_failed",
    "deliverable_adopted",
    "adoption_held",
    "department_prompt_configured",
    "command_configured",
    "material_recorded",
    "source_directory_configured",
    "initial_prd_proposed",
    "project_decision_requested",
    "project_decision_answered",
    "project_decision_withdrawn",
    "onboarding_revision_started",
    "baseline_adopted",
})

# 目录流：模型目录与凭据的修订记录，以及排空与强制升级、用户查看过的位置。
# 与项目流一样是跨版本保存的长期事实
CATALOG_EVENT_TYPES = frozenset({
    "catalog_revised",
    "catalog_candidates_collected",
    "catalog_test_finished",
    "credential_changed",
    "runtime_drain_started",
    "runtime_force_upgrade_requested",
    "home_seen",
    "parameter_set",
})

# 全部声明过分类的事件种类
DECLARED_EVENT_TYPES = RUN_EVENT_TYPES | PROJECT_EVENT_TYPES | CATALOG_EVENT_TYPES

# 因升级停止的停止原因（定义在 definitions/stop_reasons.json）：排空期间由用户发起的强制升级，以及启动时
# run 事件版本与当前不同的未结束 run（#322），都以这个原因停止，对应的事项用项目的起点重新开始
STOP_REASON_UPGRADE = "run_event_version_changed"

# 事项在队列中的优先级：因升级重新开始的事项排在队列最前面（顺序由 3.4A 的 #19 实现）
PRIORITY_UPGRADE_RESTART = "upgrade_restart"
PRIORITY_USER = "user"

# 排空状态的三种取值：未排空、排空中（还有 run 在进行）、已排空可以升级
DRAIN_IDLE = "idle"
DRAIN_DRAINING = "draining"
DRAIN_READY = "ready"

# 排空与强制升级的事件种类：记在目录流中，是控制主机这一份部署的长期事实（ADR-0019）
DRAIN_STARTED = "runtime_drain_started"
FORCE_UPGRADE_REQUESTED = "runtime_force_upgrade_requested"

@dataclass(frozen=True)
class StartupRuns:
    # 启动时按 run 事件版本分类的 run：
    # same_version 是版本与当前相同且未结束的 run，交给 #16 自动继续；
    # other_version 是未结束且版本不同（含旧事件没有记录版本）的 run，交给启动序列按强制升级处理
    # （#322），强制升级（排空期间由用户发起）把两类未结束 run 都停止；
    # finished 是已结束的 run
    same_version: tuple[str, ...]
    other_version: tuple[str, ...]
    finished: tuple[str, ...]

def classify_startup_runs(store: EventStore) -> StartupRuns:
    # 按每个 run 的 run_created 事件记录的版本与当前的 run 事件版本分类；未结束指 run 还没有写入终态事件。
    # run 流的保存投影由写入口在调用之前补建（rebuild_missing）
    from .projection import RunNotFoundError, project_run

    same, other, finished = [], [], []
    for run_id in store.list_run_ids():
        try:
            run = project_run(store, run_id)
        except RunNotFoundError:
            continue
        if run.phase in TERMINAL_PHASES:
            finished.append(run_id)
        elif run.run_event_version == RUN_EVENT_VERSION:
            same.append(run_id)
        else:
            other.append(run_id)
    return StartupRuns(tuple(same), tuple(other), tuple(finished))

@dataclass(frozen=True)
class DrainState:
    # 排空状态：state 是未排空、排空中或已排空可以升级；version 是状态的版本，命令的基准版本与它记录在一起；
    # running_runs 是还没有结束的 run 数，queued_work_items 是排空期间新建、还没有开始的事项数
    state: str = DRAIN_IDLE
    version: int = 0
    running_runs: int = 0
    queued_work_items: int = 0

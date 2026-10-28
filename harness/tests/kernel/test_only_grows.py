# 「只增」的三份清单（S6a，工单 #829；骨架与应用设计说明第 3.1、3.2、7 节；总图第二节第二环「契约」）：
# 骨架事件的种类、事件信封的字段、封闭的停止原因清单都只增——新增可以，删除与改名不行。
#
# 快照是放出这一版时的清单。删掉其中一项时这几项测试失败，信息写明是哪一种事件、哪一个字段、
# 哪一个停止原因：已经写进日志的事件不会因为一个发布而被重新解释（第 7 节），停止原因清单外的原因
# 写入口也写不进去（基础规则 3）。新加一项以后同步更新快照；新加不需要提版本，削掉已有的一项不行。
#
# 与 kernel/test_skeleton_events.py 的分工：那一个核对登记表与设计说明第 7 节的表逐项相同（增删都报警），
# 这一个守住「只增」本身——删除与改名报错，新增在这里是允许的。与 kernel/test_every_stop_has_reason.py
# 的分工：那一个核对每个基准的结束事件都带清单里的原因，这一个守住清单本身不缩。
#
# 读仓库里的静态声明与定义文件，不开数据库、不用子进程、不用网络，属于单元层。
# 守第 13 节的 R2（第二环的合同：骨架事件只增；封闭的停止原因）。

import json
from dataclasses import fields
from pathlib import Path

from harness.kernel_events import (
    SKELETON_CATALOG_EVENTS,
    SKELETON_PROJECT_EVENTS,
    SKELETON_RUN_EVENTS,
    CatalogEvent,
    Event,
    ProjectEvent,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STOP_REASONS = REPO_ROOT / "harness" / "definitions" / "stop_reasons.json"

# 放出 S6a 时的骨架事件种类，按三个流分开：run 流、项目流、目录流（设计说明第 7 节的表）
SKELETON_EVENT_SNAPSHOT = {
    "run": frozenset({
        "run_created", "department_activated", "activation_finished",
        "tool_called", "tool_started",
        "model_requested",
        "proposal_submitted", "proposal_rejected",
        "spec_accepted", "spec_superseded", "contract_accepted", "product_decision_accepted",
        "artifact_invalidated", "delivery_accepted", "qa_submitted", "structure_accepted",
        "baseline_review_accepted",
        "run_done", "run_paused", "run_failed", "run_resumed", "run_continued",
        "decision_requested", "decision_answered", "decision_withdrawn",
    }),
    "project": frozenset({
        "project_registered", "project_renamed", "project_goal_changed", "project_pinned",
        "project_archived", "project_restored",
        "work_item_created", "work_item_start_failed",
        "deliverable_adopted", "adoption_held",
        "department_prompt_configured", "material_recorded", "source_directory_configured",
        "initial_prd_proposed",
        "project_decision_requested", "project_decision_answered", "project_decision_withdrawn",
        "onboarding_revision_started", "baseline_adopted", "project_parameter_set",
        "writeback_completed", "writeback_stopped", "writeback_not_needed", "writeback_held",
        "writeback_verified",
    }),
    "catalog": frozenset({
        "catalog_revised", "catalog_candidates_collected", "catalog_test_finished",
        "credential_changed",
        "runtime_drain_started", "runtime_drain_finished", "runtime_force_upgrade_requested",
        "home_seen", "parameter_set",
        "instance_upgrade_requested", "instance_upgrade_answered", "instance_upgrade_withdrawn",
    }),
}

# 放出 S6a 时事件信封的字段（设计说明第 3.1 节：全局位置、流、流内版本、种类、来源、时间只增）
ENVELOPE_SNAPSHOT = {
    "Event": (
        "event_id", "run_id", "type", "role", "parent_event_id", "state_before", "state_after",
        "payload", "artifact_hashes", "session_id", "provider", "model", "context_digest",
        "stop_reason", "error", "created_at", "position", "stream", "stream_version",
        "project_id", "work_item_id", "department", "epoch", "command_id", "actor",
    ),
    "ProjectEvent": (
        "event_id", "project_id", "type", "payload", "created_at", "position", "stream",
        "stream_version", "work_item_id", "run_id", "department", "epoch", "command_id", "actor",
    ),
    "CatalogEvent": (
        "event_id", "type", "payload", "created_at", "position", "stream", "stream_version",
        "project_id", "work_item_id", "run_id", "department", "epoch", "command_id", "actor",
    ),
}

# 放出 S6a 时封闭的停止原因清单（stop_reasons.json 的键，18 项）
STOP_REASON_SNAPSHOT = frozenset({
    "released", "baseline_verified",
    "max_cycles", "model_steps_exhausted", "no_tool_call", "workspace_unrepresentable",
    "time_limit", "cancelled", "user_cancelled",
    "provider_error", "provider_timeout", "provider_protocol", "unsupported_protocol",
    "retry_after_too_long", "context_overflow", "compaction_failed", "host_commit_error",
    "run_event_version_changed",
})

_DECLARATIONS = {
    "run": SKELETON_RUN_EVENTS,
    "project": SKELETON_PROJECT_EVENTS,
    "catalog": SKELETON_CATALOG_EVENTS,
}

_CLASSES = {"Event": Event, "ProjectEvent": ProjectEvent, "CatalogEvent": CatalogEvent}


def test_the_skeleton_event_kinds_only_grow():
    # 骨架事件的种类只增：删掉一种或改名，读过旧日志的内核就少了它（第 7 节「停用不删除」）
    for stream, declared in _DECLARATIONS.items():
        missing = sorted(SKELETON_EVENT_SNAPSHOT[stream] - declared)
        assert not missing, (
            f"骨架事件（{stream} 流）少了 {missing}：种类只增，停用不删除。"
            f"如果是有意删掉或改名，先把设计说明第 7 节的表与内核事件模块一起改，再更新这里的快照"
        )
    # 反方向：新加的种类要进快照，否则下一次核对不到它只增
    for stream, declared in _DECLARATIONS.items():
        added = sorted(declared - SKELETON_EVENT_SNAPSHOT[stream])
        assert not added, (
            f"骨架事件（{stream} 流）多了 {added}：加进内核的登记表以后，把它补进 "
            f"harness/tests/kernel/test_only_grows.py 的快照"
        )


def test_the_envelope_fields_only_grow():
    # 信封的字段只增：删掉一个字段，日志里那一列就没有了，旧的事件读不回来（第 3.1 节）
    for name, declaration in _CLASSES.items():
        current = [field.name for field in fields(declaration)]
        missing = [field for field in ENVELOPE_SNAPSHOT[name] if field not in current]
        assert not missing, (
            f"{name} 信封少了字段 {missing}：信封的字段只增，删掉或改名都会让已写入的事件读不回来。"
            f"如果是有意改，先在设计说明第 3.1 节写明，再更新这里与 test_only_grows.py 的快照"
        )
        added = [field for field in current if field not in ENVELOPE_SNAPSHOT[name]]
        assert not added, (
            f"{name} 信封多了字段 {added}：加进信封以后，把它补进 "
            f"harness/tests/kernel/test_only_grows.py 的快照"
        )


def test_the_stop_reasons_only_grow():
    # 停止原因的封闭清单只增：删掉一项，已经写过这个原因的结束事件不再认得它（第 3.1 节）
    reasons = set(json.loads(STOP_REASONS.read_text(encoding="utf-8")))
    missing = sorted(STOP_REASON_SNAPSHOT - reasons)
    assert not missing, (
        f"停止原因清单少了 {missing}：清单只增，删掉的原因会让已经写入的结束事件不再认得它。"
        f"如果确实要停用一个原因，先在设计说明第 3.1 节写明，再更新这里的快照"
    )
    added = sorted(reasons - STOP_REASON_SNAPSHOT)
    assert not added, (
        f"停止原因清单多了 {added}：新加的原因补进 harness/tests/kernel/test_only_grows.py 的快照，"
        f"并为它的去向（run_done、run_paused、run_failed）加一条用例"
    )

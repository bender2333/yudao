# 决定请求的处理与建档的流转（应用层；骨架与应用设计说明第 6、12 节 S4a，工单 #827）。
#
# 从流程编排搬出来的四件事：
#   1. 回答一个决定请求（run 流、项目流、目录流三种）：在写入口的一个事务里核对请求仍在等待、基准版本与
#      选项，追加回答，并按回答解除阻塞、结束运行或继续暂停的 run；
#   2. 建档（onboarding）的流转：采纳基线、内核修改的批准、提出修改以后建立修改轮；
#   3. 修改轮 run 的建立，以及回答事务提交以后中断时的补建；
#   4. 继续一个暂停的 run（把 run 从暂停恢复成进行中，下一次激活由薄驱动接着开始）。
#
# 薄驱动把它接上并只转交（`Orchestrator.answer_decision`、`Orchestrator.create_revision_run`），自己不再写
# 这些处理（设计说明第 6 节「薄驱动只连接」）。这里用到的薄驱动只有三件不属于应用层的事：建立 run、
# 唤醒等待的会话、记一次失败的运行，另加事实的存储、写入口、工件库与项目服务。
#
# 不导入流程编排：薄驱动在调用时把自己作为 `driver` 交进来（与路由实现收投影、收紧检查收申请同一个做法），
# 依赖方向因此只有薄驱动 → 应用层这一份。

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from . import parameters as parameter_values
from .artifacts import ArtifactStore
from .decisions import (
    DEFINITIONS_CHANGED, INITIAL_PRD, KERNEL_MODIFICATION, MODEL_UNAVAILABLE, RESUMABLE_PAUSE_KINDS,
    DecisionClosed, DecisionNotFound, InvalidOption, NoteRequired, StaleDecision, blocks_run,
)
from .event_store import Command, EventStore, is_catalog_stream, is_run_stream, run_stream
from .models import ArtifactRef, CatalogEventType, DecisionRequest, EventType, ProjectEventType, new_id
from .projection import project_run, saved_decision
from .tree_archive import artifact_run, load_tree
from .write_path import NewCatalogEvent, NewEvent, NewProjectEvent, Transaction, WritePath


class DecisionHost(Protocol):
    # 薄驱动交给应用层的公开面：事实的存储、写入口、工件库、项目服务与建立 run，
    # 以及只有薄驱动做的两件事（唤醒等新工作的会话、记一次失败的运行）
    store: EventStore
    writes: WritePath
    artifacts: ArtifactStore
    projects: Any

    def create_run(self, task: str, **options: Any) -> str:
        ...

    def wake(self, run_id: str) -> None:
        ...

    def fail_run(self, transaction: Transaction, reason: str, message: str) -> None:
        ...


class DecisionFlow:
    # 决定请求的处理与建档的流转。方法的第一项是薄驱动（`driver`），它自己不留状态：
    # 读的是事件日志、写的也是事件日志
    def answer_decision(self, driver: DecisionHost, decision_id: str, option: str, note: str | None, *,
                        base_version: int, command: Command) -> str | None:
        # 回答一个决定请求：在写入口的一个事务中登记命令身份，核对请求仍未回答、基准版本等于请求的版本、选项是
        # 请求给出的选项，追加回答，并按回答解除阻塞（待恢复选择停止事项时在同一事务中结束运行）。
        # 核对不通过时抛出 DecisionClosed、StaleDecision 或 InvalidOption，什么也不写，命令不登记。
        # 返回回答以后需要继续执行的 run，由调用方开始（start）；没有时为空
        # 命令身份先于决定请求核对：同一身份、内容不同时按 command_id_reused 拒绝，与请求是否存在无关
        driver.store.check_command(command)
        saved = saved_decision(driver.store, decision_id)
        if saved is None:
            raise DecisionNotFound(decision_id)

        def answer(transaction: Transaction) -> str | None:
            decision = transaction.decisions[decision_id]
            if decision.status != "open":
                raise DecisionClosed(decision)
            if base_version != decision.version:
                raise StaleDecision(decision, base_version)
            if option not in [item["id"] for item in decision.request["options"]]:
                raise InvalidOption(decision, option)
            if is_catalog_stream(saved.stream):
                # 目录流中的决定请求（工单 #355）：不属于任何 run 或项目，回答只是记下用户的决定
                transaction.append(NewCatalogEvent(CatalogEventType.INSTANCE_UPGRADE_ANSWERED, {
                    "decision_id": decision_id, "option": option, "note": note, "base_version": base_version,
                }, actor="system"))
                return None
            if is_run_stream(saved.stream):
                return self._answer_run_decision(driver, transaction, decision, option, note, base_version,
                                                 decision_id)
            return self._answer_project_decision(driver, transaction, decision, option, note, base_version,
                                                 decision_id)

        revision_run_id = driver.writes.transact(saved.stream, answer, command=command)
        if revision_run_id is not None and not driver.store.stream_events(run_stream(revision_run_id),
                                                                         after_version=0):
            # 建档修改轮：run 在回答事务提交以后单独建立，进程在两者之间中断时启动时按事件补建（设计第 6 节）
            self._create_missing_revision_run(driver, revision_run_id)
        return revision_run_id

    def _create_missing_revision_run(self, driver: DecisionHost, run_id: str) -> None:
        # 按 onboarding_revision_started 事件建立缺少的 run；run 流从版本 0 开始，重复创建被拒绝
        for project_id in driver.store.list_project_ids():
            for event in driver.store.list_project_events(project_id):
                if event.type != ProjectEventType.ONBOARDING_REVISION_STARTED or event.payload["run_id"] != run_id:
                    continue
                state = driver.projects.projection(project_id)
                candidate = next((entry for entry in state.initial_prd_candidates
                                  if entry.event_id == event.payload["candidate_event_id"]), None)
                if candidate is None:
                    raise ValueError(f"onboarding candidate {event.payload['candidate_event_id']} is gone")
                self.create_revision_run(driver, project_id, candidate, run_id, int(event.payload["round"]),
                                         event.payload.get("note"))
                return
        raise ValueError(f"no onboarding revision event names run {run_id}")

    def _answer_run_decision(self, driver: DecisionHost, transaction: Transaction, decision: DecisionRequest,
                             option: str, note: str | None, base_version: int, decision_id: str) -> str | None:
        # run 流中的决定请求：追加回答，并按回答解除阻塞
        projection = transaction.projection
        transaction.append(NewEvent(
            EventType.DECISION_ANSWERED, department=decision.request["department"], parent_event_id=decision_id,
            state_before=projection.status, state_after=projection.status,
            payload={"decision_id": decision_id, "option": option, "note": note, "base_version": base_version},
        ))
        transaction.on_commit(lambda: driver.wake(projection.run_id))
        if decision.kind in RESUMABLE_PAUSE_KINDS:
            # 暂停以后继续（工单 #204）：继续时从暂停位置恢复阶段并让 run 接着执行；停止时 run 保持暂停，
            # 停止原因就是暂停时的原因，什么都不改写。已用的激活次数、模型步数与运行时间不重新计算
            if option == "continue":
                self._continue_paused_run(driver, transaction, decision_id, decision)
                if blocks_run(transaction.decisions.values()):
                    return None
                return transaction.projection.run_id
            return None
        if option == "stop" and decision.kind in (MODEL_UNAVAILABLE.name, DEFINITIONS_CHANGED.name):
            if decision.request.get("reason") == "compaction_failed":
                # 整理连续没有推进的待恢复（模型管理设计说明第 8.7 节最后一条，工单 #1238）：答「停止事项」
                # 时事项以 compaction_failed 结束，停止说明沿用请求里写明的连续的次数与最后一次的原因
                driver.fail_run(transaction, "compaction_failed",
                                str(decision.request.get("message") or "run stopped by the user's decision"))
                return None
            driver.fail_run(transaction, "cancelled", "run stopped by the user's decision")
            return None
        if blocks_run(transaction.decisions.values()):
            return None
        return projection.run_id

    def _answer_project_decision(self, driver: DecisionHost, transaction: Transaction, decision: DecisionRequest,
                                 option: str, note: str | None, base_version: int,
                                 decision_id: str) -> str | None:
        # 项目流中的决定请求（工单 #136）：确认初始 PRD 时在同一事务中追加回答与 baseline_adopted；
        # 提出修改时在同一个事务中追加回答与 onboarding_revision_started，返回新 run 编号，
        # 由调用方 start：run 在事务提交以后单独建立（设计第 4.7、6 节）
        if option == "revise" and not (note or "").strip():
            raise NoteRequired(decision, option)
        request = decision.request
        work_item_id = request["work_item_id"]
        candidate_run_id = request.get("candidate_run_id")
        transaction.append(NewProjectEvent(ProjectEventType.PROJECT_DECISION_ANSWERED, {
            "decision_id": decision_id, "option": option, "note": note, "base_version": base_version,
            "work_item_id": work_item_id, "run_id": candidate_run_id,
        }, actor="system"))
        if decision.kind == KERNEL_MODIFICATION.name:
            self._settle_kernel_modification(transaction, decision, option)
            return None
        if decision.kind != INITIAL_PRD.name:
            return None
        candidate = next((item for item in transaction.projection.initial_prd_candidates
                          if item.run_id == candidate_run_id), None)
        if candidate is None:
            return None
        if option == "confirm":
            self._adopt_baseline(transaction, candidate, decision_id)
            return None
        return self._start_onboarding_revision(transaction, candidate, note)

    def _settle_kernel_modification(self, transaction: Transaction, decision: DecisionRequest, option: str) -> None:
        # 内核修改的批准与拒绝（受控内核设计说明第 4.2 节，工单 #354）：批准时把请求携带的采纳载荷写入
        # 项目流，交付自此成为当前采纳成果；拒绝时什么都不写，交付保持未采纳
        if option != "approve":
            return
        current = transaction.projection.current_adoption
        adoption = dict(decision.request["held_adoption"],
                        previous_adoption_id=None if current is None else current.adoption_id)
        transaction.append(NewProjectEvent(ProjectEventType.DELIVERABLE_ADOPTED, adoption, actor="system"))

    def _adopt_baseline(self, transaction: Transaction, candidate: Any, decision_id: str) -> None:
        # 采纳建档基线（工单 #136，设计第 5 节）：第一次采纳的成果是快照本身，采纳编号、结果代码树与摘要
        # 都取自建档候选；现有缺陷与其他失败记为采纳成果的已知风险
        snapshot = candidate.snapshot
        defects = [item["requirement"] for item in candidate.baseline_review["conclusions"]
                   if item["status"] == "existing_defect"]
        known_risks = [f'现有缺陷：{item["requirement"]}（{item["evidence"]}）'
                       for item in candidate.baseline_review["conclusions"]
                       if item["status"] == "existing_defect"]
        known_risks += [f'检查 {item["check"]} 未通过：{item["reason"]}'
                        for item in candidate.baseline_review["other_failures"]]
        transaction.append(NewProjectEvent(ProjectEventType.BASELINE_ADOPTED, {
            "adoption_id": new_id("adopt"), "work_item_id": candidate.work_item_id, "run_id": candidate.run_id,
            "candidate_event_id": candidate.event_id, "tree_ref": snapshot["tree_ref"],
            "code_tree_digest": snapshot["tree_digest"], "summary": _onboarding_summary(candidate),
            "prd_ref": candidate.prd["prd_ref"], "product_spec_hash": candidate.prd["content_hash"],
            "structure_ref": candidate.structure["structure_ref"], "files": list(snapshot.get("files") or []),
            "check_names": [item["name"] for item in candidate.baseline_review["checks"]],
            "checks": list(candidate.baseline_review["checks"]), "known_risks": known_risks,
            "snapshot": snapshot, "previous_adoption_id": None, "existing_defects": defects,
        }, actor="system"))

    def _start_onboarding_revision(self, transaction: Transaction, candidate: Any, note: str | None) -> str:
        # 建档修改轮（工单 #136，设计第 3.3、4.7、6 节）：修改轮事件与回答在同一个事务中写入，返回新 run 编号；
        # run 在事务提交以后单独一步建立（事务之间中断时，启动时按 onboarding_revision_started 补建）。
        # 事务提交到 run 建立之间是一个可以单独被终止的窗口
        round_number = candidate.round + 1
        run_id = new_id("run")
        transaction.append(NewProjectEvent(ProjectEventType.ONBOARDING_REVISION_STARTED, {
            "work_item_id": candidate.work_item_id, "run_id": run_id,
            "candidate_event_id": candidate.event_id, "round": round_number,
            "note": None if note is None else note.strip(),
        }, actor="system"))
        return run_id

    def create_revision_run(self, driver: DecisionHost, project_id: str, candidate: Any, run_id: str,
                            round_number: int, note: str | None) -> None:
        # 建立修改轮的 run：从同一个快照建立工作区，run_created 的 onboarding_basis 记下这一轮的依据，
        # 修改意见的工件按这一轮 run 的目录存放，并与 run 的创建在同一步作为它的第二项输入写入。
        # 启动补做按同一条 onboarding_revision_started 事件再调一次，run 流从版本 0 开始，重复创建被拒绝
        snapshot = candidate.snapshot
        tree_ref = ArtifactRef(**snapshot["tree_ref"])
        tree = load_tree(driver.artifacts, artifact_run(tree_ref.path), tree_ref)
        # 项目上下文、限额与部门 Prompt 版本取自同一个建档事项（这一轮仍是它）；
        # 冻结的登记命令取自上一轮 run 的 run_created：事项创建时的副本，命令版本仍随项目后续变化
        prior = project_run(driver.store, candidate.run_id)
        item = driver.projects.projection(project_id).work_item(candidate.work_item_id)
        if item is None or prior.project_context_ref is None:
            raise ValueError(f"work item {candidate.work_item_id} is gone")
        round_limit = driver.projects.onboarding_round_limit(project_id)
        note_ref = None
        if (note or "").strip():
            ref = driver.artifacts.put(run_id, "revision_note", note.strip(), media_type="text/markdown")
            note_ref = asdict(ref)
        driver.create_run(
            item.text, max_cycles=item.max_cycles,
            run_time_limit_sec=round_limit,
            check_timeout_sec=parameter_values.frozen_check_timeout(driver.store, candidate.run_id),
            context_window=item.context_window, run_id=run_id,
            kind="onboarding", initial_tree=tree, code_snapshot=snapshot,
            project_id=project_id, work_item_id=candidate.work_item_id,
            project_context=driver.artifacts.get(ArtifactRef(**prior.project_context_ref)).decode("utf-8"),
            prompt_config_versions=dict(item.prompt_config_versions),
            round=round_number,
            onboarding_basis={"candidate_event_id": candidate.event_id, "round": round_number,
                              "note_ref": note_ref},
            additional_input=note.strip() if note_ref is not None else None,
        )

    def _continue_paused_run(self, driver: DecisionHost, transaction: Transaction, decision_id: str,
                             decision: DecisionRequest) -> None:
        # 用户回答「处理以后继续执行」：把 run 从暂停恢复成进行中，下一次激活由流程编排接着开始
        # （下一个谁工作由关注的成果决定，工单 #556）。
        # 不写限额与计数字段（激活次数、模型步数、运行时间保持暂停时的值）；连续不调用工具的计数属于步骤驱动的
        # 一次激活内部状态，暂停时激活已经结束，继续以后的第一次激活从零开始
        projection = transaction.projection
        if projection.status != "paused":
            return
        transaction.append(NewEvent(
            EventType.RUN_CONTINUED, actor="system", department=decision.request["department"],
            parent_event_id=decision_id,
            state_before="paused", state_after="running",
            payload={"decision_id": decision_id, "stop_reason": decision.request["stop_reason"]},
        ))
        transaction.on_commit(lambda: driver.wake(projection.run_id))


def _onboarding_summary(candidate: Any) -> str:
    # 建档基线的摘要（工单 #136）：把这一轮的轮次与三条产物的内容摘要写成一句话
    return (f"第 {candidate.round} 轮建档的初始 PRD 已确认：PRD {candidate.prd['content_hash']}、"
            f"现有结构说明 {candidate.structure['content_hash']}、"
            f"基线核验 {candidate.baseline_review['content_hash']}")


# 薄驱动接上的那一份：无状态，读写的都是事件日志（组装时由 runtime.py 交给流程编排）
DECISION_FLOW = DecisionFlow()

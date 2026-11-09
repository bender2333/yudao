# 流程编排：运行的生命周期（创建、输入、指导、提示词、取消、作为任务开始）、一轮工作的准备（选模型与提示词）、
# 询问分支、提案的取舍、新输入的分派、发出决定请求、MCP 与试用会话，以及事项用的定义。
# 薄驱动在 `thin_driver.py`（工单 #1512、#1513）：循环、调度、计时、安全节点、开始一轮工作与取派发编号、
# 把一轮的结果经写入口写回、事项结束时写停止原因与核对流版本都在那里，这里经它的钩子协议接上；
# 回答决定请求与建档的流转在应用层（`decision_flow.py`，工单 #827）：薄驱动只转交。
# 运行工作区与会话的检查工作区在执行环境（`environment.py` 的 `Workspaces`，工单 #863）；
# 恢复的零件在 `recovery.py` 的 `RunRecovery`（工单 #863）：薄驱动只把继续一个 run 转交过去。
# 部门与成果的名称不在这个文件里：部门标识、关注的成果与成果种类一律从定义取（docs/design/skeleton-and-application.md「薄驱动」），
# `harness/tests/test_thin_driver_names.py` 检索这个文件，命中即失败。
# 一次激活内的步骤交给步骤驱动，只调用它的开始、取消与取得结果；安全节点接口由薄驱动实现并交给它。
# 流程编排不调用模型。
# 每一处「读取运行状态、判断、写入」都是写入口的一个事务（WritePath.transact）：判断期间不持有锁，
# 另一方在读取以后写入了同一个 run，提交被拒绝，按写入以后的状态重新判断。

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Condition, Event
from typing import Any

from .actions import FactsQuery, TreeFacts
from .adapters.base import ModelAdapter
from .adapters.facade_adapter import FacadeAdapter
from .adjudication import WorkBasis, commit_decision, proposal_decision
from .artifacts import ArtifactStore
from . import assembly_contract, execution_contract, mcp_session, routing_contract, tightening_contract
from .assembly import PENDING_GUIDANCE, pending_guidance
from .bounds import TIME_BOUND, round_bound, time_limit_message, time_used_up
from .compaction import response_reserve
from .context import DEFAULT_CONTEXT_WINDOW
from .contracts import artifact_hash
from .decisions import (
    MODEL_UNAVAILABLE, QA_CANNOT_VERIFY, RESUMABLE_PAUSE_KINDS, DecisionKind, blocked_by_other_session,
    blocks_run,
)
from .environment import (
    LocalEnvironment, RoundWorkspace, Workspaces, cleanup_inspection_workspace,
)
from .deltas import DeltaChannel
from .event_store import (Command, EventStore, StreamVersionConflict, project_stream, run_stream)
from .kernel_events import accepted
from .write_path import NewEvent, Snapshot, Transaction, WritePath
from .engine import StepLimits
from .streams import (
    RUN_EVENT_VERSION, STOP_REASON_UPGRADE, classify_startup_runs,
)
from .git_versions import GitVersionStore
from .interactions import CancelledInputSaveError, InteractionWriter, RunTerminalError
from .definitions import DEFAULT_FORM, DEFINITIONS, Definitions
from .department_prompts import save_department_prompt
from .overview import repository_overview
from . import parameters as parameter_values
from .minimal_projection import MinimalProjection, SessionState, fold_events
from .models import (
    ArtifactRef,
    DecisionRequest,
    DepartmentPrompt,
    EventType,
    Form,
    ProjectEvent,
    TERMINAL_STATUSES,
    new_id,
    spec_content_hash,
)
from .providers import ProviderConnections, ProviderFacade
from .providers.selection import ModelSelection
from .projection import RunNotFoundError, RunProjection, project_run
from .public_tree import CapturedTree, IgnoreRulesUndecidable, UnrepresentableWorkspace
from .recording import ActivationScope
from .recovery import RunRecovery
from .sessions import SessionFactory
from .snapshot import SNAPSHOT_FIELDS
from .submissions import SubmissionWriter, asks_cannot_verify
from .thin_driver import RoundDependencies, RoundFailure, RoundPreparation, RoundWork, ThinDriver
from .tools import in_force
from .validation import AdjudicationView, ProposalDecision, Tightening, evaluate_proposal
from .watched_outputs import waiting_departments
from .workspace import WorkspaceSnapshot

# 由用户提出的事件：输入与部门指导（提出者为 user:local）。薄驱动的停止判断核对流版本时读这两个种类
_USER_EVENTS = frozenset({EventType.USER_INPUT_RECEIVED, EventType.DEPARTMENT_GUIDANCE_RECEIVED})


def guidance_version(projection: RunProjection, department: str) -> int:
    # 这个部门指导当前这一版的编号（工单 #964）：指导是应用的数据，最小投影里没有它（docs/design/department-guidance.md「必验反例」，S1d），
    # 所以由薄驱动按运行状态投影给出，随一轮工作的开始事件记下
    return max((item.version for item in projection.department_guidance
                if item.department == department), default=0)


def work_basis(projection: RunProjection, department: str) -> WorkBasis:
    # 一轮工作开始时采用的工作依据：有效合同的摘要取自最小投影（裁决读的那一份），
    # 用户输入与指导的版本是应用的数据，由这里一并填进来（S1d，工单 #860）
    return WorkBasis(effective_contract_hash=artifact_hash(projection.effective_contract),
                     input_version=projection.input_version,
                     guidance_version=guidance_version(projection, department))



def _round_applied_guidance(events: list[Any], projection: RunProjection,
                            scope: ActivationScope) -> list[str]:
    # 这一轮结束时要写已回答的指导：这一轮的 department_guidance_applied 带进模型输入、此刻停在已进入模型输入的。
    # 指导作为通知在轮中到达时，它的应用事件也带这一轮的激活编号，所以不是只有「以指导开始的一轮」才算
    ids: list[str] = []
    for event in events:
        if event.type != EventType.DEPARTMENT_GUIDANCE_APPLIED:
            continue
        payload = event.payload or {}
        if payload.get("activation_id") != scope.activation_id:
            continue
        for guidance_id in payload.get("guidance_ids") or []:
            if guidance_id not in ids:
                ids.append(guidance_id)
    entered = {item.id for item in projection.department_guidance
               if item.department == scope.department and item.status == "in_input"}
    return [guidance_id for guidance_id in ids if guidance_id in entered]


# 旧名留一版（工单 #1513）：一轮工作改叫 `RoundWork`（在 `thin_driver.py` 里），新的代码用新名
_Activation = RoundWork


@dataclass(frozen=True)
class _DepartmentSettings:
    # 按部门取模型与提示词（执行契约第三版，工单 #1511）：项目部门设置优先，没有写入时用这个事项所用定义里
    # 的角色说明（版本 0）。它随开始一轮工作的请求交给执行实现——这两样属于路由与定义，不是安全节点的事
    run_id: str
    project_id: str | None
    projects: Any
    artifacts: ArtifactStore
    definitions: Definitions

    def _project_setting(self, department: str):
        # 运行层的设置来源：事项创建时由项目层提供，每次请求读取该项目该部门当前的项目部门设置。
        # 不属于项目的运行（命令行与测试）没有项目层，返回空设置
        if self.project_id is None or self.projects is None:
            return None
        return self.projects.read_projection_setting(self.project_id, department)

    def department_selection(self, department: str) -> ModelSelection | None:
        # 这个部门的项目部门设置中的模型选择；不属于项目的运行时为空（全部使用部门默认）
        setting = self._project_setting(department)
        if setting is None:
            return None
        return ModelSelection(provider_id=setting.provider_id, model_id=setting.model_id,
                              requested_tier=setting.requested_tier)

    def department_prompt(self, department: str) -> DepartmentPrompt:
        # 部门 Prompt 从项目部门设置读取；没有写入时使用内置默认 Prompt（版本 0）。
        # 请求事件记录的 Prompt 版本是项目部门设置中写入的部门 Prompt 版本，没有写入时为 0。
        # Prompt 原文的工件在项目层写入项目作用域，这里只取它的引用与版本
        setting = self._project_setting(department)
        if setting is None or not setting.configured_prompt or setting.prompt_ref is None:
            # 没有项目部门设置的部门 Prompt 时，固定取内置默认 Prompt（roles.json 的角色说明）；
            # 事项种类的工作说明是单独的请求材料，由上下文装配在部门 Prompt 之后放入（工单 #248）
            text = self.definitions.role(department).prompt
            # 部门清单按这个事项冻结的定义核对（工单 #1509）
            ref = save_department_prompt(self.artifacts, self.run_id, department, text, self.definitions)
            return DepartmentPrompt(department, 0, text, ref, "")
        return DepartmentPrompt(
            department=department, version=setting.version, text=setting.text,
            prompt_ref=ArtifactRef(**setting.prompt_ref),
            created_event_id="" if setting.event_id is None else setting.event_id,
        )


BASELINE_FIELDS = frozenset({"adoption_id", "source_run_id", "delivery_event_id", "tree_ref", "code_tree_digest"})


def _validate_run_ownership(
    *,
    project_id: str | None,
    work_item_id: str | None,
    baseline: dict[str, Any] | None,
    initial_tree: CapturedTree | None,
    code_snapshot: dict[str, Any] | None,
    project_context: str | None,
    prompt_config_versions: dict[str, int] | None,
    departments: frozenset[str] = frozenset(DEFINITIONS.departments),
) -> None:
    """项目归属参数要么全给（项目层）要么全不给（bare run）；基线与初始树成对出现。"""
    ownership = {
        "project_id": project_id, "work_item_id": work_item_id, "project_context": project_context,
        "prompt_config_versions": prompt_config_versions,
    }
    given = [name for name, value in ownership.items() if value is not None]
    if given and len(given) != len(ownership):
        missing = sorted(set(ownership) - set(given))
        raise ValueError("project ownership parameters must be given together; missing: " + ", ".join(missing))
    if not given and (baseline is not None or initial_tree is not None or code_snapshot is not None):
        raise ValueError("baseline and initial_tree require project ownership parameters")
    if code_snapshot is not None:
        if baseline is not None:
            raise ValueError("snapshot and baseline cannot be given together")
        if initial_tree is None:
            raise ValueError("snapshot and initial_tree must be given together")
        if not isinstance(code_snapshot, dict) or set(code_snapshot) != SNAPSHOT_FIELDS:
            raise ValueError("snapshot must contain exactly: " + ", ".join(sorted(SNAPSHOT_FIELDS)))
        if code_snapshot["tree_digest"] != initial_tree.digest:
            raise ValueError("snapshot tree_digest does not match the initial tree digest")
    elif (baseline is None) != (initial_tree is None):
        raise ValueError("baseline and initial_tree must be given together")
    if given:
        for name in ("project_id", "work_item_id", "project_context"):
            if not isinstance(ownership[name], str) or not ownership[name].strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(prompt_config_versions, dict) or set(prompt_config_versions) != set(departments):
            raise ValueError("prompt_config_versions must cover exactly the departments of the item's form")
        if any(type(version) is not int or version < 0 for version in prompt_config_versions.values()):
            raise ValueError("prompt_config_versions must be non-negative integers")
    if baseline is not None:
        if not isinstance(baseline, dict) or set(baseline) != BASELINE_FIELDS:
            raise ValueError("baseline must contain exactly: " + ", ".join(sorted(BASELINE_FIELDS)))
        if not isinstance(initial_tree, CapturedTree):
            raise ValueError("initial_tree must be a captured tree")
        if baseline["code_tree_digest"] != initial_tree.digest:
            raise ValueError("baseline code_tree_digest does not match the initial tree digest")


class Orchestrator:
    def __init__(
        self,
        store: EventStore,
        writes: WritePath,
        artifacts: ArtifactStore,
        workspace_root: str | Path,
        *,
        facade: ProviderFacade | None = None,
        test_adapter_factory: Any | None = None,
        test_provider: str = "test",
        test_adapter_name: str = "test",
        test_model: str = "fake-script",
        sessions: SessionFactory | None = None,
        step_limits: StepLimits | None = None,
        # 运行时间读的时钟（工单 #1520）：默认是单调时钟。测试交进受控的时钟，把「运行时间用完」安排
        # 在它选定的时点（例如第一次模型调用之后），运行时间的判定不依赖真实时长
        run_clock: Callable[[], float] | None = None,
        deltas: DeltaChannel | None = None,
        tightening: Tightening,
        routing: routing_contract.Routing,
        decision_flow: Any,
        assembly: Any,
        execution: Any,
        definitions: Definitions | None = None,
        # 实例同时加载的具名形态（工单 #1392）：名字 → 一份完整的定义与它选用的路由实现、收紧检查。
        # 不给时只有默认的三部门那一份（就是上面三样参数给的那一份）
        forms: Mapping[str, Form] | None = None,
    ) -> None:
        self.store = store
        self.writes = writes
        self.step_limits = step_limits
        self.deltas = deltas if deltas is not None else DeltaChannel()
        self.artifacts = artifacts
        self.workspace_root = Path(workspace_root).absolute().resolve()
        self.materials_root = self.workspace_root.parent / "materials"
        self.git_versions = GitVersionStore(self.workspace_root.parent / "git")
        self.submissions = SubmissionWriter(artifacts, self.materials_root, self.git_versions)
        self.interactions = InteractionWriter(store, artifacts, self.materials_root, self.git_versions)
        self.facade = facade
        self.test_adapter_factory = test_adapter_factory
        self.test_provider = test_provider
        self.test_adapter_name = test_adapter_name
        self.test_model = test_model
        # 路由的收紧检查（成果驱动）：内核的通用检查通过以后由它决定拒绝或等待（工单 #1095）；
        # 组装时核对它声明的契约版本，不合格就在开始一轮工作之前失败（与执行、装配两份契约同一个做法）
        self._tightening = tightening
        tightening_contract.accept(tightening)
        # 这个事项所用的那份定义（工单 #1098）：工具许可与提案校验按它的部门、工具与提案种类判；
        # 没有交的时候是当前加载的那一份
        self._definitions = in_force(definitions)
        # 按事项冻结的形态（工单 #1392）：上面三样是默认形态的，事项创建时记下的形态名决定这个事项用哪一份。
        # 每份形态的路由实现在组装时核对过契约版本
        self._forms: dict[str, Form] = dict(forms or {})
        self._forms.setdefault(DEFAULT_FORM, Form(DEFAULT_FORM, self._definitions, routing, tightening))
        for form in self._forms.values():
            routing_contract.accept(form.routing)
        # 实例加载的具名形态（工单 #1392）：新建事项按项目现在的形态取，发布里没有那一份时拒绝
        self.forms: dict[str, Form] = self._forms
        # 事项定义副本（工单 #1175）：按 run_created 里冻结的 MCP 设置叠加一次，按 run 记住
        self._item_definitions: dict[str, Any] = {}
        # 事项冻结的形态（工单 #1392）：按 run 记住，取自 run_created 里记下的形态名
        self._item_forms: dict[str, Form] = {}
        # MCP 会话表（工单 #1175）：按 run 记住，run 结束时在会话收尾里关闭
        self._mcp_sessions: dict[str, mcp_session.McpSessions] = {}
        # 数据目录：MCP 服务器标准错误输出的日志文件放在它的 mcp-logs 下（与探测同一处，docs/design/network-and-mcp.md「运行规则」）
        self.data_dir = self.workspace_root.parent
        # 路由实现（成果驱动）：谁在等、谁能开工、一轮以什么结束、事项以什么结束由它判断（工单 #825）；
        # 薄驱动只按契约的三个问题调用它，组装时核对它声明的契约版本
        self._routing = routing
        routing_contract.accept(routing)
        # 决定请求的处理与建档的流转在应用层（工单 #827，docs/design/skeleton-and-application.md「薄驱动」「薄驱动只连接」）：这里接上它，
        # 调用时把自己作为 driver 交进去，薄驱动自己不再写这些处理
        self.decision_flow = decision_flow
        # 装配实现与执行实现由组装处（`runtime.py`）经构造参数接上（工单 #979，骨架与应用设计说明第
        # 5.2、5.3 节「接法」）：薄驱动不自己构造装配实现、也不按类名调用执行实现，源码里没有两者的名字，
        # 换实现只换构造参数。这里按契约核对两者声明的版本，不在接受范围时构造就失败（与收紧检查、
        # 路由同一个位置、同一个做法）：先核对再开始，不带着版本不合的实现在跑
        self.assembly = assembly
        assembly_contract.accept(self.assembly)
        self._execution = execution
        execution_contract.accept(self._execution)
        self.sessions = sessions or SessionFactory(self.workspace_root)
        # 事项自己的停止开关：用户取消（cancel、_abort_run）打开它，之后的核对都得到停止，
        # 事项以取消结束；停下一个会话不用它（工单 #856）
        self._abort: dict[str, Event] = {}
        # 运行工作区与会话的检查工作区在工作的一层（`environment.py`，S4c 工单 #863）：薄驱动只问
        # 「这个会话用哪份工作区」「这一轮进行中要不要换成新的交付」，两种工作区的来源与重建都在那里
        self._workspaces = Workspaces(
            self.workspace_root,
            view=self.project,
            writes=self.writes,
            artifacts=self.artifacts,
            sessions=self.sessions,
            check_timeout=lambda run_id: parameter_values.frozen_check_timeout(self.store, run_id),
            # 试用会话的开始与结束写成 run 流里的应用事件（浏览器与 computer use docs/design/browser-and-computer-use.md「事件、决定请求与查询」，
            # 工单 #1183）：会话表在执行环境一层，写入方是薄驱动——与 MCP 会话的生命周期同一个做法
            trial_events=self._trial_session_event,
            # 工作区政策（谁交出交付、谁从封存交付建立检查副本、检查材料写在哪里）按这个事项冻结的
            # 形态推（工单 #1509）：换一份把部门改了名的定义，改名后的部门照常按自己的角色工作
            definitions_for=self.item_definitions,
        )
        # 恢复的零件在 `recovery.py`（S4c 工单 #863）：核对定义版本、核实结果未知的动作、取得执行权
        self._recovery = RunRecovery(
            writes=self.writes,
            store=self.store,
            view=self.project,
            artifacts=self.artifacts,
            run_environment=self._workspaces.run_environment,
            wake=self._wake,
            # 定义版本的核对与恢复时的写入按事项冻结的形态取（工单 #1392）
            definitions_of=self.item_definitions,
        )
        # 每个 run 正在进行的取消（cancel 或 /stop）；一个取消结束时通知等待它的激活与运行循环
        self._cancellers: dict[str, set[object]] = {}
        self._cancellers_changed = Condition()
        # 会话结束（事务 on_commit）执行后留下的清理错误：Windows 句柄长期占用时会出现，
        # 留给运维或下一次启动扫描处理，不阻塞 run 的正常退出
        self._close_errors: dict[str, list[Exception]] = {}
        # 运行到停止的循环的唤醒登记、运行时间的段计时与每个会话这一段的起点都在薄驱动里（工单 #1512）：
        # 已经结算的量读最小投影，正在跑的那一段只有驱动知道（docs/design/skeleton-and-application.md「最小投影」）。
        # 作为任务开始（start）的 run 与它的任务；任务结束时移除
        self._tasks: dict[str, asyncio.Task[RunProjection]] = {}
        # 事项的执行任务与结算：run_id -> 任务；由 start_work_item 建立，任务结束时移除
        self._work_item_tasks: dict[str, asyncio.Task[Any]] = {}
        # 测试系统的确定性适配器登记的调用目标窗口：按 run 记下这一次声明的窗口（工单 #669）
        self._test_context_windows: dict[str, int] = {}
        # 项目服务在装配以后回填，用于结算与判断执行槽位（busy）
        self.projects: Any = None
        # 薄驱动（工单 #1512、#1513）：循环、调度、计时、安全节点、开始一轮工作与取派发编号、结果写回
        # 与事项结束都在 `thin_driver.py`，这里把应用一侧的流程编排作为它写在那个模块里的钩子协议交给它；
        # run_clock 是运行时间读的时钟（工单 #1520），原样交过去。正在进行的轮次也由它记，取消、唤醒与计时都问它
        self._thin_driver = ThinDriver(self.writes, self, run_clock=run_clock)

    def _transact(self, stream: str, decide: Callable[[Transaction], Any], **options: Any) -> Any:
        # 薄驱动自己的写入（工单 #1165）：停止原因与部门按这个事项所用的那份定义核对；事项创建时冻结的
        # 形态决定用哪一份（工单 #1392），第二种路由在自己那份定义里声明的结束原因与它带的部门因此写得进
        # 事件日志。按 run 叠加 MCP 设置得到的副本只多出工具，不改这两样
        if "definitions" not in options and stream.startswith("run:"):
            options["definitions"] = self.item_definitions(stream.split(":", 1)[1])
        return self.writes.transact(stream, decide, **options)

    # 薄驱动的钩子协议（`thin_driver.DriverHooks`，工单 #1512、#1513）：应用一侧的流程编排做这些事，薄驱动经它们
    # 读运行视图与路由、准备一轮工作、开始执行、结算与结束事项。薄驱动不导入这里，构造时把自己交进来的是它
    def read_run(self, run_id: str) -> Snapshot:
        # 这个 run 的只读快照：运行视图与还没回答的决定请求；run 不存在时按应用的错误抛出
        snapshot = self.writes.read(run_stream(run_id))
        if not snapshot.projection.run_id:
            raise RunNotFoundError(run_id)
        return snapshot

    def routing(self, run_id: str) -> Any:
        # 这个事项冻结的形态所选的路由实现
        return self._item_routing(run_id)

    def waiting_departments(self, run_id: str) -> set[str]:
        # 这个进程里在等待工作的部门，由会话状态给出
        return self._waiting_departments(run_id)

    def aborted(self, run_id: str) -> bool:
        return self._aborted(run_id)

    def settled(self, run_id: str) -> RunProjection:
        return self._settled(run_id)

    def definitions(self, run_id: str) -> Any:
        # 这个事项冻结的那份定义：停止原因与部门按它核对（MCP 设置带来的工具不改这两样）
        return self.item_definitions(run_id)

    def guidance_version(self, projection: RunProjection, department: str) -> int:
        return guidance_version(projection, department)

    def user_events(self) -> frozenset[str]:
        # 用户提出的事件种类：薄驱动的停止判断核对流版本时用它（工单 #964、#1513）
        return _USER_EVENTS

    def await_cancellers(self, run_id: str) -> None:
        self._await_cancellers(run_id)

    def close_run(self, run_id: str) -> None:
        self._on_close_run(run_id)

    def session_idle(self, run_id: str, department: str) -> None:
        # 这一轮结束了：这个部门的会话回到等待工作，别的会话可以接着开始
        self.sessions.get(run_id, department).idle()

    def prepare_round(self, run_id: str, transaction: Transaction, connections: ProviderConnections,
                      department: str) -> RoundPreparation | None:
        # 一轮工作的准备（选模型与提示词也在其中）：薄驱动据此在同一个事务里取派发编号、写这一轮的开始事件
        return self._prepare_activation(run_id, transaction, connections, department)

    def round_environment(self, round_work: RoundWork) -> tuple[Any | None, RoundFailure | None]:
        return self._round_environment(round_work)

    def round_dependencies(self, round_work: RoundWork,
                           environment: Any) -> RoundDependencies:
        return self._round_dependencies(round_work, environment)

    def round_failure(self, exc: Exception) -> RoundFailure | None:
        return self._describe_failure(exc)

    def apply_round_result(self, round_work: RoundWork, result: Any, current: RunProjection) -> None:
        self._apply_round_result(round_work, result, current)

    def after_round_finished(self, transaction: Transaction, round_work: RoundWork,
                             happened: list[Any]) -> None:
        self._after_round_finished(transaction, round_work, happened)

    async def _invoke_activation(self, round_work: RoundWork) -> None:
        # 这一轮工作的连接在薄驱动（`ThinDriver.invoke_round`，工单 #1513）：这里保留同名转交，
        # 应用与测试在这一轮结束的时刻做收尾（例如 `test_concurrent_commands` 在这里等收尾次序）
        await self._thin_driver.invoke_round(round_work)

    def new_connections(self) -> ProviderConnections:
        return ProviderConnections()

    def flush_trial_events(self, run_id: str) -> None:
        self.sessions.flush_trial_events(run_id)

    async def close_mcp_sessions(self, run_id: str) -> None:
        await self._close_mcp_sessions(run_id)

    def await_model(self, transaction: Transaction, round_work: RoundWork, reason: str, message: str,
                    *, target: dict[str, Any] | None = None) -> None:
        # 待恢复：run 停在这次请求之前，发出待恢复的决定请求（说明与选项在应用这一侧）
        scope = round_work.scope
        self._await_model(transaction, scope.department, target, reason, message,
                          facts=self._failed_attempts(transaction, scope.activation_id))

    def resume_after_pause(self, transaction: Transaction, reason: str, department: str,
                           message: str | None, facts: list[str]) -> None:
        # 暂停以后可以继续的那几种原因：发出继续或停止的决定请求（哪些原因可以继续在这一层决定）
        kind = RESUMABLE_PAUSE_KINDS.get(reason)
        if kind is not None:
            self._request_pause_resume(transaction, kind, department, reason, message, facts)

    def record_lesson_candidate(self, transaction: Transaction, reason: str, source_event: Any,
                                projection: RunProjection) -> None:
        # 运行失败时记下教训候选（取消不算）
        if reason != "cancelled":
            self.submissions.record_lesson_candidate(transaction, source_event, projection)

    def transact_run(self, run_id: str, decide: Callable[[Transaction], Any], **options: Any) -> Any:
        return self._transact(run_stream(run_id), decide, **options)

    def assign_new_inputs(self, transaction: Transaction) -> RunProjection:
        return self._assign_new_inputs(transaction)

    async def execute_ask(self, round_work: RoundWork, scope: ActivationScope,
                          call: dict[str, Any]) -> tuple[bool, Any, str | None, str | None, int]:
        return await self._execute_ask(round_work, scope, call)

    def blocks_run(self, decisions: Iterable[DecisionRequest]) -> bool:
        return blocks_run(decisions)

    def blocked_by_other_session(self, decisions: Iterable[DecisionRequest], department: str) -> bool:
        return blocked_by_other_session(decisions, department)

    def create_run(
        self,
        task: str,
        *,
        max_cycles: int = DEFINITIONS.rule_value("max_cycles"),
        run_time_limit_sec: int = DEFINITIONS.rule_value("run_time_limit_sec"),
        # 窗口是调用目标的属性：真实运行取模型访问定义声明的窗口。这里给的是测试适配器登记调用目标时
        # 声明的窗口，不给时按目录里已有的调用目标（工单 #669）
        context_window: int | None = None,
        # 检查的时限（迭代底座 B3，工单 #351）：不给时按项目级取值与全局现值取一次，随 run 冻结
        check_timeout_sec: int | None = None,
        run_id: str | None = None,
        project_id: str | None = None,
        work_item_id: str | None = None,
        baseline: dict[str, Any] | None = None,
        initial_tree: CapturedTree | None = None,
        code_snapshot: dict[str, Any] | None = None,
        project_context: str | None = None,
        prompt_config_versions: dict[str, int] | None = None,
        kind: str = "change",
        onboarding_basis: dict[str, Any] | None = None,
        round: int = 0,
        # 与 run 的创建在同一步写入的第二项输入（建档修改轮的用户修改意见原文，工单 #136）
        additional_input: str | None = None,
        # 事项创建时冻结的定义版本（工单 #1189）：不给时是当前加载的定义。参数快照按它记下定义版本，
        # 定义版本与当前不同时不创建 run（启动补建的那条路径在调用之前就跳过）
        item_definitions_version: str | None = None,
        # 事项创建时冻结的 MCP 服务器设置（工单 #236）：非秘密设置与凭据引用的整份文档；
        # 不给时是 None（旧事项与没有 MCP 设置的事项按空设置读取）。run 期间只读这份冻结值
        mcp_servers: dict[str, Any] | None = None,
        # 事项创建时冻结的形态名（工单 #1392）：这个 run 的部门、路由与停止原因按它的那份定义；
        # 不给时是默认的三部门那一份（直接建 run 的调用与旧数据）
        form: str | None = None,
    ) -> str:
        frozen_form = self.form_named(form)
        definitions = frozen_form.definitions
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be non-empty")
        if max_cycles < 1:
            raise ValueError("max_cycles must be positive")
        if run_time_limit_sec < 1:
            raise ValueError("run_time_limit_sec must be positive")
        if context_window is not None and context_window < 1:
            raise ValueError("context_window must be positive")
        check_timeout_sec = (parameter_values.value_for_project(self.store, project_id, "check_timeout_sec")
                             if check_timeout_sec is None else check_timeout_sec)
        if check_timeout_sec < 1:
            raise ValueError("check_timeout_sec must be positive")
        if self.facade is None and self.test_adapter_factory is None:
            raise ValueError("provider facade is required for production runs")
        if kind not in definitions.work_items.kinds:
            raise ValueError(f"work item kind {kind!r} is not defined in work_items.json")
        if kind == "onboarding":
            # 建档事项由快照开始：没有采纳成果，也没有可写的工作区（工单 #134）
            if code_snapshot is None or initial_tree is None or baseline is not None:
                raise ValueError("an onboarding run requires a code snapshot with its initial tree and has no baseline")
        _validate_run_ownership(
            project_id=project_id, work_item_id=work_item_id, baseline=baseline, initial_tree=initial_tree,
            code_snapshot=code_snapshot,
            project_context=project_context,
            prompt_config_versions=prompt_config_versions,
            departments=frozenset(definitions.departments),
        )
        run_id = run_id or new_id("run")
        # 窗口是调用目标的属性，不再随 run 冻结（工单 #669）：声明的窗口写进调用目标（目录），
        # 记在编排器里，激活时按这一次声明再写一次；不声明时按目录里已有的调用目标。
        # 写在 run 的事件之前：调用目标登记不成功时不留下半个 run
        if context_window is not None:
            self._test_context_windows[run_id] = context_window
            if self.test_adapter_factory is not None and self.facade is not None:
                self._install_test_call_target(context_window, definitions.departments)
        material_dir = self.materials_root / run_id
        if material_dir == self.materials_root or not material_dir.is_relative_to(self.materials_root):
            raise ValueError("run_id must stay within the run materials directory")
        # 工作区先于其余材料落盘：从封存快照建立失败时不留下半个 run。
        environment = LocalEnvironment.establish(
            self.workspace_root / run_id, initial_tree, check_timeout_sec=check_timeout_sec)
        workspace_digest = environment.snapshot().digest
        # 部门 Prompt 不在 run 内留副本（工单 #89）：每次模型请求按事项种类与项目部门设置读取
        initial = self.interactions.initial(run_id, task)
        follow_up = (None if additional_input is None else self.interactions.next_input(
            run_id, initial["initial_input"], additional_input, version=2))
        sessions = self.sessions.create_run_sessions(run_id, departments=definitions.departments)
        self._abort[run_id] = Event()
        project_context_ref = None
        if project_context is not None:
            project_context_ref = asdict(self.artifacts.put(
                run_id, "project_context", project_context, media_type="text/markdown",
            ))
        overview_ref = None
        if kind == "onboarding":
            # 仓库概况由快照的公开树确定性地生成，作为建档中部门读取的第一项材料
            overview_ref = asdict(self.artifacts.put(
                run_id, "repository_overview", repository_overview(initial_tree), media_type="text/markdown",
            ))
        # 建 run 时冻结的参数快照（工单 #1189）：全局现值叠加项目覆盖，
        # 事项已经解析出来的实际限额单独记下；这个 run 之后只读这份快照
        item_limits = {
            "max_cycles": max_cycles,
            "run_time_limit_sec": run_time_limit_sec,
            "check_timeout_sec": check_timeout_sec,
            "onboarding.round_time_limit_sec": parameter_values.value_for_project(
                self.store, project_id, "onboarding.round_time_limit_sec"),
        }
        frozen_definitions_version = item_definitions_version or definitions.version
        frozen_parameters = parameter_values.frozen_snapshot(
            self.store, project_id=project_id, definitions_version=frozen_definitions_version,
            item_limits=item_limits, definitions=definitions,
        )
        # 事项创建时按冻结的定义算出是不是开环（工单 #1394，形态与核验角色设计说明「开环完成」与
        # 「定义的校验」第 4 条）：看事项最后采纳的成果有没有核验角色核验。最后采纳的成果种类由这份定义
        # 所选的路由声明（成果驱动是交付，直做是交完成的那一份；`is_open_loop` 按 #1388 的核验声明判断）；
        # 路由没有声明这一项时不标开环，结束原因由它自己给。标记记进创建事件，完成时由路由读它给出结束原因
        final_outcome = definitions.routing_definition().final_outcome
        open_loop = final_outcome is not None and definitions.is_open_loop(final_outcome)
        run_created = NewEvent(
            EventType.RUN_CREATED,
            actor="system",
            department=self._start_department_of(definitions, kind),
            state_before="running",
            state_after="running",
            payload={
                "task": task,
                "kind": kind,
                **initial,
                "intend_path": (Path("materials") / run_id / "intend.md").as_posix(),
                "max_cycles": max_cycles,
                "run_time_limit_sec": run_time_limit_sec,
                "check_timeout_sec": check_timeout_sec,
                "provider": self.test_provider if self.test_adapter_factory is not None else "directory",
                "adapter": self.test_adapter_name if self.test_adapter_factory is not None else "directory",
                "sessions": {name: session.session_id for name, session in sessions.items()},
                "project_id": project_id,
                "work_item_id": work_item_id,
                "baseline": baseline,
                "snapshot": code_snapshot,
                "overview_ref": overview_ref,
                "workspace_digest": workspace_digest,
                "project_context_ref": project_context_ref,
                "prompt_config_versions": dict(prompt_config_versions or {}),
                "definitions_version": frozen_definitions_version,
                # 事项创建时冻结的形态名（工单 #1392）：这个 run 的部门、路由与停止原因都按它的那份定义
                "form": frozen_form.name,
                # 事项创建时按冻结的定义算出的开环标记（工单 #1394）：为真时这个事项以开环完成结束
                "open_loop": open_loop,
                "parameters_version": parameter_values.current_version(self.store),
                "parameters": frozen_parameters,
                # 事项创建时冻结的 MCP 服务器设置（工单 #236）：与事项创建事实同一份；没有时为空
                "mcp_servers": deepcopy(mcp_servers) if mcp_servers is not None else None,
                "run_event_version": RUN_EVENT_VERSION,
                "onboarding_basis": onboarding_basis,
                "round": round,
            },
        )
        note_received = (NewEvent(
            EventType.USER_INPUT_RECEIVED, actor="user:local", department=self._input_department_of(definitions),
            state_before="running", state_after="running",
            payload=follow_up,
            artifact_hashes=[follow_up["input_ref"]["content_hash"], follow_up["intend_ref"]["content_hash"]],
        ) if follow_up is not None else None)
        # 新的 run 流从版本 0 开始；同一编号的 run 已经存在时拒绝
        self._transact(run_stream(run_id), lambda transaction: transaction.append(
            *((run_created, note_received) if note_received is not None
              else (run_created,))), expected_version=0, definitions=definitions)
        return run_id

    def project(self, run_id: str) -> RunProjection:
        return project_run(self.store, run_id)

    def _install_test_call_target(self, context_window: int | None,
                                  departments: Any | None = None) -> None:
        # 测试系统的确定性适配器：用它的名称与模型名登记一个 fake 协议的模型访问定义。
        # 声明的输出上限取不改变默认保留的值，使既有的阈值行为与事项窗口一致。
        # 目录里已有内容时按合并处理：保留已有的连接、定义与部门默认，只补上缺的 fake 连接，
        # 并且只给它补上还没有默认的部门——测试适配器不覆盖用户在目录与项目里写入的模型选择。
        # 窗口是调用目标的属性：给了就用给的，不给时保留目录里已经登记的窗口（工单 #669）
        # 补绑定的部门清单按这个事项冻结的形态取（工单 #1509）：改名后的部门也要有模型可解析；
        # 不给时是进程加载的那一份
        if self.facade is None:
            raise ValueError("a provider facade is required for runs")
        provider_id = self.test_provider
        model_id = f"{provider_id}-model"
        view = self.facade.providers_view()
        # providers_view 给界面用的字段比目录文档多（credential、credential_configured、models），
        # 这里只取目录定义本身的字段，未知字段会被整份拒绝
        providers = [
            {key: item[key] for key in (
                "id", "name", "base_url", "credential_ref", "timeout_sec", "preset_id", "models_url")}
            for item in view["providers"]
        ]
        models = list(view["models"])
        bindings = {key: dict(value) for key, value in view["bindings"].items()}
        if not any(item["id"] == provider_id for item in providers):
            providers.append({"id": provider_id, "name": provider_id, "base_url": ""})
        existing = next((item for item in models if item["id"] == model_id), None)
        if existing is None:
            window = context_window if context_window is not None else DEFAULT_CONTEXT_WINDOW
            models.append({
                "id": model_id, "provider_id": provider_id, "model": self.test_model,
                "protocol": "fake", "context_window": window,
                "max_output_tokens": response_reserve(window, None),
            })
        elif context_window is not None:
            # fake 模型的窗口是这一次声明的（工单 #669）：同一个 fake 模型登记过的窗口要跟着这一次走
            existing["context_window"] = context_window
            existing["max_output_tokens"] = response_reserve(context_window, None)
        for department in (DEFINITIONS.departments if departments is None else departments):
            bindings.setdefault(department, {"provider_id": provider_id, "model_id": model_id})
        self.facade.store_document({"providers": providers, "models": models, "bindings": bindings})
        if self.facade.config_path is not None:
            # 调用目标随数据目录一起落盘：重开数据目录以后按同一个调用目标继续（工单 #669）
            self.facade.persist_document(self.facade.config_path)

    def _start_department_of(self, definitions: Definitions, kind: str) -> str:
        # 事项开始时开始第一轮的是接它来源的部门（工单 #1455）：来源从事项的种类取（建档或你的输入），
        # 部门从定义取。部门名不在这里写
        return definitions.source_department(definitions.item_source(kind))

    def _input_department_of(self, definitions: Definitions) -> str:
        # 接你的输入的部门（工单 #1455）：新输入分派给它。不再看谁关注用户输入——关注用户输入是另一件事，
        # 留在关注关系里。薄驱动不含部门的名称（docs/design/skeleton-and-application.md「薄驱动」），部门身份从事项所用的定义取（工单 #1392）
        return definitions.input_department()

    @property
    def _input_department(self) -> str:
        # 默认形态里收用户输入的部门：没有事项定义的写入用它
        return self._input_department_of(self._definitions)

    @staticmethod
    def _round_workspace(round_work: RoundWork) -> RoundWorkspace:
        # 这一轮工作用哪份工作区（S4c 工单 #863）：身份取自已开始的一轮，检查工作区在交付到达时换新的
        scope = round_work.scope
        return RoundWorkspace(
            run_id=scope.run_id, department=scope.department, session_id=scope.session_id,
            activation_id=scope.activation_id,
            effective_contract_hash=scope.basis.effective_contract_hash,
        )

    def _waiting_departments(self, run_id: str) -> set[str]:
        # 在等待工作的部门：这个进程里没有正在工作的会话的那些（工单 #16 的恢复口径）。
        # 「谁在等」的判断归路由实现（工单 #825），薄驱动只交出会话状态这份事实；
        # 部门清单按事项冻结的形态取（工单 #1392）：在等待的是这份定义里的部门（工单 #1509）
        definitions = self.item_definitions(run_id)
        return waiting_departments({department: self._session_status(run_id, department)
                                    for department in definitions.departments}, definitions)

    def _session_status(self, run_id: str, department: str) -> str | None:
        # 这个进程里这个部门会话的状态；还没有会话时为空（那时它同样在等待，可以被重新激活）
        try:
            return self.sessions.get(run_id, department).status
        except KeyError:
            return None

    def _department_ready(self, run_id: str, projection: RunProjection, department: str) -> bool:
        # 这个部门现在可以开始一轮工作：由路由判断（在等待工作，并且关注的成果有了新东西）。
        # 同时运行（工单 #557）：准备激活的事务里重新核对，别的会话在这期间做完了就开始
        return self._item_routing(run_id).department_ready(
            projection, department=department, waiting=self._waiting_departments(run_id))


    def add_input(self, run_id: str, text: str, *, base_version: int | None = None,
                  command: Command | None = None) -> RunProjection:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("input must be a non-empty string")
        if text.strip() in {"/stop", "/cancel"}:
            return self._stop_by_command(run_id, text)

        def receive(transaction: Transaction) -> None:
            self._require_open(run_id, transaction.projection, "This run has ended; create a new task for this input.")
            self.interactions.receive(transaction, text, command=False, base_version=base_version)

        self._transact(run_stream(run_id), receive, command=command)
        self._wake(run_id, restart=True)
        return self.project(run_id)

    def _stop_by_command(self, run_id: str, text: str) -> RunProjection:
        # /stop 与 /cancel：保存命令原文并取消运行。先中止并取消正在进行的步骤，再记录命令；
        # 命令原文没有保存成功时仍然记录取消，并在取消的事件中说明保存失败的原因
        message = "This run has ended; create a new task for this input."
        with self._cancelling(run_id):
            self._require_open(run_id, self.project(run_id), message)
            _round_work, cancel_error = self._abort_run(run_id)
            stop_error = cancel_error

            def receive(transaction: Transaction) -> None:
                if transaction.projection.status in TERMINAL_STATUSES:
                    raise RunTerminalError(message)
                self.interactions.receive(transaction, text, command=True)

            save_error = None
            cancellation_recorded = False
            try:
                try:
                    self._transact(run_stream(run_id), receive)
                except RunTerminalError:
                    raise
                except Exception as exc:
                    save_error = exc
                failure = None if save_error is None else {
                    "text": text, "error_type": type(save_error).__name__, "message": str(save_error),
                }
                try:
                    self._transact(run_stream(run_id), lambda transaction: self._fail(
                        transaction, "cancelled", "run cancelled by user command", input_save_failure=failure))
                    cancellation_recorded = True
                except Exception as exc:
                    stop_error = stop_error or exc
            finally:
                if cancel_error is not None:
                    # 取消正在进行的步骤出过错：再通知一次（这个 run 的每一个会话）
                    try:
                        self._abort_run(run_id)
                    except Exception as exc:
                        stop_error = stop_error or exc
        if save_error is not None:
            raise CancelledInputSaveError(run_id, cancellation_recorded=cancellation_recorded) from save_error
        if stop_error is not None:
            raise stop_error
        return self.project(run_id)

    def _aborted(self, run_id: str) -> bool:
        # 事项自己被中止（用户取消）：之后的核对都得到停止，事项以取消结束。
        # 停下一个会话不算中止（工单 #856）
        flag = self._abort.get(run_id)
        return flag is not None and flag.is_set()

    def _abort_run(self, run_id: str) -> tuple[RoundWork | None, Exception | None]:
        # 中止运行（用户取消）：事项的开关打开，之后的核对都得到停止，正在进行的步骤立即取消；
        # 交回正在进行的激活与取消它时的错误。
        # 同时运行（工单 #557）：取消与暂停作用于事项的全部会话，这里取消这个 run 的每一个会话
        self._abort.setdefault(run_id, Event()).set()
        activations = list(self._thin_driver.activations(run_id).values())
        first: RoundWork | None = None
        error: Exception | None = None
        for round_work in activations:
            if first is None:
                first = round_work
            try:
                self._cancel_driver(round_work)
            except Exception as exc:
                error = error or exc
        return first, error

    @contextmanager
    def _cancelling(self, run_id: str) -> Iterator[None]:
        # 登记一个正在进行的取消：运行循环看到中止时，由它写入取消（它可能还在保存命令原文）
        token = object()
        with self._cancellers_changed:
            self._cancellers.setdefault(run_id, set()).add(token)
        try:
            yield
        finally:
            with self._cancellers_changed:
                self._cancellers[run_id].discard(token)
                self._cancellers_changed.notify_all()

    def _await_cancellers(self, run_id: str) -> None:
        # 有正在进行的取消（cancel 或 /stop），等待它结束：等待时释放锁，取消线程可以在等待期间登记与结束。
        # 激活收尾与运行循环用它等取消写入，取消一方从不等待激活收尾。
        with self._cancellers_changed:
            self._cancellers_changed.wait_for(lambda: not self._cancellers.get(run_id))

    def _settled(self, run_id: str) -> RunProjection:
        # 激活与运行循环结束时交回的运行状态。有正在进行的取消（cancel 或 /stop）时，等待它结束，
        # 交回它写入以后的状态；运行已经中止而没有正在进行的取消（例如它的写入失败了）时在这里写入取消。
        # 停下一个会话（因决定请求阻塞或事项到终态）不算中止：事项的状态不变（工单 #856）
        projection = self.project(run_id)
        if projection.status in TERMINAL_STATUSES:
            return projection
        self._await_cancellers(run_id)
        projection = self.project(run_id)
        if projection.status in TERMINAL_STATUSES:
            return projection
        if self._aborted(run_id):
            return self.cancel(run_id)
        return projection

    def add_guidance(self, run_id: str, department: str, text: str, *,
                     base_version: int | None = None, command: Command | None = None) -> RunProjection:
        if department not in self.item_definitions(run_id).departments:
            raise ValueError("unknown department")

        def receive(transaction: Transaction) -> None:
            self._require_open(run_id, transaction.projection, "This run has ended; guidance can be sent to a new task.")
            # 部门清单按这个事项冻结的定义核对（工单 #1509）
            self.interactions.receive_guidance(transaction, department, text, base_version=base_version,
                                               definitions=self.item_definitions(run_id))

        self._transact(run_stream(run_id), receive, command=command)
        self._wake(run_id, restart=True)
        return self.project(run_id)

    def _require_open(self, run_id: str, projection: RunProjection, message: str) -> None:
        # 已经结束或已经中止的运行不再接收输入、指导与提示词
        if not projection.run_id:
            raise RunNotFoundError(run_id)
        if projection.status in TERMINAL_STATUSES or self._aborted(run_id):
            raise RunTerminalError(message)

    def _assign_new_inputs(self, transaction: Transaction) -> RunProjection:
        projection = transaction.projection
        if projection.status in TERMINAL_STATUSES or projection.input_version <= projection.product_work_input_version:
            return projection
        transaction.append(NewEvent(
            EventType.PRODUCT_INPUT_ASSIGNED, actor="system",
            department=self._input_department_of(self.item_definitions(projection.run_id)),
            state_before=projection.status, state_after="PRODUCT_SPEC",
            payload={"through_version": projection.input_version},
        ))
        return transaction.projection

    # 计时与安全节点在薄驱动（工单 #1512）：已经结算的用量读最小投影，当前这一段只有驱动知道。
    # 这里的入口给应用一侧的流程编排用，调用方与方法名不变
    def _elapsed_sec(self, run_id: str) -> float:
        return self._thin_driver.elapsed_sec(run_id)

    def _elapsed_ms(self, run_id: str) -> int:
        return self._thin_driver.elapsed_ms(run_id)

    def _session_used(self, run_id: str, session_id: str) -> SessionState:
        return self._thin_driver.session_used(run_id, session_id)

    def _start_session_segment(self, run_id: str, session_id: str) -> None:
        self._thin_driver.start_session_segment(run_id, session_id)

    def _settle_session_segment(self, run_id: str, session_id: str, run_elapsed_ms: int) -> int:
        return self._thin_driver.settle_session_segment(run_id, session_id, run_elapsed_ms)

    def _session_elapsed_sec(self, run_id: str, session_id: str) -> float:
        return self._thin_driver.session_elapsed_sec(run_id, session_id)

    def _pause_run_clock(self, run_id: str, exclude: str | None = None) -> None:
        self._thin_driver.pause_run_clock(run_id, exclude=exclude)

    def _resume_run_clock(self, run_id: str) -> None:
        self._thin_driver.resume_run_clock(run_id)

    def _settle_run_segment(self, run_id: str, department: str | None = None) -> int:
        return self._thin_driver.settle_run_segment(run_id, department=department)

    def _rebase_run_clock(self, run_id: str) -> None:
        self._thin_driver.rebase_run_clock(run_id)

    @property
    def _run_segment_ms(self) -> dict[str, int]:
        # 薄驱动记的「投影还没有结算的那几段」：测试用它把已用的运行时间安排到选定的时点（工单 #1520）
        return self._thin_driver.segment_ms

    def _wake(self, run_id: str, *, restart: bool = False) -> None:
        # 唤醒在薄驱动（工单 #1512）：在安全节点等待的一轮与运行到停止的循环都由它叫醒
        self._thin_driver.wake(run_id, restart=restart)

    def _on_close_run(self, run_id: str) -> None:
        # 会话结束（事务提交以后）执行的副作用：关闭会话并清理检查工作区。
        # MCP 会话的关闭在运行的执行循环收尾（run_until_stop 的收尾段，工单 #1175），
        # 不在这里做：这个钩子可能在写入口的工作线程里运行，跨事件循环等待 SDK 的会话关闭会挂起。
        # 清理错误（如 Windows 句柄长期占用）记录在 self._close_errors 供后续处理
        errors = self.sessions.close_run(run_id)
        if errors:
            self._close_errors.setdefault(run_id, []).extend(errors)

    def cancel(self, run_id: str, *, command: Command | None = None) -> RunProjection:
        # 已经结束的运行不变；否则先中止运行（之后的核对都得到停止）并写入取消，再取消正在进行的步骤：
        # 调用尝试因取消而失败的记录排在取消之后。写入出错时同样取消正在进行的步骤；取消步骤出错时再通知一次，
        # 错误交给调用方
        with self._cancelling(run_id):
            if self.project(run_id).status in TERMINAL_STATUSES:
                return self.project(run_id)
            self._abort.setdefault(run_id, Event()).set()
            try:
                self._transact(run_stream(run_id), lambda transaction: self._fail(
                    transaction, "cancelled", "run cancelled"), command=command)
            finally:
                _round_work, cancel_error = self._abort_run(run_id)
                if cancel_error is not None:
                    self._abort_run(run_id)
        if cancel_error is not None:
            raise cancel_error
        # run 进入终态时结束的试用会话把结束事件排了队（cleanup_run 在终态事件的提交之后的效果里运行）：
        # 这里已经在事务之外，把排队的结束事件写出来（工单 #1183）
        self.sessions.flush_trial_events(run_id)
        return self.project(run_id)

    def stop_for_upgrade(self, run_id: str, *, reason: str) -> RunProjection:
        # 因升级停止（ADR-0019，工单 #126、#322）：强制升级处理到的未结束 run 记为因升级停止，
        # 停止原因写在带版本定义的停止原因清单中；已经结束的 run 不变
        message = f"run event version differs from the current version: {reason}"
        self._transact(run_stream(run_id), lambda transaction: self._fail(transaction, STOP_REASON_UPGRADE, message))
        return self.project(run_id)

    def resume_incomplete_run(self, run_id: str) -> tuple[int, RunProjection] | None:
        # 启动时自动继续一个因进程中断而未结束的 run（工单 #16，ADR-0018、恢复契约 docs/design/recovery-contract-and-fault-matrix.md「角色任务的恢复」）：
        # 核对定义版本、核实结果未知的动作、取得执行权这三步在 `recovery.py`（S4c 工单 #863），
        # 薄驱动只把它接上并转交。
        # 事项冻结的形态不在发布里时（工单 #1392）：这个 run 停在原处，不换一份定义顶替、不进定义版本核对、
        # 不发决定请求、不报错；启动流程把原因写进项目流，换回带那一份形态的发布以后接着跑
        if not self.item_form_available(run_id):
            return None
        return self._recovery.resume(run_id)

    def _cancel_driver(self, round_work: RoundWork) -> None:
        # 停下这个会话：打开它自己的停止开关，取消正在进行的步骤；在安全节点等待重试的激活立即醒来。
        # 只停这个会话，不改变事项的状态（工单 #856）。实现在薄驱动（工单 #1513），这里保留同名转交
        self._thin_driver.cancel_round(round_work)

    async def run_until_stop(self, run_id: str) -> RunProjection:
        # 运行到停止的循环在薄驱动（工单 #1512）：等待工作的部门各开始一轮工作，等全部会话结束或事项到终态。
        # 外部方法的名称与返回值不变，调用方不用改
        return await self._thin_driver.run_until_stop(run_id)

    async def _no_new_work(self, run_id: str) -> RunProjection:
        # 没有部门可以开始一轮工作时的收尾在薄驱动（工单 #1512）：事项以什么结束由路由判断
        return await self._thin_driver.no_new_work(run_id)

    def start(self, run_id: str) -> asyncio.Task[RunProjection]:
        # 在当前事件循环中把这个 run 作为任务运行到停止（run_until_stop）；这个 run 已有任务时，新任务在它结束以后开始。
        # 停止以后与事项的执行走同一处结算（run_until_stop_and_settle），run 属于事项并已到终态时写入采纳（幂等，工单 #299）。
        # 任务出错时交给事件循环的异常处理报告
        previous = self._tasks.get(run_id)
        task = asyncio.get_running_loop().create_task(self._run_after(previous, run_id))
        self._tasks[run_id] = task
        task.add_done_callback(lambda done: self._task_done(run_id, done))
        return task

    def execution(self, run_id: str) -> asyncio.Task[RunProjection] | None:
        # 这个 run 正在进行的任务；没有时为空
        return self._tasks.get(run_id)

    def work_item_execution(self, run_id: str) -> asyncio.Task[Any] | None:
        # 这个事项的 run 正在进行的执行任务（由 start_work_item 建立）；没有时为空
        return self._work_item_tasks.get(run_id)

    # 执行与结算的入口（应用层与接口层 docs/design/app-and-interface.md「执行与结算的归属」）。
    # 3.4A 之前只有一个执行槽位：已有事项在执行时新建被拒绝（busy）

    def busy(self) -> bool:
        # 执行槽位是否被占用只按事件日志与正在开始的事项判断（#202、#219 的结论），不看进程内的任务表：
        # run_until_stop 读到终态事件就返回，执行任务从 self._tasks 摘除要等到事件循环的下一轮，
        # 这个窗口内任务表仍非空，但事件日志已经没有未结束的 run，按任务表判断会把这个窗口误判为占用。
        if getattr(self.projects, "starting", lambda: False)():
            return True
        unfinished = classify_startup_runs(self.store)
        return bool(unfinished.same_version or unfinished.other_version)

    def start_work_item(self, run_id: str) -> asyncio.Task[ProjectEvent | None]:
        # 在接口进程的事件循环中把事项的 run 作为任务运行；run 结束以后由流程编排结算（采纳）。
        # 任务出错时交给事件循环的异常处理报告
        previous = self._work_item_tasks.get(run_id)
        task = asyncio.get_running_loop().create_task(self._run_work_item(previous, run_id))
        self._work_item_tasks[run_id] = task
        task.add_done_callback(lambda done: self._work_item_task_done(run_id, done))
        return task

    async def _run_work_item(self, previous: asyncio.Task[Any] | None, run_id: str) -> ProjectEvent | None:
        # 事项的执行：运行到停止以后结算这一次 run，交回结算写入的项目事件（没有时为 None）
        if previous is not None:
            await asyncio.wait([previous])
        _projection, event = await self.run_until_stop_and_settle(run_id)
        return event

    async def _run_after(self, previous: asyncio.Task[RunProjection] | None, run_id: str) -> RunProjection:
        # 回答决定以后继续等入口：同样运行到停止并结算，交回停止时的运行状态
        if previous is not None:
            await asyncio.wait([previous])
        projection, _event = await self.run_until_stop_and_settle(run_id)
        return projection

    async def run_until_stop_and_settle(self, run_id: str) -> tuple[RunProjection, ProjectEvent | None]:
        # 运行一个 run 直到停止，停止以后由流程编排结算（应用层与接口层 docs/design/app-and-interface.md「执行与结算的归属」，工单 #299）。
        # 把 run 运行到停止的入口都在这里结算，不在各调用方各补一遍：事项开始（start_work_item）、
        # 回答决定以后继续（start）与启动时的自动继续（LoopSystem.resume_startup_runs）。
        # 结算是幂等的：不在终态、不属于事项、已经结算过或者没有交付与放行的 run 不再写入（projects.settle）
        projection = await self.run_until_stop(run_id)
        return projection, await asyncio.to_thread(self.projects.settle, run_id)

    def _work_item_task_done(self, run_id: str, task: asyncio.Task[Any]) -> None:
        if self._work_item_tasks.get(run_id) is task:
            del self._work_item_tasks[run_id]
        if not task.cancelled() and task.exception() is not None:
            task.get_loop().call_exception_handler({
                "message": f"work item run {run_id} stopped with an error",
                "exception": task.exception(), "task": task,
            })

    def _task_done(self, run_id: str, task: asyncio.Task[RunProjection]) -> None:
        if self._tasks.get(run_id) is task:
            del self._tasks[run_id]
        if not task.cancelled() and task.exception() is not None:
            task.get_loop().call_exception_handler({
                "message": f"run {run_id} stopped with an error", "exception": task.exception(), "task": task,
            })

    async def activate_once(self, run_id: str) -> RunProjection:
        # 开始一个部门的一轮工作（单步入口）：按关注的成果取下一个可以工作的部门。
        # 这条入口自成一个事件循环（LoopSystem.activate_once 用 asyncio.run 运行它），激活结束时
        # 这个循环退出：这个 run 的 MCP 会话随收尾关闭（网络与 MCP docs/design/network-and-mcp.md「运行规则」「run 结束、
        # 暂停或停止时关闭」，工单 #1175），下一次激活按同一台服务器重新建立
        connections = ProviderConnections()
        try:
            return await self._activate_once(run_id, connections)
        finally:
            await self._close_mcp_sessions(run_id)
            await connections.aclose()

    def item_definitions(self, run_id: str):
        # 这个 run 的定义副本（网络与 MCP docs/design/network-and-mcp.md「版本与固定」、「工具的提供」，工单 #1175）：事项冻结的形态（工单 #1392）
        # 加上 run_created 里冻结的 MCP 设置带来的工具；没有设置或没有可用快照时就是那一份形态的定义本身
        cached = self._item_definitions.get(run_id)
        if cached is not None:
            return cached
        definitions = mcp_session.item_definitions(self.item_form(run_id).definitions, self._mcp_document(run_id))
        if self.store.list_events(run_id):
            # 还没有 run_created 的 run 不记：创建时按给出的那份形态算
            self._item_definitions[run_id] = definitions
        return definitions

    def form_named(self, name: str | None) -> Form:
        # 名字对应的形态（工单 #1392，项目的组织设计说明「冻结与升级」）：没有记形态名（旧事项）时用默认的
        # 那一份；记了而发布里没有这一份时**不回退**默认形态——新建事项被拒绝并给同样的说明，已经在跑的事项
        # 停在原处（见 `item_form_available`）
        if not name:
            return self._forms[DEFAULT_FORM]
        form = self._forms.get(name)
        if form is None:
            raise ValueError(f"unknown form {name!r}: the release loads {sorted(self._forms)}")
        return form

    def item_form(self, run_id: str) -> Form:
        # 这个事项创建时冻结的形态（工单 #1392，形态与核验角色设计说明「形态随事项冻结」）：
        # 取 run_created 里记下的形态名；旧事件没有记时用默认的那一份。项目后来改了形态不影响它；
        # 记了而发布里没有这一份时抛出（见 `form_named`），不换一份定义顶替
        cached = self._item_forms.get(run_id)
        if cached is not None:
            return cached
        form = self.form_named(self.recorded_form(run_id))
        if self.store.list_events(run_id):
            # 还没有 run_created 的 run 不记：创建时按给出的那份形态算
            self._item_forms[run_id] = form
        return form

    def recorded_form(self, run_id: str) -> str | None:
        # run_created 里记下的形态名（工单 #1392）：旧事件没有这个字段时为空，按默认的那一份读
        for event in self.store.list_events(run_id):
            if event.type == EventType.RUN_CREATED:
                return (event.payload or {}).get("form")
        return None

    def completion_stop_reason(self, transaction: Transaction) -> str:
        # 事项完成时的结束原因由路由给（工单 #1394，形态与核验角色设计说明「开环完成」与「定义的校验」
        # 第 4 条，骨架与应用 docs/design/skeleton-and-application.md「路由契约」输出）：路由读事项创建事件里记下的开环标记，经契约的可选方法
        # 给出这个事项完成时的结束原因；薄驱动只把路由给的原因写进事实，不判断它是哪一种。
        # 没有声明这个方法的路由（例如任务池那一种）与路由不给原因时，按事项种类取（原来的做法）
        projection = transaction.projection
        declared = getattr(self._item_routing(projection.run_id), "completion_reason", None)
        if callable(declared):
            given = declared(projection, transaction.events())
            if given is not None:
                return given.stop_reason
        return self.item_definitions(projection.run_id).work_item(projection.kind).stop_reason

    def item_form_available(self, run_id: str) -> bool:
        # 这个 run 冻结的形态在发布里（工单 #1392，项目的组织设计说明「冻结与升级」最后一条）：
        # 创建记录里没有形态名的旧事项按默认形态算。不在发布里时事项停在原处，不换一份定义顶替
        name = self.recorded_form(run_id)
        return not name or name in self._forms

    def _item_routing(self, run_id: str) -> Any:
        # 这个事项用的路由实现：由它冻结的形态决定（工单 #1392）
        return self.item_form(run_id).routing

    def _item_tightening(self, run_id: str) -> Any:
        # 这个事项用的收紧检查：由它冻结的形态决定（工单 #1392）
        return self.item_form(run_id).tightening

    def mcp_sessions(self, run_id: str) -> mcp_session.McpSessions:
        # 这个 run 的 MCP 会话表（网络与 MCP docs/design/network-and-mcp.md「运行规则」，工单 #1175）：每台服务器一个会话实例，
        # 第一次 MCP 调用时启动，run 结束、暂停或停止时关闭（`_on_close_run`）。会话表按 run 记住；
        # 没有冻结的 MCP 设置的 run 也有这张表（空表，调用在名称表核对时拒绝）
        table = self._mcp_sessions.get(run_id)
        if table is None:
            table = mcp_session.McpSessions(
                self._mcp_document(run_id), credentials=self.facade.credential_chain(),
                stderr_dir=self.data_dir,
                # 生命周期事件写在 run 流里（工单 #1176）：会话表在启动、关闭与失败时经这个写入方写一条
                events=lambda event_type, payload: self._mcp_server_event(run_id, event_type, payload))
            self._mcp_sessions[run_id] = table
        return table

    def _mcp_document(self, run_id: str) -> dict | None:
        # run_created 里冻结的 MCP 设置：与定义副本读同一份（没有时为空，按空设置读取）
        for event in self.store.list_events(run_id):
            if event.type == EventType.RUN_CREATED:
                return (event.payload or {}).get("mcp_servers")
        return None

    def _mcp_server_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        # MCP 服务器的生命周期事件（网络与 MCP docs/design/network-and-mcp.md「运行规则」，工单 #1176）：会话表在启动、关闭与
        # 启动失败时经这里把一条应用事件写到这个 run 的流。写入不改变运行的状态（状态前后都是当时的
        # 状态），提出者是系统；写不进去不打断会话的建立与关闭，原因记下来供运维查看（与清理错误同一做法）
        def decide(transaction: Transaction) -> None:
            status = transaction.projection.status
            transaction.append(NewEvent(
                event_type, state_before=status, state_after=status, actor="system",
                department=transaction.projection.active_department, payload=payload))

        try:
            self._transact(run_stream(run_id), decide)
        except Exception as exc:
            self._close_errors.setdefault(run_id, []).append(exc)

    def _trial_session_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        # 试用会话的开始与结束事件（浏览器与 computer use docs/design/browser-and-computer-use.md「事件、决定请求与查询」，工单 #1183）：会话表在开始与
        # 结束时经这里把一条应用事件写到这个 run 的流。与 MCP 的生命周期事件同一个做法：写入不改变运行的
        # 状态，提出者是系统，部门是会话所在的那一个；写不进去不打断会话的建立与结束，原因记下来供运维查看
        def decide(transaction: Transaction) -> None:
            status = transaction.projection.status
            transaction.append(NewEvent(
                event_type, state_before=status, state_after=status, actor="system",
                department=payload.get("department"), payload=payload))

        try:
            self._transact(run_stream(run_id), decide)
        except Exception as exc:
            self._close_errors.setdefault(run_id, []).append(exc)

    async def _close_mcp_sessions(self, run_id: str) -> None:
        # run 结束（或暂停、停止）以后关闭它的全部 MCP 会话：stdio 先关标准输入，SDK 等待以后结束
        # 整个进程树；HTTP 关闭会话。表随关闭清空，重启或继续同一个 run 时按同一台服务器重新建立；
        # 关闭失败不阻塞 run 的收尾，原因记下来供运维查看（与检查工作区的清理错误同一做法）
        table = self._mcp_sessions.pop(run_id, None)
        if table is None:
            return
        try:
            await table.close()
        except Exception as exc:
            self._close_errors.setdefault(run_id, []).append(exc)

    def mcp_sessions_open(self) -> tuple[str, ...]:
        # 还有会话表在的 run：服务关闭时逐个收掉（runtime.close）
        return tuple(self._mcp_sessions)

    def close_mcp_sessions_sync(self, run_id: str) -> None:
        # 在没有运行中的事件循环时关闭一个 run 的 MCP 会话（服务关闭、测试收尾）：
        # 直接跑完关闭，错误记下来
        table = self._mcp_sessions.pop(run_id, None)
        if table is None:
            return
        try:
            asyncio.run(table.close())
        except Exception as exc:
            self._close_errors.setdefault(run_id, []).append(exc)

    async def _activate_once(self, run_id: str, connections: ProviderConnections) -> RunProjection:
        projection = self.project(run_id)
        department = self._item_routing(run_id).next_department(projection, waiting=self._waiting_departments(run_id))
        if department is None:
            return await self._no_new_work(run_id)
        return await self.activate_department(run_id, department, connections)

    async def activate_department(self, run_id: str, department: str,
                                  connections: ProviderConnections) -> RunProjection:
        # 这个部门的一轮工作由薄驱动跑完（工单 #1513）：准备（选模型与提示词在应用一侧）、取派发编号、
        # 开始执行、把结果经写入口写回与收尾都在那里；这里保留同名入口给调用方与钩子
        return await self._thin_driver.activate_department(run_id, department, connections)

    def _prepare_activation(self, run_id: str, transaction: Transaction,
                            connections: ProviderConnections, department: str) -> RoundPreparation | None:
        # 一轮工作的准备（薄驱动的 `prepare_round` 钩子）：检查能不能开始、取模型与提示词、准备会话；
        # 开始这一轮的派发编号与开始事件由薄驱动在同一个事务里写（工单 #1513）
        projection = transaction.projection
        if not projection.run_id:
            raise RunNotFoundError(run_id)
        # 已用量不在这里恢复：运行时间、激活次数与模型步数都读最小投影（S1e 工单 #1015）
        self._resume_run_clock(run_id)
        if self._aborted(run_id):
            return None
        if blocks_run(transaction.decisions.values()):
            # 等待用户回答阻塞 run 或某个动作的决定请求：不开始新的激活，什么也不写
            return None
        projection = self._assign_new_inputs(transaction)
        if projection.status in TERMINAL_STATUSES:
            return None
        minimal = transaction.minimal()
        bound = round_bound(minimal, self._elapsed_sec(run_id))
        if bound is not None:
            if bound == TIME_BOUND:
                self._fail(transaction, bound, time_limit_message(minimal, self._elapsed_sec(run_id)))
            else:
                self._pause(transaction, bound)
            return None
        # 开始一轮工作的部门由它关注的成果决定（循环结构 docs/design/department-loop.md「职能按关注的成果开始工作」）：
        # 关注的成果有了新东西、部门在等待工作时，它开始一轮工作。
        # 同时运行（工单 #557）：这个部门在准备激活之前可能已经别人的工作做完了，
        # 这时不再开始一轮工作。
        if not self._department_ready(run_id, projection, department):
            return None

        if self.test_adapter_factory is not None:
            # 确定性测试适配器没有目录条目：表示成一个 fake 协议的模型访问定义并绑定三个部门，
            # 用这一次声明的窗口（没有声明时保留目录里已登记的窗口），使步骤驱动的每次解析与真实
            # Provider 走同一条路径（#45 架构答复第 6 条）。部门按这个事项冻结的形态绑定（工单 #1509）
            self._install_test_call_target(self._test_context_windows.get(projection.run_id),
                                           self.item_definitions(run_id).departments)
            try:
                adapter = self.test_adapter_factory(department)
            except Exception as exc:
                self._await_model(transaction, department, None, "provider_unavailable",
                                  f"test adapter creation failed: {exc}")
                return None
        else:
            if self.facade is None:
                self._fail(transaction, "provider_error", "provider facade is required for runs")
                return None
            # 调用目标在每次逻辑调用之前按部门默认解析（#45）：激活只建立桥接，控制核心不持有凭据
            adapter = FacadeAdapter(self.facade, connections=connections)

        availability = adapter.availability()
        if not availability.available:
            # 确定性测试适配器在激活开始时不可用：run 停在这次请求之前，等待用户修复配置后回答
            self._await_model(transaction, department, self._adapter_target_metadata(adapter),
                              availability.reason or "provider_unavailable", availability.message)
            return None

        try:
            session = self.sessions.get(run_id, department)
        except KeyError:
            ids = {item.department: item.session_id for item in projection.sessions.values()}
            # 会话按这个事项冻结的形态的部门建（工单 #1509）：改名后的部门也要有自己的会话
            self.sessions.create_run_sessions(run_id, ids,
                                              departments=self.item_definitions(run_id).departments)
            session = self.sessions.get(run_id, department)

        activation_id = new_id("act")
        transaction.on_commit(lambda: session.activate(activation_id))
        # 部门 Prompt 每次激活从项目部门设置读取，run 内没有副本；没有写入时使用内置默认 Prompt。
        # 按部门取模型与提示词的这份来源随开始一轮工作的请求一起交给执行实现（第三版，工单 #1511）
        settings = self._department_settings(projection)
        prompt = settings.department_prompt(department)
        basis = work_basis(projection, department)
        guidance_ids = tuple(item.id for item in pending_guidance(projection, department))
        # 这一轮的身份与依据交给薄驱动：派发编号与开始事件由它写（工单 #1513）
        return RoundPreparation(
            session_id=session.session_id, activation_id=activation_id, prompt=prompt, adapter=adapter,
            settings=settings, basis=basis, guidance_ids=guidance_ids,
            provider=self._activation_provider(adapter),
        )

    def _round_environment(self, round_work: RoundWork) -> tuple[Any | None, RoundFailure | None]:
        # 这一轮用哪份工作区（S4c 工单 #863）：检查工作区从运行工作区建立，建立源里的无法表示条目、
        # 不可判定的忽略规则与读不出的封存交付各自有停止原因；绑定之后的读取错误由执行实现照常记下
        scope = round_work.scope
        run_id, department = scope.run_id, scope.department
        projection = self.project(run_id)
        try:
            environment = self._workspaces.environment_for(run_id, department, refresh=True)
        except UnrepresentableWorkspace as exc:
            # 非质检会话的检查工作区从运行工作区建立，建立源里的无法表示条目与激活开始后发现的同类：
            # 以 workspace_unrepresentable 暂停，而不是当作存储故障终止
            return None, RoundFailure("workspace_unrepresentable", str(exc), list(exc.paths))
        except IgnoreRulesUndecidable as exc:
            # 建立检查工作区时主机判断不了忽略规则：与装配请求、工具执行等位置同一个结局，
            # 以 host_commit_error 停止，说明带诊断原文（docs/design/local-tools.md「工具边界」，工单 #604）
            return None, RoundFailure("host_commit_error", str(exc))
        except (ValueError, OSError) as exc:
            # 检查工作区的建立源读不出来（质检的封存交付归档缺失或损坏）：不退回运行工作区
            # （ADR-0038 与 docs/design/local-tools.md「工作区」：检查工作区从封存的交付建立）。这次激活无法开始，
            # 以 host_commit_error 正式终止并报告真实原因，与提交判断对同一缺陷的报告方式一致
            return None, RoundFailure(
                "host_commit_error",
                f"the persisted delivery tree cannot be read for the {department} "
                f"inspection workspace: {exc}")
        try:
            self._workspaces.bind(environment, projection, activation_id=scope.activation_id,
                                  effective_contract_hash=scope.basis.effective_contract_hash)
        except UnrepresentableWorkspace as exc:
            # 打开工作区或驱动开始前发现无法表示的条目：以 workspace_unrepresentable 暂停，
            # 条目在工作区内的相对路径写进决定请求的事实引用
            return None, RoundFailure("workspace_unrepresentable", str(exc), list(exc.paths))
        except IgnoreRulesUndecidable as exc:
            # 激活开始前主机判断不了忽略规则：同一个结局，以 host_commit_error 停止（工单 #604）
            return None, RoundFailure("host_commit_error", str(exc))
        except Exception as exc:
            # 工作区打不开：依据是轮次开始时的运行状态
            return None, RoundFailure("provider_error", f"{type(exc).__name__}: {exc}")
        return environment, None

    def _round_dependencies(self, round_work: RoundWork, environment: Any) -> RoundDependencies:
        # 开始一轮工作交给执行实现的依赖（执行契约的 dependencies）：装配、工件、模型访问、定义与工作区
        # 都在这里取一次；这一轮的上限按会话剩余的步数，工作引用来自路由（工单 #861、#862）
        scope = round_work.scope
        run_id = scope.run_id
        return RoundDependencies(
            execution=self._execution,
            assembly=self.assembly,
            artifacts=self.artifacts,
            facade=self.facade,
            deltas=self.deltas,
            tightening=self._item_tightening(run_id),
            definitions=self.item_definitions(run_id),
            mcp_sessions=self.mcp_sessions(run_id),
            environment=environment,
            limits=self._session_limits(run_id, scope.session_id),
            work_ref=self._item_routing(run_id).work_reference(self.project(run_id), department=scope.department),
            refresh_workspace=self._workspaces.refresh_for(self._round_workspace(round_work)),
        )

    @staticmethod
    def _describe_failure(exc: Exception) -> RoundFailure | None:
        # 应用自己的异常翻成停止原因（执行实现开始时与提交提案时都可能抛出）；其余由薄驱动按阶段结束
        if isinstance(exc, UnrepresentableWorkspace):
            return RoundFailure("workspace_unrepresentable", str(exc), list(exc.paths))
        if isinstance(exc, IgnoreRulesUndecidable):
            return RoundFailure("host_commit_error", str(exc))
        return None

    def _apply_round_result(self, round_work: RoundWork, result: Any, current: RunProjection) -> None:
        # 一轮正常结束以后由应用问路由这一轮以什么结束，再经写入口提交提案（工单 #861）：
        # 路由说这一轮不是正常结束时不提交；提案的取舍在 `_apply_proposal`
        scope = round_work.scope
        ended = self._item_routing(scope.run_id).round_end(
            current, list(result.events), department=scope.department,
            session_id=scope.session_id, activation_id=scope.activation_id)
        if ended is None:
            return
        submission = result
        transcript_ref = None
        if submission.transcript:
            ref = self.artifacts.put(scope.run_id, "transcript", submission.transcript, media_type="text/plain")
            transcript_ref = ref.__dict__
        self._apply_proposal(
            scope.run_id, department=scope.department, projection=current, proposal=submission.submission,
            transcript_ref=transcript_ref, parent_event_id=scope.parent_event_id,
            session_id=scope.session_id,
            provider=submission.response.provider or self._activation_provider(round_work.adapter),
            model=submission.response.model,
        )

    def _after_round_finished(self, transaction: Transaction, round_work: RoundWork,
                              happened: list[Any]) -> None:
        # 这一轮收到的指导在这一轮正常结束时由主机写已回答（部门指导 docs/design/department-guidance.md「处理结果与来源」，工单 #1039）：
        # 与激活结束在同一个事务里，部门不提交。事件记下是哪一轮、这一轮怎么结束的；
        # 取消、运行时间用完、上限停下与暂停都不算正常结束，指导停在已进入模型输入。
        # 一轮以什么结束由路由判断（工单 #825）：不是正常结束的一轮没有结果，也照旧不写已回答
        scope = round_work.scope
        current = transaction.projection
        ended = self._item_routing(scope.run_id).round_end(
            current, happened, department=scope.department, session_id=scope.session_id,
            activation_id=scope.activation_id)
        if ended is None:
            return
        answered = _round_applied_guidance(happened, current, scope)
        if not answered:
            return
        for guidance_id in answered:
            transaction.append(NewEvent(
                EventType.DEPARTMENT_GUIDANCE_RESPONDED,
                actor="system",
                department=scope.department,
                parent_event_id=scope.parent_event_id,
                state_before=current.status,
                state_after=current.status,
                session_id=scope.session_id,
                payload={"guidance_id": guidance_id,
                         "activation_id": scope.activation_id,
                         "outcome": ended.outcome},
            ))


    def _department_settings(self, projection: RunProjection) -> _DepartmentSettings:
        # 按部门取模型与提示词的来源（执行契约第三版，工单 #1511）：事项所用定义与项目层在开始一轮工作时取一次，
        # 每个部门的值在问的时候读——项目部门设置在轮中改了，同一次激活的下一次请求就用新的
        return _DepartmentSettings(projection.run_id, projection.project_id, self.projects,
                                   self.artifacts, self.item_definitions(projection.run_id))

    def _safe_node(self, round_work: RoundWork, declared: int) -> execution_contract.SafeNode:
        # 安全节点接口由薄驱动实现（工单 #1512）：按执行实现声明的契约版本给，当前版拿到设计说明写的五样；
        # 声明上一版（第二版）的实现还会问按部门取模型与提示词，那一版留一版
        return self._thin_driver.safe_node(round_work, declared)

    def _activation_provider(self, adapter: ModelAdapter) -> str:
        # 激活事件上的提供方名称：确定性测试适配器用它的名称；目录驱动的运行在每次请求解析出连接
        return getattr(adapter, "name", "test") if self.test_adapter_factory is not None else "directory"

    @staticmethod
    def _adapter_target_metadata(adapter: ModelAdapter) -> dict[str, Any]:
        # 解析之前模型引用就不可用时写进待恢复请求的目标：身份取自确定性适配器，解析相关的项留空
        provider = getattr(adapter, "name", "test")
        return {
            "provider_config_id": None,
            "model_id": None,
            "provider_name": provider,
            "protocol": "test",
            "base_url": None,
            "requested_provider": provider,
            "requested_protocol": "test",
            "requested_model": getattr(adapter, "model", "unknown"),
            "credential_ref": None,
            "credential_version": None,
            "context_window": None,
            "configured_max_output_tokens": None,
            "selection_source": None,
            "accepts_required_tool_call": None,
            "input_modalities": [],
            "reasoning_levels": [],
            "default_reasoning_level": None,
            "reasoning_mode": None,
            "requested_tier": None,
            "sent_tier": None,
        }

    def _session_limits(self, run_id: str, session_id: str, *, max_model_steps: int | None = None) -> StepLimits:
        # 这个会话这一步的步数上限（工单 #475）：会话上一次没有结束的激活用掉的模型步数
        # 从它自己的上限里扣掉，重新启动以后连续累计，不因中断清零。
        # 已经结束的激活不算在内：下一轮工作重新按上限开始。
        # 两个数都读最小投影（S1e 工单 #1015）：累计的模型步数减去上一次结算时的步数。
        # max_model_steps 给出时不按运行配置的全局上限，按这个数（询问分支的这一轮由路由给上限）
        base = self._run_step_limits(run_id)
        if max_model_steps is not None:
            base = replace(base, max_model_steps=max_model_steps)
        session = self._session_used(run_id, session_id)
        used = max(0, session.model_steps - session.settled_steps)
        if used <= 0:
            return base
        return replace(base, max_model_steps=max(0, base.max_model_steps - used))

    def _run_step_limits(self, run_id: str) -> StepLimits:
        # 这个 run 的上限（工单 #1189）：组装处显式给出 step_limits 时整份照用（测试与运行配置），
        # 没有给时按 run 创建时冻结的 6 项参数构造；建 run 之后改参数事件不影响已经创建的 run
        if self.step_limits is not None:
            return self.step_limits
        frozen = parameter_values.frozen_run_parameters(self.project(run_id))
        return StepLimits(
            retry_initial_delay_sec=float(frozen["retry_initial_delay_sec"]),
            retry_max_delay_sec=float(frozen["retry_max_delay_sec"]),
            max_provider_attempts=int(frozen["max_provider_attempts"]),
            max_model_steps=int(frozen["max_model_steps"]),
            tool_call_required_limit=int(frozen["tool_call_required_limit"]),
            compaction_stalled_limit=int(frozen["compaction.stalled_limit"]),
        )

    async def _execute_ask(
        self,
        round_work: RoundWork,
        scope: ActivationScope,
        call: dict[str, Any],
    ) -> tuple[bool, Any, str | None, str | None, int]:
        # 询问分支由路由请求一轮工作（工单 #862，骨架与应用 docs/design/skeleton-and-application.md「路由契约」）：询问的开始、回问、
        # 回复给谁与这一轮的上限都归路由；薄驱动照常把这一轮交给执行契约运行。写事件、跑这一轮，
        # 以及把这个分支会话已经用掉的步数与时间从这一轮的上限里扣掉，归薄驱动（工单 #1015 的读法）
        stream = run_stream(scope.run_id)
        ask_limits = self._run_step_limits(scope.run_id)
        asked = self._item_routing(scope.run_id).ask_branch(
            self.project(scope.run_id), list(self.writes.read(stream).events()),
            requester=scope.department, session_id=scope.session_id, call=call,
            limits=routing_contract.AskLimits(
                max_model_steps=ask_limits.max_model_steps,
                department_max_model_steps=ask_limits.department_max_model_steps,
                department_max_time_sec=ask_limits.department_max_time_sec,
            ),
        )
        if isinstance(asked, routing_contract.AskRejection):
            # 这次询问的调用不合法（回复的部门不在定义里、问题为空）：不运行、不写事件，
            # 原因作为这次工具调用的错误交回提问方
            return False, None, asked.message, None, 0
        if isinstance(asked, routing_contract.AskOutcome):
            # 这一层询问已经答过（重新启动以后接着同一次询问）：结果照原样交回提问方，不再跑一轮
            steps = self._branch_steps(self.writes.read(stream).events(), asked.session_id)
            if asked.status == "answered":
                return True, asked.answer, None, None, steps
            return False, None, asked.reason, None, steps
        branch = asked
        if branch.start is not None:
            # 询问的开始：这一层是新开的一层，薄驱动把路由组好的这一层写进事件日志
            def start_ask(transaction: Transaction) -> None:
                transaction.append(NewEvent(
                    EventType.ASK_STARTED,
                    actor=f"department:{scope.department}",
                    department=scope.department,
                    parent_event_id=scope.parent_event_id,
                    session_id=scope.session_id,
                    state_before=transaction.projection.status,
                    state_after=transaction.projection.status,
                    payload=branch.start,
                ))

            self._transact(stream, start_ask)
        # 这个分支会话之前几轮用掉的步数从这一轮的上限里扣（工单 #475）：路由给的只是这一轮的上限，
        # 扣法与其他会话一致——最小投影里的累计步数减去已结算的那一部分（工单 #1015）
        branch_limits = self._session_limits(scope.run_id, branch.session_id,
                                             max_model_steps=branch.max_model_steps)
        # 这个分支会话已经用掉的时间从它自己的时限里扣掉（工单 #475）：
        # 中断以后继续时，剩余时间按已用时间连续累计
        used_time = self._session_elapsed_sec(scope.run_id, branch.session_id)
        deadline = time.monotonic() + max(0.0, branch.max_time_sec - used_time)
        if branch_limits.max_model_steps > 0:
            result = await self._run_ask_branch(round_work, scope, branch, limits=branch_limits,
                                                deadline=deadline)
            submission, stop_reason, message = result.submission, result.stop_reason, result.message
            response = result.response
            events_after = list(self.writes.read(stream).events())
            steps = self._branch_steps(events_after, branch.session_id)
        else:
            # 一步也走不了：这一轮不开，回答事件写明原因
            submission, stop_reason, message, response, steps = None, None, "", None, 0
        time_exhausted = (
            time.monotonic() >= deadline
            or time_used_up(self.writes.minimal(stream), self._elapsed_sec(scope.run_id))
        )
        outcome = self._item_routing(scope.run_id).ask_outcome(
            self.project(scope.run_id), branch=branch,
            result=routing_contract.AskRoundResult(
                submission=submission, stop_reason=stop_reason, message=message,
                time_exhausted=time_exhausted, steps_left=branch_limits.max_model_steps,
            ),
        )
        revision = None
        new_contract_hash = None
        if outcome.revises is not None:
            # 这一回答同时交上了正式成果（产品回答询问时修订 PRD）：成果的内容由路由组装，
            # 薄驱动照常经裁决入口核对、经写入口提交
            revision, new_contract_hash = self._commit_answer_revision(
                round_work, scope, branch, outcome.revises, response)
        with_spec_revision = outcome.revises is not None

        def record_ask_answered(transaction: Transaction) -> None:
            payload = {
                "requester": scope.department,
                "recipient": branch.recipient,
                "status": outcome.status,
                "answer": outcome.answer,
                "reason": outcome.reason,
                "with_spec_revision": with_spec_revision,
                "revision": revision,
            }
            if outcome.status == "answered":
                payload["facts"] = outcome.facts
                payload["explanation"] = outcome.explanation
            transaction.append(NewEvent(
                EventType.ASK_ANSWERED,
                actor=f"department:{branch.recipient}",
                department=branch.recipient,
                parent_event_id=scope.parent_event_id,
                session_id=branch.session_id,
                state_before=transaction.projection.status,
                state_after=transaction.projection.status,
                payload=payload,
            ))

        self._transact(stream, record_ask_answered)
        if outcome.status == "answered":
            return True, outcome.answer, None, new_contract_hash, steps
        return False, None, outcome.reason, None, steps

    def _commit_answer_revision(self, round_work: RoundWork, scope: ActivationScope,
                                branch: routing_contract.AskBranch, proposal: dict[str, Any],
                                response: Any) -> tuple[int, str]:
        # 回答同时交上的正式成果（循环结构 docs/design/department-loop.md「回答能做什么」）：提案与提出它的部门都由路由组装（`issuer`），
        # 薄驱动按读取时的运行状态与工作区事实校验，经写入口提交，并把新的合同带回这一步的提问方
        issuer = str(proposal["issuer"])

        def commit_prd_revision(transaction: Transaction) -> tuple[int, str]:
            projection = transaction.projection
            env = self._workspaces.new_inspection(scope.run_id, issuer, session_id=branch.session_id)
            decision = evaluate_proposal(
                AdjudicationView(minimal=transaction.minimal(), state=projection),
                department=issuer,
                proposal=proposal,
                facts=env.query(FactsQuery(tree=True)).tree,
                tightening=self._item_tightening(projection.run_id),
                events=transaction.events(),
                definitions=self.item_definitions(scope.run_id),
            )
            if not decision.accepted:
                raise RuntimeError(f"invalid prd revision: {decision.errors}")

            self._commit_accepted(
                transaction,
                department=issuer,
                snapshot=env.snapshot(),
                environment=env,
                artifact=decision.artifact,
                ends_run=decision.ends_run,
                parent_event_id=scope.parent_event_id,
                session_id=branch.session_id,
                provider=response.provider or self._activation_provider(round_work.adapter),
                model=response.model,
            )
            curr = transaction.projection
            return decision.artifact["revision"], artifact_hash(curr.effective_contract)

        revision, new_contract_hash = self._transact(run_stream(scope.run_id), commit_prd_revision)
        round_work.scope = replace(round_work.scope, basis=replace(
            round_work.scope.basis, effective_contract_hash=new_contract_hash))
        return revision, new_contract_hash


    def _branch_steps(self, events: list[Any], branch_session_id: str) -> int:
        # 这个分支会话用掉的模型步数：分支里再问一层时，回问的分支是它的下一层，
        # 那一层的步数逐层计入最初的提问方（工单 #473 的嵌套询问）。
        # 步数读最小投影里各会话的模型步数（S1e 工单 #1015），不在这里按事件一条条数
        sessions = {branch_session_id}
        grew = True
        while grew:
            grew = False
            for event in events:
                if event.type != EventType.ASK_STARTED or event.session_id not in sessions:
                    continue
                branch = (event.payload or {}).get("branch_session_id")
                if isinstance(branch, str) and branch not in sessions:
                    sessions.add(branch)
                    grew = True
        # 只记录的事件（旧派发编号）不并入，与写入口折最小投影用的是同一条规则
        minimal = fold_events(accepted(events))
        return sum(minimal.sessions.get(session_id, SessionState()).model_steps for session_id in sessions)

    async def _run_ask_branch(
        self,
        round_work: RoundWork,
        scope: ActivationScope,
        branch: routing_contract.AskBranch,
        *,
        limits: StepLimits,
        deadline: float,
    ) -> execution_contract.RoundResult:
        run_id, department, session_id = scope.run_id, branch.recipient, branch.session_id
        parent_event_id = scope.parent_event_id
        projection = self.project(run_id)
        # 按部门取模型与提示词的来源随这个分支的请求交给执行实现（第三版，工单 #1511）
        settings = self._department_settings(projection)
        prompt = settings.department_prompt(department)
        basis = work_basis(projection, department)
        activation_id = new_id("act_ask")

        def activate_branch(transaction: Transaction) -> Event:
            # 询问分支也是一轮工作：先取得这一轮的派发编号（工单 #1397），分支写入的事件都带它
            transaction.claim_dispatch_number(session_id)
            events = transaction.append(NewEvent(
                EventType.DISPATCH_NUMBER_ACQUIRED,
                actor="system",
                department=department,
                state_before=transaction.projection.status,
                state_after=transaction.projection.status,
                session_id=session_id,
                payload={"activation_id": activation_id, "cycle": transaction.projection.cycle_count},
            ), NewEvent(
                EventType.DEPARTMENT_ACTIVATED,
                actor="system",
                department=department,
                parent_event_id=parent_event_id,
                state_before=transaction.projection.status,
                state_after=transaction.projection.status,
                session_id=session_id,
                payload={
                    "activation_id": activation_id,
                    "cycle": transaction.projection.cycle_count,
                    "effective_contract_hash": artifact_hash(transaction.projection.effective_contract),
                    "input_version": transaction.projection.input_version,
                    "guidance_version": guidance_version(transaction.projection, department),
                    "prompt_version": prompt.version,
                    "prompt_hash": prompt.prompt_ref.content_hash,
                    "guidance_ids": [],
                },
            ))
            return events[1]

        act_event = self._transact(run_stream(run_id), activate_branch)
        # 这个分支会话这一段工作的起点（工单 #475）
        self._start_session_segment(run_id, session_id)

        branch_scope = ActivationScope(
            run_id, department, session_id, activation_id, act_event.event_id,
            prompt_version=prompt.version, prompt_hash=prompt.prompt_ref.content_hash,
            guidance_ids=[], basis=basis,
            provider=self._activation_provider(round_work.adapter),
            dispatch_number=act_event.dispatch_number or 0,
        )

        environment = self._workspaces.new_inspection(run_id, department, session_id=session_id)
        self._workspaces.bind(environment, projection, activation_id=activation_id,
                              effective_contract_hash=basis.effective_contract_hash)

        branch_activation = RoundWork(
            # 询问分支属于提问方的那个会话：它的停止开关就是那个会话的（工单 #856），
            # 那个会话停下时分支一起停下
            branch_scope, prompt, round_work.stop_flag, round_work.adapter, None, projection.stream_version,
            deadline=deadline, settings=settings,
        )
        # 询问分支照常按执行契约开始一轮工作：身份是这个分支会话的，这一轮的上限来自路由的请求
        # （薄驱动已经把这个分支会话之前用掉的步数扣掉）；路由自己的工作引用指向这次询问
        # （工单 #861、#862）。开始执行经薄驱动（工单 #1513）：它核对两个实现声明的版本（构造时已核对过）
        dependencies = RoundDependencies(
            execution=self._execution, assembly=self.assembly, artifacts=self.artifacts,
            facade=self.facade, deltas=self.deltas, tightening=self._item_tightening(run_id),
            definitions=self.item_definitions(run_id), environment=environment, limits=limits,
            work_ref=branch.work_ref,
            refresh_workspace=self._workspaces.refresh_for(self._round_workspace(branch_activation)),
        )
        driver = self._thin_driver.start_execution(
            branch_activation,
            execution_contract.RoundRequest(
                scope=branch_scope, prompt=prompt, limits=limits, work_ref=branch.work_ref,
                department_settings=settings,
            ),
            dependencies,
        )
        started = time.monotonic()
        try:
            result = await driver.result()
        finally:
            def finish_branch(transaction: Transaction) -> None:
                # 这个分支会话的累计用量读最小投影（S1e 工单 #1015）；它自己的已用时间含当前这一段，
                # 投影要等这条事件写进去才结算，所以由驱动算好写进事件
                session = transaction.minimal().sessions.get(session_id, SessionState())
                session_elapsed_ms = self._settle_session_segment(run_id, session_id, self._elapsed_ms(run_id))
                transaction.append(NewEvent(
                    EventType.ACTIVATION_FINISHED,
                    actor="system",
                    department=department,
                    parent_event_id=act_event.event_id,
                    state_before=transaction.projection.status,
                    state_after=transaction.projection.status,
                    session_id=session_id,
                    payload={
                        "activation_id": activation_id,
                        **branch_scope.versions(),
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "elapsed_ms": int(self._elapsed_sec(run_id) * 1000),
                        "activations": session.activations,
                        "model_steps": session.model_steps,
                        "session_elapsed_ms": session_elapsed_ms,
                        "session_activations": session.activations,
                        "session_model_steps": session.model_steps,
                        "stop_reason": None,
                    },
                ))
            self._transact(run_stream(run_id), finish_branch)
            # 这一轮的累计量已经写进事件：已结算量改由投影给出，停过表的段清零（S1e 工单 #1015）
            self._rebase_run_clock(run_id)
            try:
                cleanup_inspection_workspace(self.workspace_root / run_id, session_id)
                self._workspaces.forget(run_id, session_id)
            except Exception:
                pass
        return result


    def _apply_proposal(
        self,
        run_id: str,
        *,
        department: str,
        projection: RunProjection,
        proposal: dict[str, Any] | None,
        transcript_ref: dict[str, Any] | None,
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
    ) -> None:
        # 提案先按读取时的运行状态与工作区事实校验，并记下读取的流版本；提交以这个版本作为期望版本：
        # 事务中关闭过时的协作请求以后，由 U 按事务中的运行状态与工作区事实作提交判断，再写入提交、拒绝或接纳的事件。
        # 校验以后另一方写入了这个 run 时写入口拒绝提交，按写入以后的状态重新校验与判断（仍然有效就提交，
        # 否则按 execution_basis 拒绝）。
        # 工作区事实向执行环境查询；提交需要带文件内容的公开树（交付封存），提交判断使用同一次读取的事实
        # 提案由激活中的会话提交：用会话的执行环境查询工作区事实（工单 #481：非工程交接的会话使用检查工作区）
        while True:
            # 每次尝试按当前运行状态解析执行环境：取消等结束路径可能已经删除了检查工作区，
            # 重试时按同一根重新打开，读到的是这份工作区此刻的样子
            environment = self._workspaces.environment_for(run_id, department)
            evaluated = self.writes.read(run_stream(run_id))
            facts = environment.query(FactsQuery(tree=True)).tree
            view = AdjudicationView(minimal=evaluated.minimal(), state=evaluated.projection)
            decision = proposal_decision(view, department=department, proposal=proposal, facts=facts,
                                         tightening=self._item_tightening(run_id), events=evaluated.events(),
                                         definitions=self.item_definitions(run_id))
            try:
                self._transact(run_stream(run_id), lambda transaction: self._commit_proposal(
                    transaction, evaluated=evaluated, facts=facts, decision=decision, environment=environment,
                    department=department, proposal=proposal,
                    transcript_ref=transcript_ref, parent_event_id=parent_event_id, session_id=session_id,
                    provider=provider, model=model,
                ), expected_version=evaluated.version)
                return
            except StreamVersionConflict:
                continue

    def _commit_proposal(
        self,
        transaction: Transaction,
        *,
        evaluated: Snapshot,
        facts: TreeFacts,
        decision: ProposalDecision,
        environment: LocalEnvironment,
        department: str,
        proposal: dict[str, Any] | None,
        transcript_ref: dict[str, Any] | None,
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
    ) -> None:
        # 提交的事务：读取的流版本就是校验时的版本
        run_id = transaction.projection.run_id
        current = transaction.projection
        if current.status in TERMINAL_STATUSES or self._aborted(run_id):
            return
        current = self._assign_new_inputs(transaction)
        snapshot = environment.snapshot()
        judged = commit_decision(
            decision, department=department, proposal=proposal,
            evaluated=AdjudicationView(minimal=evaluated.minimal(), state=evaluated.projection), facts=facts,
            current=AdjudicationView(minimal=transaction.minimal(), state=current), current_facts=snapshot.facts,
            events=transaction.events(), tightening=self._item_tightening(run_id),
            definitions=self.item_definitions(run_id),
        )
        if proposal is not None:
            transaction.append(NewEvent(
                EventType.PROPOSAL_SUBMITTED, actor=f"department:{department}", department=department,
                parent_event_id=parent_event_id,
                state_before=current.status, state_after=current.status,
                session_id=session_id, provider=provider, model=model,
                payload={"kind": proposal.get("kind"), "transcript_ref": transcript_ref,
                         "raw_keys": sorted(proposal.keys()), "input_version": current.input_version,
                         "definitions_version": self.item_definitions(run_id).version,
                         "parameters_version": current.parameters_version},
            ))
            # 提交被写入以后唤醒正在安全节点等待的会话（工单 #561）：质检的放行可能正等着产品这一轮处理完输入
            transaction.on_commit(lambda: self._wake(run_id))
        if not judged.accepted:
            transaction.append(NewEvent(
                EventType.PROPOSAL_REJECTED, actor=f"department:{department}", department=department,
                parent_event_id=parent_event_id,
                state_before=current.status, state_after=current.status,
                session_id=session_id, provider=provider, model=model,
                payload={
                    "errors": judged.error_dicts,
                    "transcript_ref": transcript_ref,
                    "kind": None if proposal is None else proposal.get("kind"),
                    "input_version": current.input_version,
                    "definitions_version": self.item_definitions(run_id).version,
                    "parameters_version": current.parameters_version,
                },
            ))
            return
        self._commit_accepted(
            transaction, department=department, snapshot=snapshot, environment=environment,
            artifact=judged.artifact or {}, ends_run=judged.ends_run,
            parent_event_id=parent_event_id, session_id=session_id, provider=provider, model=model,
        )

    def _commit_accepted(
        self,
        transaction: Transaction,
        *,
        department: str,
        snapshot: WorkspaceSnapshot,
        environment: LocalEnvironment,
        artifact: dict[str, Any],
        ends_run: bool,
        parent_event_id: str,
        session_id: str,
        provider: str | None,
        model: str | None,
    ) -> None:
        projection = transaction.projection
        run_id = projection.run_id
        if projection.status in TERMINAL_STATUSES or self._aborted(run_id):
            return
        try:
            acceptance = self.submissions.prepare(
                transaction, projection=projection, snapshot=snapshot, environment=environment,
                artifact=artifact,
                department=department, parent_event_id=parent_event_id, session_id=session_id,
                provider=provider, model=model,
            )
        except Exception as exc:
            # 接纳所需的工件、材料或 Git 版本没有保存成功：提交的记录保留，运行在同一事务中以 host_commit_error 结束
            self._fail(transaction, "host_commit_error", f"{type(exc).__name__}: {exc}")
            return
        source_event = acceptance.append(transaction)
        self.submissions.record_accepted_lesson(transaction, source_event, projection, artifact)
        if asks_cannot_verify(artifact):
            # 质检无法核验（浏览器与 computer use docs/design/browser-and-computer-use.md「无法核验」，工单 #1179）：不是放行也不是退回，
            # 由流程编排发出决定请求，阻塞整个 run；等待回答期间恢复页显示待恢复
            self._await_cannot_verify(transaction, department=department, artifact=artifact,
                                      parent_event_id=parent_event_id)
            return
        # 只有质检的放行与基线核验的一致结论结束事项（工单 #556）：结束以后控制核心不再决定下一个谁工作
        if ends_run:
            # 进入完成状态的停止原因由路由给（工单 #1394）：路由读创建事件里记下的开环标记，按它的定义
            # 给出事项完成时的结束原因；没有声明这个方法的路由按事项种类取（普通事项与建档事项各自的取值）
            stop_reason = self.completion_stop_reason(transaction)
            self._withdraw_decisions(transaction, stop_reason)
            transaction.append(NewEvent(
                EventType.RUN_DONE,
                actor="system",
                department=department,
                parent_event_id=parent_event_id,
                state_before="running",
                state_after="done",
                session_id=session_id,
                stop_reason=stop_reason,
                payload={"stop_reason": stop_reason},
            ))
            transaction.on_commit(lambda: self._on_close_run(run_id))

    def _await_cannot_verify(self, transaction: Transaction, *, department: str, artifact: dict[str, Any],
                             parent_event_id: str) -> None:
        # 质检无法核验的决定请求：说明列出每条无法核验的验收条件与原因，选项是「重新核验」与「停止事项」
        projection = transaction.projection
        criteria = [{"criterion": row.get("criterion"), "note": row.get("note") or ""}
                    for row in artifact.get("criteria") or [] if row.get("result") == "unverified"]
        listed = "；".join(f"{item['criterion']}（{item['note'] or '没有写原因'}）" for item in criteria)
        transaction.append(NewEvent(
            EventType.DECISION_REQUESTED, actor="system", department=department,
            parent_event_id=parent_event_id,
            state_before=projection.status, state_after=projection.status,
            session_id=None,
            payload={
                "kind": QA_CANNOT_VERIFY.name, "blocks": QA_CANNOT_VERIFY.blocks,
                "options": [{"id": option.id, "label": option.label} for option in QA_CANNOT_VERIFY.options],
                "facts": [item["criterion"] for item in criteria],
                "department": department,
                "reason": "qa_cannot_verify",
                "criteria": criteria,
                "description": ("质检无法核验这些验收条件：" + listed + "。修改质检使用的模型（例如换成能看图的）"
                                "或在执行位置上装好缺少的程序以后选择「重新核验」，质检会以新的激活重新检查同一份交付；"
                                "选择「停止事项」则事项结束，这份交付不被采纳。"),
            },
        ))
        transaction.on_commit(lambda: self._wake(projection.run_id))

    @staticmethod
    def _failed_attempts(transaction: Transaction, activation_id: str) -> list[str]:
        # 这次激活中最后一次失败的调用尝试（这次请求无法发送或被拒绝的记录）
        failed = [event.event_id for event in transaction.events()
                  if event.type == EventType.MODEL_ATTEMPT_FAILED and event.payload["activation_id"] == activation_id]
        return failed[-1:]

    def _await_model(self, transaction: Transaction, department: str, target: dict[str, Any] | None,
                     reason: str, message: str, *, facts: list[str] | None = None) -> None:
        # 待恢复（模型管理 docs/design/model-management.md「引用无法使用时」、docs/design/model-management.md「失败处理」最后一条）：run 进入待恢复，停在这次请求（对整理是这次
        # 整理）之前，发出待恢复的决定请求，写明部门、模型与具体问题；不改用其他模型。已经结束或正在取消的
        # 运行不再写入
        projection = transaction.projection
        run_id = projection.run_id
        if projection.status in TERMINAL_STATUSES or self._aborted(run_id):
            return
        kind = MODEL_UNAVAILABLE
        model = "（没有找到调用目标）" if target is None else target["requested_model"]
        if reason == "compaction_failed":
            # 整理连续失败：用户可以先换这个部门的模型，再选「继续执行」，事项从这次整理接着进行
            description = (f"部门 {department} 的模型 {model} 连续整理没有推进：{message}"
                           "可以先换这个部门的模型，再选择「继续执行」，事项从这次整理接着进行，"
                           "已完成的工作与已收下的交付保留；选择「停止事项」则事项结束。")
        else:
            description = (f"部门 {department} 的模型 {model} 无法使用：{message}。修复模型配置或凭据以后选择"
                           "「继续执行」，事项从这次请求接着进行，已完成的工作与已用限额保留；"
                           "选择「停止事项」则运行结束。")
        transaction.append(NewEvent(
            EventType.DECISION_REQUESTED, actor="system", department=department,
            state_before=projection.status, state_after=projection.status,
            payload={
                "kind": kind.name, "blocks": kind.blocks,
                "options": [{"id": option.id, "label": option.label} for option in kind.options],
                "description": description,
                "facts": list(facts or []), "department": department, "target": target,
                "reason": reason, "message": message,
            },
        ))
        transaction.on_commit(lambda: self._wake(run_id))

    def answer_decision(self, decision_id: str, option: str, note: str | None, *, base_version: int,
                        command: Command) -> str | None:
        # 决定请求的处理在应用层（工单 #827）：薄驱动只转交。返回回答以后需要继续执行的 run，由调用方开始
        # （start）；没有时为空。核对不通过时的 DecisionNotFound、DecisionClosed、StaleDecision、
        # InvalidOption 与 NoteRequired 照旧向上抛出
        return self.decision_flow.answer_decision(self, decision_id, option, note, base_version=base_version,
                                                  command=command)

    def create_revision_run(self, project_id: str, candidate: Any, run_id: str, round_number: int,
                            note: str | None) -> None:
        # 建档修改轮的 run 在应用层建立（工单 #827）：进程在回答事务与 run 之间中断以后，项目服务补建时经这里
        self.decision_flow.create_revision_run(self, project_id, candidate, run_id, round_number, note)

    def wake(self, run_id: str) -> None:
        # 应用层的流转写完事实以后唤醒等新工作的会话（工单 #827）：这是它要薄驱动做的两件事之一
        self._wake(run_id)

    def fail_run(self, transaction: Transaction, reason: str, message: str) -> None:
        # 应用层的流转要结束一次运行时经这里记成失败（工单 #827）：撤销待回答的决定请求、写停止原因
        self._fail(transaction, reason, message)

    def _stop_reason(self, transaction: Transaction, reason: str):
        # 停止原因按这个事项冻结的形态的那份定义核对（工单 #1392）：路由自己的结束原因也在它那份清单里
        return self.item_definitions(transaction.projection.run_id).stop_reason(reason)

    def _withdraw_decisions(self, transaction: Transaction, reason: str) -> None:
        # 撤销未回答的决定请求：写入由薄驱动提供（工单 #1513），完成路径（接纳写入 RUN_DONE）也用它
        self._thin_driver.withdraw_decisions(transaction, reason)

    def _end(self, transaction: Transaction, reason: str, message: str,
             *, facts: list[str] | None = None) -> None:
        # 按定义中停止原因规定的方式暂停或结束运行在薄驱动（工单 #1513）：这里保留同名转交
        self._thin_driver.end(transaction, reason, message, facts=facts)

    def _pause(self, transaction: Transaction, reason: str, message: str | None = None,
               *, facts: list[str] | None = None) -> None:
        # 暂停的写入（停止原因、撤销决定请求、继续的决定请求）在薄驱动（工单 #1513）：这里保留同名转交
        self._thin_driver.pause(transaction, reason, message, facts=facts)

    def _request_pause_resume(self, transaction: Transaction, kind: DecisionKind, department: str,
                              reason: str, message: str | None,
                              facts: list[str]) -> None:
        # 暂停以后继续的决定请求：说明写明停止原因与人工处理说明，工作区无法表示的条目列为事实引用
        human = self._stop_reason(transaction, reason).human_action
        description = f"运行暂停，停止原因为 {reason}。{human}"
        if message:
            description = f"{description} 停止说明：{message}"
        transaction.append(NewEvent(
            EventType.DECISION_REQUESTED, actor="system", department=department,
            state_before="paused", state_after="paused",
            payload={
                "kind": kind.name, "blocks": kind.blocks,
                "options": [{"id": option.id, "label": option.label} for option in kind.options],
                "description": description, "facts": list(facts), "department": department,
                "stop_reason": reason,
            },
        ))
        transaction.on_commit(lambda: self._wake(transaction.projection.run_id))

    def _fail(self, transaction: Transaction, reason: str, message: str,
              *, input_save_failure: dict[str, str] | None = None) -> None:
        # 失败的写入（停止原因、撤销决定请求、教训候选）在薄驱动与它的钩子（工单 #1513）：这里保留同名转交
        self._thin_driver.fail(transaction, reason, message, input_save_failure=input_save_failure)

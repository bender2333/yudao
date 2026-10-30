from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .adapters.base import ModelAdapter
from .artifacts import ArtifactStore
from .assembly import ContextAssembly
from .deltas import DeltaChannel
from .decision_flow import DECISION_FLOW
from .definitions import DEFINITIONS
from . import parameters, routing_contract
from .engine import StepDriver, StepLimits
from .environment import LocalEnvironment, cleanup_run_inspections
from .event_store import Command, EventStore, catalog_stream
from .models import CatalogEventType, ProjectEventType, TERMINAL_STATUSES
from .orchestrator import CancelledInputSaveError, Orchestrator, RunTerminalError
from .write_path import NewCatalogEvent, WritePath
from .projection import RunNotFoundError, RunProjection, project_run
from .project_projection import catalog_handler, handler_for
from .projects import ProjectService, project_projection
from .providers import ProviderFacade
from .tightening import WATCHED_OUTPUTS
from .streams import (
    DRAIN_DRAINING, DRAIN_FINISHED, DRAIN_IDLE, DRAIN_READY, DRAIN_STARTED, FORCE_UPGRADE_REQUESTED,
    DrainState, classify_startup_runs, last_drain_event,
)
from .replay_check import verify_replay
from .workspace import Workspace

__all__ = [
    "LoopSystem",
    "CancelledInputSaveError",
    "RunTerminalError",
]


class LoopSystem:
    # 系统装配：持久化、独立 Provider 模块与原生编排器，空态可启动
    read_only = False

    def __init__(
        self,
        data_dir: str | Path,
        *,
        facade: ProviderFacade | None = None,
        test_adapter_factory: Callable[[str], ModelAdapter] | None = None,
        test_adapter: ModelAdapter | None = None,
        provider_config_path: str | Path | None = None,
        dotenv_path: str | Path | None = None,
        step_limits: StepLimits = StepLimits(),
        resume_on_startup: bool = True,
        assembly: Any | None = None,
        execution: Any | None = None,
    ) -> None:
        # 数据目录可能以 8.3 短路径给出（工单 #250）：在这里解析一次，工作区根、材料根与其余由它派生的根都从解析后的路径派生
        self.data_dir = Path(data_dir).absolute().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = EventStore(self.data_dir / "events.sqlite")
        # 输出片段通道：步骤驱动发布，应用层订阅并转发给 live=1 的连接（设计说明第 5.6 节）
        self.deltas = DeltaChannel()
        # 唯一的写入口；保存的投影缺失的流（例如投影被删除）在启动时由重放补建
        self.writes = WritePath(self.store, handler_for)
        self.writes.rebuild_missing()
        self.artifacts = ArtifactStore(self.data_dir / "artifacts")
        if test_adapter_factory is not None and facade is not None:
            raise ValueError("facade and test_adapter_factory are mutually exclusive")
        if test_adapter is not None and test_adapter_factory is not None:
            raise ValueError("provide test_adapter or test_adapter_factory, not both")
        if test_adapter is not None:
            test_adapter_factory = lambda _department: test_adapter
        self.test_adapter = test_adapter
        # 测试或演示方式启动的系统以 test 方式读取目录：fake 连接只在测试与演示下可用（工单 #86）。
        # 判据是生效的确定性适配器工厂：提供单个适配器时上面已把它换成工厂，
        # 只提供工厂的调用同样由它驱动的运行写入 fake 连接，也要按 test 方式读取
        startup_mode = "test" if test_adapter_factory is not None else "normal"
        self.facade = facade if facade is not None else ProviderFacade(startup_mode=startup_mode)
        if provider_config_path is not None or dotenv_path is not None:
            config = None if provider_config_path is None else Path(provider_config_path)
            dotenv = None if dotenv_path is None else Path(dotenv_path)
            self.facade.configure_paths(config, dotenv)
            # 启动读取一致版本：缺文件空态，有效修订与重载错误由模块记录，不抛错
            self.facade.reload()
        self.workspace_root = self.data_dir / "workspaces"
        # 装配实现与执行实现由组装处接上（工单 #979，骨架与应用设计说明第 5.2、5.3 节「接法」）：
        # 现在各只有一种产品实现，定义里不写它们的名字，默认接上的就是这一种；测试入口（for_testing）
        # 用同一个构造参数换成第二种。薄驱动不认这两个类的名字，只经装配契约与执行契约调用它们
        assembly_implementation = (ContextAssembly(self.artifacts, self.store, tightening=WATCHED_OUTPUTS)
                                   if assembly is None else assembly)
        execution_implementation = StepDriver if execution is None else execution
        self.orchestrator = Orchestrator(
            self.store,
            self.writes,
            self.artifacts,
            self.workspace_root,
            facade=self.facade,
            test_adapter_factory=test_adapter_factory,
            test_provider=(getattr(test_adapter, "name", "test") if test_adapter is not None else "test"),
            test_adapter_name=(getattr(test_adapter, "name", "test") if test_adapter is not None else "test"),
            test_model=(getattr(test_adapter, "model", "fake-script") if test_adapter is not None else "fake-script"),
            step_limits=step_limits,
            deltas=self.deltas,
            tightening=WATCHED_OUTPUTS,
            # 路由实现按组织定义里的名称接上（工单 #825）：watched_outputs 在模块加载时登记名称，
            # 定义加载时已经核对过这个名字在 routings.json 里；这里接上、核对契约版本、让它校验同一份定义，
            # 并把事件库的只读读取器交给声明了 use_facts 的路由（契约第三版，工单 #1164）
            routing=routing_contract.select(DEFINITIONS.routing, DEFINITIONS, store=self.store),
            # 决定请求的处理与建档的流转在应用层（工单 #827）：薄驱动接上它，只转交
            decision_flow=DECISION_FLOW,
            assembly=assembly_implementation,
            execution=execution_implementation,
        )
        self.git_versions = self.orchestrator.git_versions
        self.projects = ProjectService(self.store, self.writes, self.artifacts, self.orchestrator)
        # 流程编排的结算与执行槽位判断经项目服务完成（应用层与接口层设计说明第 7.2 节）
        self.orchestrator.projects = self.projects
        # 排空在服务下一次启动时结束（工单 #731）：启动时把还没结束的排空记成已结束，
        # 这个实例重新开始新事项。这一步在补建排队事项的 run 之前：
        # 排空结束以后那些事项这一次就补建并开始，之后新建的事项直接开始。
        self.drain_finished_on_startup = self.finish_drain_on_startup()
        # 启动时补做未完成的结算（#17 的「采纳结算幂等」）：run 已经结束、还在等结算的事项在这里补齐
        self.projects.settle_pending_on_startup()
        # 启动时补建缺少的建档修改轮 run（工单 #136，设计第 6 节）：回答「提出修改」以后
        # 修改轮事件已经写入项目流，run 在事务提交以后创建，两者之间中断时在这里补建
        self.recovered_revision_runs = self.projects.create_missing_revision_runs_on_startup()
        # 启动时扫描上次异常退出留下的检查工作区（工单 #481）：run 已经结束但 on_commit 没有跑过
        # 的目录在这里清掉；文件未删除时不阻塞启动
        self._cleanup_orphaned_inspections_on_startup()
        # 启动时补建缺少的普通事项 run（工单 #321，设计第 7 节）：work_item_created 已提交而 run 还没有创建时
        # 进程中断，这里按事项记录（含起始文件夹快照）补建
        self.recovered_work_item_runs = self.projects.create_missing_work_item_runs_on_startup()
        # 启动时核对 run 事件版本（ADR-0019，工单 #126、#322）：版本不同的未结束 run 按强制升级处理，
        # 停止并用项目的起点重新开始；处理完重新分类，新建的 run（当前版本）与版本相同的未结束 run
        # 一起由 #16 自动继续
        self.startup_runs = classify_startup_runs(self.store)
        self.upgrade_other_version_runs()
        # 启动的最后一步：自动继续未结束的 run（工单 #16）
        self.resumed_runs = self.resume_startup_runs() if resume_on_startup else {}
        # 目录文件被外部修改并发布以后补写 catalog_revised（应用层与接口层设计说明第 10 节第 1 项）
        self.facade.set_reload_listener(self.sync_catalog_revision)

    def upgrade_other_version_runs(self) -> tuple[list[str], list[str]]:
        # 启动时把 run 事件版本不同的未结束 run 按强制升级处理（ADR-0019，恢复契约第 1 节）：
        # 与排空期间由用户发起的强制升级同样停止并重新开始，启动时不记目录事件；处理完重新分类
        stopped, restarted = self.stop_and_restart_runs(self.startup_runs.other_version,
                                                         reason="run event version differs from the current version")
        self.startup_runs = classify_startup_runs(self.store)
        return stopped, restarted

    def stop_and_restart_runs(self, run_ids: Iterable[str], *, reason: str) -> tuple[list[str], list[str]]:
        # 强制升级对一批 run 的处理：逐个记为因升级停止，对应的事项用项目的起点重新开始，
        # 并记下「因升级重新开始」的优先级；找不到事项的 run 只停止
        stopped, restarted = [], []
        for run_id in run_ids:
            self.orchestrator.stop_for_upgrade(run_id, reason=reason)
            stopped.append(run_id)
            started = self.projects.restart_work_item_for_upgrade(run_id)
            if started is not None:
                restarted.append(started[0])
        return stopped, restarted

    def resume_startup_runs(self) -> dict[str, int]:
        # 启动时自动继续所有因进程中断而未结束的 run（工单 #16，恢复契约第 3、5.2 节）：
        # run 事件版本与当前不同的 run 已在启动序列里按强制升级处理，这里只有版本相同的 run；
        # 每个 run 由流程编排先核对事项记录的定义版本（不同时发出决定请求，不取得执行权），
        # 再原子取得执行权并记下中断位置与继续的依据；已经结束的 run 与等待用户回答的 run 不继续。
        # 3.1 保持单任务运行：取得执行权以后串行运行到停止，不并发推进两个 run。
        # 运行到停止与结算都经流程编排的 run_until_stop_and_settle（工单 #299）：这条入口与事项开始、
        # 回答决定以后继续共用同一处结算，不在这里各补一遍；服务进程里它是事件循环中的任务（_continue_run）
        # 返回取得执行权的 run 与它这次取得的执行权编号
        resumed: dict[str, int] = {}
        for run_id in self.startup_runs.same_version:
            claimed = self.orchestrator.resume_incomplete_run(run_id)
            if claimed is None:
                continue
            epoch, _ = claimed
            resumed[run_id] = epoch
            self._continue_run(run_id)
        return resumed

    def _continue_run(self, run_id: str) -> None:
        # 取得执行权以后运行到停止并结算：服务进程里控制核心在接口层的事件循环中运行（总体架构第 3 节第 2 条），
        # 这次运行是那个循环里的任务（与事项开始、回答决定以后继续同一条路径）；
        # 打开数据目录时还没有事件循环（测试、演示、命令行）时由 asyncio.run 运行到停止
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.orchestrator.run_until_stop_and_settle(run_id))
        else:
            self.orchestrator.start(run_id)

    @classmethod
    def _resume(cls, data_dir: str | Path, adapter: ModelAdapter) -> dict[str, int]:
        # 只取得执行权，不继续运行：测试用它表示「这一次恢复在取得执行权之后、继续执行之前退出」，
        # 下一次打开的进程因此必须重新取得执行权。与 for_testing 一样只接受显式的确定性适配器，
        # 并且不做启动时的自动继续（传 null 适配器），避免取得执行权以后又运行到停止
        system = cls(data_dir, test_adapter=adapter, resume_on_startup=False)
        for run_id in system.startup_runs.same_version:
            claimed = system.orchestrator.resume_incomplete_run(run_id)
            if claimed is not None:
                system.resumed_runs[run_id] = claimed[0]
        return system.resumed_runs

    # 排空与强制升级（应用层与接口层设计说明第 3.2 节「升级」，ADR-0019）

    @property
    def running_runs(self) -> int:
        # 还没有结束的 run 数：客户端在停止之前用它显示确认，也用于排空状态（设计说明第 4.4 节）
        unfinished = classify_startup_runs(self.store)
        return len(unfinished.same_version) + len(unfinished.other_version)

    @property
    def drain(self) -> DrainState:
        # 排空状态：未排空、排空中（还有 run 在进行）、已排空可以升级；正在进行的 run 数与期间排队的事项数
        # 排空在升级完成（换了版本）以后结束：最后一条排空事件是「排空已结束」时不再排空（工单 #731）
        running = self.running_runs
        last = last_drain_event(self.store.stream_events(catalog_stream()))
        if last is None or last.type == DRAIN_FINISHED:
            return DrainState(state=DRAIN_IDLE, version=0, running_runs=running)
        version = int(last.payload["version"])
        state = DRAIN_READY if running == 0 else DRAIN_DRAINING
        return DrainState(state=state, version=version, running_runs=running,
                          queued_work_items=len(self._queued_work_items()))

    def finish_drain_on_startup(self) -> bool:
        # 排空在服务下一次启动时结束（工单 #731，应用层与接口层设计说明第 3.2 节「升级」）：
        # 排空的用处是让服务可以停下来升级，服务一旦重新启动，这个用处就完成了。
        # 记一条「排空已结束」的事件，排空状态以后从事件里读得出来（跨版本保存的长期事实）。
        last = last_drain_event(self.store.stream_events(catalog_stream()))
        if last is None or last.type == DRAIN_FINISHED:
            return False
        version = self._drain_version() or 0

        def decide(transaction):
            transaction.append(NewCatalogEvent(
                DRAIN_FINISHED, {"version": version}, actor="system"))

        self.writes.transact(catalog_stream(), decide)
        return True

    def _drain_version(self) -> int | None:
        # 目录流中最后一条开始排空的事件给出的排空状态版本；没有开始排空时为空
        started = [event for event in self.store.stream_events(catalog_stream()) if event.type == DRAIN_STARTED]
        return None if not started else int(started[-1].payload["version"])

    def _queued_work_items(self) -> list[str]:
        # 排空期间新建、还没有开始的事项：事项已登记而它的 run 流还没有任何事件
        queued = []
        for project_id in self.store.list_project_ids():
            for item in project_projection(self.store, self.artifacts, project_id, include_history=False).work_items:
                try:
                    project_run(self.store, item.run_id)
                except RunNotFoundError:
                    queued.append(item.work_item_id)
        return queued

    def start_drain(self, *, command: Command | None = None) -> DrainState:
        # 开始排空：记下这一刻还没有结束的 run 数，之后新建的事项排队不开始；
        # 排空在服务下一次启动时结束（工单 #731）
        version = (self._drain_version() or 0) + 1
        unfinished = classify_startup_runs(self.store)
        running = len(unfinished.same_version) + len(unfinished.other_version)

        def decide(transaction):
            transaction.append(NewCatalogEvent(
                DRAIN_STARTED, {"version": version, "running_runs": running}, actor="system"))

        self.writes.transact(catalog_stream(), decide, command=command)
        return self.drain

    def force_upgrade(self, *, command: Command | None = None) -> DrainState:
        # 强制升级：正在进行的 run 记为因升级停止，对应的事项用已采纳成果重新开始，
        # 并记下「因升级重新开始」的优先级；只在排空期间可用，由应用层的命令核对
        unfinished = classify_startup_runs(self.store)
        stopped, restarted = self.stop_and_restart_runs(
            (*unfinished.same_version, *unfinished.other_version), reason="force upgrade")
        version = self._drain_version() or 0

        def decide(transaction):
            transaction.append(NewCatalogEvent(
                FORCE_UPGRADE_REQUESTED,
                {"version": version, "stopped_runs": stopped, "restarted_work_items": restarted}, actor="system"))

        self.writes.transact(catalog_stream(), decide, command=command)
        return self.drain

    def sync_catalog_revision(self, *, operation: str = "reload") -> int | None:
        # 目录修订号与最后一条 catalog_revised 不同就补写一条；相同或已补写过时什么也不写
        revision = self.facade.catalog_revision()

        def decide(transaction):
            if transaction.projection.revision == revision:
                return None
            transaction.append(NewCatalogEvent(CatalogEventType.CATALOG_REVISED, {
                "revision": revision,
                "base_revision": transaction.projection.revision or None,
                "operation": operation,
                "provider_id": None,
            }, actor="system"))
            return revision

        return self.writes.transact(catalog_stream(), decide)

    def mark_seen(self, position: int, *, command: Command | None = None) -> int:
        # 把用户查看过的全局位置更新为 position（工单 #127），写入目录流。控制主机上只有一个位置，
        # 上一次的查看位置由这次写入取代；位置必须在日志范围内（0 到日志末尾）
        end = self.store.end_position()
        if position < 0 or position > end:
            raise ValueError(f"seen position {position} is outside the log (end {end})")

        def decide(transaction):
            transaction.append(NewCatalogEvent(CatalogEventType.HOME_SEEN, {"position": position},
                                               actor="user:local"))

        self.writes.transact(catalog_stream(), decide, command=command)
        return position

    def set_parameter(self, name: str, value: Any, *, reason: str, modified_by: str,
                      command: Command | None = None) -> str:
        # 界内修改一次全局参数现值：先核对条目、是否已经接入行为与界限，通过后在目录流写一条 parameter_set。
        # 未接入的条目拒绝修改（工单 #643）。run 已经在创建时冻结参数版本，运行中修改不影响已经创建的 run。
        # 返回修改以后的参数版本
        new_value = parameters.check_parameter(name, value)
        values = parameters.current_values(self.store)
        old_value = values[name]
        after = {**values, name: new_value}
        version = parameters.parameters_version(after)
        bounds = list(DEFINITIONS.rule(name).bounds)

        def decide(transaction):
            transaction.append(NewCatalogEvent(CatalogEventType.PARAMETER_SET, {
                "name": name, "old_value": old_value, "new_value": new_value,
                "reason": reason, "modified_by": modified_by,
                "bounds": bounds, "parameters_version": version,
            }, actor=modified_by))

        self.writes.transact(catalog_stream(), decide, command=command)
        return version

    def parameters(self) -> dict[str, Any]:
        # 参数现值：目录流事件折叠的结果
        return parameters.current_values(self.store)

    def parameters_version(self) -> str:
        # 参数现值的版本摘要：全部参数条目当前取值的内容摘要
        return parameters.current_version(self.store)

    def parameter_history(self) -> list[parameters.ParameterChange]:
        # 参数修改历史：按事件顺序，包含修改者、原值、新值与理由
        return parameters.history(self.store)

    @property
    def home_seen(self) -> tuple[int, str] | None:
        # 用户查看过的全局位置与它的写入时间；从未查看过时为空
        saved = self.store.projection(catalog_stream())
        if saved is None:
            return None
        state = catalog_handler().load(saved)
        if state.last_seen_position is None:
            return None
        return state.last_seen_position, state.last_seen_at

    @property
    def provider_config_path(self) -> Path | None:
        return self.facade.config_path

    @property
    def dotenv_path(self) -> Path | None:
        return self.facade.dotenv_path

    @classmethod
    def for_testing(cls, data_dir: str | Path, adapter: ModelAdapter, *,
                    step_limits: StepLimits = StepLimits(),
                    resume_on_startup: bool = True,
                    assembly: Any | None = None,
                    execution: Any | None = None) -> "LoopSystem":
        # 显式提供的确定性适配器只用于确定性测试。resume_on_startup=False 用于测试自己控制激活的时机，
        # 打开数据目录时不自动继续未结束的 run（工单 #16）。
        # 模型目录放在数据目录里：调用目标（fake 模型定义）随数据目录一起保留，
        # 重开数据目录以后这一次运行按同一个调用目标继续，窗口不随进程消失（工单 #669）
        # assembly 与 execution 是装配实现与执行实现（工单 #979）：不给时由组装处接上默认的那一种，
        # 测试给第二种实现时走同一个构造参数，其余什么也不变
        config = Path(data_dir).absolute().resolve() / "providers.json"
        return cls(data_dir, test_adapter=adapter, step_limits=step_limits,
                   resume_on_startup=resume_on_startup, provider_config_path=config,
                   assembly=assembly, execution=execution)

    def start_provider_watching(self, interval_sec: float = 1.0) -> None:
        # 文件重载由系统装配启动，Web 只提交命令和读取状态
        self.facade.start_watching(interval_sec)

    def close(self) -> None:
        # 服务关闭停止轮询并释放存储
        self.facade.stop_watching()
        self.store.close()

    def provider_status(self) -> dict[str, Any]:
        # 服务健康与模型就绪分开描述，不露密钥
        if self.test_adapter is not None:
            availability = self.test_adapter.availability()
            return {
                "available": availability.available,
                "reason": availability.reason,
                "message": availability.message,
                "departments": {},
            }
        status = self.facade.describe_readiness()
        return {
            "available": status["available"],
            "reason": status["reason"],
            "message": status["message"],
            "departments": status["departments"],
        }

    def create_run(self, task: str, **kwargs) -> str:
        return self.orchestrator.create_run(task, **kwargs)

    def run_until_stop(self, run_id: str) -> RunProjection:
        # 公开方法保持同步调用方式：在内部的事件循环中运行，一次运行期间的模型调用复用同一组连接
        return asyncio.run(self.orchestrator.run_until_stop(run_id))

    def activate_once(self, run_id: str) -> RunProjection:
        return asyncio.run(self.orchestrator.activate_once(run_id))

    def cancel(self, run_id: str) -> RunProjection:
        return self.orchestrator.cancel(run_id)

    def add_input(self, run_id: str, text: str) -> RunProjection:
        return self.orchestrator.add_input(run_id, text)

    def add_guidance(self, run_id: str, department: str, text: str) -> RunProjection:
        return self.orchestrator.add_guidance(run_id, department, text)

    def project(self, run_id: str) -> RunProjection:
        return project_run(self.store, run_id)

    def workspace(self, run_id: str) -> Workspace:
        return Workspace(self.workspace_root / run_id)

    def environment(self, run_id: str) -> LocalEnvironment:
        # 检查的时限按这个 run 创建时冻结的取值（迭代底座 B3，工单 #351）
        return LocalEnvironment.open(self.workspace_root / run_id,
                                     check_timeout_sec=parameters.frozen_check_timeout(self.store, run_id))

    def _cleanup_orphaned_inspections_on_startup(self) -> None:
        # 启动扫描：上次进程异常退出时，部分事务的 on_commit 没有跑过，
        # 留下的 inspections 目录以「对应 run 已结束」为信号删除。run 还在进行时不删，
        # 下一个会话首次激活时按会话检查工作区规则重建。删除失败留给下次启动
        for run_id in self.list_run_ids():
            try:
                status = self.project(run_id).status
            except Exception:
                continue
            if status not in TERMINAL_STATUSES:
                continue
            try:
                cleanup_run_inspections(self.workspace_root / run_id)
            except (OSError, RuntimeError):
                pass

    def replay(self, run_id: str) -> RunProjection:
        return verify_replay(self.store, self.artifacts, self.git_versions, run_id)

    def list_run_ids(self) -> list[str]:
        return self.store.list_run_ids()

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .adapters.base import ModelAdapter
from .artifacts import ArtifactStore
from .engine import StepLimits
from .environment import LocalEnvironment
from .event_store import EventStore, catalog_stream
from .models import CatalogEventType, ProjectEventType
from .orchestrator import CancelledInputSaveError, Orchestrator, RunTerminalError
from .write_path import NewCatalogEvent, WritePath
from .projection import RunNotFoundError, RunProjection, project_run
from .projects import ProjectService
from .providers import ProviderFacade
from .streams import (
    DRAIN_DRAINING, DRAIN_IDLE, DRAIN_READY, DRAIN_STARTED, FORCE_UPGRADE_REQUESTED, RUN_EVENT_VERSION,
    STOP_REASON_UPGRADE, DrainState, classify_startup_runs,
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
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = EventStore(self.data_dir / "events.sqlite")
        # 唯一的写入口；保存的投影缺失的流（例如投影被删除）在启动时由重放补建
        self.writes = WritePath(self.store)
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
        )
        self.git_versions = self.orchestrator.git_versions
        self.projects = ProjectService(self.store, self.writes, self.artifacts, self.orchestrator)
        # 流程编排的结算与执行槽位判断经项目服务完成（应用层与接口层设计说明第 7.2 节）
        self.orchestrator.projects = self.projects
        # 启动时补做未完成的结算（#17 的「采纳结算幂等」）：run 已经结束、还在等结算的事项在这里补齐
        self.projects.settle_pending_on_startup()
        # 启动时核对 run 事件版本（ADR-0019，工单 #126）：版本相同的未结束 run 交给 #16 自动继续，这里不动它们；
        # 版本不同（含旧事件没有记录版本）的未结束 run 记为因升级停止，对应的事项用采纳成果重新开始
        self.startup_runs = classify_startup_runs(self.store)
        for run_id in self.startup_runs.other_version:
            self.upgrade_run(run_id)
        # 启动的最后一步：自动继续 run 事件版本相同的未结束 run（工单 #16）
        self.resumed_runs = self.resume_startup_runs() if resume_on_startup else {}
        # 目录文件被外部修改并发布以后补写 catalog_revised（应用层与接口层设计说明第 10 节第 1 项）
        self.facade.set_reload_listener(self.sync_catalog_revision)

    def upgrade_run(self, run_id: str) -> tuple[str, str] | None:
        # 按强制升级处理一个未结束的 run：记为因升级停止，再用项目当前的采纳成果为它所属的事项开始新的 run。
        # 已经结束的 run 不停止；没有对应事项的 run 只停止，不重新开始
        projection = self.orchestrator.stop_for_upgrade(
            run_id, reason=f"recorded version differs from {RUN_EVENT_VERSION}")
        if projection.phase == "FAILED" and projection.stop_reason == STOP_REASON_UPGRADE:
            return self.projects.restart_work_item_for_upgrade(run_id)

    def resume_startup_runs(self) -> dict[str, int]:
        # 启动时自动继续所有因进程中断而未结束、run 事件版本相同的 run（工单 #16，恢复契约第 3、5.2 节）：
        # 每个 run 由流程编排原子取得执行权并记下中断位置与继续的依据；已经结束的 run 与等待用户回答的 run 不继续。
        # 3.1 保持单任务运行：取得执行权以后串行运行到停止，不并发推进两个 run。
        # 返回取得执行权的 run 与它这次取得的执行权编号
        resumed: dict[str, int] = {}
        for run_id in self.startup_runs.same_version:
            claimed = self.orchestrator.resume_incomplete_run(run_id)
            if claimed is None:
                continue
            epoch, _ = claimed
            resumed[run_id] = epoch
            self.run_until_stop(run_id)
            self.projects.settle(run_id)
        return resumed

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
    def drain(self) -> DrainState:
        # 排空状态：未排空、排空中（还有 run 在进行）、已排空可以升级；正在进行的 run 数与期间排队的事项数
        unfinished = classify_startup_runs(self.store)
        running = len(unfinished.same_version) + len(unfinished.other_version)
        version = self._drain_version()
        if version is None:
            return DrainState(state=DRAIN_IDLE, version=0, running_runs=running)
        state = DRAIN_READY if running == 0 else DRAIN_DRAINING
        return DrainState(state=state, version=version, running_runs=running,
                          queued_work_items=len(self._queued_work_items()))

    def _drain_version(self) -> int | None:
        # 目录流中最后一条开始排空的事件给出的排空状态版本；没有开始排空时为空
        started = [event for event in self.store.stream_events(catalog_stream()) if event.type == DRAIN_STARTED]
        return None if not started else int(started[-1].payload["version"])

    def _queued_work_items(self) -> list[str]:
        # 排空期间新建、还没有开始的事项：事项已登记而它的 run 流还没有任何事件
        queued = []
        for project_id in self.store.list_project_ids():
            for item in self.projects.projection(project_id).work_items:
                try:
                    project_run(self.store, item.run_id)
                except RunNotFoundError:
                    queued.append(item.work_item_id)
        return queued

    def start_drain(self, *, command: Command | None = None) -> DrainState:
        # 开始排空：记下这一刻还没有结束的 run 数，之后新建的事项排队不开始
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
        stopped, restarted = [], []
        for run_id in (*unfinished.same_version, *unfinished.other_version):
            self.orchestrator.stop_for_upgrade(run_id, reason="force upgrade")
            stopped.append(run_id)
            started = self.projects.restart_work_item_for_upgrade(run_id)
            if started is not None:
                restarted.append(started[0])
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

    @property
    def provider_config_path(self) -> Path | None:
        return self.facade.config_path

    @property
    def dotenv_path(self) -> Path | None:
        return self.facade.dotenv_path

    @classmethod
    def for_testing(cls, data_dir: str | Path, adapter: ModelAdapter, *,
                    step_limits: StepLimits = StepLimits()) -> "LoopSystem":
        # 显式提供的确定性适配器只用于确定性测试
        return cls(data_dir, test_adapter=adapter, step_limits=step_limits)

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

    def update_prompt(self, run_id: str, department: str, text: str) -> RunProjection:
        return self.orchestrator.update_prompt(run_id, department, text)

    def add_guidance(self, run_id: str, department: str, text: str) -> RunProjection:
        return self.orchestrator.add_guidance(run_id, department, text)

    def project(self, run_id: str) -> RunProjection:
        return project_run(self.store, run_id)

    def workspace(self, run_id: str) -> Workspace:
        return Workspace(self.workspace_root / run_id)

    def environment(self, run_id: str) -> LocalEnvironment:
        return LocalEnvironment.open(self.workspace_root / run_id)

    def replay(self, run_id: str) -> RunProjection:
        return verify_replay(self.store, self.artifacts, self.git_versions, run_id)

    def list_run_ids(self) -> list[str]:
        return self.store.list_run_ids()

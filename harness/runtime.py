from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .adapters.base import ModelAdapter
from .artifacts import ArtifactStore
from .engine import StepLimits
from .event_store import EventStore
from .orchestrator import CancelledInputSaveError, Orchestrator, RunTerminalError
from .write_path import WritePath
from .projection import RunProjection, project_run
from .projects import ProjectService
from .providers import ProviderFacade
from .replay_check import verify_replay

__all__ = [
    "LoopSystem",
    "CancelledInputSaveError",
    "RunTerminalError",
]


class LoopSystem:
    # 系统装配：持久化、独立 Provider 模块与原生编排器，空态可启动
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
        self.facade = facade if facade is not None else ProviderFacade()
        if provider_config_path is not None or dotenv_path is not None:
            config = None if provider_config_path is None else Path(provider_config_path)
            dotenv = None if dotenv_path is None else Path(dotenv_path)
            self.facade.configure_paths(config, dotenv)
            # 启动读取一致版本：缺文件空态，有效修订与重载错误由模块记录，不抛错
            self.facade.reload()
        self.orchestrator = Orchestrator(
            self.store,
            self.writes,
            self.artifacts,
            self.data_dir / "workspaces",
            facade=self.facade,
            test_adapter_factory=test_adapter_factory,
            test_provider=(getattr(test_adapter, "name", "test") if test_adapter is not None else "test"),
            test_adapter_name=(getattr(test_adapter, "name", "test") if test_adapter is not None else "test"),
            test_model=(getattr(test_adapter, "model", "fake-script") if test_adapter is not None else "fake-script"),
            step_limits=step_limits,
        )
        self.git_versions = self.orchestrator.git_versions
        self.projects = ProjectService(self.store, self.writes, self.artifacts, self.orchestrator)

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

    def workspace(self, run_id: str):
        return self.orchestrator.workspace(run_id)

    def replay(self, run_id: str) -> RunProjection:
        return verify_replay(self.store, self.artifacts, self.git_versions, run_id)

    def list_run_ids(self) -> list[str]:
        return self.store.list_run_ids()

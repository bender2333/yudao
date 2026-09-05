"""Loop System 门面：装配 store、workspace、adapter 与 orchestrator。"""

from __future__ import annotations

from pathlib import Path

from .adapters.base import DepartmentAdapter
from .adapters.fake import FakeAdapter
from .adapters.omp import OmpConfig, OmpRpcAdapter
from .artifacts import ArtifactStore
from .event_store import EventStore
from .orchestrator import Orchestrator
from .projection import RunProjection, project_run


class LoopSystem:
    def __init__(self, data_dir: str | Path, adapter: DepartmentAdapter | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = EventStore(self.data_dir / "events.sqlite")
        self.artifacts = ArtifactStore(self.data_dir / "artifacts")
        self.adapter = adapter or FakeAdapter()
        self.orchestrator = Orchestrator(
            self.store,
            self.artifacts,
            self.data_dir / "workspaces",
            self.adapter,
        )

    def create_run(self, task: str, **kwargs) -> str:
        return self.orchestrator.create_run(task, **kwargs)

    def run_until_stop(self, run_id: str) -> RunProjection:
        return self.orchestrator.run_until_stop(run_id)

    def activate_once(self, run_id: str) -> RunProjection:
        return self.orchestrator.activate_once(run_id)

    def cancel(self, run_id: str) -> RunProjection:
        return self.orchestrator.cancel(run_id)

    def project(self, run_id: str) -> RunProjection:
        return project_run(self.store, run_id)

    def workspace(self, run_id: str):
        return self.orchestrator.workspace(run_id)

    def replay(self, run_id: str) -> RunProjection:
        return project_run(self.store, run_id)

    def list_run_ids(self) -> list[str]:
        return self.store.list_run_ids()


def build_adapter(name: str, **kwargs) -> DepartmentAdapter:
    if name == "fake":
        return FakeAdapter(kwargs.get("script"))
    if name == "omp":
        config = kwargs.get("config")
        if config is None:
            config = OmpConfig.from_env()
        return OmpRpcAdapter(config)
    raise ValueError(f"unknown adapter: {name}")

"""Loop System 门面：装配持久化、Provider 目录与原生编排器。"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .adapters.base import ModelAdapter
from .adapters.fake import FakeAdapter
from .artifacts import ArtifactStore
from .event_store import EventStore
from .orchestrator import CancelledInputSaveError, Orchestrator, RunTerminalError
from .provider_catalog import CatalogValidationError, CredentialMaterial, CredentialSource, ProviderCatalog
from .projection import RunProjection, project_run


class LoopSystem:
    def __init__(
        self,
        data_dir: str | Path,
        *,
        provider_catalog: ProviderCatalog | None = None,
        credentials: CredentialSource | None = None,
        test_adapter_factory: Callable[[str], ModelAdapter] | None = None,
        test_adapter: ModelAdapter | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = EventStore(self.data_dir / "events.sqlite")
        self.artifacts = ArtifactStore(self.data_dir / "artifacts")
        if test_adapter_factory is not None and provider_catalog is not None:
            raise ValueError("provider_catalog and test_adapter_factory are mutually exclusive")
        if test_adapter is not None and test_adapter_factory is not None:
            raise ValueError("provide test_adapter or test_adapter_factory, not both")
        if test_adapter is not None:
            test_adapter_factory = lambda _department: test_adapter
        self.test_adapter = test_adapter
        self.orchestrator = Orchestrator(
            self.store,
            self.artifacts,
            self.data_dir / "workspaces",
            provider_catalog=provider_catalog,
            credentials=credentials,
            test_adapter_factory=test_adapter_factory,
            test_provider=(getattr(test_adapter, "name", "test") if test_adapter is not None else "test"),
            test_adapter_name=(getattr(test_adapter, "name", "test") if test_adapter is not None else "test"),
        )
        self.git_versions = self.orchestrator.git_versions

    @property
    def provider_catalog(self) -> ProviderCatalog | None:
        return self.orchestrator.provider_catalog

    @provider_catalog.setter
    def provider_catalog(self, value: ProviderCatalog | None) -> None:
        self.orchestrator.provider_catalog = value

    @property
    def credentials(self) -> CredentialSource | None:
        return self.orchestrator.credentials

    @credentials.setter
    def credentials(self, value: CredentialSource | None) -> None:
        self.orchestrator.credentials = value

    @classmethod
    def for_testing(cls, data_dir: str | Path, adapter: ModelAdapter) -> "LoopSystem":
        """Use one explicitly supplied adapter in deterministic tests only."""

        return cls(data_dir, test_adapter=adapter)

    def provider_status(self) -> dict[str, Any]:
        """Return safe provider readiness information for CLI and Web health."""

        if self.provider_catalog is None:
            if self.test_adapter is None:
                return {
                    "available": False,
                    "reason": "provider_config_missing",
                    "message": "Provider catalog is required to create a production run.",
                    "departments": {},
                }
            availability = self.test_adapter.availability()
            return {
                "available": availability.available,
                "reason": availability.reason,
                "message": availability.message,
                "departments": {},
            }
        try:
            snapshot = self.provider_catalog.resolve_snapshot(self.credentials)
        except CatalogValidationError as exc:
            return {
                "available": False,
                "reason": "provider_unavailable",
                "message": str(exc),
                "departments": {},
            }
        return {
            "available": True,
            "reason": "",
            "message": "",
            "departments": snapshot.public_dict()["departments"],
        }

    def create_run(self, task: str, **kwargs) -> str:
        return self.orchestrator.create_run(task, **kwargs)

    def run_until_stop(self, run_id: str) -> RunProjection:
        return self.orchestrator.run_until_stop(run_id)

    def activate_once(self, run_id: str) -> RunProjection:
        return self.orchestrator.activate_once(run_id)

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
        return project_run(self.store, run_id)

    def list_run_ids(self) -> list[str]:
        return self.store.list_run_ids()


def build_adapter(name: str, **kwargs) -> ModelAdapter:
    """Build only an explicitly requested deterministic test adapter.

    Production adapters are created from a ProviderCatalogSnapshot at activation
    time so a single environment-wide Responses adapter cannot bypass bindings.
    """

    if name == "fake":
        return FakeAdapter(kwargs.get("script"))
    raise ValueError(f"unknown test adapter: {name}")


def environment_credentials(reference: str) -> CredentialMaterial | None:
    """Resolve a catalog credential reference from the current host environment."""

    value = os.environ.get(reference)
    if value is None:
        return None
    return CredentialMaterial(value)

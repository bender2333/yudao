"""本地 Web 控制台：查询投影、SSE 订阅，命令交给 LoopSystem。"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..adapters.base import ModelRequest, ProviderError
from ..context import AssembledContext, ContextPart
from ..git_audit import git_version_detail
from ..models import ArtifactRef, ContextManifest, DEPARTMENTS, EventType, GIT_VERSION_EVENTS, json_dumps
from ..observability import MAX_LIMIT, AttemptNotFoundError, ObservabilityQuery
from ..provider_catalog import (
    CatalogValidationError,
    ProviderCatalog,
    ResolvedProviderTarget,
    SUPPORTED_PROTOCOLS,
    ValidationIssue,
)
from ..projection import RunNotFoundError, project_run
from ..replay_check import ReplayIntegrityError
from ..projects import (
    ProjectArchivedError,
    ProjectEventType,
    ProjectNotFoundError,
    PromptConfigConflict,
    WorkItemInProgressError,
    project_event_card,
    project_overview,
    work_item_handoffs,
)
from ..runtime import CancelledInputSaveError, LoopSystem, RunTerminalError
from ..tree_archive import load_tree
from ..views import event_card, run_board, run_payload

STATIC_DIR = Path(__file__).parent / "static"


class BusyError(Exception):
    pass


class ProviderUnavailableError(Exception):
    def __init__(self, message: str, reason: str = "provider_unavailable") -> None:
        super().__init__(message)
        self.reason = reason


class _ResponseSent(Exception):
    pass


class LoopConsoleServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        host: str,
        port: int,
        system: LoopSystem,
        *,
        provider_config: str | Path | None = None,
    ) -> None:
        super().__init__((host, port), LoopConsoleHandler)
        self.system = system
        self.store = system.store
        path = provider_config if provider_config is not None else getattr(system, "provider_config_path", None)
        self.provider_config_path = None if path is None else Path(path)
        self._worker_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._active_run_id: str | None = None
        self._active_work: tuple[str, str] | None = None
        self._worker_errors: dict[str, str] = {}
        bound_host, bound_port = self.server_address
        self.base_url = f"http://{bound_host}:{bound_port}"


    def handle_error(self, request, client_address) -> None:
        return

    def busy(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def active_run_id(self) -> str | None:
        if not self.busy():
            return None
        return self._active_run_id

    def active_project_id(self) -> str | None:
        if not self.busy() or self._active_work is None:
            return None
        return self._active_work[0]

    def active_work_item_id(self) -> str | None:
        if not self.busy() or self._active_work is None:
            return None
        return self._active_work[1]

    def error_for(self, run_id: str) -> str | None:
        with self._worker_lock:
            return self._worker_errors.get(run_id)

    def last_worker_error(self) -> dict[str, str] | None:
        with self._worker_lock:
            if not self._worker_errors:
                return None
            run_id, message = next(reversed(self._worker_errors.items()))
            return {"run_id": run_id, "message": message}

    def start_work_item(self, project_id: str, text: str, options: dict[str, Any]) -> tuple[str, str]:
        with self._worker_lock:
            self._require_idle_and_available()
            work_item_id, run_id = self.system.projects.start_work_item(project_id, text, **options)
            self._spawn_worker(run_id, (project_id, work_item_id))
            return work_item_id, run_id

    def _require_idle_and_available(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            raise BusyError("已有任务正在运行")
        status = self.system.provider_status()
        if not status.get("available", False):
            raise ProviderUnavailableError(
                status.get("message") or "provider unavailable",
                status.get("reason") or "provider_unavailable",
            )

    def _spawn_worker(self, run_id: str, work: tuple[str, str] | None) -> None:
        worker = threading.Thread(
            target=self._run_worker,
            args=(run_id,),
            name=f"loop-worker-{run_id}",
            daemon=True,
        )
        self._active_run_id = run_id
        self._active_work = work
        self._worker = worker
        worker.start()

    def _run_worker(self, run_id: str) -> None:
        try:
            self.system.run_until_stop(run_id)
            self.system.projects.settle(run_id)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            with self._worker_lock:
                self._worker_errors[run_id] = message
            print(f"loop worker {run_id} failed: {message}", file=sys.stderr)


class LoopConsoleHandler(BaseHTTPRequestHandler):
    server: LoopConsoleServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        store = self.server.store
        try:
            if path == "/":
                return self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                return self._send_static(path[len("/static/") :])
            if path == "/api/health":
                return self._send_json(self._health())
            if path == "/api/runs":
                return self._send_json({"runs": self._list_runs(store)})
            if path.startswith("/api/runs/"):
                return self._get_run(path, query, store)
            if path == "/api/projects":
                return self._send_json({"projects": self._list_projects(query)})
            if path.startswith("/api/projects/"):
                return self._get_project(path, query, store)
            if path == "/api/providers":
                return self._send_json(self._providers_payload())
            if path == "/api/department-bindings":
                return self._send_json(self._bindings_payload())
            self._send_json({"error": "not found"}, 404)
        except RunNotFoundError as exc:
            self._send_json({"error": f"run not found: {exc}"}, 404)
        except ProjectNotFoundError as exc:
            self._send_json({"error": f"project not found: {exc}"}, 404)
        except AttemptNotFoundError as exc:
            self._send_json({"error": f"model attempt not found: {exc}"}, 404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parts = self._path_parts()

        def dispatch() -> None:
            if parts == ["api", "runs"]:
                self._drain_body()
                return self._send_json({"error": "not found"}, 404)
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
                return self._cancel_run(parts[2])
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "replay":
                return self._replay_run(parts[2])
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "inputs":
                return self._add_input(parts[2])
            if len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3] == "prompts":
                return self._update_prompt(parts[2], parts[4])
            if len(parts) == 6 and parts[:2] == ["api", "runs"] and parts[3] == "departments" and parts[5] == "guidance":
                return self._add_guidance(parts[2], parts[4])
            if parts == ["api", "projects"]:
                return self._create_project()
            if len(parts) == 4 and parts[:2] == ["api", "projects"]:
                return self._post_project(parts[2], parts[3])
            if parts == ["api", "providers"]:
                return self._post_providers()
            if len(parts) == 4 and parts[:2] == ["api", "providers"] and parts[3] == "test":
                return self._test_provider(unquote(parts[2]))
            self._send_json({"error": "not found"}, 404)

        self._command(dispatch)

    def do_PUT(self) -> None:
        parts = self._path_parts()

        def dispatch() -> None:
            if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "prompts":
                return self._configure_prompt(parts[2], unquote(parts[4]))
            if len(parts) == 3 and parts[:2] == ["api", "providers"]:
                return self._put_provider(unquote(parts[2]))
            if parts == ["api", "department-bindings"]:
                return self._put_bindings()
            self._send_json({"error": "not found"}, 404)

        self._command(dispatch)

    def do_DELETE(self) -> None:
        parts = self._path_parts()

        def dispatch() -> None:
            if len(parts) == 3 and parts[:2] == ["api", "providers"]:
                return self._delete_provider(unquote(parts[2]))
            self._send_json({"error": "not found"}, 404)

        self._command(dispatch)


    def _path_parts(self) -> list[str]:
        path = urlparse(self.path).path.rstrip("/")
        return [item for item in path.split("/") if item]

    def _command(self, dispatch: Callable[[], None]) -> None:
        try:
            dispatch()
        except _ResponseSent:
            return
        except BusyError as exc:
            self._send_json({"error": str(exc), "reason": "busy"}, 409)
        except RunTerminalError as exc:
            self._send_json({"error": str(exc), "reason": "run_terminal"}, 409)
        except WorkItemInProgressError as exc:
            self._send_json({"error": str(exc), "reason": "work_item_in_progress"}, 409)
        except ProjectArchivedError as exc:
            self._send_json({"error": str(exc), "reason": "project_archived"}, 409)
        except PromptConfigConflict as exc:
            self._send_json({"error": str(exc), "reason": "prompt_config_conflict", "current": exc.current}, 409)
        except CancelledInputSaveError as exc:
            message = "执行已取消，但命令原文未形成正式 Git 版本；输入框保留原文。"
            if not exc.cancellation_recorded:
                message += "取消事实也未能保存。"
            self._send_json({"error": message, "code": "cancelled_input_not_saved",
                             "run_id": exc.run_id, "cancelled": exc.cancelled,
                             "cancellation_recorded": exc.cancellation_recorded}, 503)
        except ProviderUnavailableError as exc:
            self._send_json({"error": str(exc), "reason": exc.reason}, 503)
        except CatalogValidationError as exc:
            self._send_json({"error": str(exc), "reason": "provider_unavailable"}, 503)
        except RunNotFoundError as exc:
            self._send_json({"error": f"run not found: {exc}"}, 404)
        except ProjectNotFoundError as exc:
            self._send_json({"error": f"project not found: {exc}"}, 404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _health(self) -> dict[str, Any]:
        status = self.server.system.provider_status()
        test_adapter = getattr(self.server.system, "test_adapter", None)
        return {
            "ok": True,
            "busy": self.server.busy(),
            "active_run_id": self.server.active_run_id(),
            "active_project_id": self.server.active_project_id(),
            "active_work_item_id": self.server.active_work_item_id(),
            "adapter": getattr(test_adapter, "name", "directory"),
            "provider_available": bool(status.get("available", False)),
            "provider_message": status.get("message", ""),
            "provider_bindings": status.get("departments", {}),
            "provider_status": status,
            "worker_error": self.server.last_worker_error(),
        }

    def _cancel_run(self, run_id: str) -> None:
        self._drain_body()
        projection = self.server.system.cancel(run_id)
        self._send_json(
            {
                "ok": True,
                "run_id": run_id,
                "phase": projection.phase,
                "stop_reason": projection.stop_reason,
            }
        )

    def _text_body(self) -> str:
        body = self._read_json_body()
        if set(body) != {"text"}:
            raise ValueError("body must contain only text")
        text = body["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        return text

    def _add_input(self, run_id: str) -> None:
        projection = self.server.system.add_input(run_id, self._text_body())
        self._send_json({"ok": True, "run_id": run_id, "phase": projection.phase,
                         "input_version": projection.input_version,
                         "processed_input_version": projection.processed_input_version}, 201)

    def _update_prompt(self, run_id: str, department: str) -> None:
        projection = self.server.system.update_prompt(run_id, department, self._text_body())
        prompt = projection.department_prompts[department]
        self._send_json({"ok": True, "run_id": run_id, "department": department,
                         "prompt_version": prompt.version,
                         "prompt_hash": prompt.prompt_ref.content_hash}, 201)

    def _add_guidance(self, run_id: str, department: str) -> None:
        projection = self.server.system.add_guidance(run_id, department, self._text_body())
        guidance = max(
            (item for item in projection.department_guidance if item.department == department),
            key=lambda item: item.version,
        )
        self._send_json({
            "ok": True,
            "run_id": run_id,
            "department": department,
            "guidance_id": guidance.id,
            "guidance_version": guidance.version,
            "status": guidance.status,
        }, 201)

    def _replay_run(self, run_id: str) -> None:
        self._drain_body()
        try:
            first = self.server.system.replay(run_id)
        except ReplayIntegrityError as exc:
            self._send_json(
                {
                    "ok": False,
                    "mutated": False,
                    "reason": exc.reason,
                    "error": str(exc),
                },
                500,
            )
            return
        self._send_json(
            {
                "ok": True,
                "mutated": False,
                "event_count": first.last_seq,
                "phase": first.phase,
            }
        )

    # ------------------------------------------------------------------ projects

    def _list_projects(self, query: dict[str, list[str]]) -> list[dict[str, Any]]:
        include_archived = self._query_scalar(query, "archived") in {"1", "true"}
        rows = []
        for project in self.server.system.projects.list_projects(include_archived=include_archived):
            adoption = project.current_adoption
            rows.append({
                "project_id": project.project_id,
                "name": project.name,
                "pinned": project.pinned,
                "archived": project.archived,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
                "work_item_count": len(project.work_items),
                "active_work_item_id": project.active_work_item_id,
                "current_adoption": None if adoption is None else {
                    "adoption_id": adoption.adoption_id, "summary": adoption.summary, "adopted_at": adoption.adopted_at,
                },
            })
        return rows

    def _create_project(self) -> None:
        body = self._read_json_body()
        if set(body) != {"name", "goal"}:
            raise ValueError("body must contain name and goal")
        project_id = self.server.system.projects.register(body["name"], body["goal"])
        self._send_json({"project_id": project_id}, 201)

    def _post_project(self, project_id: str, command: str) -> None:
        projects = self.server.system.projects
        if command == "rename":
            body = self._read_json_body()
            if set(body) != {"name"}:
                raise ValueError("body must contain only name")
            projects.rename(project_id, body["name"])
            return self._send_json({"ok": True, "project_id": project_id, "name": body["name"]})
        if command == "pin":
            body = self._read_json_body()
            if set(body) != {"pinned"}:
                raise ValueError("body must contain only pinned")
            projects.pin(project_id, body["pinned"])
            return self._send_json({"ok": True, "project_id": project_id, "pinned": body["pinned"]})
        if command == "archive":
            self._drain_body()
            projects.archive(project_id)
            return self._send_json({"ok": True, "project_id": project_id, "archived": True})
        if command == "restore":
            self._drain_body()
            projects.restore(project_id)
            return self._send_json({"ok": True, "project_id": project_id, "archived": False})
        if command == "work-items":
            body = self._read_json_body()
            unknown = set(body) - {"text", "title", "max_cycles", "context_window"}
            if unknown:
                raise ValueError("unsupported work item fields: " + ", ".join(sorted(unknown)))
            text = body.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be a non-empty string")
            options: dict[str, Any] = {}
            if body.get("title") is not None:
                if not isinstance(body["title"], str) or not body["title"].strip():
                    raise ValueError("title must be a non-empty string")
                options["title"] = body["title"]
            for key in ("max_cycles", "context_window"):
                if key not in body or body[key] is None:
                    continue
                options[key] = _positive_int(key, body[key])
            work_item_id, run_id = self.server.start_work_item(project_id, text, options)
            projection = project_run(self.server.store, run_id)
            return self._send_json({"work_item_id": work_item_id, "run_id": run_id, "phase": projection.phase}, 201)
        if command == "materials":
            body = self._read_json_body()
            unknown = set(body) - {"text", "department"}
            if unknown:
                raise ValueError("unsupported material fields: " + ", ".join(sorted(unknown)))
            text = body.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be a non-empty string")
            department = body.get("department")
            if department is not None and department not in DEPARTMENTS:
                raise ValueError("unknown department")
            material_id = projects.record_material(project_id, text, department=department)
            return self._send_json({"material_id": material_id}, 201)
        self._send_json({"error": "not found"}, 404)

    def _configure_prompt(self, project_id: str, department: str) -> None:
        body = self._read_json_body()
        if set(body) != {"text", "base_version"}:
            raise ValueError("body must contain text and base_version")
        result = self.server.system.projects.configure_prompt(project_id, department, body["text"], body["base_version"])
        self._send_json(result)

    def _providers_payload(self) -> dict[str, Any]:
        catalog = self.server.system.provider_catalog
        if catalog is None:
            return {"providers": [], "models": [], "bindings": {}}
        credentials = self.server.system.credentials
        providers = []
        for provider in catalog.providers.values():
            item = provider.public_dict()
            item["credential_configured"] = _credential_ready(provider, credentials)
            item["models"] = [
                model.public_dict()
                for model in catalog.models.values()
                if model.provider_id == provider.id
            ]
            providers.append(item)
        providers.sort(key=lambda item: item["id"])
        return {
            "providers": providers,
            "models": [catalog.models[key].public_dict() for key in sorted(catalog.models)],
            "bindings": {
                department: catalog.bindings[department].public_dict()
                for department in DEPARTMENTS
                if department in catalog.bindings
            },
        }

    def _bindings_payload(self) -> dict[str, Any]:
        catalog = self.server.system.provider_catalog
        if catalog is None:
            return {"bindings": {}}
        bindings: dict[str, Any] = {}
        for department in DEPARTMENTS:
            binding = catalog.bindings.get(department)
            if binding is None:
                continue
            provider = catalog.providers.get(binding.provider_id)
            model = catalog.models.get(binding.model_id)
            item = binding.public_dict()
            if provider is not None:
                item["provider_name"] = provider.name
                item["protocol"] = provider.protocol
            if model is not None:
                item["model"] = model.model
                item["context_window"] = model.context_window
                item["max_output_tokens"] = model.max_output_tokens
            bindings[department] = item
        return {"bindings": bindings}

    def _post_providers(self) -> None:
        body = self._read_json_body()
        if "providers" in body:
            catalog = self._catalog_from_document(body)
            self._persist_catalog(catalog)
            return self._send_json(self._providers_payload())
        catalog = self._merge_provider(body, existing_id=None)
        self._persist_catalog(catalog)
        return self._send_json(self._providers_payload(), 201)

    def _put_provider(self, provider_id: str) -> None:
        body = self._read_json_body()
        if "id" in body and body["id"] != provider_id:
            raise ValueError("provider id cannot be changed")
        body = {**body, "id": provider_id}
        catalog = self._merge_provider(body, existing_id=provider_id)
        self._persist_catalog(catalog)
        return self._send_json(self._providers_payload())

    def _delete_provider(self, provider_id: str) -> None:
        self._drain_body()
        catalog = self.server.system.provider_catalog
        if catalog is None or provider_id not in catalog.providers:
            return self._send_json({"error": "provider not found"}, 404)
        dependents = _provider_dependents(catalog, provider_id)
        if dependents:
            return self._send_json({
                "error": "provider is in use: " + ", ".join(dependents),
                "reason": "in_use",
                "dependents": dependents,
            }, 409)
        raw = catalog.to_dict()
        raw["providers"] = [item for item in raw["providers"] if item["id"] != provider_id]
        raw["models"] = [item for item in raw["models"] if item["provider_id"] != provider_id]
        try:
            updated = ProviderCatalog.from_dict(raw)
        except CatalogValidationError as exc:
            return self._send_catalog_error(exc)
        self._persist_catalog(updated)
        return self._send_json(self._providers_payload())

    def _put_bindings(self) -> None:
        body = self._read_json_body()
        bindings = body.get("bindings", body)
        if not isinstance(bindings, dict):
            raise ValueError("bindings must be an object")
        catalog = self.server.system.provider_catalog
        raw = {"providers": [], "models": [], "bindings": {}} if catalog is None else catalog.to_dict()
        raw["bindings"] = bindings
        try:
            updated = ProviderCatalog.from_dict(raw)
        except CatalogValidationError as exc:
            return self._send_catalog_error(exc)
        self._persist_catalog(updated)
        return self._send_json(self._bindings_payload())

    def _test_provider(self, provider_id: str) -> None:
        self._drain_body()
        catalog = self.server.system.provider_catalog
        if catalog is None or provider_id not in catalog.providers:
            return self._send_json({"error": "provider not found"}, 404)
        provider = catalog.providers[provider_id]
        model = next((item for item in catalog.models.values() if item.provider_id == provider_id), None)
        if model is None:
            raise ValueError("provider has no models")
        started = time.monotonic()
        if provider.protocol == "fake":
            elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
            return self._send_json({
                "ok": True, "error": None, "actual_model": model.model, "elapsed_ms": elapsed_ms,
            })
        if provider.protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError("unsupported provider protocol")
        material = _resolved_secret(self.server.system.credentials, provider.credential_ref)
        if material is None:
            elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
            return self._send_json({
                "ok": False,
                "error": f"credential reference {provider.credential_ref} cannot be resolved",
                "actual_model": None,
                "elapsed_ms": elapsed_ms,
            })
        target = ResolvedProviderTarget(
            department="product",
            provider_id=provider.id,
            provider_name=provider.name,
            model_id=model.id,
            protocol=provider.protocol,
            base_url=provider.base_url,
            model=model.model,
            context_window=model.context_window or model.max_output_tokens,
            max_output_tokens=model.max_output_tokens,
            timeout_sec=provider.timeout_sec,
            credential_ref=provider.credential_ref or None,
            api_key=material,
        )
        adapter = target.create_adapter()
        request = _connection_test_request(model.max_output_tokens)
        try:
            response = adapter.complete(request)
        except ProviderError as exc:
            elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
            return self._send_json({
                "ok": False,
                "error": _redact_secret(str(exc), material),
                "actual_model": None,
                "elapsed_ms": elapsed_ms,
            })
        elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        actual = response.model or model.model
        return self._send_json({
            "ok": True,
            "error": None,
            "actual_model": _redact_secret(str(actual), material),
            "elapsed_ms": elapsed_ms,
        })

    def _merge_provider(self, body: dict[str, Any], *, existing_id: str | None) -> ProviderCatalog:
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        models = body.get("models", [])
        provider_fields = {key: value for key, value in body.items() if key != "models"}
        _validate_provider_fields(provider_fields)
        provider_id = provider_fields["id"]
        catalog = self.server.system.provider_catalog
        raw = {"providers": [], "models": [], "bindings": {}} if catalog is None else catalog.to_dict()
        existing_ids = {item["id"] for item in raw["providers"]}
        if existing_id is None and provider_id in existing_ids:
            self._send_json({"error": f"provider already exists: {provider_id}", "reason": "conflict"}, 409)
            raise _ResponseSent()
        if existing_id is not None and existing_id not in existing_ids:
            self._send_json({"error": "provider not found"}, 404)
            raise _ResponseSent()
        raw["providers"] = [item for item in raw["providers"] if item["id"] != provider_id]
        raw["providers"].append({
            "id": provider_fields["id"],
            "name": provider_fields["name"],
            "protocol": provider_fields["protocol"],
            "base_url": provider_fields.get("base_url", ""),
            "credential_ref": provider_fields.get("credential_ref", ""),
            "timeout_sec": provider_fields.get("timeout_sec", 600.0),
        })
        if "models" in body:
            if not isinstance(models, list):
                raise ValueError("models must be an array")
            nested = []
            for index, item in enumerate(models):
                if not isinstance(item, dict):
                    raise ValueError(f"models[{index}] must be an object")
                nested.append({**item, "provider_id": provider_id})
            raw["models"] = [item for item in raw["models"] if item.get("provider_id") != provider_id]
            raw["models"].extend(nested)
        try:
            return ProviderCatalog.from_dict(raw)
        except CatalogValidationError as exc:
            self._send_catalog_error(exc)
            raise _ResponseSent() from exc

    def _catalog_from_document(self, body: dict[str, Any]) -> ProviderCatalog:
        try:
            return ProviderCatalog.from_dict(body)
        except CatalogValidationError as exc:
            self._send_catalog_error(exc)
            raise _ResponseSent() from exc

    def _persist_catalog(self, catalog: ProviderCatalog) -> None:
        path = self.server.provider_config_path
        if path is None:
            raise ProviderUnavailableError("provider catalog path is not configured")
        payload = json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2) + "\n"
        tmp_path = path.with_name(path.name + ".tmp")
        try:
            tmp_path.write_text(payload, encoding="utf-8")
            os.replace(tmp_path, path)
        except OSError as exc:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ProviderUnavailableError("provider catalog file is not writable") from exc
        self.server.system.provider_catalog = catalog

    def _send_catalog_error(self, exc: CatalogValidationError) -> None:
        issues = [{"location": issue.location, "message": issue.message} for issue in exc.issues]
        self._send_json({"error": str(exc), "reason": "invalid_catalog", "issues": issues}, 400)


    def _get_project(self, path: str, query: dict[str, list[str]], store) -> None:
        parts = [item for item in path.split("/") if item]
        project_id = parts[2]
        rest = parts[3:]
        projects = self.server.system.projects
        if not rest:
            projects.settle_pending(project_id)
            project = projects.projection(project_id)
            payload = project.to_dict()
            payload["overview"] = project_overview(store, project)
            return self._send_json(payload)
        project = projects.projection(project_id)
        if rest == ["board"]:
            return self._send_json({"project_id": project_id, "work_items": [item.to_dict() for item in project.work_items]})
        if rest[:1] == ["work-items"] and len(rest) == 2:
            item = project.work_item(rest[1])
            if item is None:
                return self._send_json({"error": "work item not found"}, 404)
            detail = item.to_dict()
            try:
                run = project_run(store, item.run_id)
                events = store.list_events(item.run_id)
            except RunNotFoundError:
                run, events = None, []
            detail["handoffs"] = work_item_handoffs(events)
            detail["adoption"] = next((entry.to_dict() for entry in project.adoptions if entry.work_item_id == item.work_item_id), None)
            detail["held"] = next((entry.to_dict() for entry in project.held if entry.work_item_id == item.work_item_id), None)
            detail["run"] = None if run is None else {
                "run_id": run.run_id, "phase": run.phase, "outcome": run.outcome, "stop_reason": run.stop_reason,
            }
            return self._send_json(detail)
        if rest[:1] == ["departments"] and len(rest) == 2:
            department = unquote(rest[1])
            if department not in DEPARTMENTS:
                raise ValueError("unknown department")
            items = list(reversed(project.work_items))
            wanted = self._query_scalar(query, "work_item")
            if wanted is not None:
                items = [item for item in items if item.work_item_id == wanted]
                if not items:
                    return self._send_json({"error": "work item not found"}, 404)
            observability = ObservabilityQuery(store, self.server.system.artifacts)
            config = project.prompt_configs[department]
            return self._send_json({
                "department": department,
                "project_id": project_id,
                "prompt_config": {"version": config.version, "source": config.source},
                "items": [
                    {
                        "work_item_id": item.work_item_id, "title": item.title, "status": item.status,
                        "view": None if item.status == "not_started" else observability.department(item.run_id, department),
                    }
                    for item in items
                ],
            })
        if rest[:1] == ["prompts"] and len(rest) == 2:
            return self._send_json(projects.read_prompt(project_id, unquote(rest[1])))
        if rest in (["model-attempts"], ["model-usage"]):
            wanted = self._query_scalar(query, "work_item")
            if wanted is not None and project.work_item(wanted) is None:
                return self._send_json({"error": "work item not found"}, 404)
            if rest == ["model-attempts"]:
                return self._send_json(self._project_attempts(project, query, store))
            return self._send_json(self._project_usage(project, query, store))
        if rest == ["stream"]:
            return self._project_stream(project, query, store)
        self._send_json({"error": "not found"}, 404)

    def _project_records(self, project, query: dict[str, list[str]], store) -> tuple[list[tuple[Any, dict[str, Any]]], dict[str, Any]]:
        filters = {
            "department": self._query_scalar(query, "department"),
            "status": self._query_scalar(query, "status"),
            "q": self._query_scalar(query, "q"),
            "provider": self._query_scalar(query, "provider"),
            "requested_model": self._query_scalar(query, "requested_model"),
            "actual_model": self._query_scalar(query, "actual_model"),
        }
        wanted = self._query_scalar(query, "work_item")
        items = [item for item in project.work_items if wanted is None or item.work_item_id == wanted]
        observability = ObservabilityQuery(store, self.server.system.artifacts)
        merged: list[tuple[Any, dict[str, Any]]] = []
        for item in items:
            if item.status == "not_started":
                continue
            merged.extend((item, record) for record in observability.attempt_records(item.run_id, **filters))
        return merged, filters

    def _project_attempts(self, project, query: dict[str, list[str]], store) -> dict[str, Any]:
        merged, filters = self._project_records(project, query, store)
        merged.sort(key=lambda pair: (pair[1].get("started_at") or pair[1].get("prepared_at") or "", pair[1].get("seq", 0)),
                    reverse=True)
        limit = self._query_limit(query)
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
        offset = _decode_offset(self._query_scalar(query, "cursor"), len(merged))
        page = merged[offset:offset + limit]
        next_offset = offset + len(page)
        return {
            "project_id": project.project_id,
            "items": [
                {**ObservabilityQuery.public_attempt(record), "run_id": item.run_id,
                 "work_item_id": item.work_item_id, "title": item.title}
                for item, record in page
            ],
            "total": len(merged),
            "next_cursor": _encode_cursor({"offset": next_offset}) if next_offset < len(merged) else None,
            "filters": {**filters, "work_item": self._query_scalar(query, "work_item")},
        }

    def _project_usage(self, project, query: dict[str, list[str]], store) -> dict[str, Any]:
        merged, filters = self._project_records(project, query, store)
        observability = ObservabilityQuery(store, self.server.system.artifacts)
        by_work_item = []
        for item in project.work_items:
            records = [record for owner, record in merged if owner is item]
            if not records and item.status == "not_started":
                continue
            by_work_item.append({
                "work_item_id": item.work_item_id, "title": item.title, "run_id": item.run_id,
                **observability.usage_summary(records, **filters),
            })
        return {
            "project_id": project.project_id,
            **observability.usage_summary([record for _owner, record in merged], **filters),
            "by_work_item": by_work_item,
        }

    def _project_stream(self, project, query: dict[str, list[str]], store) -> None:
        cursor = self._project_cursor(query)
        runs = {item.run_id: item.work_item_id for item in project.work_items}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        idle = 0
        try:
            while True:
                wrote = False
                for event in store.list_project_events(project.project_id, after_seq=cursor["p"]):
                    cursor["p"] = event.seq
                    if event.type == ProjectEventType.WORK_ITEM_CREATED:
                        runs[event.payload["run_id"]] = event.payload["work_item_id"]
                    self._write_sse(_encode_cursor(cursor), "project", project_event_card(event))
                    wrote = True
                for run_id, work_item_id in list(runs.items()):
                    for event in store.list_events(run_id, after_seq=cursor["r"].get(run_id, 0)):
                        cursor["r"][run_id] = event.seq
                        self._write_sse(_encode_cursor(cursor), "loop",
                                        {**event_card(event), "run_id": run_id, "work_item_id": work_item_id})
                        wrote = True
                if wrote:
                    idle = 0
                else:
                    self.wfile.write(b": keepalive\n\n")
                    idle += 1
                self.wfile.flush()
                time.sleep(0.2 if idle < 25 else 1.0)
        except Exception:
            return

    def _project_cursor(self, query: dict[str, list[str]]) -> dict[str, Any]:
        header = self.headers.get("Last-Event-ID")
        if header not in (None, ""):
            cursor = _decode_cursor(header)
            if (not isinstance(cursor, dict) or set(cursor) != {"p", "r"} or type(cursor["p"]) is not int
                    or not isinstance(cursor["r"], dict)
                    or any(not isinstance(key, str) or type(value) is not int for key, value in cursor["r"].items())):
                raise ValueError("Last-Event-ID is not a project stream cursor")
            return cursor
        return {"p": self._resume_seq(query, default=0), "r": {}}

    def _write_sse(self, identity: str, event_name: str, data: dict[str, Any]) -> None:
        chunk = f"id: {identity}\nevent: {event_name}\ndata: {json_dumps(data)}\n\n"
        self.wfile.write(chunk.encode("utf-8"))

    # ------------------------------------------------------------------ runs

    def _get_run(self, path: str, query: dict[str, list[str]], store) -> None:
        parts = [item for item in path.split("/") if item]
        run_id = parts[2]
        rest = parts[3:]
        if not rest:
            payload = run_payload(store, run_id)
            payload["execution_error"] = self.server.error_for(run_id)
            payload["worker_active"] = self.server.active_run_id() == run_id
            return self._send_json(payload)
        observability = ObservabilityQuery(store, self.server.system.artifacts)
        if rest == ["model-attempts"]:
            return self._send_json(observability.list_model_attempts(
                run_id,
                department=self._query_scalar(query, "department"),
                status=self._query_scalar(query, "status"),
                q=self._query_scalar(query, "q"),
                provider=self._query_scalar(query, "provider"),
                requested_model=self._query_scalar(query, "requested_model"),
                actual_model=self._query_scalar(query, "actual_model"),
                cursor=self._query_scalar(query, "cursor"),
                limit=self._query_limit(query),
            ))
        if rest[:1] == ["model-attempts"] and len(rest) == 2:
            return self._send_json(observability.model_attempt_detail(run_id, unquote(rest[1])))
        if rest == ["model-usage"]:
            return self._send_json(observability.model_usage(
                run_id,
                department=self._query_scalar(query, "department"),
                status=self._query_scalar(query, "status"),
                q=self._query_scalar(query, "q"),
                provider=self._query_scalar(query, "provider"),
                requested_model=self._query_scalar(query, "requested_model"),
                actual_model=self._query_scalar(query, "actual_model"),
                cursor=self._query_scalar(query, "cursor"),
                limit=self._query_limit(query),
            ))
        if len(rest) == 2 and rest[0] == "departments":
            return self._send_json(observability.department(run_id, unquote(rest[1])))
        if rest == ["events"]:
            project_run(store, run_id)
            after = self._resume_seq(query, default=0)
            events = store.list_events(run_id, after_seq=after)
            return self._send_json({"events": [event_card(event) for event in events]})
        if rest[:1] == ["events"] and len(rest) == 3 and rest[2] == "files":
            event = store.get_event(rest[1])
            if event is None or event.run_id != run_id or event.type != EventType.DELIVERY_ACCEPTED:
                return self._send_json({"error": "delivery not found"}, 404)
            tree, _archive = self._delivery_archive(event)
            requested = query.get("path", [])
            if len(requested) != 1:
                raise ValueError("one archived file path is required")
            file = next((item for item in tree.files if item.path == requested[0]), None)
            if file is None:
                return self._send_json({"error": "archived file not found"}, 404)
            return self._send_bytes(file.data, "application/octet-stream", download_name=Path(file.path).name)
        if rest[:1] == ["events"] and len(rest) == 2:
            event = store.get_event(rest[1])
            if event is None or event.run_id != run_id:
                return self._send_json({"error": "event not found"}, 404)
            detail = event.to_dict()
            if event.type in GIT_VERSION_EVENTS:
                version = event.payload.get("git_version")
                if version is None:
                    raise ValueError("该正式事件缺少 Git 版本记录")
                detail["git_version_detail"] = git_version_detail(
                    self.server.system.git_versions, self.server.system.artifacts,
                    store.list_events(run_id), event,
                )
            elif event.payload.get("git_version") is not None:
                raise ValueError("Git 版本未绑定正式事件")
            if event.type == EventType.DELIVERY_ACCEPTED:
                _tree, detail["tree_archive"] = self._delivery_archive(event)
            for name in ("prd", "plan"):
                ref = event.payload.get(f"{name}_ref")
                if ref:
                    detail[f"{name}_markdown"] = self.server.system.artifacts.get_for_run(
                        run_id, ArtifactRef(**ref)
                    ).decode("utf-8")
            request_ref = event.payload.get("request_ref")
            if request_ref:
                detail["model_input"] = json.loads(
                    self.server.system.artifacts.get_for_run(run_id, ArtifactRef(**request_ref))
                )
            for key in ("input_ref", "message_ref", "output_ref", "guidance_ref"):
                ref = event.payload.get(key)
                if ref:
                    raw = self.server.system.artifacts.get_for_run(run_id, ArtifactRef(**ref))
                    detail[key.removesuffix("_ref")] = (
                        raw.decode("utf-8") if event.type in {
                            EventType.USER_INPUT_RECEIVED,
                            EventType.DEPARTMENT_GUIDANCE_RECEIVED,
                        }
                        else json.loads(raw)
                    )
            for key in ("intend_ref", "prompt_ref"):
                ref = event.payload.get(key)
                if ref:
                    detail[key.removesuffix("_ref")] = self.server.system.artifacts.get_for_run(
                        run_id, ArtifactRef(**ref)
                    ).decode("utf-8")
            if event.payload.get("summary_ref"):
                detail["compaction_summary"] = self.server.system.artifacts.get_for_run(
                    run_id, ArtifactRef(**event.payload["summary_ref"])
                ).decode("utf-8")
                sources = []
                seen = set()
                for ref in event.payload["source_refs"]:
                    source = store.get_event(ref["event_id"])
                    if (source is None or source.run_id != run_id or source.role != event.role
                            or source.seq != ref["seq"] or source.payload.get("activation_id") != ref["activation_id"]
                            or source.payload.get("step_id") != ref["step_id"]):
                        raise ValueError("compaction source does not match its department history")
                    if source.event_id not in seen:
                        sources.append(event_card(source))
                        seen.add(source.event_id)
                prior = event.payload.get("previous_compaction_event_id")
                if prior:
                    source = store.get_event(prior)
                    if source is None or source.run_id != run_id or source.role != event.role or source.type != "compaction_recorded":
                        raise ValueError("previous compaction does not match its department")
                    sources.insert(0, event_card(source))
                detail["source_events"] = sources
            return self._send_json(detail)
        if rest == ["stream"]:
            project_run(store, run_id)
            after = self._resume_seq(query, default=0)
            return self._stream(run_id, after, store)
        if rest == ["export"]:
            projection = project_run(store, run_id)
            observability = ObservabilityQuery(store, self.server.system.artifacts)
            return self._send_json(
                {
                    "events": [event.to_dict() for event in store.list_events(run_id)],
                    "projection": projection.to_dict(),
                    "observability": observability.export_run(run_id),
                }
            )
        if rest == ["board"]:
            return self._send_json(run_board(project_run(store, run_id)))
        self._send_json({"error": "not found"}, 404)

    @staticmethod
    def _query_scalar(query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key, [])
        if len(values) > 1:
            raise ValueError(f"{key} must appear at most once")
        return values[0] if values else None

    def _query_limit(self, query: dict[str, list[str]]) -> int:
        raw = self._query_scalar(query, "limit")
        if raw in (None, ""):
            return 50
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError("limit must be an integer") from exc

    def _delivery_archive(self, event):
        ref = ArtifactRef(**event.payload["tree_ref"])
        artifacts = self.server.system.artifacts
        tree = load_tree(artifacts, event.run_id, ref)
        if tree.digest != event.payload["code_tree_digest"]:
            raise ValueError("archived tree does not match its accepted delivery")
        return tree, json.loads(artifacts.get_for_run(event.run_id, ref))

    def _resume_seq(self, query: dict[str, list[str]], default: int = 0) -> int:
        header = self.headers.get("Last-Event-ID")
        if header not in (None, ""):
            try:
                return int(header)
            except ValueError:
                pass
        raw = (query.get("after_seq") or [str(default)])[0]
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError("after_seq must be an integer") from exc

    def _stream(self, run_id: str, after_seq: int, store) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last = after_seq
        idle = 0
        try:
            while True:
                events = store.list_events(run_id, after_seq=last)
                if events:
                    for event in events:
                        payload = json_dumps(event_card(event))
                        chunk = f"id: {event.seq}\nevent: loop\ndata: {payload}\n\n"
                        self.wfile.write(chunk.encode("utf-8"))
                        last = event.seq
                    idle = 0
                else:
                    self.wfile.write(b": keepalive\n\n")
                    idle += 1
                self.wfile.flush()
                time.sleep(0.2 if idle < 25 else 1.0)
        except Exception:
            return

    def _list_runs(self, store) -> list[dict[str, Any]]:
        rows = []
        for run_id in store.list_run_ids():
            projection = project_run(store, run_id)
            rows.append(
                {
                    "run_id": run_id,
                    "project_id": projection.project_id,
                    "work_item_id": projection.work_item_id,
                    "task": projection.task,
                    "phase": projection.phase,
                    "outcome": projection.outcome,
                    "stop_reason": projection.stop_reason,
                    "provider_bindings": projection.provider_bindings,
                    "requested_model": projection.requested_model,
                    "actual_model": projection.actual_model,
                    "cycle_count": projection.cycle_count,
                    "last_seq": projection.last_seq,
                }
            )
        return rows

    def _drain_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        return self.rfile.read(length) if length else b""

    def _read_json_body(self) -> dict[str, Any]:
        raw = self._drain_body()
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _send_static(self, rel: str) -> None:
        path = (STATIC_DIR / rel).resolve()
        if STATIC_DIR.resolve() not in path.parents and path != STATIC_DIR.resolve():
            return self._send_json({"error": "not found"}, 404)
        if not path.is_file():
            return self._send_json({"error": "not found"}, 404)
        content_type = {
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(path.suffix, "application/octet-stream")
        self._send_file(path, content_type)

    def _send_file(self, path: Path, content_type: str) -> None:
        self._send_bytes(path.read_bytes(), content_type)

    def _send_bytes(self, data: bytes, content_type: str, *, download_name: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if download_name is not None:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(download_name)}")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _credential_ready(provider: Any, source: Any) -> bool:
    if getattr(provider, "protocol", "") != "responses":
        return True
    reference = getattr(provider, "credential_ref", "")
    return _resolved_secret(source, reference) is not None


def _resolved_secret(source: Any, reference: str) -> str | None:
    if not reference or source is None:
        return None
    try:
        value = source(reference) if callable(source) else source.get(reference)
    except Exception:
        return None
    if value is None:
        return None
    secret = getattr(value, "secret", value)
    if isinstance(secret, str) and secret.strip():
        return secret
    return None


def _redact_secret(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


def _provider_dependents(catalog: ProviderCatalog, provider_id: str) -> list[str]:
    dependents: list[str] = []
    model_ids = []
    for model in catalog.models.values():
        if model.provider_id == provider_id:
            dependents.append(f"models.{model.id}")
            model_ids.append(model.id)
    for department, binding in catalog.bindings.items():
        if binding.provider_id == provider_id:
            dependents.append(f"bindings.{department}")
        elif binding.model_id in model_ids:
            dependents.append(f"bindings.{department}")
    return dependents


def _validate_provider_fields(body: dict[str, Any]) -> None:
    required = {"id", "name", "protocol"}
    missing = required - set(body)
    if missing:
        raise ValueError("missing fields: " + ", ".join(sorted(missing)))
    protocol = body["protocol"]
    if not isinstance(protocol, str) or protocol.strip().casefold() not in SUPPORTED_PROTOCOLS:
        raise ValueError("protocol must be responses or fake")
    timeout = body.get("timeout_sec", 600)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout_sec must be positive")


def _connection_test_request(max_output_tokens: int) -> ModelRequest:
    manifest = ContextManifest(
        session_id="provider-test",
        department="product",
        activation_id="provider-test",
        injected=[],
        excluded=[],
        token_estimate=1,
        budget=max(16, max_output_tokens),
        digest="provider-test",
        purpose="work",
        max_output_tokens=max_output_tokens,
    )
    context = AssembledContext(
        department="product",
        prompt_text="ping",
        parts=[ContextPart("intend", "1", "ping")],
        manifest=manifest,
        input_items=[{"role": "user", "content": "ping"}],
        tools=[],
    )
    return ModelRequest(
        "provider-test", "product", "provider-test", "provider-test", 1,
        context, [], Event(), max_output_tokens=max_output_tokens,
    )


def _positive_int(key: str, value: Any) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _encode_cursor(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json_dumps(value).encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(raw: str) -> Any:
    try:
        padded = raw + "=" * (-len(raw) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("cursor is invalid") from exc


def _decode_offset(cursor: str | None, total: int) -> int:
    if cursor in (None, ""):
        return 0
    value = _decode_cursor(cursor)
    if not isinstance(value, dict) or set(value) != {"offset"} or type(value["offset"]) is not int:
        raise ValueError("cursor is invalid")
    if value["offset"] < 0 or value["offset"] > total:
        raise ValueError("cursor is outside the result set")
    return value["offset"]


def serve(
    system: LoopSystem,
    host: str = "127.0.0.1",
    port: int = 8765,
    provider_config: str | Path | None = None,
) -> LoopConsoleServer:
    return LoopConsoleServer(host, port, system, provider_config=provider_config)

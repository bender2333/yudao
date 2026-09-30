"""本地 Web 控制台：查询投影、SSE 订阅，命令交给 LoopSystem。"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..git_audit import git_version_detail
from ..models import ArtifactRef, DEPARTMENTS, EventType, GIT_VERSION_EVENTS, ProjectEvent, json_dumps
from ..observability import MAX_LIMIT, AttemptNotFoundError, ObservabilityQuery
from ..providers.errors import CatalogValidationError
from ..providers.selection import ModelSelection
from ..projection import RunNotFoundError, project_run
from ..replay_check import ReplayIntegrityError
from ..projects import (
    CommandConfigConflict,
    DepartmentSettingConflict,
    ProjectArchivedError,
    ProjectNotFoundError,
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
        # 本地源真相在独立 Provider 模块内，Web 只提交命令和读取状态
        if provider_config is not None and system.facade.config_path is None:
            system.facade.configure_paths(Path(provider_config), system.facade.dotenv_path)
        self.provider_config_path = system.facade.config_path
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
            if options.get("source_dir") is not None:
                source_dir = options["source_dir"]
                if not isinstance(source_dir, str) or not source_dir.strip():
                    raise ValueError("source_dir must be a non-empty string")
                rest = {key: value for key, value in options.items() if key != "source_dir"}
                work_item_id, run_id = self.system.projects.start_work_item_from_snapshot(
                    project_id, source_dir, text, **rest)
            else:
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
            if path == "/api/provider-presets":
                return self._send_json(self._provider_presets())
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
            if len(parts) == 6 and parts[:2] == ["api", "runs"] and parts[3] == "departments" and parts[5] == "guidance":
                return self._add_guidance(parts[2], parts[4])
            if parts == ["api", "projects"]:
                return self._create_project()
            if len(parts) == 4 and parts[:2] == ["api", "projects"]:
                return self._post_project(parts[2], parts[3])
            if parts == ["api", "providers"]:
                return self._post_providers()
            if parts == ["api", "providers", "reload"]:
                return self._post_reload()
            if parts == ["api", "provider-credentials"]:
                return self._post_credentials()
            if len(parts) == 4 and parts[:2] == ["api", "providers"] and parts[3] == "candidates":
                return self._provider_candidates(unquote(parts[2]))
            if len(parts) == 4 and parts[:2] == ["api", "providers"] and parts[3] == "test":
                return self._test_provider(unquote(parts[2]))
            self._send_json({"error": "not found"}, 404)

        self._command(dispatch)

    def do_PUT(self) -> None:
        parts = self._path_parts()

        def dispatch() -> None:
            if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "prompts":
                return self._configure_prompt(parts[2], unquote(parts[4]))
            if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "commands":
                return self._configure_command(parts[2], unquote(parts[4]))
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
        except DepartmentSettingConflict as exc:
            self._send_json({"error": str(exc), "reason": "prompt_config_conflict", "current": exc.current}, 409)
        except CommandConfigConflict as exc:
            self._send_json({"error": str(exc), "reason": "command_config_conflict", "current": exc.current}, 409)
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
        config = self.server.system.facade.config_status()
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
            "provider_config": config["config_path"],
            "provider_revision": config["revision"],
            "provider_reload_error": config["reload_error"],
            "provider_issues": config["issues"],
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
                "event_count": first.stream_version,
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
            unknown = set(body) - {"text", "title", "max_cycles", "run_time_limit_sec", "context_window", "source_dir"}
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
            if body.get("source_dir") is not None:
                if not isinstance(body["source_dir"], str) or not body["source_dir"].strip():
                    raise ValueError("source_dir must be a non-empty string")
                options["source_dir"] = body["source_dir"]
            for key in ("max_cycles", "run_time_limit_sec", "context_window"):
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
        result = self.server.system.projects.configure_department_settings(
            project_id, department, ModelSelection(department_prompt=body["text"]), body["base_version"])
        self._send_json(result)

    def _configure_command(self, project_id: str, name: str) -> None:
        body = self._read_json_body()
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        unknown = set(body) - {"argv", "args", "timeout_sec", "output_limit", "base_version"}
        if unknown:
            raise ValueError("unsupported command fields: " + ", ".join(sorted(unknown)))
        if "argv" not in body or "base_version" not in body:
            raise ValueError("body must contain argv and base_version")
        if not isinstance(body["base_version"], int) or isinstance(body["base_version"], bool):
            raise ValueError("base_version must be an integer")
        kwargs: dict[str, Any] = {"base_version": body["base_version"]}
        for key in ("args", "timeout_sec", "output_limit"):
            if body.get(key) is not None:
                kwargs[key] = body[key]
        result = self.server.system.projects.configure_command(project_id, name, body["argv"], **kwargs)
        self._send_json(result)

    def _facade(self):
        return self.server.system.facade

    def _providers_payload(self) -> dict[str, Any]:
        # 处理器只转交独立 Provider 模块，不读写目录与密钥
        return self._facade().providers_view()

    def _bindings_payload(self) -> dict[str, Any]:
        facade = self._facade()
        view = facade.providers_view()
        providers = {item["id"]: item for item in view["providers"]}
        models = {item["id"]: item for item in view["models"]}
        bindings: dict[str, Any] = {}
        for department, binding in view["bindings"].items():
            item = dict(binding)
            provider = providers.get(binding.get("provider_id", ""))
            model = models.get(binding.get("model_id", ""))
            if provider is not None:
                item["provider_name"] = provider["name"]
                item["protocol"] = provider["protocol"]
            if model is not None:
                item["model"] = model["model"]
                item["context_window"] = model["context_window"]
                item["max_output_tokens"] = model["max_output_tokens"]
                # 档位选项取自所选模型访问定义的声明（设计说明第 9.1 节）
                item["reasoning_levels"] = model.get("reasoning_levels", [])
                item["default_reasoning_level"] = model.get("default_reasoning_level")
                item["reasoning_mode"] = model.get("reasoning_mode")
            bindings[department] = item
        return {"bindings": bindings}

    def _post_providers(self) -> None:
        body = self._read_json_body()
        if "providers" in body:
            previous = self._facade().to_document()
            try:
                self._facade().store_document(body)
            except CatalogValidationError as exc:
                return self._send_catalog_error(exc)
            try:
                self._persist_facade(previous)
            except ProviderUnavailableError as exc:
                return self._send_json({"error": str(exc), "reason": exc.reason}, 503)
            return self._send_json(self._providers_payload())
        self._save_provider_entry(body, existing_id=None, created=True)

    def _put_provider(self, provider_id: str) -> None:
        body = self._read_json_body()
        if "id" in body and body["id"] != provider_id:
            raise ValueError("Provider ID 不可修改")
        body = {**body, "id": provider_id}
        self._save_provider_entry(body, existing_id=provider_id, created=False)

    def _save_provider_entry(self, body: dict[str, Any], *, existing_id: str | None,
                             created: bool) -> None:
        if not isinstance(body, dict):
            raise ValueError("请求体必须是 JSON 对象")
        facade = self._facade()
        known_ids = {item["id"] for item in facade.providers_view()["providers"]}
        provider_id = body.get("id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("缺少字段：id")
        if existing_id is None and provider_id in known_ids:
            self._send_json({"error": f"Provider 已存在：{provider_id}", "reason": "conflict"}, 409)
            raise _ResponseSent()
        if existing_id is not None and existing_id not in known_ids:
            self._send_json({"error": "Provider 不存在"}, 404)
            raise _ResponseSent()
        _validate_provider_entry(body)
        models = body.get("models")
        if models is not None and not isinstance(models, list):
            raise ValueError("models 必须是数组")
        previous = facade.to_document()
        try:
            facade.save_provider_entry(
                {key: value for key, value in body.items() if key != "models"},
                [dict(item) for item in models] if isinstance(models, list) else None,
            )
        except CatalogValidationError as exc:
            return self._send_catalog_error(exc)
        try:
            self._persist_facade(previous)
        except ProviderUnavailableError as exc:
            return self._send_json({"error": str(exc), "reason": exc.reason}, 503)
        return self._send_json(self._providers_payload(), 201 if created else 200)

    def _delete_provider(self, provider_id: str) -> None:
        self._drain_body()
        previous = self._facade().to_document()
        try:
            self._facade().delete_provider(provider_id)
        except CatalogValidationError as exc:
            issues = [{"location": issue.location, "message": issue.message} for issue in exc.issues]
            if any("仍被引用" in issue.message for issue in exc.issues):
                dependents = [issue.location for issue in exc.issues]
                return self._send_json({
                    "error": "Provider 仍被引用：" + "、".join(dependents),
                    "reason": "in_use",
                    "dependents": dependents,
                }, 409)
            if any("不存在" in issue.message for issue in exc.issues):
                return self._send_json({"error": "Provider 不存在"}, 404)
            return self._send_json({"error": str(exc), "reason": "invalid_catalog",
                                    "issues": issues}, 400)
        try:
            self._persist_facade(previous)
        except ProviderUnavailableError as exc:
            return self._send_json({"error": str(exc), "reason": exc.reason}, 503)
        return self._send_json(self._providers_payload())

    def _put_bindings(self) -> None:
        body = self._read_json_body()
        bindings = body.get("bindings", body)
        if not isinstance(bindings, dict):
            raise ValueError("bindings 必须是对象")
        previous = self._facade().to_document()
        try:
            self._facade().save_bindings(bindings)
        except CatalogValidationError as exc:
            return self._send_catalog_error(exc)
        try:
            self._persist_facade(previous)
        except ProviderUnavailableError as exc:
            return self._send_json({"error": str(exc), "reason": exc.reason}, 503)
        return self._send_json(self._bindings_payload())

    def _provider_presets(self) -> dict[str, Any]:
        # 服务方案预置表带版本与来源，Web 只转交独立 Provider 模块
        return self._facade().presets_public_view()

    def _provider_candidates(self, provider_id: str) -> None:
        # 显式刷新候选模型：上游不可用时返回状态 unknown，不沿用上次列表
        body = self._read_json_body()
        override = None
        if isinstance(body, dict):
            raw = body.get("models_url")
            if isinstance(raw, str) and raw.strip():
                override = raw.strip()
        view = self._facade().providers_view()
        if not any(item["id"] == provider_id for item in view["providers"]):
            return self._send_json({"error": "Provider 不存在"}, 404)
        result = self._facade().refresh_candidates(provider_id, models_url_override=override)
        return self._send_json(result)

    def _test_provider(self, provider_id: str) -> None:
        body = self._read_json_body()
        if not isinstance(body, dict):
            raise ValueError("请求体必须是 JSON 对象")
        kind = body.get("kind", "connection")
        model_id = body.get("model_id")
        facade = self._facade()
        view = facade.providers_view()
        provider = next((item for item in view["providers"] if item["id"] == provider_id), None)
        if provider is None:
            return self._send_json({"error": "Provider 不存在"}, 404)
        if kind == "model":
            return self._model_test(provider_id, model_id, provider, facade)
        if kind != "connection":
            raise ValueError("kind 必须是 connection 或 model")
        candidates = [item for item in view["models"]
                      if item["provider_id"] == provider_id
                      and (model_id is None or item["id"] == model_id)]
        if model_id is not None and not candidates:
            return self._send_json({"error": "模型不存在"}, 404)
        if not candidates:
            raise ValueError("Provider 还没有模型，请先保存模型再测试连接")
        model = candidates[0]
        started = time.monotonic()
        try:
            result = facade.test_connection(
                {"key": provider_id, "provider_id": provider_id, "model_id": model["id"]})
        except CatalogValidationError as exc:
            elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
            reference = provider.get("credential_ref", "")
            if reference and any(issue.location.endswith(".credential")
                                 or "凭据引用无法解析" in issue.message for issue in exc.issues):
                error = f"缺少凭据环境变量 {reference}，请补充后重试"
            else:
                error = _readiness_message(exc, facade)
            return self._send_json({
                "ok": False,
                "error": error,
                "actual_model": None,
                "elapsed_ms": elapsed_ms,
                "revision": facade.revision,
                "admitted": None,
                "protocol": None,
            })
        elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        if not result.get("ok"):
            return self._send_json({
                "ok": False,
                "error": result.get("message") or result.get("reason") or "连接失败",
                "actual_model": None,
                "elapsed_ms": elapsed_ms,
                "revision": facade.revision,
                "admitted": None,
                "protocol": result.get("protocol"),
            })
        return self._send_json({
            "ok": True,
            "error": None,
            "actual_model": model["model"],
            "elapsed_ms": elapsed_ms,
            "revision": result.get("revision", facade.revision),
            "admitted": None,
            "protocol": result.get("protocol"),
        })

    def _model_test(self, provider_id: str, model_id: Any, provider: dict[str, Any],
                    facade: Any) -> None:
        # 模型测试发一次真实最小推理，通过后由模块记录准入
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("模型测试需要 model_id")
        model_id = model_id.strip()
        view = facade.providers_view()
        model = next((item for item in view["models"]
                      if item["provider_id"] == provider_id and item["id"] == model_id), None)
        if model is None:
            return self._send_json({"error": "模型不存在"}, 404)
        started = time.monotonic()
        try:
            result = facade.model_test(provider_id, model_id)
        except CatalogValidationError as exc:
            elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
            reference = provider.get("credential_ref", "")
            if reference and any(issue.location.endswith(".credential")
                                 or "凭据引用无法解析" in issue.message for issue in exc.issues):
                error = f"缺少凭据环境变量 {reference}，请补充后重试"
            else:
                error = _readiness_message(exc, facade)
            return self._send_json({
                "ok": False, "error": error, "actual_model": None,
                "elapsed_ms": elapsed_ms, "revision": facade.revision,
                "admitted": False, "protocol": model.get("protocol"),
            })
        elapsed_ms = result.get("elapsed_ms")
        if not isinstance(elapsed_ms, int):
            elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        ok = bool(result.get("ok"))
        payload = {
            "ok": ok,
            "error": result.get("error"),
            "actual_model": result.get("model") or result.get("actual_model"),
            "elapsed_ms": elapsed_ms,
            "revision": result.get("revision", facade.revision),
            "admitted": bool(result.get("admitted", ok)),
            "protocol": result.get("protocol") or model.get("protocol"),
            "usage_reported": bool(result.get("usage_reported", False)),
            "persisted": bool(result.get("persisted", False)),
        }
        if result.get("persist_error"):
            payload["persist_error"] = result["persist_error"]
        return self._send_json(payload)

    def _post_credentials(self) -> None:
        # 提交凭据及是否持久化；清除与删除用显式动作，不拿空字符串猜意图
        body = self._read_json_body()
        if not isinstance(body, dict):
            raise ValueError("请求体必须是 JSON 对象")
        facade = self._facade()
        ref = body.get("ref", body.get("credential_ref", ""))
        action = body.get("action", "set")
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError("缺少字段：ref")
        ref = ref.strip()
        if action == "set":
            secret = body.get("secret", body.get("api_key"))
            if not isinstance(secret, str) or not secret.strip():
                raise ValueError("提交凭据需要非空 secret，清除请用 clear_override 动作")
            facade.set_credential_override(ref, secret)
            if body.get("persist"):
                dotenv_path = facade.dotenv_path
                if dotenv_path is None:
                    return self._send_json(
                        {"error": "dotenv path is not configured", "reason": "dotenv_unconfigured"}, 503)
                try:
                    facade.save_dotenv_value(dotenv_path, ref, secret)
                except (CatalogValidationError, ValueError, OSError) as exc:
                    facade.clear_credential_override(ref)
                    return self._send_json({"error": f"持久化失败，未保存：{exc}",
                                            "reason": "dotenv_write_failed"}, 500)
            described = facade.providers_view()
            credential = next(
                (item["credential"] for item in described["providers"]
                 if item.get("credential_ref") == ref),
                {"ref": ref, "configured": True, "source": "override", "has_override": True},
            )
            return self._send_json({"ok": True, "ref": ref, "credential": credential,
                                    "revision": described["revision"]})
        if action == "clear_override":
            cleared = facade.clear_credential_override(ref)
            described = facade.providers_view()
            credential = next(
                (item["credential"] for item in described["providers"]
                 if item.get("credential_ref") == ref),
                {"ref": ref, "configured": False, "source": "missing", "has_override": False},
            )
            return self._send_json({"ok": True, "ref": ref, "cleared": cleared,
                                    "credential": credential, "revision": described["revision"]})
        if action == "remove_persisted":
            dotenv_path = facade.dotenv_path
            if dotenv_path is None:
                return self._send_json(
                    {"error": "dotenv path is not configured", "reason": "dotenv_unconfigured"}, 503)
            try:
                result = facade.remove_dotenv_value(dotenv_path, ref)
            except (ValueError, OSError) as exc:
                return self._send_json({"error": f"删除失败：{exc}",
                                        "reason": "dotenv_write_failed"}, 500)
            return self._send_json({"ok": True, "ref": ref,
                                    "removed": bool(result.get("removed")),
                                    "credential": {key: result[key] for key in
                                                   ("ref", "configured", "source", "has_override")
                                                   if key in result},
                                    "revision": facade.revision})
        raise ValueError("未知动作：action 必须是 set、clear_override 或 remove_persisted")

    def _post_reload(self) -> None:
        # 手动重载立即重读本地源，不调模型，返回实际生效修订及错误
        self._drain_body()
        result = self._facade().reload()
        return self._send_json(result)

    def _persist_facade(self, previous: dict[str, Any] | None = None) -> None:
        # 界面保存经模块原子写盘并立即发布；落盘失败回滚内存，不报成功
        facade = self._facade()
        path = facade.config_path
        if path is None:
            raise ProviderUnavailableError("provider catalog path is not configured")
        try:
            facade.persist_document(path)
        except OSError as exc:
            if previous is not None:
                try:
                    facade.store_document(previous)
                except (CatalogValidationError, ValueError):
                    pass
            raise ProviderUnavailableError("provider catalog file is not writable") from exc

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
            setting = project.department_settings[department]
            return self._send_json({
                "department": department,
                "project_id": project_id,
                "prompt_config": {"version": setting.version, "source": setting.source},
                "items": [
                    {
                        "work_item_id": item.work_item_id, "title": item.title, "status": item.status,
                        "view": None if item.status == "not_started" else observability.department(item.run_id, department),
                    }
                    for item in items
                ],
            })
        if rest[:1] == ["prompts"] and len(rest) == 2:
            return self._send_json(projects.read_department_setting(project_id, unquote(rest[1])))
        if rest == ["commands"]:
            return self._send_json({"project_id": project_id, "commands": projects.read_commands(project_id)})
        if rest[:1] == ["commands"] and len(rest) == 2:
            try:
                return self._send_json(projects.read_command(project_id, unquote(rest[1])))
            except ValueError as exc:
                return self._send_json({"error": str(exc)}, 404)
        if rest in (["model-attempts"], ["model-usage"]):
            wanted = self._query_scalar(query, "work_item")
            if wanted is not None and project.work_item(wanted) is None:
                return self._send_json({"error": "work item not found"}, 404)
            if rest == ["model-attempts"]:
                return self._send_json(self._project_attempts(project, query, store))
            return self._send_json(self._project_usage(project, query, store))
        if rest == ["stream"]:
            # 项目事件与所属 run 的事件
            return self._event_stream(self._resume_position(query), store, project_events=True,
                                      projects=[project.project_id])
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

    def _event_stream(self, after: int, store, *, project_events: bool, **scope: list[str]) -> None:
        # 旧控制台的事件流：按全局位置从事件日志读取范围内的事件并推送，SSE 的 id 是全局位置；
        # 断线以后从 Last-Event-ID 或 after 参数给出的位置续传。定时查询日志，没有新事件时发送保活注释
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last, idle = after, 0
        try:
            while True:
                events = store.read(last, **scope)
                for event in events:
                    last = event.position
                    if isinstance(event, ProjectEvent):
                        if project_events:
                            self._write_sse(event.position, "project", project_event_card(event))
                        continue
                    self._write_sse(event.position, "loop", {**event_card(event), "run_id": event.run_id,
                                                              "work_item_id": event.work_item_id})
                if events:
                    idle = 0
                else:
                    self.wfile.write(b": keepalive\n\n")
                    idle += 1
                self.wfile.flush()
                time.sleep(0.2 if idle < 25 else 1.0)
        except Exception:
            return

    def _resume_position(self, query: dict[str, list[str]]) -> int:
        # 续传的全局位置：Last-Event-ID 请求头优先，其次是 after 参数，都没有时从日志开头
        header = self.headers.get("Last-Event-ID")
        raw = header if header not in (None, "") else (query.get("after") or ["0"])[0]
        try:
            position = int(raw)
        except ValueError as exc:
            raise ValueError("the resume position must be a non-negative integer") from exc
        if position < 0:
            raise ValueError("the resume position must be a non-negative integer")
        return position

    def _write_sse(self, position: int, event_name: str, data: dict[str, Any]) -> None:
        chunk = f"id: {position}\nevent: {event_name}\ndata: {json_dumps(data)}\n\n"
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
            after = self._resume_position(query)
            events = [event for event in store.list_events(run_id) if event.position > after]
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
                    if (source is None or source.run_id != run_id or source.department != event.department
                            or source.stream_version != ref["seq"]
                            or source.payload.get("activation_id") != ref["activation_id"]
                            or source.payload.get("step_id") != ref["step_id"]):
                        raise ValueError("compaction source does not match its department history")
                    if source.event_id not in seen:
                        sources.append(event_card(source))
                        seen.add(source.event_id)
                prior = event.payload.get("previous_compaction_event_id")
                if prior:
                    source = store.get_event(prior)
                    if source is None or source.run_id != run_id or source.department != event.department or source.type != "compaction_recorded":
                        raise ValueError("previous compaction does not match its department")
                    sources.insert(0, event_card(source))
                detail["source_events"] = sources
            return self._send_json(detail)
        if rest == ["stream"]:
            # 这个 run 的事件；与它有关的项目事件（事项新建、采纳等）属于项目事件流
            project_run(store, run_id)
            return self._event_stream(self._resume_position(query), store, project_events=False, runs=[run_id])
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
                    "stream_version": projection.stream_version,
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


def _validate_provider_entry(body: dict[str, Any]) -> None:
    # 连接声明一种协议（ADR-0004）；模型访问定义不再声明协议
    required = {"id", "name", "protocol"}
    missing = required - set(body)
    if missing:
        raise ValueError("缺少字段：" + ", ".join(sorted(missing)))
    timeout = body.get("timeout_sec", 600)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout_sec 必须是正数")


def _readiness_message(exc: CatalogValidationError, facade: Any) -> str:
    # 连接测试失败的可定位说明：缺凭据点名引用，不露密钥
    view = facade.providers_view()
    providers = {item["id"]: item for item in view["providers"]}
    bindings = view["bindings"]
    parts: list[str] = []
    for issue in exc.issues:
        location = issue.location
        if location.endswith(".credential") or "凭据引用无法解析" in issue.message:
            department = location.split(".")[1] if location.startswith("selections.") else ""
            reference = ""
            binding = bindings.get(department)
            if isinstance(binding, dict):
                provider = providers.get(binding.get("provider_id", ""))
                reference = "" if provider is None else provider.get("credential_ref", "")
            if reference:
                parts.append(f"缺少凭据环境变量 {reference}，请补充后重试")
                continue
        parts.append(f"{location}: {issue.message}")
    return "；".join(parts) if parts else str(exc)


def _positive_int(key: str, value: Any) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{key} 必须是正整数")
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

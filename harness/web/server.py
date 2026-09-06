"""本地 Web 控制台：查询投影、SSE 订阅，命令交给 LoopSystem。"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..git_audit import git_version_detail
from ..models import ArtifactRef, EventType, GIT_VERSION_EVENTS, json_dumps
from ..observability import AttemptNotFoundError, ObservabilityQuery
from ..provider_catalog import CatalogValidationError
from ..projection import RunNotFoundError, project_run
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


class LoopConsoleServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, port: int, system: LoopSystem) -> None:
        super().__init__((host, port), LoopConsoleHandler)
        self.system = system
        self.store = system.store
        self._worker_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._active_run_id: str | None = None
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

    def error_for(self, run_id: str) -> str | None:
        with self._worker_lock:
            return self._worker_errors.get(run_id)

    def last_worker_error(self) -> dict[str, str] | None:
        with self._worker_lock:
            if not self._worker_errors:
                return None
            run_id, message = next(reversed(self._worker_errors.items()))
            return {"run_id": run_id, "message": message}

    def start_run(self, task: str, options: dict[str, int]) -> str:
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                raise BusyError("已有任务正在运行")
            status = self.system.provider_status()
            if not status.get("available", False):
                raise ProviderUnavailableError(
                    status.get("message") or "provider unavailable",
                    status.get("reason") or "provider_unavailable",
                )
            run_id = self.system.create_run(task, **options)
            worker = threading.Thread(
                target=self._run_worker,
                args=(run_id,),
                name=f"loop-worker-{run_id}",
                daemon=True,
            )
            self._active_run_id = run_id
            self._worker = worker
            worker.start()
            return run_id

    def _run_worker(self, run_id: str) -> None:
        try:
            self.system.run_until_stop(run_id)
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
            self._send_json({"error": "not found"}, 404)
        except RunNotFoundError as exc:
            self._send_json({"error": f"run not found: {exc}"}, 404)
        except AttemptNotFoundError as exc:
            self._send_json({"error": f"model attempt not found: {exc}"}, 404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        parts = [item for item in path.split("/") if item]
        try:
            if parts == ["api", "runs"]:
                return self._create_run()
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
            if path.startswith("/api/"):
                return self._send_json({"error": "not found"}, 404)
            self._send_json({"error": "not found"}, 404)
        except BusyError as exc:
            self._send_json({"error": str(exc), "reason": "busy"}, 409)
        except RunTerminalError as exc:
            self._send_json({"error": str(exc), "reason": "run_terminal"}, 409)
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
            "adapter": getattr(test_adapter, "name", "directory"),
            "provider_available": bool(status.get("available", False)),
            "provider_message": status.get("message", ""),
            "provider_bindings": status.get("departments", {}),
            "provider_status": status,
            "worker_error": self.server.last_worker_error(),
        }

    def _create_run(self) -> None:
        body = self._read_json_body()
        unknown = set(body) - {"task", "max_cycles", "context_window"}
        if unknown:
            raise ValueError("unsupported task fields: " + ", ".join(sorted(unknown)))
        task = body.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        options: dict[str, int] = {}
        for key in ("max_cycles", "context_window"):
            if key not in body or body[key] is None:
                continue
            options[key] = _positive_int(key, body[key])
        run_id = self.server.start_run(task, options)
        projection = project_run(self.server.store, run_id)
        self._send_json({"run_id": run_id, "phase": projection.phase}, 201)

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
        first = project_run(self.server.store, run_id)
        second = project_run(self.server.store, run_id)
        match = first.canonical_state() == second.canonical_state()
        self._send_json(
            {
                "ok": match,
                "mutated": False,
                "event_count": first.last_seq,
                "phase": first.phase,
            }
        )

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


def _positive_int(key: str, value: Any) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def serve(system: LoopSystem, host: str = "127.0.0.1", port: int = 8765) -> LoopConsoleServer:
    return LoopConsoleServer(host, port, system)

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from threading import Event
from typing import Any, Mapping, Sequence

from .credentials import CredentialChain, CredentialMaterial
from .discovery import refresh_candidates as _refresh_candidates
from .errors import CatalogValidationError, ProviderError, ValidationIssue
from .invoke import (
    CancelRegistry,
    InvokeResult,
    Observer,
    ProviderInput,
    invoke_once as _invoke_once,
    to_provider_input,
)
from .presets import PRESET_TABLE_SOURCE, PRESET_TABLE_VERSION, list_presets
from .resolve import FrozenTarget, ResolveSnapshot, resolve_snapshot
from .responses import ResponsesExecutionScope, check_availability
from .store import ProviderStore


# 三部门默认绑定键，模块自身不硬编码部门语义，只提供默认选择
REQUIRED_DEPARTMENTS = ("product", "engineering", "quality")


class ProviderFacade:
    # 独立 Provider 模块统一接口：目录、凭据、冻结目标、单次调用与取消
    def __init__(
        self,
        store: ProviderStore | None = None,
        credentials: CredentialChain | Mapping[str, Any] | None = None,
        execution_scope: ResponsesExecutionScope | None = None,
    ) -> None:
        self._store = store if store is not None else ProviderStore.empty()
        if isinstance(credentials, CredentialChain):
            self._credentials = credentials
        elif isinstance(credentials, Mapping):
            self._credentials = CredentialChain(overrides=credentials)
        elif credentials is None:
            self._credentials = CredentialChain()
        else:
            self._credentials = CredentialChain()
        self._scope = execution_scope
        self._cancels = CancelRegistry()
        # 部门绑定：department -> {"provider_id": ..., "model_id": ...}，与目录一起发布
        self._bindings: dict[str, dict[str, str]] = {}
        # 实际生效修订：目录与绑定任一发布即单调递增，包含 store.revision 的推进
        self._revision = 0
        self._lock = threading.RLock()
        # 本地源路径与轮询状态，Web 只提交命令与读取状态，不持有目录真相
        self._config_path: Path | None = None
        self._dotenv_path: Path | None = None
        self._config_state = "empty"
        self._reload_error: str | None = None
        self._disk_config_hash: bytes | None = None
        self._disk_config_seen = False
        self._disk_dotenv_hash: bytes | None = None
        self._disk_dotenv_seen = False
        self._watch_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()
        self._watch_interval_sec = 1.0

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def dotenv_path(self) -> Path | None:
        return self._dotenv_path

    def load(self, path: str | Path) -> int:
        # 读取本地非敏感目录并整体发布
        with self._lock:
            loaded = ProviderStore.load(path)
            self._store = loaded
            self._publish()
            return self._revision

    def load_dotenv_file(self, path: str | Path) -> int:
        # 载入独立 .env 字典来源，缺失即空
        with self._lock:
            return self._credentials.load_dotenv_file(path)

    def store(self, raw: Mapping[str, Any]) -> int:
        # 保存整份目录，结构合法但未就绪也可保存，不验证凭据
        with self._lock:
            self._store.save_catalog(raw)
            self._publish()
            return self._revision

    def save_provider(self, raw: Mapping[str, Any]) -> int:
        with self._lock:
            self._store.save_provider(raw)
            self._publish()
            return self._revision

    def save_model(self, raw: Mapping[str, Any]) -> int:
        with self._lock:
            self._store.save_model(raw)
            self._publish()
            return self._revision

    def persist(self, path: str | Path) -> Path:
        # 校验成功后原子落盘 providers.json 非敏感部分
        with self._lock:
            target = self._store.persist(path)
            self._note_config_written(target)
            return target

    def _publish(self) -> int:
        # 任一有效发布推进实际生效修订，单调递增
        self._revision += 1
        return self._revision

    def get_bindings(self) -> dict[str, dict[str, str]]:
        with self._lock:
            return {key: dict(value) for key, value in self._bindings.items()}

    def save_bindings(self, raw: Mapping[str, Any]) -> int:
        # 整体替换部门绑定，只校验引用结构，不验证凭据就绪
        with self._lock:
            bindings = _parse_bindings(raw, self._store)
            self._bindings = bindings
            self._publish()
            return self._revision

    def to_document(self) -> dict[str, Any]:
        # 非敏感文档：目录、模型访问定义与默认绑定，不含凭据
        with self._lock:
            document = self._store.to_dict()
            document["bindings"] = {key: dict(value) for key, value in self._bindings.items()}
            return document

    def store_document(self, raw: Mapping[str, Any]) -> int:
        # 校验整份文档后整体发布，失败不改内存，落盘由 persist_document 完成
        with self._lock:
            store, bindings = _parse_document(raw)
            self._store = store
            self._bindings = bindings
            self._publish()
            return self._revision

    def load_document(self, path: str | Path) -> int:
        # 启动与短命 CLI 读取一致版本：缺文件即空态发布，坏内容报错并保留内存
        source = Path(path)
        with self._lock:
            try:
                data = source.read_bytes()
            except OSError:
                self._store = ProviderStore.empty()
                self._bindings = {}
                self._config_state = "missing"
                self._reload_error = None
                self._disk_config_hash = None
                self._disk_config_seen = True
                self._publish()
                return self._revision
            try:
                raw = json.loads(data.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                self._config_state = "invalid"
                self._reload_error = f"Provider 配置无法解析：{exc}"
                raise CatalogValidationError((ValidationIssue("catalog", "无法读取 Provider 目录"),)) from exc
            try:
                store, bindings = _parse_document(raw)
            except CatalogValidationError as exc:
                self._config_state = "invalid"
                self._reload_error = str(exc)
                raise
            self._store = store
            self._bindings = bindings
            self._config_state = "loaded" if (store.providers or store.models or bindings) else "empty"
            self._reload_error = None
            self._disk_config_hash = hashlib.sha256(data).digest()
            self._disk_config_seen = True
            self._publish()
            return self._revision

    def persist_document(self, path: str | Path) -> Path:
        # 校验成功后原子落盘整份非敏感文档，落盘成功才发布跟踪哈希
        with self._lock:
            document = self.to_document()
            store, bindings = _parse_document(document)
            payload = json.dumps(
                {"revision": document["revision"], "providers": document["providers"],
                 "models": document["models"], "bindings": document["bindings"]},
                ensure_ascii=False, indent=2, sort_keys=True,
            ) + "\n"
            target = Path(path)
            parent = target.parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=str(parent) if str(parent) not in ("", ".") else None,
                                             prefix=target.name + ".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, target)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            self._store = store
            self._bindings = bindings
            self._note_config_written(target)
            return target

    def save_provider_entry(self, provider_raw: Mapping[str, Any],
                            models_raw: Sequence[Mapping[str, Any]] | None = None) -> int:
        # 单个 Provider 连带其模型一次提交：先按合并后整份校验，通过才逐项应用
        with self._lock:
            if not isinstance(provider_raw, Mapping):
                raise CatalogValidationError((ValidationIssue("providers", "应为对象"),))
            provider_id = provider_raw.get("id")
            document = self.to_document()
            providers = [item for item in document["providers"] if item.get("id") != provider_id]
            entry = dict(provider_raw)
            entry.pop("models", None)
            providers.append(entry)
            if models_raw is not None:
                if not isinstance(models_raw, list):
                    raise CatalogValidationError((ValidationIssue("models", "应为数组"),))
                models = [item for item in document["models"] if item.get("provider_id") != provider_id]
                for item in models_raw:
                    nested = dict(item)
                    nested["provider_id"] = provider_id
                    models.append(nested)
            else:
                models = document["models"]
            merged = {"providers": providers, "models": models, "bindings": document["bindings"]}
            _parse_document(merged)
            self._store.save_provider(entry)
            if models_raw is not None:
                for item in models_raw:
                    nested = dict(item)
                    nested["provider_id"] = provider_id
                    self._store.save_model(nested)
            self._publish()
            return self._revision

    def delete_provider(self, provider_id: str) -> int:
        # 删除无引用 Provider 及其模型，被模型或绑定引用时报可定位错误，不删改
        with self._lock:
            key = str(provider_id)
            if key not in self._store.providers:
                raise CatalogValidationError((ValidationIssue(f"providers.{key}", "Provider 不存在"),))
            dependents = _provider_dependents(self._store, self._bindings, key)
            if dependents:
                raise CatalogValidationError(tuple(
                    ValidationIssue(name, "仍被引用，无法删除") for name in dependents
                ))
            providers = [self._store.providers[name].public_dict()
                         for name in sorted(self._store.providers) if name != key]
            models = [self._store.models[name].public_dict()
                      for name in sorted(self._store.models)
                      if self._store.models[name].provider_id != key]
            candidate = ProviderStore.from_dict({"providers": providers, "models": models})
            candidate.revision = self._store.revision + 1
            self._store = candidate
            self._bindings = {name: dict(value) for name, value in self._bindings.items()}
            self._publish()
            return self._revision

    def set_credential_override(self, ref: str, secret: str | CredentialMaterial) -> None:
        # 内存覆盖，优先级最高
        with self._lock:
            self._credentials.set_override(ref, secret)

    def clear_credential_override(self, ref: str) -> bool:
        # 清除内存覆盖，露出下层来源，返回是否确实存在覆盖
        with self._lock:
            return self._credentials.clear_override(ref)

    def save_dotenv_value(self, dotenv_path: str | Path, ref: str, secret: str) -> dict[str, object]:
        # 持久化单个凭据到独立 .env：先原子落盘，成功才更新内存文件源；
        # 落盘失败时不报成功，也不悄悄降级为只在内存生效
        key = str(ref).strip()
        if not key:
            raise CatalogValidationError((ValidationIssue("credentials.ref", "凭据引用不能为空"),))
        if not isinstance(secret, str) or not secret.strip():
            raise CatalogValidationError((ValidationIssue("credentials.secret", "凭据内容不能为空"),))
        target = Path(dotenv_path)
        with self._lock:
            current = _read_dotenv_strict(target)
            current[key] = secret
            _atomic_write_dotenv(target, current)
            data = _read_dotenv_strict(target)
            self._credentials.replace_dotenv_dict(data)
            self._note_dotenv_written(target, data)
            return self._credentials.describe(key)

    def remove_dotenv_value(self, dotenv_path: str | Path, ref: str) -> dict[str, object]:
        # 移除持久凭据文件中的单个值，与清除内存覆盖是两个明确动作
        key = str(ref).strip()
        target = Path(dotenv_path)
        with self._lock:
            try:
                data = target.read_text(encoding="utf-8")
            except OSError:
                self._credentials.remove_dotenv_value(key)
                return {**self._credentials.describe(key), "removed": False}
            parsed = _parse_dotenv_or_raise(data)
            removed = parsed.pop(key, None) is not None
            _atomic_write_dotenv(target, parsed)
            self._credentials.remove_dotenv_value(key)
            self._note_dotenv_written(target, parsed)
            return {**self._credentials.describe(key), "removed": removed}

    def validate(self) -> None:
        with self._lock:
            self._store.validate()
            _parse_bindings(self._bindings, self._store)

    def public_view(self) -> dict[str, Any]:
        # 脱敏视图：secret 与 version 不进入
        with self._lock:
            view = self._store.public_view()
            described = []
            seen: set[str] = set()
            for provider_id in sorted(self._store.providers):
                ref = self._store.providers[provider_id].credential_ref
                if ref and ref not in seen:
                    seen.add(ref)
                    described.append(self._credentials.describe(ref))
            view["credentials"] = described
            return view

    def resolve_snapshot(
        self,
        selections: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]],
    ) -> ResolveSnapshot:
        # 解析任意选择列表，返回绑定 revision 的冻结目标，或逐项原因
        with self._lock:
            return resolve_snapshot(self._store, selections, self._credentials)

    def resolve_departments(
        self,
        departments: Sequence[str] = REQUIRED_DEPARTMENTS,
    ) -> ResolveSnapshot:
        # 按当前默认绑定一次读取一致的目录版本、凭据来源与目标列表；
        # 真实协议要求模型已通过模型测试准入，fake 只用于确定性测试不设门槛
        with self._lock:
            selections = []
            issues: list[ValidationIssue] = []
            for department in departments:
                binding = self._bindings.get(str(department))
                if binding is None:
                    issues.append(ValidationIssue(
                        f"bindings.{department}", f"部门 {department} 未绑定 Provider 与模型"))
                    continue
                selections.append({"key": str(department), **binding})
            if issues:
                raise CatalogValidationError(issues)
            snapshot = resolve_snapshot(self._store, selections, self._credentials)
            admission_issues: list[ValidationIssue] = []
            for key in sorted(snapshot.targets):
                binding = self._bindings.get(key, {})
                model = self._store.models.get(binding.get("model_id", ""))
                if model is not None and model.protocol != "fake" and not model.admitted:
                    admission_issues.append(ValidationIssue(
                        f"bindings.{key}.model_id",
                        f"模型 {model.id} 尚未通过模型测试准入，请先执行模型测试",
                    ))
            if admission_issues:
                raise CatalogValidationError(admission_issues)
            return snapshot

    def presets_public_view(self) -> dict[str, Any]:
        # 预置表数据与版本由模块提供，Web 只读取，不做远端热更
        return {
            "table_version": PRESET_TABLE_VERSION,
            "source": PRESET_TABLE_SOURCE,
            "presets": list_presets(),
        }

    def refresh_candidates(self, provider_id: str,
                           *, models_url_override: str | None = None) -> dict[str, Any]:
        # 显式刷新候选：结果只服务本次会话，不落盘、不自动绑定
        with self._lock:
            provider = self._store.providers.get(str(provider_id))
            if provider is None:
                raise CatalogValidationError((ValidationIssue(
                    f"providers.{provider_id}", "Provider 配置不存在"),))
        return _refresh_candidates(provider, models_url_override=models_url_override)

    def record_admission(self, provider_id: str, model_id: str,
                         *, admitted_model: str | None) -> dict[str, Any]:
        # 记录一次已通过的模型测试，绑定当前发布修订
        with self._lock:
            provider = self._store.providers.get(str(provider_id))
            model = self._store.models.get(str(model_id))
            if provider is None or model is None or model.provider_id != provider.id:
                raise CatalogValidationError((ValidationIssue(
                    f"models.{model_id}", "模型访问定义不存在"),))
            revision = self._store.mark_admitted(model.id, admitted_model=admitted_model)
            self._publish()
            stored = self._store.models[model.id]
            return {
                "model_id": stored.id,
                "revision": revision,
                "admitted_at": stored.admitted_at,
                "admitted_model": stored.admitted_model,
                "admitted_protocol": stored.admitted_protocol,
            }

    def model_test(self, provider_id: str, model_id: str) -> dict[str, Any]:
        # 对某个模型访问定义发一次真实最小推理；通过后记录准入，失败不记录
        with self._lock:
            provider = self._store.providers.get(str(provider_id))
            model = self._store.models.get(str(model_id))
            if provider is None or model is None or model.provider_id != provider.id:
                raise CatalogValidationError((ValidationIssue(
                    f"models.{model_id}", "模型访问定义不存在"),))
            snapshot = resolve_snapshot(
                self._store,
                [{"key": model.id, "provider_id": provider.id, "model_id": model.id}],
                self._credentials,
            )
        target = snapshot.target(model.id)
        provider_input = to_provider_input(
            [{"role": "user", "content": "ping"}],
            max_output_tokens=model.max_output_tokens,
        )
        started = time.monotonic()
        try:
            result = self._invoke_for_test(target, provider_input, model)
        except ProviderError as exc:
            elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
            return {
                "ok": False, "error": str(exc), "model": None, "admitted": False,
                "protocol": model.protocol, "revision": self.revision,
                "elapsed_ms": elapsed_ms, "usage_reported": False,
            }
        elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        actual = result.actual_model or result.model or None
        admission = self.record_admission(provider_id, model.id, admitted_model=actual)
        return {
            "ok": True, "error": None, "model": actual, "admitted": True,
            "protocol": model.protocol, "revision": admission["revision"],
            "elapsed_ms": elapsed_ms,
            "usage_reported": bool(result.usage.get("reported", False)),
        }

    def _invoke_for_test(self, target: FrozenTarget, provider_input: ProviderInput,
                         model: Any) -> InvokeResult:
        # 诊断调用走与正式调用相同的协议与身份路径，使用独立会话与尝试身份
        session_id = f"diagnostic:{target.provider_id}:{model.id}"
        attempt_id = f"diagnostic:{model.id}:1"
        if target.protocol == "fake":
            return _invoke_once(target, provider_input, session_id, attempt_id)
        if self._scope is not None:
            return _invoke_once(target, provider_input, session_id, attempt_id,
                                execution_scope=self._scope)
        with ResponsesExecutionScope() as scope:
            return _invoke_once(target, provider_input, session_id, attempt_id,
                                execution_scope=scope)

    def describe_readiness(
        self,
        departments: Sequence[str] = REQUIRED_DEPARTMENTS,
    ) -> dict[str, Any]:
        # 服务健康与模型就绪分开描述：是否可创建新任务、原因、可定位 issues，不露密钥
        with self._lock:
            names = [str(item) for item in departments]
            try:
                snapshot = self.resolve_departments(names)
            except CatalogValidationError as exc:
                issues = [{"location": issue.location, "message": issue.message}
                          for issue in exc.issues]
                if not self._store.providers and not self._store.models and not self._bindings:
                    reason = "provider_config_missing" if self._config_state in {"empty", "missing"} else "provider_invalid"
                    message = "尚未配置 Provider：请在控制台完成服务接入后再创建事项" if reason == "provider_config_missing" else "; ".join(
                        f"{item['location']}: {item['message']}" for item in issues)
                else:
                    reason = "provider_unavailable"
                    message = _readiness_message(exc, self._store, self._bindings)
                return {
                    "available": False,
                    "reason": reason,
                    "message": message,
                    "departments": {},
                    "issues": issues,
                    "revision": self._revision,
                    "model_admissions": self._model_admissions(),
                }
            return {
                "available": True,
                "reason": "",
                "message": "",
                "departments": {
                    key: _frozen_compat(snapshot.target(key), key) for key in sorted(snapshot.targets)
                },
                "issues": [],
                "revision": self._revision,
                "model_admissions": self._model_admissions(),
            }

    def _model_admissions(self) -> list[dict[str, Any]]:
        # 逐模型的准入事实与陈旧标记：陈旧结果保留为历史，绑定不因此失效；
        # 陈旧按目录修订判断，部门绑定变化不使已通过的模型测试失效
        catalog_revision = self._store.revision
        admissions = []
        for model_id in sorted(self._store.models):
            model = self._store.models[model_id]
            admissions.append({
                "model_id": model.id,
                "provider_id": model.provider_id,
                "protocol": model.protocol,
                "admitted": model.admitted,
                "admitted_at": model.admitted_at,
                "admitted_revision": model.admitted_revision,
                "admitted_model": model.admitted_model,
                "stale": bool(model.admitted and model.admitted_revision != catalog_revision),
            })
        return admissions

    def providers_view(self) -> dict[str, Any]:
        # 可编辑目录及就绪状态：凭据只显示 configured/source/覆盖状态
        with self._lock:
            providers = []
            for provider_id in sorted(self._store.providers):
                provider = self._store.providers[provider_id]
                item = provider.public_dict()
                described = (self._credentials.describe(provider.credential_ref)
                             if provider.credential_ref else
                             {"ref": "", "configured": True, "source": "none", "has_override": False})
                item["credential"] = described
                item["credential_configured"] = bool(described.get("configured"))
                item["models"] = [
                    self._store.models[key].public_dict()
                    for key in sorted(self._store.models)
                    if self._store.models[key].provider_id == provider_id
                ]
                providers.append(item)
            return {
                "revision": self._revision,
                "catalog_revision": self._store.revision,
                "providers": providers,
                "models": [self._store.models[key].public_dict() for key in sorted(self._store.models)],
                "bindings": {key: dict(value) for key, value in self._bindings.items()},
            }

    def invoke_once(
        self,
        frozen_target: FrozenTarget,
        provider_input: ProviderInput | Mapping[str, Any],
        session_id: str,
        attempt_id: str,
        abort_event: Event | None = None,
        observer: Observer | None = None,
        *,
        execution_scope: ResponsesExecutionScope | None = None,
    ) -> InvokeResult:
        # 单次调用，取消按 attempt_id 隔离；调用方可传入本次运行的连接作用域
        normalized = provider_input if isinstance(provider_input, ProviderInput) else _coerce_input(provider_input)
        event = abort_event if abort_event is not None else Event()
        scope = execution_scope if execution_scope is not None else self._scope
        if self._cancels.contains(attempt_id):
            # 同一次调用尝试不允许并发执行，避免两个请求共享取消身份
            raise ProviderError("Model invocation already has an active attempt", reason="provider_error")
        self._cancels.register(attempt_id, event)
        try:
            return _invoke_once(
                frozen_target, normalized, session_id, attempt_id,
                event, observer, execution_scope=scope,
            )
        finally:
            self._cancels.discard(attempt_id)

    def cancel(self, attempt_id: str) -> bool:
        # 只作用于本次调用尝试
        return self._cancels.cancel(attempt_id)

    def test_connection(self, selection: Mapping[str, Any]) -> dict[str, Any]:
        # 连接测试只证明地址与凭据可用，不证明具体模型可调
        snapshot = resolve_snapshot(self._store, [selection], self._credentials)
        key = str(selection.get("key", selection.get("target_key", selection.get("department", "target"))))
        frozen_target = snapshot.target(key)
        if frozen_target.protocol == "fake":
            return {"ok": True, "kind": "connection", "target_key": key,
                    "revision": snapshot.revision, "protocol": "fake"}
        if frozen_target.protocol == "responses":
            from .responses import ResponsesConfig
            availability = check_availability(ResponsesConfig(
                model=frozen_target.model, api_key=frozen_target.api_key,
                provider=frozen_target.provider_id, base_url=frozen_target.base_url,
                timeout_sec=frozen_target.timeout_sec,
            ))
            if not availability["available"]:
                return {"ok": False, "kind": "connection", "target_key": key,
                        "revision": snapshot.revision, "reason": availability["reason"],
                        "message": availability["message"]}
            return {"ok": True, "kind": "connection", "target_key": key,
                    "revision": snapshot.revision, "protocol": "responses"}
        raise ProviderError(f"unsupported provider protocol: {frozen_target.protocol}",
                            reason="unsupported_protocol")

    def configure_paths(self, config_path: str | Path | None,
                        dotenv_path: str | Path | None = None) -> None:
        # 记录本地源固定路径，不读取，读取由 load/reload/轮询完成
        with self._lock:
            self._config_path = None if config_path is None else Path(config_path)
            self._dotenv_path = None if dotenv_path is None else Path(dotenv_path)

    def config_status(self) -> dict[str, Any]:
        # 健康检查用：配置路径、有效修订、最近重载状态与 issues，不露密钥
        readiness = self.describe_readiness()
        with self._lock:
            return {
                "config_path": None if self._config_path is None else str(self._config_path),
                "dotenv_path": None if self._dotenv_path is None else str(self._dotenv_path),
                "config_state": self._config_state,
                "revision": self._revision,
                "reload_error": self._reload_error,
                "watching": self._watch_thread is not None and self._watch_thread.is_alive(),
                "available": readiness["available"],
                "reason": readiness["reason"],
                "message": readiness["message"],
                "issues": readiness["issues"],
            }

    def reload(self) -> dict[str, Any]:
        # 手动重载立即重读本地源，不调模型；损坏保留上一有效版本并暴露错误
        with self._lock:
            changed = False
            if self._config_path is not None:
                changed = self._poll_config_file() or changed
            if self._dotenv_path is not None:
                changed = self._poll_dotenv_file() or changed
            return {
                "ok": self._reload_error is None,
                "revision": self._revision,
                "config_state": self._config_state,
                "reload_error": self._reload_error,
                "changed": changed,
            }

    def start_watching(self, interval_sec: float = 1.0) -> None:
        # 模块内部文件轮询：约 1 秒，只读 providers.json 与 .env，用内容哈希核对
        with self._lock:
            if self._watch_thread is not None and self._watch_thread.is_alive():
                return
            self._watch_interval_sec = float(interval_sec) if interval_sec and interval_sec > 0 else 1.0
            self._watch_stop.clear()
            worker = threading.Thread(target=self._watch_loop, name="provider-config-watch",
                                      daemon=True)
            self._watch_thread = worker
            worker.start()

    def stop_watching(self) -> None:
        # 服务关闭停止轮询
        with self._lock:
            worker = self._watch_thread
            self._watch_thread = None
        self._watch_stop.set()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=5.0)

    def _watch_loop(self) -> None:
        while not self._watch_stop.wait(self._watch_interval_sec):
            try:
                with self._lock:
                    if self._config_path is not None:
                        self._poll_config_file()
                    if self._dotenv_path is not None:
                        self._poll_dotenv_file()
            except Exception as exc:
                with self._lock:
                    self._reload_error = f"配置轮询失败：{exc}"

    def _poll_config_file(self) -> bool:
        # 返回磁盘内容是否导致内存发布变化；失败保留上一有效版本
        assert self._config_path is not None
        try:
            data = self._config_path.read_bytes()
        except OSError:
            if self._disk_config_seen and self._disk_config_hash is None:
                return False
            # 明确删除目录文件表示撤销默认配置：新任务停止创建，旧任务不变
            self._store = ProviderStore.empty()
            self._bindings = {}
            self._config_state = "missing"
            self._reload_error = None
            self._disk_config_hash = None
            self._disk_config_seen = True
            self._publish()
            return True
        digest = hashlib.sha256(data).digest()
        if self._disk_config_seen and digest == self._disk_config_hash:
            return False
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            self._reload_error = f"Provider 配置无法解析：{exc}"
            self._disk_config_hash = digest
            self._disk_config_seen = True
            return False
        try:
            store, bindings = _parse_document(raw)
        except CatalogValidationError as exc:
            self._reload_error = str(exc)
            self._disk_config_hash = digest
            self._disk_config_seen = True
            return False
        self._store = store
        self._bindings = bindings
        self._config_state = "loaded" if (store.providers or store.models or bindings) else "empty"
        self._reload_error = None
        self._disk_config_hash = digest
        self._disk_config_seen = True
        self._publish()
        return True

    def _poll_dotenv_file(self) -> bool:
        # .env 删除或其中 Key 被删除即清除对应文件源值，不复活缓存
        assert self._dotenv_path is not None
        try:
            data = self._dotenv_path.read_bytes()
        except OSError:
            if self._disk_dotenv_seen and self._disk_dotenv_hash is None:
                return False
            self._credentials.clear_dotenv()
            self._disk_dotenv_hash = None
            self._disk_dotenv_seen = True
            return True
        digest = hashlib.sha256(data).digest()
        if self._disk_dotenv_seen and digest == self._disk_dotenv_hash:
            return False
        try:
            parsed = _parse_dotenv_or_raise(data.decode("utf-8"))
        except ValueError as exc:
            self._reload_error = f".env 解析失败：{exc}"
            self._disk_dotenv_hash = digest
            self._disk_dotenv_seen = True
            return False
        self._credentials.replace_dotenv_dict(parsed)
        self._reload_error = None
        self._disk_dotenv_hash = digest
        self._disk_dotenv_seen = True
        return True

    def _note_config_written(self, target: Path) -> None:
        # 自身落盘后同步跟踪哈希，轮询不再把刚发布版本当外部变更
        try:
            data = target.read_bytes()
        except OSError:
            return
        self._disk_config_hash = hashlib.sha256(data).digest()
        self._disk_config_seen = True
        if self._config_path is not None and target == self._config_path:
            self._reload_error = None

    def _note_dotenv_written(self, target: Path, data: Mapping[str, str]) -> None:
        _ = data
        try:
            raw = target.read_bytes()
        except OSError:
            return
        self._disk_dotenv_hash = hashlib.sha256(raw).digest()
        self._disk_dotenv_seen = True


def _coerce_input(raw: Mapping[str, Any]) -> ProviderInput:
    return to_provider_input(
        raw.get("messages", []), raw.get("tools", ()),
        raw.get("tool_results", ()), raw.get("max_output_tokens"),
    )


def _parse_document(raw: Any) -> tuple[ProviderStore, dict[str, dict[str, str]]]:
    # 整份非敏感文档：providers/models 走目录校验，bindings 校验引用结构
    if not isinstance(raw, Mapping):
        raise CatalogValidationError((ValidationIssue("catalog", "应为 JSON 对象"),))
    allowed = {"providers", "models", "bindings", "revision"}
    unknown = sorted(set(raw) - allowed, key=str)
    if unknown:
        raise CatalogValidationError(tuple(
            ValidationIssue(f"catalog.{key}", "未知字段") for key in unknown
        ))
    catalog_part = {
        "providers": raw.get("providers", []),
        "models": raw.get("models", []),
        "revision": raw.get("revision", 1),
    }
    store = ProviderStore.from_dict(catalog_part)
    bindings = _parse_bindings(raw.get("bindings", {}), store)
    return store, bindings


def _parse_bindings(raw: Any, store: ProviderStore) -> dict[str, dict[str, str]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise CatalogValidationError((ValidationIssue("bindings", "应为对象"),))
    bindings: dict[str, dict[str, str]] = {}
    issues: list[ValidationIssue] = []
    for department, item in raw.items():
        location = f"bindings.{department}"
        if not isinstance(item, Mapping):
            issues.append(ValidationIssue(location, "应为对象"))
            continue
        provider_id = item.get("provider_id")
        model_id = item.get("model_id")
        if not isinstance(provider_id, str) or not provider_id.strip() \
                or not isinstance(model_id, str) or not model_id.strip():
            issues.append(ValidationIssue(location, "必须包含 provider_id 与 model_id"))
            continue
        provider = store.providers.get(provider_id)
        model = store.models.get(model_id)
        if provider is None:
            issues.append(ValidationIssue(f"{location}.provider_id", "Provider 配置不存在"))
            continue
        if model is None:
            issues.append(ValidationIssue(f"{location}.model_id", "模型访问定义不存在"))
            continue
        if model.provider_id != provider.id:
            issues.append(ValidationIssue(location, "模型访问定义不属于该 Provider 配置"))
            continue
        bindings[str(department)] = {"provider_id": provider.id, "model_id": model.id}
    if issues:
        raise CatalogValidationError(issues)
    return bindings


def _provider_dependents(store: ProviderStore, bindings: Mapping[str, Mapping[str, str]],
                         provider_id: str) -> list[str]:
    dependents: list[str] = []
    model_ids = []
    for model_id in sorted(store.models):
        if store.models[model_id].provider_id == provider_id:
            dependents.append(f"models.{model_id}")
            model_ids.append(model_id)
    for department in sorted(bindings):
        binding = bindings[department]
        if binding.get("provider_id") == provider_id:
            dependents.append(f"bindings.{department}")
        elif binding.get("model_id") in model_ids:
            dependents.append(f"bindings.{department}")
    return dependents


def _frozen_compat(frozen_target: FrozenTarget, department: str) -> dict[str, Any]:
    # 任务快照只存非敏感身份：公开身份加部门与凭据版本，不含密钥
    payload = frozen_target.public_dict()
    payload["department"] = str(department)
    payload["credential_version"] = frozen_target.credential_version
    return payload


def _readiness_message(exc: CatalogValidationError, store: ProviderStore,
                       bindings: Mapping[str, Mapping[str, str]]) -> str:
    parts: list[str] = []
    for issue in exc.issues:
        location = issue.location
        if location.endswith(".credential") or "凭据引用无法解析" in issue.message:
            department = location.split(".")[1] if location.startswith("selections.") else ""
            reference = ""
            binding = bindings.get(department)
            if binding is not None:
                provider = store.providers.get(binding.get("provider_id", ""))
                reference = "" if provider is None else provider.credential_ref
            if reference:
                parts.append(f"{location}: 部门 {department} 缺少凭据环境变量 {reference}，请补充后重试")
                continue
        if "部门绑定缺失" in issue.message or "未绑定" in issue.message:
            department = location.rsplit(".", 1)[-1]
            parts.append(f"{location}: 部门 {department} 未绑定 Provider 与模型")
            continue
        if "context_window" in issue.message:
            parts.append(f"{location}: {issue.message}（请为该部门绑定声明容量的模型）")
            continue
        parts.append(f"{location}: {issue.message}")
    return "；".join(parts) if parts else str(exc)


def _parse_dotenv_or_raise(text: str) -> dict[str, str]:
    from .credentials import parse_dotenv_text
    return parse_dotenv_text(text)


def _read_dotenv_strict(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return _parse_dotenv_or_raise(text)


def _atomic_write_dotenv(path: Path, data: Mapping[str, str]) -> Path:
    # 原子替换写 .env：临时文件同目录创建，成功才替换；保持文件权限语义，
    # 已有文件沿用原权限，新文件使用用户私有权限；Windows 下 ACL 由目录继承，
    # 不把数字模式当成权限已受保护的证明
    parent = path.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in sorted(data.items(), key=lambda item: str(item[0]))]
    payload = "".join(line + "\n" for line in lines)
    existing_mode = None
    try:
        existing_mode = path.stat().st_mode & 0o777
    except OSError:
        existing_mode = None
    fd, tmp_name = tempfile.mkstemp(dir=str(parent) if str(parent) not in ("", ".") else None,
                                     prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            try:
                os.chmod(tmp_name, existing_mode)
            except OSError:
                pass
        elif os.name == "posix":
            try:
                os.chmod(tmp_name, 0o600)
            except OSError:
                pass
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


__all__ = ["ProviderFacade", "CatalogValidationError", "REQUIRED_DEPARTMENTS"]

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Callable, Container
from contextlib import aclosing
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .call import CallUsage, ModelCall, ModelResponse, ModelStreamEvent
from .credentials import CredentialChain, CredentialMaterial
from .discovery import refresh_candidates as _refresh_candidates
from .errors import CatalogValidationError, ProviderError, ValidationIssue
from .invoke import (
    CancelRegistry,
    InvokeResult,
    ProviderInput,
    check_target_availability,
    provider_input_for,
    stream_invocation,
    to_provider_input,
)
from .presets import PRESET_TABLE_SOURCE, PRESET_TABLE_VERSION, list_presets
from .resolve import (
    CallTargetResolution,
    FrozenTarget,
    ResolveSnapshot,
    call_target_public,
    resolve_call_target as _resolve_call_target,
    resolve_snapshot,
)
from .responses import ProviderConnections
from .store import SUPPORTED_PROTOCOLS, ProviderStore


# 三部门默认绑定键，模块自身不硬编码部门语义，只提供默认选择
REQUIRED_DEPARTMENTS = ("product", "engineering", "quality")


class ProviderFacade:
    # 独立 Provider 模块统一接口：目录、凭据、冻结目标、单次调用与取消
    def __init__(
        self,
        store: ProviderStore | None = None,
        credentials: CredentialChain | Mapping[str, Any] | None = None,
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
        self._cancels = CancelRegistry()
        # 部门绑定：department -> {"provider_id": ..., "model_id": ...}，与目录一起发布
        self._bindings: dict[str, dict[str, str]] = {}
        # 按句柄持有的调用目标：句柄 -> (内部目标, 公开部分)。凭据材料只在这里，控制核心不持有
        self._call_targets: dict[str, tuple[FrozenTarget, dict[str, Any]]] = {}
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
        # 凭据版本：每次被接受的凭据命令推进，供基准版本核对；只在本次进程内累计
        self._credential_versions: dict[str, int] = {}
        # 目录文件被外部修改并发布以后的回调，由系统装配登记（写入口据它补写 catalog_revised）
        self._reload_listener: Callable[[], None] | None = None

    @property
    def revision(self) -> int:
        return self._revision

    def catalog_revision(self) -> int:
        # 目录修订号：保存在目录文件里，重启以后继续可比；目录内容修改一次就推进
        with self._lock:
            return self._store.revision

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
        # 整体替换部门绑定，只校验引用结构，不验证凭据就绪；有变化时推进目录修订号
        with self._lock:
            bindings = _parse_bindings(raw, self._store)
            if bindings != self._bindings:
                self._store.bump_revision()
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

    def replace_catalog_document(self, raw: Mapping[str, Any]) -> int:
        # 导入整份文档：以当前修订号加一发布，文档里的旧修订号不会让修订号回退
        with self._lock:
            document = dict(raw)
            document["revision"] = self._store.revision + 1
            self.store_document(document)
            return self._store.revision

    def merge_model_admissions(self, models: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        # 命令保存访问定义时保留已有的准入事实：准入只由模型测试写入，客户端不提交它
        merged: list[dict[str, Any]] = []
        for item in models:
            entry = dict(item)
            existing = self._store.models.get(str(entry.get("id")))
            if existing is not None:
                for key in ("admitted_at", "admitted_revision", "admitted_model"):
                    if getattr(existing, key) is not None:
                        entry[key] = getattr(existing, key)
            merged.append(entry)
        return merged

    def persist_catalog(self, previous: Mapping[str, Any]) -> str | None:
        # 保存以后落盘；失败时恢复上一份文档并返回错误说明；没有配置路径时不做任何事
        with self._lock:
            if self._config_path is None:
                return None
            try:
                self.persist_document(self._config_path)
                return None
            except OSError as exc:
                self.store_document(previous)
                return f"目录文件写入失败：{exc}"

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
        # 删除 Provider 配置：其下的模型访问定义一并删除（定义本身不算引用方）；
        # 仍被部门默认引用时拒绝并列出引用方，不删改
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

    def credential_version(self, ref: str) -> int:
        # 凭据版本：目录查询返回它，凭据命令的基准版本与它核对
        with self._lock:
            return self._credential_versions.get(str(ref), 0)

    def credential_status(self, ref: str) -> dict[str, Any]:
        # 脱敏状态加版本，不含 Key
        with self._lock:
            status: dict[str, Any] = dict(self._credentials.describe(ref))
            status["version"] = self._credential_versions.get(str(ref), 0)
            return status

    def set_credential(self, ref: str, secret: str, *, persist: bool) -> dict[str, Any]:
        # 保存 Key：只在本进程内覆盖，或同时写入独立 .env；落盘失败时不报成功
        with self._lock:
            key = str(ref)
            self._credentials.set_override(key, secret)
            persisted = False
            if persist:
                if self._dotenv_path is None:
                    self._credentials.clear_override(key)
                    raise CatalogValidationError((ValidationIssue("credentials.ref", "未配置凭据文件路径"),))
                try:
                    self.save_dotenv_value(self._dotenv_path, key, secret)
                except OSError as exc:
                    self._credentials.clear_override(key)
                    raise CatalogValidationError((ValidationIssue(
                        "credentials.ref", f"持凭据写入失败：{exc}"),))
                persisted = True
            version = self._credential_versions[key] = self._credential_versions.get(key, 0) + 1
            return {"status": dict(self._credentials.describe(key)), "version": version, "persisted": persisted}

    def clear_credential(self, ref: str) -> dict[str, Any]:
        # 清除内存覆盖，露出下层来源；版本照常推进
        with self._lock:
            key = str(ref)
            cleared = self._credentials.clear_override(key)
            version = self._credential_versions[key] = self._credential_versions.get(key, 0) + 1
            return {"status": dict(self._credentials.describe(key)), "version": version, "cleared": cleared}

    def remove_persisted_credential(self, ref: str) -> dict[str, Any]:
        # 删除独立 .env 中的单个值；版本照常推进
        with self._lock:
            if self._dotenv_path is None:
                raise CatalogValidationError((ValidationIssue("credentials.ref", "未配置凭据文件路径"),))
            key = str(ref)
            try:
                result = self.remove_dotenv_value(self._dotenv_path, key)
            except (ValueError, OSError) as exc:
                raise CatalogValidationError((ValidationIssue("credentials.ref", f"删除凭据失败：{exc}"),))
            version = self._credential_versions[key] = self._credential_versions.get(key, 0) + 1
            return {"status": dict(self._credentials.describe(key)), "version": version,
                    "removed": bool(result.get("removed"))}

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
                provider = self._store.providers.get(binding.get("provider_id", ""))
                if model is not None and provider is not None \
                        and provider.protocol != "fake" and not model.admitted:
                    admission_issues.append(ValidationIssue(
                        f"bindings.{key}.model_id",
                        f"模型 {model.id} 尚未通过模型测试准入，请先执行模型测试",
                    ))
            if admission_issues:
                raise CatalogValidationError(admission_issues)
            return snapshot

    def resolve_call_target(self, model_id: str, requested_tier: str | None = None) -> CallTargetResolution:
        # 每次模型请求之前解析调用目标：只接收模型访问定义引用与请求档位，不认识部门。
        # 检查定义存在、所属连接存在、准入有效、窗口已知、凭据可用；凭据材料留在 Provider 模块内，
        # 交回的公开部分不含密钥，执行调用时按句柄取出材料
        with self._lock:
            resolution, target = _resolve_call_target(self._store, self._credentials, model_id, requested_tier)
            if target is None:
                return resolution
            handle_id = f"target_{uuid4().hex[:16]}"
            self._call_targets[handle_id] = (target, dict(resolution.public))
            return replace(resolution, handle_id=handle_id)

    def release_call_handle(self, handle_id: str) -> dict[str, Any]:
        # 一次逻辑调用结束（成功，或不再重试）时丢弃它保留的凭据材料，交回这次解析的公开部分
        with self._lock:
            _, public = self._call_targets.pop(str(handle_id))
            return dict(public)

    def resolve_department_default(self, department: str,
                                   requested_tier: str | None = None) -> CallTargetResolution:
        # 步骤驱动使用的内部入口：同一把锁内读取该部门的部门默认并解析。
        # 对外的解析入口仍只接收模型访问定义引用与请求档位，不接收部门（#45 架构答复第 4 条）
        with self._lock:
            binding = self._bindings.get(str(department))
            if binding is None:
                return CallTargetResolution(
                    False, "provider_unavailable", f"部门 {department} 未绑定 Provider 与模型",
                    call_target_public(None, requested_tier),
                )
            resolution, target = _resolve_call_target(
                self._store, self._credentials, binding.get("model_id"), requested_tier,
            )
            if target is None:
                return resolution
            handle_id = f"target_{uuid4().hex[:16]}"
            self._call_targets[handle_id] = (target, dict(resolution.public))
            return replace(resolution, handle_id=handle_id)

    def bind_call_key(self, handle_id: str, call_key: str) -> None:
        # 把已解析的目标改挂到这次逻辑调用的身份上；重试沿用同一身份，凭据材料仍留在 Provider 模块
        with self._lock:
            current = str(handle_id)
            key = str(call_key)
            if current == key:
                return
            self._call_targets[key] = self._call_targets.pop(current)

    def presets_public_view(self) -> dict[str, Any]:
        # 预置表数据与版本由模块提供，Web 只读取，不做远端热更
        return {
            "revision": PRESET_TABLE_VERSION,
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
                "admitted_protocol": provider.protocol,
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
                "protocol": provider.protocol, "revision": self.revision,
                "elapsed_ms": elapsed_ms, "usage_reported": False,
            }
        elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        actual = result.actual_model or result.model or None
        admission = self.record_admission(provider_id, model.id, admitted_model=actual)
        persisted, persist_error = self._persist_admission()
        payload = {
            "ok": True, "error": None, "model": actual, "admitted": True,
            "protocol": provider.protocol, "revision": admission["revision"],
            "elapsed_ms": elapsed_ms,
            "usage_reported": bool(result.usage.get("reported", False)),
            "persisted": persisted,
        }
        if persist_error is not None:
            payload["persist_error"] = persist_error
        return payload

    def _persist_admission(self) -> tuple[bool, str | None]:
        # 准入是需落盘的结果：CLI 与 smoke 在独立进程读取同一份配置；
        # 写入失败时保留内存准入并如实报告，不谎称已持久化
        if self._config_path is None:
            return False, None
        try:
            self.persist_document(self._config_path)
        except OSError as exc:
            return False, f"准入未能写入 {self._config_path}：{exc}"
        return True, None

    def _invoke_for_test(self, target: FrozenTarget, provider_input: ProviderInput,
                         model: Any) -> InvokeResult:
        # 诊断调用由接口层同步发起，在自己的事件循环中走与正式调用相同的协议与身份路径，
        # 使用独立会话，每次新建客户端；Web 服务多线程，同一个模型可能同时测试，每次调用使用唯一的尝试身份
        session_id = f"diagnostic:{target.provider_id}:{model.id}"
        attempt_id = f"diagnostic:{model.id}:{uuid4().hex}"

        async def run() -> InvokeResult:
            async with aclosing(stream_invocation(target, provider_input, session_id, attempt_id,
                                                  self._cancels)) as items:
                async for item in items:
                    if isinstance(item, InvokeResult):
                        return item
            raise ProviderError("Model invocation ended without a result", reason="provider_protocol")

        return asyncio.run(run())

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
            provider = self._store.providers.get(model.provider_id)
            admissions.append({
                "model_id": model.id,
                "provider_id": model.provider_id,
                "protocol": None if provider is None else provider.protocol,
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

    async def stream(
        self,
        frozen_target: FrozenTarget,
        call: ModelCall,
        *,
        connections: ProviderConnections | None = None,
        cancelled: Container[str] = (),
    ) -> AsyncIterator[ModelStreamEvent | ModelResponse]:
        # 一次模型调用尝试：逐条交回流式输出，最后交回结果；取消按 call.attempt_id 生效。
        # connections 由调用方在自己的事件循环中持有，用于复用连接；不给时本次调用新建客户端。
        # cancelled 是调用方记下的、在尝试开始之前收到取消的尝试身份，由调用方持有与释放；
        # 调用方取消时先记入 cancelled 再调用 cancel
        items = stream_invocation(frozen_target, provider_input_for(call), call.session_id, call.attempt_id,
                                  self._cancels, connections=connections, cancelled=cancelled)
        async with aclosing(items):
            async for item in items:
                if isinstance(item, InvokeResult):
                    yield _model_response(item)
                    return
                event = _stream_event(item)
                if event is not None:
                    yield event

    async def stream_handle(
        self,
        handle_id: str,
        call: ModelCall,
        *,
        connections: ProviderConnections | None = None,
        cancelled: Container[str] = (),
    ) -> AsyncIterator[ModelStreamEvent | ModelResponse]:
        # 按这次逻辑调用的身份取出保留的目标再发送。目标在调用开始时取出，进行中的调用不随 reload 更换；
        # 句柄不存在说明调用开始前目标已经释放，按模型不可用报错
        with self._lock:
            try:
                target, _public = self._call_targets[str(handle_id)]
            except KeyError as exc:
                raise ProviderError(f"调用目标句柄不存在：{handle_id}", reason="provider_unavailable") from exc
        async for item in self.stream(target, call, connections=connections, cancelled=cancelled):
            yield item

    def cancel(self, attempt_id: str) -> bool:
        # 只作用于正在进行的这次调用尝试，返回是否找到；尝试不在进行时不留下记录
        return self._cancels.cancel(attempt_id)

    def test_connection(self, selection: Mapping[str, Any]) -> dict[str, Any]:
        # 连接测试只证明地址与凭据可用，不证明具体模型可调；三种协议同一套缺失项检查
        snapshot = resolve_snapshot(self._store, [selection], self._credentials)
        key = str(selection.get("key", selection.get("target_key", selection.get("department", "target"))))
        frozen_target = snapshot.target(key)
        protocol = frozen_target.protocol
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ProviderError(f"unsupported provider protocol: {protocol}",
                                reason="unsupported_protocol")
        availability = check_target_availability(frozen_target)
        if not availability["available"]:
            return {"ok": False, "kind": "connection", "target_key": key,
                    "revision": snapshot.revision, "protocol": protocol,
                    "reason": availability["reason"], "message": availability["message"]}
        return {"ok": True, "kind": "connection", "target_key": key,
                "revision": snapshot.revision, "protocol": protocol}

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

    def set_reload_listener(self, listener: Callable[[], None] | None) -> None:
        # 目录文件被外部修改并成功发布以后的回调；由系统装配登记
        with self._lock:
            self._reload_listener = listener

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
                changed = False
                with self._lock:
                    if self._config_path is not None:
                        changed = self._poll_config_file() or changed
                    if self._dotenv_path is not None:
                        changed = self._poll_dotenv_file() or changed
                if changed:
                    self._notify_reload()
            except Exception as exc:
                with self._lock:
                    self._reload_error = f"配置轮询失败：{exc}"

    def _notify_reload(self) -> None:
        # 在锁外调用：回调要经写入口追加目录事件
        listener = self._reload_listener
        if listener is not None:
            listener()

    def _poll_config_file(self) -> bool:
        # 返回磁盘内容是否导致内存发布变化；失败保留上一有效版本
        assert self._config_path is not None
        try:
            data = self._config_path.read_bytes()
        except OSError:
            if self._disk_config_seen and self._disk_config_hash is None:
                return False
            # 明确删除目录文件表示撤销默认配置：新任务停止创建，旧任务不变；修订号继续前进
            previous_revision = self._store.revision
            self._store = ProviderStore.empty()
            self._store.revision = previous_revision + 1
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
        previous_revision = self._store.revision
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
        # 外部修改的事件必须带新修订号：文件里的修订号不比当前大时推进一号
        if store.revision <= previous_revision:
            store.revision = previous_revision + 1
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


def _stream_event(event: Mapping[str, Any]) -> ModelStreamEvent | None:
    # 协议实现交出的观察换成合同中的流式输出；未知种类不交回
    kind = event.get("kind")
    payload = event.get("payload")
    payload = dict(payload) if isinstance(payload, Mapping) else {}
    provider = event.get("provider")
    model = event.get("model")
    identity = {
        "id": str(event.get("id")) if event.get("id") is not None else "",
        "payload": payload,
        "provider": str(provider) if provider is not None else None,
        "model": str(model) if model is not None else None,
    }
    if kind == "request":
        return ModelStreamEvent(kind="request", **identity)
    if kind == "stream_event":
        return ModelStreamEvent(kind="stream_event", source="sdk_decoded_stream", sequence=event.get("sequence"),
                                stage=event["stage"], response_id=event["response_id"], **identity)
    if kind == "response":
        return ModelStreamEvent(kind="response", source="sdk_response", **identity)
    if kind == "usage":
        # 优先使用协议实现已经归一化的用量（缓存字段不重复计入输入），payload.usage 只是原始证据
        mapped = event.get("usage")
        raw = mapped if isinstance(mapped, Mapping) else payload.get("usage")
        return ModelStreamEvent(kind="usage", usage=_call_usage(raw), **identity)
    if kind == "message":
        text = event.get("text")
        return ModelStreamEvent(kind="message", text=str(text) if text is not None else "", **identity)
    return None


def _model_response(result: InvokeResult) -> ModelResponse:
    # 只记录服务实际返回的模型，未返回保持未知，不拿请求模型冒充
    return ModelResponse(
        output=result.output,
        usage=_call_usage(result.usage),
        provider=result.provider,
        model=result.actual_model or "",
        response_id=result.response_id,
        sdk_response=dict(result.wire_evidence),
    )


def _call_usage(raw: Any) -> CallUsage:
    # 用量只做只读记录，未上报保持未知，不估算
    if not isinstance(raw, Mapping):
        return CallUsage(reported=False)

    def count(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    return CallUsage(
        input_tokens=count("input_tokens"),
        output_tokens=count("output_tokens"),
        total_tokens=count("total_tokens"),
        latency_ms=count("latency_ms"),
        cache_read_tokens=count("cache_read_tokens"),
        cache_write_tokens=count("cache_write_tokens"),
        reported=bool(raw.get("reported", False)),
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
    # 定义本身不算引用方：删除连接时它下面的定义一并删除；只有部门默认等引用会拒绝
    dependents: list[str] = []
    model_ids = {model_id for model_id in store.models
                 if store.models[model_id].provider_id == provider_id}
    for department in sorted(bindings):
        binding = bindings[department]
        if binding.get("provider_id") == provider_id or binding.get("model_id") in model_ids:
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

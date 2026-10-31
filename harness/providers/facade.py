from __future__ import annotations

import asyncio
import copy
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
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from .call import CallUsage, ModelCall, ModelResponse, ModelStreamEvent
from .credentials import CredentialChain, CredentialMaterial, connection_credential_ref, dotenv_key_problem
from .discovery import _parse_candidates, effective_models_url, probe_connection as _probe_connection
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
    EffectiveModelResolution,
    FrozenTarget,
    ResolveSnapshot,
    call_target_public,
    resolve_call_target as _resolve_call_target,
    resolve_snapshot,
)
from ..definitions import DEFINITIONS
from .responses import ProviderConnections
from .sdk import prepare_protocols
from .selection import ModelSelection, SelectionResolution, merge_selection
from .selection_flow import ProviderChange, SelectionAttempt, SelectionFlow
from .suggested import reminders as _suggested_reminders
from .store import (
    REASONING_LEVELS,
    SUPPORTED_PROTOCOLS,
    AdmissionRecord,
    ProviderStore,
    _parse_admission_document,
    _utc_now,
    admission_is_current,
)


# 三部门默认绑定键，模块自身不硬编码部门语义，只提供默认选择
REQUIRED_DEPARTMENTS = ("product", "engineering", "quality")

# 启动方式：normal 读取真实目录，拒绝 fake 连接；test 与 demo 为测试和演示放行 fake（工单 #86）
STARTUP_MODES = ("normal", "test", "demo")


class ProviderFacade:
    # 独立 Provider 模块统一接口：目录、凭据、冻结目标、单次调用与取消
    def __init__(
        self,
        store: ProviderStore | None = None,
        credentials: CredentialChain | Mapping[str, Any] | None = None,
        startup_mode: str = "normal",
    ) -> None:
        if startup_mode not in STARTUP_MODES:
            raise ValueError("startup_mode 只能是 " + "、".join(STARTUP_MODES))
        self._store = store if store is not None else ProviderStore.empty()
        prepare_protocols(model.protocol for model in self._store.models.values())
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
        self.selections = SelectionFlow(self._lock, self._cancels.cancel)
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
        # 最近获取的候选只在本次服务进程内存在，目录文件与重启都不恢复它。
        self._candidate_results: dict[str, dict[str, Any]] = {}
        # 目录文件被外部修改并发布以后的回调，由系统装配登记（写入口据它补写 catalog_revised）
        self._reload_listener: Callable[[], None] | None = None
        # 启动方式：normal 拒绝 fake 连接，test 与 demo 放行（工单 #86）
        self._startup_mode = startup_mode
        # 准入记录：model_id -> AdmissionRecord，与目录分开保存，按受影响字段逐项判有效性
        self._admissions: dict[str, AdmissionRecord] = {}
        self._admission_path: Path | None = None
        self._admission_seen = False
        # 有效地址/凭据的差异只在进程内比较；回调只携带版本和动作，不携带凭据或摘要。
        self._change_listener: Callable[[tuple[ProviderChange, ...]], None] | None = None
        self._source_snapshot: dict[str, tuple[tuple[str, str], bytes | None]] = {}
        self._source_versions: dict[str, int] = {}

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

    @property
    def admission_path(self) -> Path | None:
        return self._admission_path

    @property
    def startup_mode(self) -> str:
        # 启动方式属性：normal 拒绝 fake 连接，test 与 demo 放行（工单 #86）
        return self._startup_mode

    @startup_mode.setter
    def startup_mode(self, value: str) -> None:
        if value not in STARTUP_MODES:
            raise ValueError("startup_mode 只能是 " + "、".join(STARTUP_MODES))
        with self._lock:
            self._startup_mode = value

    def load(self, path: str | Path) -> int:
        # 读取本地非敏感目录并整体发布；fake 门禁在 _parse_document，故走整份文档路径
        return self.load_document(path)

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

    def _publish(self, *, refresh_state: bool = True) -> int:
        # 任一有效发布推进实际生效修订，单调递增；成功发布以后配置状态按内存内容重算
        # （工单 #301：保存成功页头不再停留旧的删除或缺失）。删除与缺失是文件层面的状态，
        # 由各自的入口显式传入 refresh_state=False 保留
        if refresh_state:
            self._config_state = ("loaded" if (self._store.providers or self._store.models
                                               or self._bindings) else "empty")
        # 模型目录用到的协议在这里准备 SDK（第一次请求之前，不计入请求时限）
        prepare_protocols(model.protocol for model in self._store.models.values())
        self._revision += 1
        return self._revision

    def get_bindings(self) -> dict[str, dict[str, str]]:
        with self._lock:
            return {key: dict(value) for key, value in self._bindings.items()}

    def save_bindings(self, raw: Mapping[str, Any]) -> int:
        # 保存部门默认要求所选定义已准入且未作废；引用结构不合法或未准入都整份拒绝，
        # 有变化时推进目录修订号（准入有效性按字段比较，与目录修订无关）
        with self._lock:
            bindings = _parse_bindings(raw, self._store)
            _require_bound_admissions(bindings, self._store, self._admissions)
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
            store, bindings = _parse_document(raw, self._startup_mode)
            self._store = store
            self._bindings = bindings
            self._publish()
            return self._revision

    def replace_catalog_document(self, raw: Mapping[str, Any]) -> int:
        # 导入整份文档：以当前修订号加一发布，文档里的旧修订号不会让修订号回退。
        # 部门默认与角色默认只能引用已准入、并且属于所填连接的定义（设计说明第 4.6 节），
        # 整份文档的全部绑定在此核对，与现有绑定相同的条目不豁免（工单 #1310）；
        # 准入有效性按保存前的配置核对（effective_store=self._store，与 save_bindings 同一基准）：
        # 文档自带连接字段的重新配置（如改地址）不作废引用，由保存后的重测重新准入
        # （设计说明第 5.5 节引用保留、第 14 节验收第 10 条）。
        # 导入移除被引用的定义、或移除被引用定义所属的连接时由应用层按移除单条定义的同一规则拒绝
        # （第 4.5、4.6 节），引用方包含各部门默认与项目部门设置；
        # 启动读取目录文件容错陈旧引用与未准入的默认，两者走出不同的入口
        with self._lock:
            document = dict(raw)
            document["revision"] = self._store.revision + 1
            _require_capacity(document.get("models", []), None, set(self._store.models))
            store, bindings = _parse_document(document, self._startup_mode)
            _require_bound_admissions(bindings, store, self._admissions, effective_store=self._store)
            self._store = store
            self._bindings = bindings
            self._publish()
            return self._store.revision

    def remove_model(self, provider_id: str, model_id: str,
                     extra_referrers: Sequence[str] = ()) -> int:
        # 移除一条模型访问定义：仍被部门默认引用时拒绝并列出引用方，Provider 配置与其余定义原样保留；
        # 项目部门设置的引用由应用层汇总后经 extra_referrers 传入，与部门默认一起列出（设计说明第 4.5 节）
        with self._lock:
            key = str(model_id)
            model = self._store.models.get(key)
            if model is None:
                raise CatalogValidationError((ValidationIssue(f"models.{key}", "模型访问定义不存在"),))
            if str(provider_id) != model.provider_id:
                raise CatalogValidationError((ValidationIssue(f"models.{key}", "模型访问定义不属于该 Provider 配置"),))
            referrers = _model_referrers(self._bindings, key) + list(extra_referrers)
            if referrers:
                raise CatalogValidationError(tuple(
                    ValidationIssue(name, "仍被引用，无法移除") for name in referrers
                ))
            self.selections.cancel(key)
            previous_store = self._store
            previous_admission = self._admissions.pop(key, None)
            providers = [self._store.providers[name].public_dict()
                         for name in sorted(self._store.providers)]
            models = [self._store.models[name].public_dict()
                      for name in sorted(self._store.models) if name != key]
            candidate = ProviderStore.from_dict({"providers": providers, "models": models})
            candidate.revision = self._store.revision + 1
            self._store = candidate
            self._publish()
            if previous_admission is not None:
                _persisted, problem = self._persist_admissions()
                if problem is not None:
                    self._store = previous_store
                    self._admissions[key] = previous_admission
                    self._publish()
                    raise CatalogValidationError((ValidationIssue("admissions", problem),))
            return self._revision

    def impacted_definitions(self, document: Mapping[str, Any]) -> list[dict[str, str]]:
        # 按拟议的目录文档算出会作废准入的模型访问定义（设计说明第 4.4 节的受影响字段）：
        # 只比较受影响字段（连接的地址与凭据引用，定义的协议、上游模型 ID 与推理参数方式），
        # 定义本身被移除时不列在这里，由应用层按「将一并删除」处理。
        # Provider 模块只交出定义，引用方与进行中事项由应用层汇总
        with self._lock:
            proposed = _catalog_part(document, self._startup_mode)
            impacted: list[dict[str, str]] = []
            for model_id in sorted(self._store.models):
                record = self._admissions.get(model_id)
                if record is None:
                    continue
                model = proposed.models.get(model_id)
                if model is None:
                    continue
                provider = proposed.providers.get(model.provider_id)
                if provider is None or not admission_is_current(record, model, provider):
                    impacted.append(_definition_identity(model_id, model.provider_id))
            return impacted

    def deletable_definitions(self, provider_id: str) -> list[dict[str, str]]:
        # 删除一份 Provider 配置时会被一并删除的模型访问定义（设计说明第 4.5 节）；
        # 定义本身不算引用方，只有部门默认等引用会拒绝删除
        with self._lock:
            key = str(provider_id)
            if key not in self._store.providers:
                raise CatalogValidationError((ValidationIssue(f"providers.{key}", "Provider 不存在"),))
            return [_definition_identity(model_id, key)
                    for model_id in sorted(self._store.models)
                    if self._store.models[model_id].provider_id == key]

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
                self._publish(refresh_state=False)
                return self._revision
            try:
                raw = json.loads(data.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                self._config_state = "invalid"
                self._reload_error = f"Provider 配置无法解析：{exc}"
                raise CatalogValidationError((ValidationIssue("catalog", "无法读取 Provider 目录"),)) from exc
            try:
                store, bindings = _parse_document(raw, self._startup_mode)
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
            self._load_admissions_file()
            self._publish()
            return self._revision

    def persist_document(self, path: str | Path) -> Path:
        # 校验成功后原子落盘整份非敏感文档，落盘成功才发布跟踪哈希
        with self._lock:
            document = self.to_document()
            store, bindings = _parse_document(document, self._startup_mode)
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
        # 每行容量必须有值；新增行还必须带容量确认，已存在的行提交即带值视为已确认（工单 #86）
        with self._lock:
            if not isinstance(provider_raw, Mapping):
                raise CatalogValidationError((ValidationIssue("providers", "应为对象"),))
            provider_id = provider_raw.get("id")
            document = self.to_document()
            providers = [item for item in document["providers"] if item.get("id") != provider_id]
            entry = dict(provider_raw)
            entry.pop("models", None)
            providers.append(entry)
            if models_raw is None:
                models = document["models"]
            else:
                if not isinstance(models_raw, list):
                    raise CatalogValidationError((ValidationIssue("models", "应为数组"),))
                _require_capacity(models_raw, provider_id, set(self._store.models))
                models = [item for item in document["models"] if item.get("provider_id") != provider_id]
                for item in models_raw:
                    nested = dict(item)
                    nested["provider_id"] = provider_id
                    models.append(nested)
            merged = {"providers": providers, "models": models, "bindings": document["bindings"]}
            _parse_document(merged, self._startup_mode)
            self._store.save_provider(entry)
            if models_raw is not None:
                submitted: set[str] = set()
                for item in models_raw:
                    nested = dict(item)
                    nested["provider_id"] = provider_id
                    self._store.save_model(nested)
                    submitted.add(str(nested.get("id")))
                self._prune_admissions(str(provider_id), submitted)
            self._publish()
            return self._revision

    def connect(self, base_url: str, api_key: str | None = None) -> dict[str, Any]:
        # 先校验完整连接，再写入 Key；凭据文件写入失败时目录、凭据内存与版本都不改变。
        address = _normalized_connection_url(base_url)
        with self._lock:
            previous = self.to_document()
            existing = next((provider for provider in self._store.providers.values()
                             if provider.base_url and _normalized_connection_url(provider.base_url) == address), None)
            if existing is not None:
                provider = {**existing.public_dict(), "base_url": address}
                if not provider["credential_ref"]:
                    provider["credential_ref"] = connection_credential_ref(existing.id)
            else:
                host = urlsplit(address).hostname
                assert host is not None
                # IPv6 的主机名以冒号开头，目录 ID 使用可读且符合既有标识符规则的形式。
                stem = host.strip(":")
                names = {item.name for item in self._store.providers.values()}
                references = {item.credential_ref for item in self._store.providers.values()}
                identifier, number = stem, 2
                while (identifier in self._store.providers or identifier in names or
                       connection_credential_ref(identifier) in references):
                    identifier = f"{stem}-{number}"
                    number += 1
                preset_id = next((preset["id"] for preset in list_presets()
                                  if any(_normalized_connection_url(value) == address
                                         for value in preset["base_urls"].values())), "")
                provider = {"id": identifier, "name": identifier, "base_url": address,
                            "credential_ref": connection_credential_ref(identifier), "preset_id": preset_id}
            provider_id = provider["id"]
            merged = {**previous, "providers": [item for item in previous["providers"]
                                                if item["id"] != provider_id] + [provider]}
            _parse_document(merged, self._startup_mode)
            credential = None
            if api_key is not None:
                credential = self.set_credential(provider["credential_ref"], api_key, persist=True)
            elif existing is None or not self._resolve_api_key(existing):
                raise CatalogValidationError((ValidationIssue("credentials.secret", "请填写 API Key"),))
            self.save_provider_entry(provider)
            return {"provider_id": provider_id, "credential": credential}

    def delete_provider(self, provider_id: str,
                        extra_referrers: Sequence[str] = ()) -> int:
        # 删除 Provider 配置：其下的模型访问定义一并删除（定义本身不算引用方）；
        # 仍被部门默认引用时拒绝并列出引用方，不删改；
        # 项目部门设置的引用由应用层汇总后经 extra_referrers 传入，与部门默认一起列出（设计说明第 4.5 节）
        with self._lock:
            key = str(provider_id)
            if key not in self._store.providers:
                raise CatalogValidationError((ValidationIssue(f"providers.{key}", "Provider 不存在"),))
            dependents = _provider_dependents(self._store, self._bindings, key) + list(extra_referrers)
            if dependents:
                raise CatalogValidationError(tuple(
                    ValidationIssue(name, "仍被引用，无法删除") for name in dependents
                ))
            self.prepare_provider_reselection(key)
            providers = [self._store.providers[name].public_dict()
                         for name in sorted(self._store.providers) if name != key]
            models = [self._store.models[name].public_dict()
                      for name in sorted(self._store.models)
                      if self._store.models[name].provider_id != key]
            candidate = ProviderStore.from_dict({"providers": providers, "models": models})
            candidate.revision = self._store.revision + 1
            reference = self._store.providers[key].credential_ref
            if reference and self._dotenv_path is not None:
                self.remove_persisted_credential(reference)
                self._credentials.clear_override(reference)
            self._store = candidate
            self._candidate_results.pop(key, None)
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
        # 持久化单个凭据到独立 .env：先按 .env 的键名规则核对引用，再用读 .env 的同一个解析器
        # 核对要写的内容，都通过了才原子替换文件；不落盘时文件与内存都不动，
        # 也不悄悄降级为只在内存生效（模型管理设计说明第 4.2 节，工单 #1158）
        key = str(ref).strip()
        if not key:
            raise CatalogValidationError((ValidationIssue("credentials.ref", "凭据引用不能为空"),))
        if not isinstance(secret, str) or not secret.strip():
            raise CatalogValidationError((ValidationIssue("credentials.secret", "凭据内容不能为空"),))
        problem = dotenv_key_problem(key)
        if problem is not None:
            raise CatalogValidationError((ValidationIssue("credentials.ref", problem),))
        target = Path(dotenv_path)
        with self._lock:
            try:
                current = _read_dotenv_strict(target)
            except ValueError as exc:
                raise CatalogValidationError((ValidationIssue(
                    "credentials.ref", f"现有的 .env 读不了：{exc}；请先修正这一行再保存"),))
            try:
                payload = _dotenv_payload_readable({**current, key: secret})
            except ValueError as exc:
                raise CatalogValidationError((ValidationIssue("credentials.ref", str(exc)),))
            _write_dotenv_payload(target, payload)
            data = _parse_dotenv_or_raise(payload)
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
            except FileNotFoundError:
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

    def credential_chain(self) -> CredentialChain:
        # 控制主机的凭据来源本体（进程内存、进程环境、数据目录的 .env）：
        # MCP 服务器的探测与调用按名称从这里取值（网络与 MCP 设计说明第 4.4 节）
        return self._credentials

    def credential_status(self, ref: str) -> dict[str, Any]:
        # 脱敏状态加版本，不含 Key
        with self._lock:
            status: dict[str, Any] = dict(self._credentials.describe(ref))
            status["version"] = self._credential_versions.get(str(ref), 0)
            status["persisted"] = self._credentials.has_persisted(ref)
            return status

    def set_credential(self, ref: str, secret: str, *, persist: bool) -> dict[str, Any]:
        # 保存 Key：只在本进程内覆盖，或写入独立 .env，两种写入方式二选一（设计说明第 9.1 节）。
        # 写入 .env 成功以后不留内存覆盖，来源显示 .env；写入失败时文件、内存与来源都不改，
        # 不悄悄改成只在内存生效（设计说明第 4.2 节、D22 第 5 节，工单 #1158）
        with self._lock:
            key = str(ref)
            persisted = False
            if persist:
                if self._dotenv_path is None:
                    raise CatalogValidationError((ValidationIssue("credentials.ref", "未配置凭据文件路径"),))
                try:
                    self.save_dotenv_value(self._dotenv_path, key, secret)
                except OSError as exc:
                    raise CatalogValidationError((ValidationIssue(
                        "credentials.ref", f"持久凭据写入失败：{exc}"),))
                # 写进 .env 以后清掉这个引用上残留的内存覆盖：覆盖优先级最高，留着就盖住了 .env
                self._credentials.clear_override(key)
                persisted = True
            else:
                self._credentials.set_override(key, secret)
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
        # 真实协议要求模型已准入且按受影响字段判定为有效，fake 不设此门槛（工单 #86）
        with self._lock:
            selections = []
            issues: list[ValidationIssue] = []
            for department in departments:
                binding = self._bindings.get(str(department))
                if binding is None:
                    issues.append(ValidationIssue(
                        f"bindings.{department}",
                        f"{DEFINITIONS.department_labels.get(department, department)}部门还没有选择模型"))
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
                if model is None or provider is None or model.protocol == "fake":
                    continue
                record = self._admissions.get(model.id)
                if record is None or not admission_is_current(record, model, provider):
                    admission_issues.append(ValidationIssue(
                        f"bindings.{key}.model_id",
                        f"模型 {model.id} {_admission_state_text(record)}，请先执行模型测试",
                    ))
            if admission_issues:
                raise CatalogValidationError(admission_issues)
            return snapshot

    def resolve_call_target(self, model_id: str, requested_tier: str | None = None) -> CallTargetResolution:
        # 每次模型请求之前解析调用目标：只接收模型访问定义引用与请求档位，不认识部门。
        # 检查定义存在、所属连接存在、准入有效、窗口已知、凭据可用；凭据材料留在 Provider 模块内，
        # 交回的公开部分不含密钥，执行调用时按句柄取出材料
        with self._lock:
            resolution, target = _resolve_call_target(self._store, self._credentials, model_id, requested_tier,
                                                      self._admissions)
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

    def _merge_department_selection(self, department: str,
                                    project: ModelSelection | Mapping[str, Any] | None,
                                    requested_tier: str | None,
                                    ) -> tuple[SelectionResolution, tuple[CallTargetResolution, FrozenTarget | None]]:
        # 读取该部门的部门默认，与项目部门设置一起合并，再解析调用目标。
        # 模型访问定义与请求档位分别按「项目部门设置、部门默认」的顺序取得第一个写入了的项，
        # 选择来源是提供模型访问定义的那一层（设计说明第 5.3 节）
        default = _as_selection(self._bindings.get(str(department)))
        project_selection = _as_selection(project) if project is not None else None
        merged = merge_selection(project_selection, default)
        if not merged.resolved:
            return merged, (CallTargetResolution(
                False, "provider_unavailable",
                f"部门 {department} 未选择模型访问定义，请配置部门默认或本项目的部门设置",
                call_target_public(None, requested_tier), selection_source=merged.selection_source,
            ), None)
        tier = requested_tier if requested_tier is not None else merged.requested_tier
        resolution, target = _resolve_call_target(
            self._store, self._credentials, merged.model_id, tier, self._admissions)
        return merged, (replace(resolution, selection_source=merged.selection_source), target)

    def resolve_department_default(self, department: str, requested_tier: str | None = None, *,
                                   project: ModelSelection | Mapping[str, Any] | None = None,
                                   ) -> CallTargetResolution:
        # 步骤驱动使用的内部入口：同一把锁内合并该部门的设置并解析调用目标，保留调用句柄。
        # 调用方给出 requested_tier 时按它解析（整理请求使用最低支持档位），否则使用合并得到的请求档位；
        # 解析时按当前模型声明的支持档位限制（#87）
        with self._lock:
            _merged, (resolution, target) = self._merge_department_selection(
                department, project, requested_tier)
            if target is None:
                return resolution
            handle_id = f"target_{uuid4().hex[:16]}"
            self._call_targets[handle_id] = (target, dict(resolution.public))
            return replace(resolution, handle_id=handle_id)

    def resolve_effective_model(self, department: str,
                                project: ModelSelection | Mapping[str, Any] | None = None,
                                ) -> EffectiveModelResolution:
        # 查询用入口：按第 5.3 节的选择规则合并项目部门设置与部门默认，并解析调用目标，
        # 不发送请求、不保留调用句柄（部门工作间的生效模型）。没有任何一层写入模型时为「未设置」，
        # 引用无法使用时为「无法使用」并带回原因；两种情况都不交回其他连接或模型
        with self._lock:
            merged, (resolution, _target) = self._merge_department_selection(department, project, None)
            if not merged.resolved:
                return EffectiveModelResolution("unset", None)
            return EffectiveModelResolution("effective" if resolution.available else "unusable", resolution)

    def validate_department_setting(self, department: str,
                                    project: ModelSelection | Mapping[str, Any] | None,
                                    ) -> None:
        # 保存项目部门设置时的检查（设计说明第 5.2 节）：模型访问定义与请求档位分别继承，每一项都可以单独写入。
        # 写入了请求档位时，它必须属于档位全集，与是否写入模型无关；是否落在生效模型的支持档位由每次请求的限制
        # 决定（第 7.3 节，部门默认与项目部门设置同一套核对）。写入了模型时，所选定义必须已准入且未作废。
        # 目录与准入的校验留在 Provider 模块，应用层只转调
        selection = _as_selection(project)
        if selection is None:
            return
        if selection.writes_tier() and selection.requested_tier not in REASONING_LEVELS:
            raise CatalogValidationError((ValidationIssue(
                f"departments.{department}.requested_tier", "请求档位不属于支持的档位"),))
        if not selection.writes_model():
            return
        with self._lock:
            model = self._store.models.get(selection.model_id or "")
            if model is None:
                raise CatalogValidationError((ValidationIssue(
                    f"departments.{department}.model_id", "模型访问定义不存在"),))
            provider = self._store.providers.get(model.provider_id)
            if provider is None:
                raise CatalogValidationError((ValidationIssue(
                    f"departments.{department}.model_id", "Provider 配置不存在"),))
            if model.protocol != "fake":
                record = self._admissions.get(model.id)
                if record is None:
                    raise CatalogValidationError((ValidationIssue(
                        f"departments.{department}.model_id", "该模型访问定义尚未通过模型测试准入"),))
                if not admission_is_current(record, model, provider):
                    raise CatalogValidationError((ValidationIssue(
                        f"departments.{department}.model_id", "该模型访问定义的准入已作废，请重新执行模型测试"),))

    def project_department_reminders(
            self, departments: Mapping[str, Mapping[str, Any] | None]) -> dict[str, list[str]]:
        # 项目各部门生效模型不具备该部门建议能力时的提醒（设计说明第 5.6 节「一直显示」）。
        # 生效模型按第 5.3 节的顺序解析：项目部门设置写入了模型时用它，否则用部门默认
        notes: dict[str, list[str]] = {}
        for department, project_setting in departments.items():
            model_id = (project_setting or {}).get("model_id")
            if not model_id:
                with self._lock:
                    model_id = (self._bindings.get(str(department)) or {}).get("model_id")
            notes[department] = self.model_reminders(str(model_id) if model_id else None, department)
        return notes

    def model_reminders(self, model_id: str | None, department: str) -> list[str]:
        # 一个模型访问定义在指定部门下的建议能力提醒（设计说明第 5.6 节）。
        # 模型管理页与项目部门设置按各自的生效模型引用调用；没有绑定模型或模型不存在时没有提醒
        if not model_id:
            return []
        with self._lock:
            model = self._store.models.get(model_id)
            return [] if model is None else _suggested_reminders(department, model)

    def model_reminders_by_department(self, model_ids: Sequence[str]) -> dict[str, dict[str, list[str]]]:
        # 目录中各条模型访问定义在各部门的建议能力提醒（模型 ID → 部门 → 提醒）。
        # 一次读锁算完：部门默认的下拉选中一条定义时界面立即显示提醒（设计说明第 5.6 节）
        with self._lock:
            notes: dict[str, dict[str, list[str]]] = {}
            for model_id in model_ids:
                model = self._store.models.get(str(model_id))
                if model is None:
                    continue
                per_department = {department: _suggested_reminders(department, model)
                                  for department in REQUIRED_DEPARTMENTS}
                notes[str(model_id)] = {key: value for key, value in per_department.items() if value}
        return notes

    def department_setting_reminders(self, department: str,
                                     project: ModelSelection | Mapping[str, Any] | None,
                                     ) -> list[str]:
        # 项目部门设置写入的模型不具备该部门建议能力时的提醒（设计说明第 5.6 节「保存时」）。
        # 没有写入模型的设置不检查；提醒只按模型访问定义中的输入方式判断
        selection = _as_selection(project)
        if selection is None or not selection.writes_model():
            return []
        with self._lock:
            model = self._store.models.get(selection.model_id or "")
            if model is None:
                return []
            return _suggested_reminders(department, model)

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
        # 显式刷新候选：按服务方案认证，最近结果供查询读取，不落盘、不自动绑定。
        with self._lock:
            provider = self._store.providers.get(str(provider_id))
            if provider is None:
                raise CatalogValidationError((ValidationIssue(
                    f"providers.{provider_id}", "Provider 配置不存在"),))
            api_key = self._resolve_api_key(provider)
            source = self._provider_source(provider)
        result = _refresh_candidates(provider, models_url_override=models_url_override, api_key=api_key,
                                     timeout_sec=min(provider.timeout_sec, 30.0))
        with self._lock:
            if (self._store.providers.get(provider.id) == provider
                    and self._provider_source(provider) == source):
                self._candidate_results[provider.id] = copy.deepcopy(result)
        return result

    def latest_candidates(self, provider_id: str) -> dict[str, Any] | None:
        with self._lock:
            return copy.deepcopy(self._candidate_results.get(str(provider_id)))

    def select_model(self, provider_id: str, upstream_model: str, *, protocol: str | None = None,
                     context_window: int | None = None, max_output_tokens: int | None = None,
                     force: bool = False, definition_id: str | None = None) -> tuple[SelectionAttempt | None, bool]:
        # 候选与手动添加共用候选补全；重复选用复用当前测试或有效准入。
        with self._lock:
            provider = self._store.providers.get(provider_id)
            if provider is None:
                raise CatalogValidationError((ValidationIssue(f"providers.{provider_id}", "Provider 配置不存在"),))
            matches = [item for item in self._store.models.values()
                       if item.provider_id == provider_id and item.model == upstream_model
                       and (definition_id is None or item.id == definition_id)]
            if not force:
                for item in matches:
                    current = self.selections.current(item.id)
                    if current is not None and current.status in {"completing", "waiting", "testing"}:
                        return current, False
                    record = self._admissions.get(item.id)
                    if record is not None and admission_is_current(record, item, provider):
                        return None, False
            existing = next(iter(matches), None)
            latest = self._candidate_results.get(provider_id) or {}
            candidate = next((item for item in latest.get("candidates", ()) if item["id"] == upstream_model), None)
            from_list = candidate is not None
            if candidate is None:
                candidate = _parse_candidates([{"id": upstream_model}], provider.preset_id)[0]
            if not candidate.get("applicable", True):
                raise CatalogValidationError((ValidationIssue("model", "不适用于部门任务：模型不输出文本"),))
            values = dict(candidate)
            details = copy.deepcopy(values.get("source_details", {}))
            if existing is not None:
                for name in ("context_window", "max_output_tokens", "protocol"):
                    if ((not from_list and (name == "protocol" or values.get(name) is None))
                            or (existing.source_details.get(name, {}).get("source") == "manual"
                                and (name == "protocol" or values.get(name) is None))):
                        values[name] = getattr(existing, name)
                        details[name] = dict(existing.source_details.get(name, {"source": "manual"}))
            for name, value in (("context_window", context_window), ("max_output_tokens", max_output_tokens),
                                ("protocol", protocol)):
                if value is not None and (name == "protocol" or values.get(name) is None
                                          or details.get(name, {}).get("source") == "manual"):
                    values[name] = value
                    details[name] = {"source": "manual"}
            identifier = (existing.id if existing is not None else
                          "selected-" + hashlib.sha256(f"{provider_id}\0{upstream_model}".encode()).hexdigest()[:24])
            if values["protocol"] == "fake" and self._startup_mode == "normal":
                raise CatalogValidationError((ValidationIssue("protocol", "正常启动不能选用 fake 协议"),))
            previous = self.to_document()
            self.save_model({"id": identifier, "provider_id": provider_id, "model": upstream_model,
                             "protocol": values["protocol"], "context_window": values.get("context_window"),
                             "max_output_tokens": values.get("max_output_tokens"),
                             "input_modalities": values["input_modalities"], "source_details": details,
                             "reasoning_levels": [] if existing is None else list(existing.reasoning_levels),
                             "default_reasoning_level": None if existing is None else existing.default_reasoning_level,
                             "reasoning_mode": "" if existing is None else existing.reasoning_mode,
                             "accepts_required_tool_call": True if existing is None else existing.accepts_required_tool_call,
                             "capability_source": " · ".join(f"{name}：{detail['source']}"
                                                             for name, detail in details.items())})
            problem = self.persist_catalog(previous)
            if problem is not None:
                raise CatalogValidationError((ValidationIssue("catalog", problem),))
            selected = self.selections.begin(provider_id, identifier, upstream_model)
            selected.missing = [name for name in ("context_window", "max_output_tokens") if values.get(name) is None]
            selected.status = "capacity_unknown" if selected.missing else "waiting"
            return selected, not selected.missing

    def prepare_provider_reselection(self, provider_id: str) -> None:
        with self._lock:
            self._candidate_results.pop(provider_id, None)
            for model in self._store.models.values():
                if model.provider_id == provider_id:
                    self.selections.cancel(model.id)

    def _provider_source(self, provider: Any) -> tuple[tuple[str, str], bytes | None]:
        material = self._credentials.resolve(provider.credential_ref)
        fingerprint = None if material is None else hashlib.sha256(material.secret.encode()).digest()
        return (provider.base_url, provider.credential_ref), fingerprint

    def set_change_listener(self, listener: Callable[[tuple[ProviderChange, ...]], None] | None) -> None:
        with self._lock:
            self._change_listener = listener
            self._source_snapshot = {key: self._provider_source(provider)
                                     for key, provider in self._store.providers.items()}

    def connection_version(self, provider_id: str) -> int:
        with self._lock:
            return self._source_versions.get(provider_id, 0)

    def change_is_current(self, provider_id: str, version: int) -> bool:
        with self._lock:
            provider = self._store.providers.get(provider_id)
            return (provider is not None and self._source_versions.get(provider_id, 0) == version
                    and self._source_snapshot.get(provider_id) == self._provider_source(provider))

    def notify_changes(self) -> tuple[ProviderChange, ...]:
        # 命令保存、显式重载、目录/.env监视共享这一份差异与版本；同一内容再次读到不会重复调度。
        with self._lock:
            current = {key: self._provider_source(provider) for key, provider in self._store.providers.items()}
            changes: list[ProviderChange] = []
            for key in self._source_snapshot.keys() | current.keys():
                before, after = self._source_snapshot.get(key), current.get(key)
                if before == after:
                    continue
                self._source_versions[key] = self._source_versions.get(key, 0) + 1
                if after is None:
                    self._candidate_results.pop(key, None)
                    for selected in self.selections.snapshot():
                        if selected["provider_id"] == key:
                            self.selections.cancel(selected["model_id"])
                elif before is not None:
                    retest = before[0] != after[0]
                    if retest:
                        self.prepare_provider_reselection(key)
                    changes.append(ProviderChange(key, self._source_versions[key], retest, before[1] != after[1]))
            self._source_snapshot = current
            listener = self._change_listener
        result = tuple(changes)
        if listener is not None and result:
            listener(result)
        return result

    def reselect_provider(self, provider_id: str) -> list[SelectionAttempt]:
        # 地址修改后只使用这次获取的候选；缺少的定义保留引用，明确说明无法重新测试的原因。
        with self._lock:
            latest = self._candidate_results.get(provider_id) or {}
            candidate_ids = {item["id"] for item in latest.get("candidates", ())}
            ready: list[SelectionAttempt] = []
            for model in tuple(self._store.models.values()):
                if model.provider_id != provider_id:
                    continue
                if latest.get("status") == "ok" and model.model in candidate_ids:
                    try:
                        selected, start = self.select_model(provider_id, model.model, force=True, definition_id=model.id)
                    except CatalogValidationError as exc:
                        selected = self.selections.begin(provider_id, model.id, model.model)
                        selected.status, selected.error = "failed", str(exc)
                        continue
                    if start:
                        ready.append(selected)
                else:
                    selected = self.selections.begin(provider_id, model.id, model.model)
                    selected.status = "not_in_list" if latest.get("status") == "ok" else "failed"
                    selected.error = ("不在新的模型列表中" if selected.status == "not_in_list"
                                      else latest.get("error") or "未能获取新的模型列表")
            return ready

    def run_selection(self, selected: SelectionAttempt, limit: Callable[[], int],
                      default_keys: Sequence[str]) -> dict[str, Any] | None:
        if not self.selections.acquire(selected, limit):
            return None
        try:
            result = self.model_test(selected.provider_id, selected.model_id, selection=selected,
                                     default_keys=default_keys)
            return result if result.get("admitted") or self.selections.finish(selected, result) else None
        finally:
            self.selections.release(selected)

    def retry_selection(self, provider_id: str, model_id: str) -> tuple[SelectionAttempt, bool]:
        with self._lock:
            model = self._store.models.get(model_id)
            if model is None or model.provider_id != provider_id:
                raise CatalogValidationError((ValidationIssue(f"models.{model_id}", "模型访问定义不存在"),))
            current = self.selections.current(model_id)
            if current is not None and current.status in {"completing", "waiting", "testing"}:
                return current, False
            selected = self.selections.begin(provider_id, model_id, model.model)
            selected.missing = [name for name in ("context_window", "max_output_tokens")
                                if getattr(model, name) is None]
            selected.status = "capacity_unknown" if selected.missing else "waiting"
            return selected, not selected.missing

    def _fill_missing_defaults(self, model_id: str, keys: Sequence[str]) -> tuple[int, int]:
        # 由准入提交所在的同一把锁串行决定先通过者，已有选择逐项保留。
        before = self.catalog_revision()
        model = self._store.models[model_id]
        additions = {name: {"provider_id": model.provider_id, "model_id": model.id}
                     for name in keys if name not in self._bindings}
        if additions:
            previous = self.to_document()
            _require_bound_admissions(additions, self._store, self._admissions)
            self._bindings.update(additions)
            self._store.bump_revision()
            self._publish()
            problem = self.persist_catalog(previous)
            if problem is not None:
                raise CatalogValidationError((ValidationIssue("bindings", problem),))
        return before, self.catalog_revision()

    def models_url_of(self, provider_id: str, models_url_override: str | None = None) -> str:
        # 这次请求实际读取的模型列表地址：覆盖值、已保存值、预置表地址，最后是自定义默认值
        with self._lock:
            provider = self._store.providers.get(str(provider_id))
            if provider is None:
                return ""
            return effective_models_url(provider, models_url_override)

    def _resolve_api_key(self, provider: Any) -> str:
        # 模型列表地址要求认证时按协议取凭据；fake 不需要凭据。
        # 凭据引用无法解析时交回空串，由获取模型列表与连接测试报告「候选未知」并说明原因
        if not provider.credential_ref:
            return ""
        material = self._credentials.resolve(provider.credential_ref)
        if material is None:
            return ""
        return material.secret

    def record_admission(self, provider_id: str, model_id: str,
                         *, admitted_model: str | None) -> dict[str, Any]:
        # 记录一次已通过的模型测试：写独立的准入记录，不改动目录文件，也不推进目录修订号（工单 #86）
        # 内容含测试时间、实际返回模型与协议，外加测试时受影响字段快照（地址、凭据引用、协议、上游模型 ID）
        with self._lock:
            provider = self._store.providers.get(str(provider_id))
            model = self._store.models.get(str(model_id))
            if provider is None or model is None or model.provider_id != provider.id:
                raise CatalogValidationError((ValidationIssue(
                    f"models.{model_id}", "模型访问定义不存在"),))
            record = AdmissionRecord(
                model_id=model.id,
                provider_id=provider.id,
                admitted_at=_utc_now(),
                admitted_model="" if admitted_model is None else str(admitted_model),
                protocol=model.protocol,
                base_url=provider.base_url,
                credential_ref=provider.credential_ref,
                model=model.model,
                reasoning_mode=model.reasoning_mode,
            )
            self._admissions[model.id] = record
            self._publish()
            return {
                "model_id": record.model_id,
                "revision": self._revision,
                "admitted_at": record.admitted_at,
                "admitted_model": record.admitted_model,
                "admitted_protocol": record.protocol,
            }

    def model_test(self, provider_id: str, model_id: str, *,
                   selection: SelectionAttempt | None = None,
                   default_keys: Sequence[str] = ()) -> dict[str, Any]:
        # 最小问答与工具往返都成功才准入；每次请求走正式协议路径并有独立等待上限。
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
        frozen = snapshot.target(model.id)
        target = replace(frozen, timeout_sec=min(
            frozen.timeout_sec, float(DEFINITIONS.rule_value("provider.model_test_timeout_sec"))))
        provider_input = to_provider_input(
            [{"role": "user", "content": "ping"}],
            max_output_tokens=model.max_output_tokens,
        )
        started = time.monotonic()
        group, step = "minimal_qa", "request"
        accepts_required = True
        result: InvokeResult | None = None
        try:
            result = self._invoke_for_test(target, provider_input, model, selection)
            if model.protocol != "fake":
                group, step = "tool_round_trip", "tool_call"
                tool = {"type": "function", "name": "yudao_model_test",
                        "description": "无副作用的模型接入测试工具，返回 pong。请调用一次。",
                        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}
                prompt = {"role": "user", "content": "请调用 yudao_model_test，不需要参数。收到工具结果后回复。"}
                tool_input = replace(to_provider_input([prompt], [tool],
                                                       max_output_tokens=model.max_output_tokens),
                                     tool_choice="required")
                try:
                    result = self._invoke_for_test(target, tool_input, model, selection)
                except ProviderError as exc:
                    if not _required_tool_parameter_rejected(exc):
                        raise
                    accepts_required = False
                    step = "tool_call_retry"
                    result = self._invoke_for_test(target, replace(tool_input, tool_choice="auto"), model, selection)
                outputs = _model_test_tool_outputs(result)
                step = "tool_result"
                reasoning = [] if result.reasoning is None else result.reasoning.items
                follow_up = replace(tool_input, tool_choice="auto", raw_request={
                    "input": [prompt, *reasoning, *result.output, *outputs], "tools": [tool]})
                result = self._invoke_for_test(target, follow_up, model, selection)
        except ProviderError as exc:
            elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
            group_text = "最小问答" if group == "minimal_qa" else "工具往返"
            step_text = {"request": "请求", "tool_call": "调用测试工具", "tool_call_retry": "不要求调用工具重试",
                         "tool_result": "回传工具结果"}[step]
            reason = (f"请求超时（等待上限 {target.timeout_sec:g} 秒）" if exc.reason == "provider_timeout"
                      else _model_test_failure_reason(exc))
            return {
                "ok": False, "error": f"{group_text} / {step_text}：{reason}",
                "model": None if result is None else (result.actual_model or None), "admitted": False,
                "protocol": model.protocol, "revision": self.revision,
                "elapsed_ms": elapsed_ms, "usage_reported": False,
                "accepts_required_tool_call": accepts_required,
                "failure_group": group, "failure_step": step, "request_timeout_sec": target.timeout_sec,
            }
        elapsed_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        actual = result.actual_model or None
        capacity_confirmed = model.context_window is not None and model.max_output_tokens is not None
        defaults_before = defaults_after = self.catalog_revision()
        with self._lock:
            if capacity_confirmed:
                with self._lock:
                    current = self._store.models.get(model.id)
                    current_provider = self._store.providers.get(provider.id)
                    if (current is None or current_provider is None
                            or (selection is not None and not self.selections.is_current(selection))
                            or (provider.base_url, provider.credential_ref, model.protocol, model.model, model.reasoning_mode)
                            != (current_provider.base_url, current_provider.credential_ref,
                                current.protocol, current.model, current.reasoning_mode)):
                        return {"ok": False, "admitted": False, "error": "选用已取消或测试目标已经改变"}
                    if current.accepts_required_tool_call != accepts_required:
                        previous = self.to_document()
                        self.save_model(replace(current, accepts_required_tool_call=accepts_required).public_dict())
                        persist_error = self.persist_catalog(previous)
                        if persist_error is not None:
                            return {"ok": False, "error": f"工具往返 / 保存测试能力：{persist_error}",
                                    "model": actual, "admitted": False, "protocol": model.protocol,
                                    "revision": self.revision, "elapsed_ms": elapsed_ms, "usage_reported": False,
                                    "accepts_required_tool_call": accepts_required, "failure_group": "tool_round_trip",
                                    "failure_step": "save_capability", "request_timeout_sec": target.timeout_sec}
                    previous_admission = self._admissions.get(model.id)
                    self.record_admission(provider_id, model.id, admitted_model=actual)
                    if selection is not None:
                        try:
                            defaults_before, defaults_after = self._fill_missing_defaults(model.id, default_keys)
                        except CatalogValidationError:
                            if previous_admission is None:
                                self._admissions.pop(model.id, None)
                            else:
                                self._admissions[model.id] = previous_admission
                            raise
            persisted, persist_error = self._persist_admissions()
            payload = {
                "ok": True,
                "error": None,
                "model": actual,
                "admitted": bool(capacity_confirmed),
                "protocol": model.protocol,
                "revision": self.revision,
                "elapsed_ms": elapsed_ms,
                "usage_reported": bool(result.usage.get("reported", False)),
                "persisted": persisted,
                "accepts_required_tool_call": accepts_required,
                "failure_group": None,
                "failure_step": None,
                "request_timeout_sec": target.timeout_sec,
                "defaults_before": defaults_before, "defaults_after": defaults_after,
            }
            if persist_error is not None:
                payload["persist_error"] = persist_error
            if selection is not None and payload["admitted"]:
                self.selections.finish(selection, payload)
            return payload

    def _persist_admissions(self) -> tuple[bool, str | None]:
        # 准入记录落在与目录分开的文件里：CLI 与 smoke 在独立进程读取同一份配置；
        # 写入失败时保留内存记录并如实报告，不谎称已持久化
        if self._admission_path is None:
            return False, None
        try:
            self.persist_admissions()
        except OSError as exc:
            return False, f"准入记录未能写入 {self._admission_path}：{exc}"
        return True, None

    def persist_admissions(self) -> Path:
        # 原子落盘准入记录：只写文件自身的结构，坏内容下次读取时报错
        with self._lock:
            if self._admission_path is None:
                raise CatalogValidationError((ValidationIssue("admissions", "未配置准入记录路径"),))
            payload = json.dumps(
                {"admissions": [self._admissions[key].public_dict()
                                for key in sorted(self._admissions)]},
                ensure_ascii=False, indent=2, sort_keys=True,
            ) + "\n"
            target = self._admission_path
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
            self._admission_seen = True
            return target

    def _load_admissions_file(self, *, keep_when_missing: bool = False) -> None:
        # 读取独立准入文件：缺文件即空记录，坏内容报错并保留内存记录。
        # 进程启动（load_document）缺文件就是空态；进行中的重新读取（_poll_config_file）缺文件时
        # 保留内存记录：本进程写入的准入尚未落盘或文件被外部删除都不作废已通过的测试（工单 #266）
        if self._admission_path is None:
            return
        try:
            data = self._admission_path.read_bytes()
        except OSError:
            if not keep_when_missing:
                self._admissions = {}
            self._admission_seen = True
            return
        raw = json.loads(data.decode("utf-8"))
        self._admissions = _parse_admission_document(raw)
        self._admission_seen = True

    def _prune_admissions(self, provider_id: str, submitted_ids: Container[str]) -> None:
        # 保存连接时丢弃不再存在的定义的准入记录；仍在的定义保留记录，
        # 是否作废由受影响字段逐项判断，不在这里预先删除（工单 #86）
        kept: dict[str, AdmissionRecord] = {}
        for model_id, record in self._admissions.items():
            if record.provider_id == provider_id and model_id not in submitted_ids:
                model = self._store.models.get(model_id)
                if model is None:
                    continue
            kept[model_id] = record
        self._admissions = kept

    def _invoke_for_test(self, target: FrozenTarget, provider_input: ProviderInput,
                         model: Any, selection: SelectionAttempt | None = None) -> InvokeResult:
        # 诊断调用由接口层同步发起，在自己的事件循环中走与正式调用相同的协议与身份路径，
        # 使用独立会话，每次新建客户端；Web 服务多线程，同一个模型可能同时测试，每次调用使用唯一的尝试身份
        session_id = f"diagnostic:{target.provider_id}:{model.id}"
        attempt_id = f"diagnostic:{model.id}:{uuid4().hex}"
        if selection is not None:
            with self._lock:
                selection.attempts.add(attempt_id)

        async def run() -> InvokeResult:
            async with aclosing(stream_invocation(target, provider_input, session_id, attempt_id,
                                                  self._cancels, cancelled=() if selection is None else selection)) as items:
                async for item in items:
                    if isinstance(item, InvokeResult):
                        return item
            raise ProviderError("Model invocation ended without a result", reason="provider_protocol")

        try:
            return asyncio.run(run())
        finally:
            if selection is not None:
                with self._lock:
                    selection.attempts.discard(attempt_id)

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
                    reason = ("provider_config_missing"
                              if self._config_state in {"empty", "missing", "deleted"} else "provider_invalid")
                    message = "尚未配置 Provider：请在模型管理页完成服务接入后再创建事项" if reason == "provider_config_missing" else "; ".join(
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
                    "model_admissions": self.model_admissions(),
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
                "model_admissions": self.model_admissions(),
            }

    def model_admissions(self) -> list[dict[str, Any]]:
        # 有准入记录的定义逐条交回准入事实与作废标记（工单 #86）：有效性按受影响字段逐项比较，
        # 记录存在且字段全等才算已准入；字段不等保留为历史并标为已作废，引用不因此删除。
        # 没有记录的定义没有这一行：未测试与未记录是同一事实；定义已删除的记录不再可见
        with self._lock:
            rows: list[dict[str, Any]] = []
            for model_id in sorted(self._store.models):
                record = self._admissions.get(model_id)
                if record is None:
                    continue
                model = self._store.models[model_id]
                provider = self._store.providers.get(model.provider_id)
                current = bool(provider is not None and admission_is_current(record, model, provider))
                rows.append({
                    "model_id": model_id,
                    "provider_id": model.provider_id,
                    "protocol": model.protocol,
                    "admitted": current,
                    "stale": not current,
                    "admitted_at": record.admitted_at,
                    "admitted_model": record.admitted_model,
                    "base_url": record.base_url,
                    "credential_ref": record.credential_ref,
                    "model": record.model,
                })
            return rows

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
                "admissions": self.model_admissions(),
                "selections": self.selections.snapshot(),
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

    def test_connection(self, provider_id: str) -> dict[str, Any]:
        # 连接测试只依赖已保存的连接与凭据，读取模型列表地址，不改变准入。
        with self._lock:
            provider = self._store.providers[provider_id]
            revision = self._revision
            material = self._credentials.resolve(provider.credential_ref)
            is_fake = any(m.protocol == "fake" for m in self._store.models.values() if m.provider_id == provider.id)
        result = {"kind": "connection", "revision": revision,
                  "source_url": effective_models_url(provider)}
        if is_fake:
            return {**result, "ok": True, "reason": "", "message": ""}
        if material is None:
            return {**result, "ok": False, "reason": "provider_unavailable",
                    "message": "Missing configuration: provider credential"}
        probed = _probe_connection(provider, api_key=material.secret, timeout_sec=provider.timeout_sec)
        return {**result, **probed}

    def configure_paths(self, config_path: str | Path | None,
                        dotenv_path: str | Path | None = None) -> None:
        # 记录本地源固定路径，不读取，读取由 load/reload/轮询完成
        # 准入记录与目录分开保存：与目录文件同目录的 admissions.json（工单 #86）
        with self._lock:
            self._config_path = None if config_path is None else Path(config_path)
            self._dotenv_path = None if dotenv_path is None else Path(dotenv_path)
            self._admission_path = None if self._config_path is None \
                else self._config_path.with_name("admissions.json")

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
        self.notify_changes()

    def _poll_config_file(self) -> bool:
        # 返回磁盘内容是否导致内存发布变化；失败保留上一有效版本
        assert self._config_path is not None
        try:
            data = self._config_path.read_bytes()
        except OSError:
            if self._disk_config_seen and self._disk_config_hash is None:
                return False
            if not self._disk_config_seen:
                # 从来没有读到过文件：这是「没有文件」，不是文件被删除。
                # 与 load_document 的缺文件处理一致（记为 missing），不按删除处理：
                # 不推进修订号、不清空准入记录、不发布（设计说明第 4.7 节，工单 #844）
                self._config_state = "missing"
                self._reload_error = None
                self._disk_config_hash = None
                self._disk_config_seen = True
                return False
            # 明确删除目录文件表示撤销默认配置：目录、部门默认与角色默认一起清空，部门默认变为「未设置」；
            # 新任务停止创建，进行中事项的下一次模型请求进入待恢复；修订号继续前进（设计说明第 4.7 节）
            previous_revision = self._store.revision
            self._store = ProviderStore.empty()
            self._store.revision = previous_revision + 1
            self._bindings = {}
            # 目录文件被删除时准入记录一并清空：定义已不存在，记录无从生效（工单 #266）
            self._admissions = {}
            self._admission_seen = True
            self._config_state = "deleted"
            self._reload_error = None
            self._disk_config_hash = None
            self._disk_config_seen = True
            self._publish(refresh_state=False)
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
            store, bindings = _parse_document(raw, self._startup_mode)
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
        # 外部修改目录并成功发布以后一并读取准入文件，读取口径与 load_document 相同：
        # 记录是否仍然有效按受影响字段逐项判断，作废的记录不恢复为已准入（工单 #266）
        self._load_admissions_file(keep_when_missing=True)
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
            # 落盘成功以后状态不再是删除或缺失：按内存里的内容重算（工单 #301）
            self._config_state = ("loaded" if (self._store.providers or self._store.models or self._bindings)
                                  else "empty")

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
                                stage=event["stage"], response_id=event["response_id"],
                                deltas=tuple(event.get("deltas") or ()), **identity)
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
    if kind == "reasoning":
        return ModelStreamEvent(kind="reasoning", **identity)
    return None


def _model_response(result: InvokeResult) -> ModelResponse:
    # 只记录服务实际返回的模型，未返回保持未知，不拿请求模型冒充
    reasoning = None
    if result.reasoning is not None and result.reasoning.items:
        reasoning = {"items": result.reasoning.items}
    return ModelResponse(
        output=result.output,
        usage=_call_usage(result.usage),
        provider=result.provider,
        model=result.actual_model or "",
        response_id=result.response_id,
        sdk_response=dict(result.wire_evidence),
        reasoning=reasoning,
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


def _parse_document(raw: Any, startup_mode: str = "normal") -> tuple[ProviderStore, dict[str, dict[str, str]]]:
    # 整份非敏感文档：providers/models 走目录校验，bindings 校验引用结构（读取时容忍陈旧引用）
    # 文档键只认这四个：带 admitted_* 的定义或顶层 admissions 会作为未知字段整份拒绝（工单 #86）
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
    _reject_fake_if_normal(store, startup_mode)
    bindings = _parse_bindings(raw.get("bindings", {}), store)
    return store, bindings


def _catalog_part(raw: Any, startup_mode: str) -> ProviderStore:
    # 只解析文档的目录部分（providers/models）并做 fake 拒绝：影响列表与导入的引用检查
    # 以当前引用为准比较拟议定义，拟议文档自己的 bindings 不在这里校验
    if not isinstance(raw, Mapping):
        raise CatalogValidationError((ValidationIssue("catalog", "应为 JSON 对象"),))
    store = ProviderStore.from_dict({"providers": raw.get("providers", []),
                                     "models": raw.get("models", [])})
    _reject_fake_if_normal(store, startup_mode)
    return store


def _reject_fake_if_normal(store: ProviderStore, startup_mode: str) -> None:
    # fake 协议只在测试/演示方式启动的系统可用；正常启动读取目录时拒绝，错误指出字段位置（工单 #86）
    if startup_mode != "normal":
        return
    issues = [
        ValidationIssue(f"models.{model_id}.protocol",
                        "正常启动的系统不允许 fake 协议的模型访问定义，fake 只在测试或演示方式下可用")
        for model_id in sorted(store.models)
        if store.models[model_id].protocol == "fake"
    ]
    if issues:
        raise CatalogValidationError(issues)


def _as_selection(raw: Any) -> ModelSelection | None:
    # 部门默认（绑定）与项目部门设置都表示成一层的模型选择：模型两项、请求档位与部门 Prompt。
    # 未知形状按没有写入处理，由合并规则决定使用哪一层
    if raw is None:
        return None
    if isinstance(raw, ModelSelection):
        return raw
    if isinstance(raw, Mapping):
        return ModelSelection(
            provider_id=_optional_text(raw.get("provider_id")),
            model_id=_optional_text(raw.get("model_id")),
            requested_tier=_optional_text(raw.get("requested_tier")),
            department_prompt=_optional_text(raw.get("department_prompt")),
        )
    return None

def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None

# 部门默认在目录文档中的字段：模型两项与请求档位（设计说明第 5.1 节）
_BINDING_FIELDS = frozenset({"provider_id", "model_id", "requested_tier"})

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
        # 部门默认只写入三项（设计说明第 4.6、5.1 节）：模型两项与请求档位；
        # 未知字段整份拒绝并指出字段位置，界面表单与编辑 JSON 走同一套校验
        unknown = sorted(set(item) - _BINDING_FIELDS, key=str)
        if unknown:
            issues.extend(ValidationIssue(f"{location}.{key}", "未知字段") for key in unknown)
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
        # 请求档位（#87）：可以为空，写入时只核对它属于档位全集；
        # 是否落在所选模型的支持档位由每次请求的限制决定（设计说明第 7.3 节）
        requested_tier = item.get("requested_tier")
        if requested_tier is not None and not isinstance(requested_tier, str):
            issues.append(ValidationIssue(f"{location}.requested_tier", "请求档位必须为字符串"))
            continue
        tier = (requested_tier or "").strip()
        if tier and tier not in REASONING_LEVELS:
            issues.append(ValidationIssue(
                f"{location}.requested_tier", "请求档位不属于支持的档位"))
            continue
        binding = {"provider_id": provider.id, "model_id": model.id}
        if tier:
            binding["requested_tier"] = tier
        bindings[str(department)] = binding
    if issues:
        raise CatalogValidationError(issues)
    return bindings


def _require_bound_admissions(bindings: Mapping[str, Mapping[str, str]],
                              store: ProviderStore,
                              admissions: Mapping[str, AdmissionRecord],
                              *,
                              effective_store: ProviderStore | None = None) -> None:
    # 保存部门默认要求所选定义已准入且未作废；fake 定义无真实上游可测，豁免该要求（工单 #86）。
    # 定义与协议从 store（被保存的目录）取，准入有效性按 effective_store 核对（不填即 store）：
    # 文档自带连接字段重新配置时（如改地址），按保存前的配置核对，引用不作废、由重测重新准入（工单 #1310）；
    # 定义不在有效配置里（文档新增的定义）必然没有准入记录，按未准入拒绝
    issues: list[ValidationIssue] = []
    anchor = store if effective_store is None else effective_store
    for department in sorted(bindings):
        model_id = bindings[department].get("model_id", "")
        model = store.models.get(model_id)
        if model is None:
            continue
        if model.protocol == "fake":
            continue
        record = admissions.get(model_id)
        location = f"bindings.{department}.model_id"
        if record is None:
            issues.append(ValidationIssue(location, "该模型访问定义尚未通过模型测试准入"))
            continue
        provider = anchor.providers.get(model.provider_id)
        current = anchor.models.get(model_id)
        if (provider is None or current is None
                or not admission_is_current(record, current, provider)):
            issues.append(ValidationIssue(location, "该模型访问定义的准入已作废，请重新执行模型测试"))
    if issues:
        raise CatalogValidationError(issues)


def _require_capacity(rows: Sequence[Mapping[str, Any]], provider_id: Any,
                      known_ids: Container[str]) -> None:
    # 表单每一行都必须填写窗口与输出上限；从候选建立或保存直接采用预填容量（工单 #562）
    # 缺少容量时写明缺少的字段，窗口与输出上限的大小关系由目录校验判定
    issues: list[ValidationIssue] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        model_id = row.get("id")
        location = f"models[{index}]"
        if isinstance(model_id, str) and model_id.strip():
            location = f"models.{model_id}"
        if row.get("context_window") is None:
            issues.append(ValidationIssue(f"{location}.context_window", "缺少 context_window"))
        if row.get("max_output_tokens") is None:
            issues.append(ValidationIssue(f"{location}.max_output_tokens", "缺少 max_output_tokens"))
    if issues:
        raise CatalogValidationError(issues)


def _admission_state_text(record: AdmissionRecord | None) -> str:
    # 未写记录与已作废分开表述，各处解析入口共用同一措辞
    return "尚未通过模型测试准入" if record is None else "准入已作废"


def _model_test_failure_reason(error: ProviderError) -> str:
    # 模型测试失败时写上游给出的原因（设计说明第 9.1 节，工单 #294）：上游有错误原文时写原文，
    # 没有时照旧写状态码那句（401 与 403 不记回应体，见第 13.4 节）
    status = (error.diagnostics or {}).get("status_code")
    if status in {401, 403}:
        return f"HTTP {status}：" + ("凭据无效" if status == 401 else "没有访问权限")
    message = (error.diagnostics or {}).get("error_message")
    return message if isinstance(message, str) and message.strip() else str(error)


def _required_tool_parameter_rejected(error: ProviderError) -> bool:
    # 只允许明确的 tool_choice 参数错误触发一次能力探测；不重试工具 schema、认证或服务故障。
    details = error.diagnostics or {}
    if details.get("status_code") not in {400, 422}:
        return False
    param = details.get("param")
    if isinstance(param, str):
        return param == "tool_choice" or param.startswith("tool_choice.")
    message = " ".join(str(details.get("error_message") or "").casefold().split())
    message = message.replace("'", "").replace('"', "").replace("`", "")
    before, separator, after = message.partition("tool_choice")
    if not separator:
        return False
    # 错误必须直接说明这个参数不被接受；其他字段的 invalid/unknown 不能作为工具能力证据。
    after = after.lstrip(" :=,.-")
    if after.startswith("parameter "):
        after = after[len("parameter "):]
    return after.startswith((
        "is not supported", "not supported", "is unsupported", "unsupported", "is invalid", "invalid",
        "is not allowed", "not allowed", "is incompatible", "must be", "required is not supported",
        "required is invalid", "不支持", "无效", "不能")) or before.rstrip().endswith((
        "unsupported parameter:", "unsupported parameter", "unknown parameter:", "invalid parameter:",
        "unrecognized parameter:", "unsupported value for", "invalid value for", "does not support",
        "not support", "不支持", "不支持参数", "无效参数"))


def _non_object_tool_arguments(raw: Any) -> str | None:
    # 测试工具的参数只要是对象就通过：{}、null、省略，以及带任意字段的对象（例如
    # {"reason": "测试连接"}）都算通过（工单 #1332 第 2 轮）。准入要证的是「会不会调工具、
    # 能不能用工具结果」，不是「参数写得像我们期望的样子」；网关与代理接入的模型常自己加字段，
    # 把参数写法当成能力差异会挡住整个准入。
    # 参数是对象（含 null 与省略）时返回 None；不是对象时返回收到的原文，
    # 供拒绝原因写明这家模型是怎么写的
    if raw is None:
        return None
    if isinstance(raw, str):
        candidate = raw.strip()
        if candidate == "":
            return None
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            return _quoted_arguments(raw)
        if value is None or isinstance(value, dict):
            return None
        return _quoted_arguments(raw)
    if isinstance(raw, dict):
        return None
    return _quoted_arguments(raw)


def _quoted_arguments(raw: Any) -> str:
    # 收到的原文：字符串照抄，其它形状按 JSON 写出来；空白压成一行，超过 120 字截断
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= 120 else collapsed[:120] + "…"


def _model_test_tool_outputs(result: InvokeResult) -> list[dict[str, Any]]:
    calls = [item for item in result.output if item.get("type") == "function_call"]
    if not calls:
        raise ProviderError("模型没有调用测试工具", reason="provider_protocol")
    outputs: list[dict[str, Any]] = []
    for call in calls:
        if call.get("name") != "yudao_model_test" or not call.get("call_id") \
                or call.get("status", "completed") != "completed":
            raise ProviderError("测试工具的调用不完整或工具名称不符", reason="provider_protocol")
        received = _non_object_tool_arguments(call.get("arguments"))
        if received is not None:
            raise ProviderError(f"测试工具的参数应当是对象，收到的是 {received}", reason="provider_protocol")
        outputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": "pong"})
    return outputs


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


def _model_referrers(bindings: Mapping[str, Mapping[str, str]], model_id: str) -> list[str]:
    # 部门默认中引用这一条模型访问定义的引用方；定义本身不算引用方
    return [f"bindings.{department}" for department in sorted(bindings)
            if bindings[department].get("model_id") == model_id]


def _definition_identity(model_id: str, provider_id: str) -> dict[str, str]:
    # 一条模型访问定义的公开身份：Provider 模块的影响列表只交出这个形状
    return {"model_id": model_id, "provider_id": provider_id}


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
                parts.append(f"{DEFINITIONS.department_labels.get(department, department)}部门缺少凭据环境变量 {reference}，请补充后重试")
                continue
        if "还没有选择模型" in issue.message or "未绑定" in issue.message:
            department = location.rsplit(".", 1)[-1]
            name = DEFINITIONS.department_labels.get(department, department)
            parts.append(f"{name}部门还没有选择模型，"
                         f"到系统的模型管理页设置部门默认，或在本项目的设置页为这个项目选择")
            continue
        if "准入" in issue.message:
            # 准入的说明（工单 #715）：补上部门名与模型标识，不写内部的定位串
            department = location.split(".")[1] if location.startswith("bindings.") else ""
            name = DEFINITIONS.department_labels.get(department, department)
            model_id = str(bindings.get(department, {}).get("model_id", ""))
            state = "准入已作废" if "作废" in issue.message else "尚未通过模型测试准入"
            parts.append(f"{name}部门绑定的模型 {model_id} {state}，请在模型管理页重新测试通过后再用")
            continue
        if "context_window" in issue.message:
            parts.append(f"{location}: {issue.message}（请为该部门绑定声明容量的模型）")
            continue
        parts.append(f"{location}: {issue.message}")
    return "；".join(parts) if parts else str(exc)


def _normalized_connection_url(value: str) -> str:
    text = value.strip()
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlsplit(text)
        host, port = parsed.hostname, parsed.port
        if parsed.scheme not in ("http", "https") or not host or parsed.username is not None or parsed.password is not None:
            raise ValueError("必须是 HTTP(S) 服务地址且不能携带凭据")
        authority = f"[{host.lower()}]" if ":" in host else host.lower()
        if port is not None:
            authority += f":{port}"
        return urlunsplit((parsed.scheme, authority, parsed.path.rstrip("/"), parsed.query, parsed.fragment))
    except ValueError as exc:
        raise CatalogValidationError((ValidationIssue("providers.base_url", str(exc)),)) from exc


def _parse_dotenv_or_raise(text: str) -> dict[str, str]:
    from .credentials import parse_dotenv_text
    return parse_dotenv_text(text)


def _read_dotenv_strict(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return _parse_dotenv_or_raise(text)


def _dotenv_text(data: Mapping[str, str]) -> str:
    # 写出的 .env 形状：一行一个 KEY=VALUE，按键名排序
    lines = [f"{key}={value}" for key, value in sorted(data.items(), key=lambda item: str(item[0]))]
    return "".join(line + "\n" for line in lines)


def _dotenv_payload_readable(data: Mapping[str, str]) -> str:
    # 要写的内容先用读 .env 的同一个解析器解析一遍，再核对读回来的值就是写进去的值：
    # 读不回来就不写，Yudao 不写出自己读不回的 .env（工单 #1158）
    payload = _dotenv_text(data)
    parsed = _parse_dotenv_or_raise(payload)
    for key, value in data.items():
        if parsed.get(str(key)) != value:
            raise ValueError(f"凭据内容写进 .env 以后读不回来：{key} 的值里有换行、引号或首尾空格")
    return payload


def _atomic_write_dotenv(path: Path, data: Mapping[str, str]) -> Path:
    return _write_dotenv_payload(path, _dotenv_text(data))


def _write_dotenv_payload(path: Path, payload: str) -> Path:
    # 原子替换写 .env：临时文件同目录创建，成功才替换；保持文件权限语义，
    # POSIX 上每次保存都使用用户私有权限；Windows 下 ACL 由目录继承，
    # 不把数字模式当成权限已受保护的证明
    parent = path.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(parent) if str(parent) not in ("", ".") else None,
                                     prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix":
            os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


__all__ = ["ProviderFacade", "CatalogValidationError", "REQUIRED_DEPARTMENTS"]

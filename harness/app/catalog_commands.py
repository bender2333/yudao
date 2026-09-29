# 模型目录与凭据的命令（设计说明第 3.2 节「模型管理」）。
# 目录内容仍由 Provider 模块保存；每次被接受的修改、测试结果与凭据变化经写入口追加事件（只含修订号、变化与结果，不含 Key）。
# 连接测试、获取模型列表与模型测试作为任务进行：命令先被接受，结果以后以事件出现。

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Literal

from pydantic import PositiveInt

from ..event_store import Command, catalog_stream
from ..models import CatalogEventType
from ..providers import CatalogValidationError, ProviderError, SUPPORTED_PROTOCOLS
from ..write_path import NewCatalogEvent
from .commands import Rejection
from .contracts import CommandRequest, Contract, NoRefs, Text
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application

# 与 Provider 模块支持的协议同一份清单
ProtocolName = Literal[tuple(sorted(SUPPORTED_PROTOCOLS))]


class ProviderInput(Contract):
    # 一份 Provider 配置：声明一种协议（ADR-0004），地址是该协议的请求基址
    id: Text
    name: Text
    protocol: ProtocolName
    base_url: str = ""
    credential_ref: str = ""
    timeout_sec: float = 600.0
    preset_id: str = ""
    models_url: str = ""


class ModelInput(Contract):
    # 一条模型访问定义；协议取自所属连接，容量逐行在这条命令中确认（窗口与输出上限）
    id: Text
    model: Text
    context_window: int | None = None
    max_output_tokens: PositiveInt
    capability_source: str = ""


class DocumentModelInput(ModelInput):
    # 目录文档中的定义自己带上所属连接
    provider_id: Text


class BindingInput(Contract):
    provider_id: Text
    model_id: Text


class CatalogDocumentInput(Contract):
    # 目录文档（编辑 JSON 与导入）：不含 Key、准入记录与项目部门设置，格式与目录文件相同
    providers: list[ProviderInput]
    models: list[DocumentModelInput]
    bindings: dict[str, BindingInput] = {}


class CatalogConnectionSave(CommandRequest):
    base_version: int
    provider: ProviderInput
    models: list[ModelInput] = []


class CatalogConnectionSaveRefs(Contract):
    provider_id: str


class CatalogConnectionDelete(CommandRequest):
    base_version: int
    provider_id: Text


class CatalogDocumentSave(CommandRequest):
    base_version: int
    document: CatalogDocumentInput


class CatalogReload(CommandRequest):
    base_version: int


class CatalogCandidatesCollect(CommandRequest):
    base_version: int
    provider_id: Text
    models_url: str | None = None


class CatalogConnectionTest(CommandRequest):
    base_version: int
    provider_id: Text
    model_id: Text | None = None


class CatalogModelTest(CommandRequest):
    base_version: int
    provider_id: Text
    model_id: Text


class CatalogDepartmentDefaultsSave(CommandRequest):
    base_version: int
    bindings: dict[str, BindingInput]


class CredentialSet(CommandRequest):
    base_version: int
    ref: Text
    secret: Text
    persist: bool = False


class CredentialClearOverride(CommandRequest):
    base_version: int
    ref: Text


class CredentialRemovePersisted(CommandRequest):
    base_version: int
    ref: Text


# ---------------------------------------------------------------------------
# 事务与事件


def _register(application: Application, command: Command) -> None:
    # 结果以后以事件出现的命令：先登记命令身份，提交还没有事件的结果位置
    application.system.writes.transact(catalog_stream(), lambda _transaction: None, command=command)


def _revised(application: Application, command: Command, operation: str, before: int, after: int,
             *, provider_id: str | None) -> None:
    payload = {"revision": after, "base_revision": before, "operation": operation, "provider_id": provider_id}
    application.system.writes.transact(catalog_stream(), lambda transaction: transaction.append(
        NewCatalogEvent(CatalogEventType.CATALOG_REVISED, payload)), command=command)


def _result(application: Application, event_type: str, payload: dict[str, Any]) -> None:
    # 任务结果：不是由命令写入，提出者记为系统
    application.system.writes.transact(catalog_stream(), lambda transaction: transaction.append(
        NewCatalogEvent(event_type, payload, actor="system")))


def _stale_base(facade, base_version: int) -> None:
    current = facade.catalog_revision()
    if base_version != current:
        raise Rejection("stale_base", "目录已经变化，请重新读取以后再提交", current_version=current)


def _provider_view(facade, provider_id: str) -> dict[str, Any] | None:
    return next((item for item in facade.providers_view()["providers"] if item["id"] == provider_id), None)


def _check_not_registered(application: Application, command: Command) -> None:
    # 已经登记过的命令身份不再执行（内容相同 → DuplicateCommand，不同 → CommandIdReused）：
    # 修改 Provider 目录或凭据之前先核对，重复提交不会把目录、目录文件与 .env 再改一遍
    application.system.store.check_command(command)


# ---------------------------------------------------------------------------
# 目录内容


async def _save_connection(application: Application, command: Command, request: CatalogConnectionSave) -> None:
    facade = application.system.facade
    _check_not_registered(application, command)
    _stale_base(facade, request.base_version)
    before = facade.catalog_revision()
    previous = facade.to_document()
    provider = request.provider.model_dump()
    models = facade.merge_model_admissions([item.model_dump() for item in request.models])
    try:
        facade.save_provider_entry(provider, models)
    except CatalogValidationError as exc:
        raise Rejection("catalog_invalid", str(exc))
    after = facade.catalog_revision()
    problem = facade.persist_catalog(previous)
    if problem is not None:
        raise Rejection("catalog_invalid", problem)
    _revised(application, command, "save_connection", before, after, provider_id=request.provider.id)


async def _delete_connection(application: Application, command: Command, request: CatalogConnectionDelete) -> None:
    facade = application.system.facade
    _check_not_registered(application, command)
    _stale_base(facade, request.base_version)
    before = facade.catalog_revision()
    previous = facade.to_document()
    try:
        facade.delete_provider(request.provider_id)
    except CatalogValidationError as exc:
        if any("不存在" in issue.message for issue in exc.issues):
            raise Rejection("not_found", f"Provider 配置不存在：{request.provider_id}")
        referrers = [issue.location for issue in exc.issues]
        raise Rejection("in_use", "仍被引用，无法删除：" + "、".join(referrers))
    after = facade.catalog_revision()
    problem = facade.persist_catalog(previous)
    if problem is not None:
        raise Rejection("catalog_invalid", problem)
    _revised(application, command, "delete_connection", before, after, provider_id=request.provider_id)


async def _save_document(application: Application, command: Command, request: CatalogDocumentSave) -> None:
    facade = application.system.facade
    _check_not_registered(application, command)
    _stale_base(facade, request.base_version)
    before = facade.catalog_revision()
    previous = facade.to_document()
    document = {
        "providers": [item.model_dump() for item in request.document.providers],
        "models": facade.merge_model_admissions([item.model_dump() for item in request.document.models]),
        "bindings": {key: item.model_dump() for key, item in request.document.bindings.items()},
    }
    try:
        facade.replace_catalog_document(document)
    except CatalogValidationError as exc:
        raise Rejection("catalog_invalid", str(exc))
    after = facade.catalog_revision()
    problem = facade.persist_catalog(previous)
    if problem is not None:
        raise Rejection("catalog_invalid", problem)
    _revised(application, command, "save_document", before, after, provider_id=None)


async def _save_department_defaults(application: Application, command: Command,
                                    request: CatalogDepartmentDefaultsSave) -> None:
    facade = application.system.facade
    _check_not_registered(application, command)
    _stale_base(facade, request.base_version)
    before = facade.catalog_revision()
    previous = facade.to_document()
    try:
        facade.save_bindings({key: item.model_dump() for key, item in request.bindings.items()})
    except CatalogValidationError as exc:
        raise Rejection("catalog_invalid", str(exc))
    after = facade.catalog_revision()
    problem = facade.persist_catalog(previous)
    if problem is not None:
        raise Rejection("catalog_invalid", problem)
    if after == before:
        _register(application, command)
        return
    _revised(application, command, "department_defaults", before, after, provider_id=None)


async def _reload(application: Application, command: Command, request: CatalogReload) -> None:
    # 重新读取目录文件：修订号变化时才追加事件；事件记录提交时依据的修订号（追加类命令，不要求相等）
    facade = application.system.facade
    _check_not_registered(application, command)
    before = facade.catalog_revision()
    await asyncio.to_thread(facade.reload)
    after = facade.catalog_revision()
    if after == before:
        _register(application, command)
        return
    _revised(application, command, "reload", request.base_version, after, provider_id=None)


# ---------------------------------------------------------------------------
# 任务：获取模型列表与两种测试


async def _collect_candidates(application: Application, command: Command, request: CatalogCandidatesCollect) -> None:
    facade = application.system.facade
    if _provider_view(facade, request.provider_id) is None:
        raise Rejection("not_found", f"Provider 配置不存在：{request.provider_id}")
    _register(application, command)

    async def run() -> None:
        try:
            result = await asyncio.to_thread(facade.refresh_candidates, request.provider_id,
                                             models_url_override=request.models_url)
        except (CatalogValidationError, ProviderError) as exc:
            _result(application, CatalogEventType.CATALOG_CANDIDATES_COLLECTED, {
                "base_revision": request.base_version,
                "provider_id": request.provider_id, "status": "unknown", "source_url": request.models_url or "",
                "fetched_at": "", "candidates": [], "candidate_ids": [], "error": str(exc),
            })
            return
        _result(application, CatalogEventType.CATALOG_CANDIDATES_COLLECTED, {
            "base_revision": request.base_version,
            "provider_id": request.provider_id, "status": result["status"], "source_url": result["source_url"],
            "fetched_at": result["fetched_at"], "candidates": result["candidates"],
            "candidate_ids": [item["id"] for item in result["candidates"]], "error": result["error"],
        })

    application.schedule(run())


def _test_payload(base_revision: int, kind: str, provider_id: str, model_id: str, started: float,
                  result: dict[str, Any], error: str | None) -> dict[str, Any]:
    return {
        "base_revision": base_revision,
        "kind": kind, "provider_id": provider_id, "model_id": model_id, "ok": bool(result.get("ok")),
        "protocol": result.get("protocol"), "error": error,
        "actual_model": result.get("model") if kind == "model" else None,
        "elapsed_ms": int(round((time.monotonic() - started) * 1000)),
        "admitted": (bool(result["admitted"]) if "admitted" in result and result["admitted"] is not None else None),
    }


async def _test_connection(application: Application, command: Command, request: CatalogConnectionTest) -> None:
    facade = application.system.facade
    view = facade.providers_view()
    if _provider_view(facade, request.provider_id) is None:
        raise Rejection("not_found", f"Provider 配置不存在：{request.provider_id}")
    models = [item for item in view["models"] if item["provider_id"] == request.provider_id]
    if request.model_id is not None:
        models = [item for item in models if item["id"] == request.model_id]
        if not models:
            raise Rejection("not_found", f"模型访问定义不存在：{request.model_id}")
    if not models:
        raise Rejection("catalog_invalid", "Provider 还没有模型访问定义，请先保存以后测试连接")
    model_id = models[0]["id"]
    _register(application, command)

    async def run() -> None:
        started = time.monotonic()
        selection = {"key": model_id, "provider_id": request.provider_id, "model_id": model_id}
        try:
            result = await asyncio.to_thread(facade.test_connection, selection)
        except (CatalogValidationError, ProviderError) as exc:
            _result(application, CatalogEventType.CATALOG_TEST_FINISHED,
                    _test_payload(request.base_version, "connection", request.provider_id, model_id, started,
                                  {"ok": False, "admitted": None}, str(exc)))
            return
        error = None
        if not result.get("ok"):
            error = str(result.get("message") or result.get("reason") or "连接失败")
        _result(application, CatalogEventType.CATALOG_TEST_FINISHED,
                _test_payload(request.base_version, "connection", request.provider_id, model_id, started,
                              result, error))

    application.schedule(run())


async def _test_model(application: Application, command: Command, request: CatalogModelTest) -> None:
    facade = application.system.facade
    view = facade.providers_view()
    if _provider_view(facade, request.provider_id) is None:
        raise Rejection("not_found", f"Provider 配置不存在：{request.provider_id}")
    if not any(item["id"] == request.model_id and item["provider_id"] == request.provider_id
               for item in view["models"]):
        raise Rejection("not_found", f"模型访问定义不存在：{request.model_id}")
    _register(application, command)

    async def run() -> None:
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(facade.model_test, request.provider_id, request.model_id)
        except (CatalogValidationError, ProviderError) as exc:
            _result(application, CatalogEventType.CATALOG_TEST_FINISHED,
                    _test_payload(request.base_version, "model", request.provider_id, request.model_id, started,
                                  {"ok": False, "admitted": None}, str(exc)))
            return
        _result(application, CatalogEventType.CATALOG_TEST_FINISHED,
                _test_payload(request.base_version, "model", request.provider_id, request.model_id, started,
                              result, result.get("error")))

    application.schedule(run())


# ---------------------------------------------------------------------------
# 凭据


def _credential_event(action: str, status: dict[str, Any], version: int, persisted: bool) -> dict[str, Any]:
    return {"ref": status["ref"], "action": action, "source": status["source"], "version": version,
            "persisted": persisted}


async def _set_credential(application: Application, command: Command, request: CredentialSet) -> None:
    facade = application.system.facade
    _check_not_registered(application, command)
    current = facade.credential_version(request.ref)
    if request.base_version != current:
        raise Rejection("stale_base", "凭据已经变化，请重新读取以后再提交", current_version=current)
    try:
        result = await asyncio.to_thread(facade.set_credential, request.ref, request.secret,
                                         persist=request.persist)
    except CatalogValidationError as exc:
        raise Rejection("catalog_invalid", str(exc))
    _credential_changed(application, command, "set", result, persisted=result["persisted"])


async def _clear_credential_override(application: Application, command: Command, request: CredentialClearOverride) -> None:
    facade = application.system.facade
    _check_not_registered(application, command)
    current = facade.credential_version(request.ref)
    if request.base_version != current:
        raise Rejection("stale_base", "凭据已经变化，请重新读取以后再提交", current_version=current)
    result = await asyncio.to_thread(facade.clear_credential, request.ref)
    _credential_changed(application, command, "clear_override", result, persisted=False)


async def _remove_persisted_credential(application: Application, command: Command,
                                       request: CredentialRemovePersisted) -> None:
    facade = application.system.facade
    _check_not_registered(application, command)
    current = facade.credential_version(request.ref)
    if request.base_version != current:
        raise Rejection("stale_base", "凭据已经变化，请重新读取以后再提交", current_version=current)
    try:
        result = await asyncio.to_thread(facade.remove_persisted_credential, request.ref)
    except CatalogValidationError as exc:
        raise Rejection("catalog_invalid", str(exc))
    _credential_changed(application, command, "remove_persisted", result, persisted=True)


def _credential_changed(application: Application, command: Command, action: str, result: dict[str, Any], *,
                        persisted: bool) -> None:
    payload = _credential_event(action, result["status"], result["version"], persisted)
    application.system.writes.transact(catalog_stream(), lambda transaction: transaction.append(
        NewCatalogEvent(CatalogEventType.CREDENTIAL_CHANGED, payload)), command=command)


# ---------------------------------------------------------------------------
# 登记

CATALOG_CONNECTION_SAVE = CommandDefinition(
    name="catalog.connection.save", request=CatalogConnectionSave, refs=CatalogConnectionSaveRefs,
    handle=_save_connection,
    derive_refs=lambda events: CatalogConnectionSaveRefs(provider_id=events[0].payload["provider_id"]),
    reasons=("stale_base", "catalog_invalid"),
)
CATALOG_CONNECTION_DELETE = CommandDefinition(
    name="catalog.connection.delete", request=CatalogConnectionDelete, refs=NoRefs,
    handle=_delete_connection, derive_refs=lambda _events: NoRefs(),
    reasons=("stale_base", "not_found", "in_use"),
)
CATALOG_DOCUMENT_SAVE = CommandDefinition(
    name="catalog.document.save", request=CatalogDocumentSave, refs=NoRefs, handle=_save_document,
    derive_refs=lambda _events: NoRefs(), reasons=("stale_base", "catalog_invalid"),
)
CATALOG_RELOAD = CommandDefinition(
    name="catalog.reload", request=CatalogReload, refs=NoRefs, handle=_reload,
    derive_refs=lambda _events: NoRefs(),
)
CATALOG_CANDIDATES_COLLECT = CommandDefinition(
    name="catalog.candidates.collect", request=CatalogCandidatesCollect, refs=NoRefs,
    handle=_collect_candidates, derive_refs=lambda _events: NoRefs(), reasons=("not_found",),
)
CATALOG_CONNECTION_TEST = CommandDefinition(
    name="catalog.connection.test", request=CatalogConnectionTest, refs=NoRefs, handle=_test_connection,
    derive_refs=lambda _events: NoRefs(), reasons=("not_found", "catalog_invalid"),
)
CATALOG_MODEL_TEST = CommandDefinition(
    name="catalog.model.test", request=CatalogModelTest, refs=NoRefs, handle=_test_model,
    derive_refs=lambda _events: NoRefs(), reasons=("not_found",),
)
CATALOG_DEPARTMENT_DEFAULTS_SAVE = CommandDefinition(
    name="catalog.department_defaults.save", request=CatalogDepartmentDefaultsSave, refs=NoRefs,
    handle=_save_department_defaults, derive_refs=lambda _events: NoRefs(),
    reasons=("stale_base", "catalog_invalid"),
)
CREDENTIAL_SET = CommandDefinition(
    name="credential.set", request=CredentialSet, refs=NoRefs, handle=_set_credential,
    derive_refs=lambda _events: NoRefs(), reasons=("stale_base", "catalog_invalid"),
)
CREDENTIAL_CLEAR_OVERRIDE = CommandDefinition(
    name="credential.clear_override", request=CredentialClearOverride, refs=NoRefs,
    handle=_clear_credential_override, derive_refs=lambda _events: NoRefs(), reasons=("stale_base",),
)
CREDENTIAL_REMOVE_PERSISTED = CommandDefinition(
    name="credential.remove_persisted", request=CredentialRemovePersisted, refs=NoRefs,
    handle=_remove_persisted_credential, derive_refs=lambda _events: NoRefs(),
    reasons=("stale_base", "catalog_invalid"),
)

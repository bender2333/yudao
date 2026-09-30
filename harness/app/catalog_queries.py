# 系统页的目录查询（设计说明第 4.3 节「系统页」）。
# 目录内容仍由 Provider 模块保存；这里把目录、准入与凭据状态整理成界面需要的形状，只读取，不写入。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import CatalogEventType
from .contracts import Contract, Snapshot
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application


class CatalogCredential(Contract):
    # 凭据状态：是否就绪、来源、是否有内存覆盖与版本；不含 Key
    ref: str
    configured: bool
    source: str
    has_override: bool
    version: int


class CatalogModel(Contract):
    # 模型访问定义与它的准入事实；协议取自所属连接；stale 表示准入以后目录修订号又变化过
    id: str
    provider_id: str
    model: str
    context_window: int | None
    max_output_tokens: int
    capability_source: str
    accepts_required_tool_call: bool
    admitted_at: str | None
    admitted_revision: int | None
    admitted_model: str | None
    stale: bool


class CatalogProvider(Contract):
    id: str
    name: str
    protocol: str
    base_url: str
    credential_ref: str
    timeout_sec: float
    preset_id: str
    models_url: str
    credential: CatalogCredential
    credential_configured: bool
    models: list[CatalogModel]


class CatalogBinding(Contract):
    provider_id: str
    model_id: str


class CatalogPresets(Contract):
    # 服务方案预置表与它的 revision 与来源
    revision: str
    source: str
    presets: list[dict[str, Any]]


class Catalog(Contract):
    # 查询 catalog：目录内容、准入与凭据状态、预置表，以及目录修订号
    revision: int
    config_state: str
    reload_error: str | None
    presets: CatalogPresets
    providers: list[CatalogProvider]
    models: list[CatalogModel]
    bindings: dict[str, CatalogBinding]


class CatalogDocument(Contract):
    # 查询 catalog.document：编辑 JSON 与导出使用，不含 Key、准入记录与项目部门设置
    revision: int
    providers: list[dict[str, Any]]
    models: list[dict[str, Any]]
    bindings: dict[str, dict[str, Any]]


def _model(item: dict[str, Any], revision: int) -> CatalogModel:
    admitted = item.get("admitted_at") is not None
    return CatalogModel.model_validate({
        **item,
        "stale": bool(admitted and item.get("admitted_revision") != revision),
    })


def _catalog(application: Application, _request: None) -> Snapshot[Catalog]:
    system = application.system
    facade = system.facade
    position = system.store.end_position()
    revision = facade.catalog_revision()
    view = facade.providers_view()
    status = facade.config_status()
    providers = []
    for item in view["providers"]:
        reference = item.get("credential_ref") or ""
        credential = (facade.credential_status(reference) if reference else
                      {"ref": "", "configured": True, "source": "none", "has_override": False, "version": 0})
        providers.append(CatalogProvider.model_validate({
            **item, "credential": credential,
            "models": [_model(model, revision) for model in item["models"]],
        }))
    presets = facade.presets_public_view()
    data = Catalog(
        revision=revision,
        config_state=status["config_state"],
        reload_error=status["reload_error"],
        presets=CatalogPresets(revision=presets["revision"], source=presets["source"],
                               presets=list(presets["presets"])),
        providers=providers,
        models=[_model(item, revision) for item in view["models"]],
        bindings={key: CatalogBinding.model_validate(value) for key, value in view["bindings"].items()},
    )
    return Snapshot[Catalog](position=position, data=data)


def _catalog_document(application: Application, _request: None) -> Snapshot[CatalogDocument]:
    system = application.system
    position = system.store.end_position()
    document = system.facade.to_document()
    data = CatalogDocument(
        revision=int(document["revision"]),
        providers=[dict(item) for item in document["providers"]],
        models=[dict(item) for item in document["models"]],
        bindings={key: dict(value) for key, value in document["bindings"].items()},
    )
    return Snapshot[CatalogDocument](position=position, data=data)


# 目录事件改变这里的结果：客户端收到这些事件时重新查询
_CATALOG_EVENTS = (CatalogEventType.CATALOG_REVISED, CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
                   CatalogEventType.CATALOG_TEST_FINISHED, CatalogEventType.CREDENTIAL_CHANGED)

CATALOG_QUERY = QueryDefinition(name="catalog", request=None, result=Catalog, handle=_catalog,
                                changed_by=_CATALOG_EVENTS)
CATALOG_DOCUMENT_QUERY = QueryDefinition(name="catalog.document", request=None, result=CatalogDocument,
                                         handle=_catalog_document, changed_by=_CATALOG_EVENTS)

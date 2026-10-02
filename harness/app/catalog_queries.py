# 系统页的目录查询（设计说明第 4.3 节「系统页」）。
# 目录内容仍由 Provider 模块保存；这里把目录、准入与凭据状态整理成界面需要的形状，只读取，不写入。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import DEPARTMENTS, CatalogEventType
from ..providers import capabilities
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
    # 模型访问定义；协议取自所属连接。准入记录由 catalog.admissions 单独返回（工单 #86）
    id: str
    provider_id: str
    model: str
    context_window: int | None
    max_output_tokens: int
    capability_source: str
    accepts_required_tool_call: bool
    # 输入方式（设计说明第 4.3 节）：模型访问定义中的值，文本总是包含
    input_modalities: list[str]
    reasoning_levels: list[str]
    default_reasoning_level: str | None
    reasoning_mode: str


class CatalogAdmission(Contract):
    # 一条定义的准入事实：是否已准入、是否已作废、测试时间与实际返回的模型（工单 #86）
    model_id: str
    provider_id: str
    protocol: str | None
    admitted: bool
    stale: bool
    admitted_at: str | None
    admitted_model: str | None
    base_url: str | None
    credential_ref: str | None
    model: str | None

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
    # 请求档位（#87）：部门默认保存的可为空档位，实际发送的档位由 Provider 按模型声明限制
    requested_tier: str | None = None


class CatalogPresets(Contract):
    # 服务方案预置表与它的 revision 与来源
    revision: str
    source: str
    presets: list[dict[str, Any]]


class CatalogCapabilityTable(Contract):
    # 模型能力表：整张表的 revision、快照日期与来源，以及预置服务方案在表中的条目
    # （设计说明第 4.1 节；手动添加模型访问定义时客户端据此预填，运行时不从远端刷新）
    revision: str
    snapshot_date: str
    source: str
    presets: dict[str, list[dict[str, Any]]]

class Catalog(Contract):
    # 查询 catalog：目录内容、凭据状态、预置表、准入记录与目录修订号（准入与目录分开返回，工单 #86）
    revision: int
    config_state: str
    reload_error: str | None
    presets: CatalogPresets
    capability_table: CatalogCapabilityTable
    providers: list[CatalogProvider]
    models: list[CatalogModel]
    admissions: list[CatalogAdmission]
    bindings: dict[str, CatalogBinding]
    # 部门默认当前绑定的模型不具备该部门建议能力时的提醒（设计说明第 5.6 节「一直显示」）
    department_reminders: dict[str, list[str]]


class CatalogDocument(Contract):
    # 查询 catalog.document：编辑 JSON 与导出使用，不含 Key、准入记录与项目部门设置
    revision: int
    providers: list[dict[str, Any]]
    models: list[dict[str, Any]]
    bindings: dict[str, dict[str, Any]]


def _model(item: dict[str, Any]) -> CatalogModel:
    return CatalogModel.model_validate(dict(item))


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
            "models": [_model(model) for model in item["models"]],
        }))
    presets = facade.presets_public_view()
    table = capabilities.table_public()
    bindings = {key: CatalogBinding.model_validate(value) for key, value in view["bindings"].items()}
    data = Catalog(
        revision=revision,
        config_state=status["config_state"],
        reload_error=status["reload_error"],
        presets=CatalogPresets(revision=presets["revision"], source=presets["source"],
                               presets=list(presets["presets"])),
        capability_table=CatalogCapabilityTable(
            revision=table["revision"], snapshot_date=table["snapshot_date"],
            source=table["source"], presets=table["presets"]),
        providers=providers,
        models=[_model(item) for item in view["models"]],
        admissions=[CatalogAdmission.model_validate(item) for item in view["admissions"]],
        bindings=bindings,
        # 部门默认各自当前绑定的模型的建议能力提醒（设计说明第 5.6 节）
        department_reminders={department: facade.model_reminders(
            None if bindings.get(department) is None else bindings[department].model_id, department)
            for department in DEPARTMENTS},
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

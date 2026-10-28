# 系统页的目录查询（设计说明第 4.3 节「系统页」）。
# 目录内容仍由 Provider 模块保存；这里把目录、准入与凭据状态整理成界面需要的形状，只读取，不写入。

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, Mapping

from ..models import DEPARTMENTS, CatalogEventType, EventType, ProjectEventType
from ..providers import DEFAULT_TIMEOUT_SEC, capabilities
from ..providers.errors import CatalogValidationError
from .contracts import Contract, Snapshot
from .project_queries import NotFound
from .registry import QueryDefinition, UnchangedEvent

if TYPE_CHECKING:
    from .application import Application

class CatalogQueryInvalid(Exception):
    # 拟议文档或选择结构非法：接口层映射为 422，原因写出字段位置（与命令被拒绝时 catalog_invalid 同一写法）。
    # Provider 模块的 CatalogValidationError 在这一层转成它，接口层只认应用层的异常（工单 #261）
    pass


class CatalogCredential(Contract):
    # 凭据状态：是否就绪、来源、是否有内存覆盖与版本；不含 Key
    ref: str
    configured: bool
    source: str
    has_override: bool
    version: int


class CatalogModel(Contract):
    # 模型访问定义；调用协议是定义自己的字段（模型管理设计说明第 4.3 节）。准入记录由 catalog.admissions 单独返回（工单 #86）
    id: str
    provider_id: str
    model: str
    protocol: str
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
    # 新建连接表单的默认请求时限，单位秒：与目录文件、目录命令的默认值同一份，
    # 界面取它填表单，不在客户端另写一个数（工单 #294）
    default_timeout_sec: float
    presets: CatalogPresets
    capability_table: CatalogCapabilityTable
    providers: list[CatalogProvider]
    models: list[CatalogModel]
    admissions: list[CatalogAdmission]
    bindings: dict[str, CatalogBinding]
    # 部门默认当前绑定的模型不具备该部门建议能力时的提醒（设计说明第 5.6 节「一直显示」）
    department_reminders: dict[str, list[str]]
    # 目录中每条模型访问定义在各部门的建议能力提醒（模型 ID → 部门 → 提醒）：
    # 部门默认的下拉选中一条定义时界面立即给出提醒，不等保存（设计说明第 5.6 节）
    model_reminders: dict[str, dict[str, list[str]]]


class CatalogDocument(Contract):
    # 查询 catalog.document：编辑 JSON 与导出使用，不含 Key、准入记录与项目部门设置
    revision: int
    providers: list[dict[str, Any]]
    models: list[dict[str, Any]]
    bindings: dict[str, dict[str, Any]]


def _model(item: dict[str, Any]) -> CatalogModel:
    return CatalogModel.model_validate(dict(item))

class ChangeImpactRequest(Contract):
    # 拟议的修改（get 查询参数）：kind 决定改动的形状，document 是 JSON 文本。
    # connection：{"provider": {...}, "models": [...]}（catalog.connection.save 的两个字段，models 可省，省略时保留当前值）；
    # provider：不使用 document，按 provider_id 算出删除该份配置之后的影响；
    # document：与目录文件同形的整份目录文档（编辑 JSON 与导入，设计说明第 4.6 节）
    kind: Literal["connection", "provider", "document"]
    provider_id: str | None = None
    document: str | None = None

class ImpactDefinition(Contract):
    # 受影响的模型访问定义（准入会作废），或将被一并删除的定义
    model_id: str
    provider_id: str

class ImpactDepartmentDefault(Contract):
    # 部门默认中的引用方
    department: str
    model_id: str
    provider_id: str

class ImpactProjectSetting(Contract):
    # 某个项目的部门设置中的引用方
    project_id: str
    project_name: str
    department: str
    model_id: str
    provider_id: str

class ImpactWorkItem(Contract):
    # 正在使用受影响定义的进行中事项（设计说明第 5.3 节的生效模型：项目部门设置优先，否则部门默认）。
    # 按（事项，部门）逐条列出：事项里哪个部门的模型选择落在受影响的定义上就写哪个部门，
    # 与它此刻在不在工作无关（设计说明第 4.4 节，工单 #872）
    project_id: str
    project_name: str
    work_item_id: str
    title: str
    department: str

class ChangeImpact(Contract):
    # catalog.change_impact 的结果：只读取，不写入任何内容（设计说明第 4.4、4.5 节）
    revision: int
    impacted: list[ImpactDefinition] = []
    deletions: list[ImpactDefinition] = []
    department_defaults: list[ImpactDepartmentDefault] = []
    project_settings: list[ImpactProjectSetting] = []
    work_items: list[ImpactWorkItem] = []


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
        default_timeout_sec=DEFAULT_TIMEOUT_SEC,
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
        # 目录中每条定义在各部门的提醒：部门默认的下拉选中一条定义时立即给出提醒，不等保存
        model_reminders=facade.model_reminders_by_department([item["id"] for item in view["models"]]),
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

# 模型调用的过程事件：这些高频事件不改变目录的内容（工单 #891）
_CATALOG_UNCHANGED_EVENTS = (
    UnchangedEvent(EventType.CONTEXT_ASSEMBLED, "上下文装配不改变目录的内容"),
    UnchangedEvent(EventType.MODEL_REQUEST_SERIALIZED, "请求序列化不改变目录的内容"),
    UnchangedEvent(EventType.MODEL_REQUESTED, "发出模型请求不改变目录的内容"),
    UnchangedEvent(EventType.MODEL_MESSAGE, "模型消息不改变目录的内容"),
    UnchangedEvent(EventType.MODEL_REASONING, "模型的推理内容不改变目录的内容"),
    UnchangedEvent(EventType.MODEL_STREAM_PROGRESS, "流式进度不改变目录的内容"),
    UnchangedEvent(EventType.TOOL_STARTED, "工具开始不改变目录的内容"),
    UnchangedEvent(EventType.TOOL_CALLED, "工具调用不改变目录的内容"),
)


def _definition_identity(item: Mapping[str, Any]) -> ImpactDefinition:
    return ImpactDefinition(model_id=str(item.get("id") or ""),
                            provider_id=str(item.get("provider_id") or ""))


def _strand(value: Any) -> str:
    # 查询参数里的标识：只有字符串才算给出，其余一律当作没给
    return value.strip() if isinstance(value, str) else ""


def _json_object(raw: Any, location: str) -> Mapping[str, Any]:
    # 查询参数里的 JSON 文本：不是对象时按查询目标不存在拒绝，与其它查询一致（接口层映射为 404）
    if not isinstance(raw, str) or not raw.strip():
        raise NotFound(location, "应为 JSON 文本")
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise NotFound(location, f"不是合法的 JSON：{exc}") from exc
    if not isinstance(parsed, Mapping):
        raise NotFound(location, "应为 JSON 对象")
    return parsed


def _removed_definitions(current: Mapping[str, Any], proposed: Mapping[str, Any]) -> list[ImpactDefinition]:
    # 拟议目录里消失的定义：整条不在，或所属连接不在（随连接一起消失）
    provider_ids = {str(item.get("id")) for item in proposed["providers"]}
    model_ids = {str(item.get("id")) for item in proposed["models"]}
    return [_definition_identity(item) for item in current["models"]
            if str(item.get("id")) not in model_ids
            or str(item.get("provider_id")) not in provider_ids]


def _proposed_document(current: Mapping[str, Any], request: ChangeImpactRequest) -> dict[str, Any]:
    # 按拟议的修改构造目录形状的拟议终态；结构由 Provider 模块在计算受影响定义时校验
    if request.kind == "provider":
        provider_id = _strand(request.provider_id)
        if not provider_id:
            raise NotFound("provider_id", "缺少要删除的 Provider 配置")
        if not any(item.get("id") == provider_id for item in current["providers"]):
            raise NotFound(provider_id, "Provider 配置不存在")
        return {"providers": [item for item in current["providers"] if item.get("id") != provider_id],
                "models": [item for item in current["models"] if item.get("provider_id") != provider_id]}
    if request.kind == "connection":
        proposed = _json_object(request.document, "document")
        provider = proposed.get("provider")
        if not isinstance(provider, Mapping):
            raise NotFound("document", "document 缺少 provider 对象")
        provider_id = _strand(provider.get("id"))
        providers = [item for item in current["providers"] if item.get("id") != provider_id]
        providers.append(dict(provider))
        models = [item for item in current["models"] if item.get("provider_id") != provider_id]
        nested = proposed.get("models")
        if nested is None:
            models = [item for item in current["models"]
                      if item.get("provider_id") == provider_id] + models
        elif isinstance(nested, list):
            for item in nested:
                if not isinstance(item, Mapping):
                    raise NotFound("document", "models 里应为对象")
                entry = dict(item)
                entry["provider_id"] = provider_id
                models.append(entry)
        else:
            raise NotFound("document", "models 应为数组")
        return {"providers": providers, "models": models}
    proposed = _json_object(request.document, "document")
    providers = proposed.get("providers")
    models = proposed.get("models")
    if not isinstance(providers, list) or not isinstance(models, list):
        raise NotFound("document", "document 应带 providers 与 models 数组")
    return {"providers": [dict(item) for item in providers if isinstance(item, Mapping)],
            "models": [dict(item) for item in models if isinstance(item, Mapping)]}


def _change_impact(application: Application, request: ChangeImpactRequest) -> Snapshot[ChangeImpact]:
    # 保存会作废准入的修改之前的影响列表（设计说明第 4.4 节最后一段）与删除时的一并删除清单（第 4.5 节）：
    # 只读取，不写入任何内容。Provider 模块只返回受影响与将被删除的定义；
    # 引用方与进行中事项由应用层汇总：目录中的部门默认、各项目的项目部门设置、运行状态投影中的进行中事项。
    # 角色默认与项目角色设置（第 5.1、5.2 节）还没有实现，这两层引用方尚未汇总
    system = application.system
    facade = system.facade
    position = system.store.end_position()
    revision = facade.catalog_revision()
    current = facade.to_document()
    proposed = _proposed_document(current, request)
    try:
        impacted = [ImpactDefinition(**item) for item in facade.impacted_definitions(proposed)]
        deletions = _removed_definitions(current, proposed)
        if request.kind == "provider":
            deletions = [ImpactDefinition(**item)
                         for item in facade.deletable_definitions(_strand(request.provider_id))]
    except CatalogValidationError as exc:
        # 拟议文档结构非法：接口层按输入问题映射为 422，原因保留字段位置（工单 #261）
        raise CatalogQueryInvalid(str(exc)) from exc
    affected = {item.model_id for item in impacted} | {item.model_id for item in deletions}

    bindings = facade.get_bindings()
    department_defaults = [ImpactDepartmentDefault(department=department,
                                                   model_id=str(binding.get("model_id") or ""),
                                                   provider_id=str(binding.get("provider_id") or ""))
                           for department, binding in sorted(bindings.items())
                           if str(binding.get("model_id") or "") in affected]
    project_settings: list[ImpactProjectSetting] = []
    work_items: list[ImpactWorkItem] = []
    for project in system.projects.list_projects(include_archived=True):
        settings = project.department_settings
        for department in sorted(settings):
            setting = settings[department] if isinstance(settings, Mapping) else None
            if setting is not None and setting.model_id in affected:
                project_settings.append(ImpactProjectSetting(
                    project_id=project.project_id, project_name=project.name, department=department,
                    model_id=str(setting.model_id or ""), provider_id=str(setting.provider_id or "")))
        item = (None if project.active_work_item_id is None
                else project.work_item(project.active_work_item_id))
        if item is None or item.status != "in_progress":
            continue
        # 进行中事项按（事项，部门）逐条列出（设计说明第 4.4 节，工单 #872）：
        # 事项里哪个部门的模型选择（项目部门设置，没有时取部门默认）落在受影响的定义上，就列出这个部门，
        # 不论它此刻在不在工作——它下一次开始工作时同样会被挡住。一个事项可以出现几次。
        for department in DEPARTMENTS:
            setting = settings.get(department) if isinstance(settings, Mapping) else None
            selected = str((setting.model_id if setting is not None else None) or "") or \
                str((bindings.get(department) or {}).get("model_id") or "")
            if selected not in affected:
                continue
            work_items.append(ImpactWorkItem(
                project_id=project.project_id, project_name=project.name,
                work_item_id=item.work_item_id, title=item.title, department=department))
    data = ChangeImpact(revision=revision, impacted=impacted, deletions=deletions,
                        department_defaults=department_defaults, project_settings=project_settings,
                        work_items=work_items)
    return Snapshot[ChangeImpact](position=position, data=data)


CATALOG_QUERY = QueryDefinition(name="catalog", request=None, result=Catalog, handle=_catalog,
                                changed_by=_CATALOG_EVENTS, unchanged_by=_CATALOG_UNCHANGED_EVENTS)
CATALOG_DOCUMENT_QUERY = QueryDefinition(name="catalog.document", request=None, result=CatalogDocument,
                                         handle=_catalog_document, changed_by=_CATALOG_EVENTS,
                                         unchanged_by=_CATALOG_UNCHANGED_EVENTS)
CATALOG_CHANGE_IMPACT_QUERY = QueryDefinition(name="catalog.change_impact", request=ChangeImpactRequest,
                                              result=ChangeImpact, handle=_change_impact,
                                              # 结果里列出进行中的事项：事项开始与结束改变这份清单
                                              changed_by=(*_CATALOG_EVENTS,
                                                          EventType.RUN_CREATED, EventType.RUN_DONE,
                                                          EventType.RUN_FAILED, EventType.RUN_PAUSED,
                                                          ProjectEventType.WORK_ITEM_CREATED,
                                                          ProjectEventType.WORK_ITEM_START_FAILED))

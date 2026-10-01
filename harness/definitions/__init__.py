# 带版本的定义（ADR-0014）：随系统发布的 JSON 数据文件，放在本目录。
# 导入本模块时读取并校验全部定义文件：标准库解析 JSON（重复的键不合法），pydantic 类型校验每个文件的结构，
# 任何一项不合法都抛出 DefinitionError，写明文件与字段，导入本模块的程序因此无法启动。
# 定义的版本是全部定义文件内容的摘要：每个文件解析以后按原来的键顺序写成紧凑的 JSON，只改格式不改变版本。
# 运行中任何代码都不能修改定义：类型不可改写，映射是只读映射、列表是元组；请求等需要普通 JSON 结构的地方用 thaw
# 取得副本。项目部门设置中的 Prompt 与模型属于设置，不在这里。

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError,
                      field_validator, model_validator)

DEFINITIONS_DIR = Path(__file__).parent

# 定义中的编号：小写字母开头，由小写字母、数字与下划线组成
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


def _freeze(value: Any) -> Any:
    # 逐层把字典换成只读映射、把列表换成元组，键的顺序不变
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    # 定义中只读的 JSON 结构的普通副本（字典与列表），键的顺序不变
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


class DefinitionError(ValueError):
    # 定义不合法：每一项是（文件、字段、原因）
    def __init__(self, issues: list[tuple[str, str, str]]) -> None:
        self.issues = tuple(issues)
        super().__init__("定义不合法：\n" + "\n".join(
            f"  {file} {field}：{message}" for file, field, message in self.issues))


class UnknownStopReason(ValueError):
    # 停止原因不在定义的清单中
    def __init__(self, reason: str) -> None:
        super().__init__(f"stop reason {reason!r} is not in the stop reason definitions (stop_reasons.json)")
        self.reason = reason


class _Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _frozen(*fields: str) -> Any:
    # 这些字段校验以后逐层换成只读结构
    return field_validator(*fields, mode="after")(lambda cls, value: _freeze(value))


class Limits(_Definition):
    # 运行时间上限（秒）：达到时运行失败（time_limit）
    run_time_limit_sec: int = Field(gt=0)
    # 部门激活次数上限：达到时运行暂停（max_cycles）
    max_cycles: int = Field(gt=0)
    # 一次激活的模型步数上限，重试同样计入：达到时运行暂停（model_steps_exhausted）
    max_model_steps: int = Field(gt=0)
    # 一次模型调用的最多尝试次数，与重试的初始间隔、最大间隔（秒）
    max_provider_attempts: int = Field(gt=0)
    retry_initial_delay_sec: float = Field(gt=0, allow_inf_nan=False)
    retry_max_delay_sec: float = Field(gt=0, allow_inf_nan=False)
    # 连续没有调用工具的回复最多追加说明的次数，再出现一次运行暂停（no_tool_call）
    tool_call_required_limit: int = Field(gt=0)
    # 检查的时限（秒），也是登记命令没有写明时限时的默认值
    check_timeout_sec: int = Field(gt=0)
    # 一次工具结果的输出上限（字符），也是登记命令没有写明输出上限时的默认值
    tool_output_limit: int = Field(gt=0)
    # 登记命令时限的最大值（秒）
    command_timeout_max_sec: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> Limits:
        if self.retry_initial_delay_sec > self.retry_max_delay_sec:
            raise ValueError("retry_initial_delay_sec cannot exceed retry_max_delay_sec")
        if self.check_timeout_sec > self.command_timeout_max_sec:
            raise ValueError("check_timeout_sec cannot exceed command_timeout_max_sec")
        return self


class Department(_Definition):
    id: Identifier
    # 部门的角色：现在每个部门一个角色，角色编号与部门编号相同（事件的 role 字段记录部门）
    roles: tuple[Identifier, ...] = Field(min_length=1)


class OrganizationRules(_Definition):
    # 全体角色共同的规则文字，每次请求原样放进上下文：输入的处理、专业补全、协作规则
    input_handling: str = Field(min_length=1)
    professional_completion: str = Field(min_length=1)
    collaboration_rules: str = Field(min_length=1)


class Organization(_Definition):
    # 部门按这个顺序排列
    departments: tuple[Department, ...] = Field(min_length=1)
    rules: OrganizationRules


class Role(_Definition):
    # 内置默认 Prompt：项目部门设置没有写入时使用；用户在项目部门设置中写入的 Prompt 属于设置
    prompt: str = Field(min_length=1)
    # 可以使用的工具，按这个顺序提供给模型
    tools: tuple[Identifier, ...]
    # 可见范围：除全体角色共同的材料以外，本角色还能看到的材料
    visibility: tuple[Literal["current_delivery_spec", "prior_delivery", "qa_defects", "existing_structure"], ...]


class Tool(_Definition):
    # host：主机工具，由控制核心执行（现在只有提交类工具）；environment：环境工具，每次调用是一个动作，
    # 经过工具许可以后在执行环境中执行
    kind: Literal["host", "environment"]
    # 环境工具的动作类别：读取、写入、检查、登记的本地命令；许可规则按动作类别适用（写入要在工程计划的范围之内等）
    action: Literal["read", "write", "check", "command"] | None = None
    # 结果未知时这个动作能否重新执行（恢复契约第 4 节：「重新执行」只在契约声明可以重复的动作上提供）：
    # 只读、检查与不改变工作区外的命令可以重复，写入与有外部副作用的命令不能；主机工具不产生动作，不使用这一项
    repeatable: bool = False
    # 提交类主机工具提交的提案种类
    proposal: Identifier | None = None
    # 许可规则：因待处理指导被提前安排、只能回应指导的激活可以使用
    guidance_only: bool
    # 提供给模型的描述与参数（JSON Schema），原样放进请求
    description: str = Field(min_length=1)
    parameters: Mapping[str, Any]

    freeze_parameters = _frozen("parameters")

    @model_validator(mode="after")
    def _category(self) -> Tool:
        if self.kind == "environment" and (self.action is None or self.proposal is not None):
            raise ValueError("an environment tool requires action and has no proposal")
        if self.kind == "host" and (self.proposal is None or self.action is not None):
            raise ValueError("a host tool requires proposal and has no action")
        return self


class ProposalContract(_Definition):
    # 提供给模型的提案合同：提交工具、各提案种类的说明与注意事项，整份写成 JSON 放进请求
    submit_tools: tuple[Identifier, ...]
    kinds: Mapping[Identifier, Mapping[str, Any]]
    notes: tuple[str, ...]

    freeze_kinds = _frozen("kinds")


class ProposalContracts(_Definition):
    # 各角色自己的部分；shared 是每个角色都有的部分（协作请求、回应与指导的回应），接在角色自己的部分之后
    roles: Mapping[Identifier, ProposalContract]
    shared: ProposalContract

    freeze_roles = _frozen("roles")


Protocol = Literal["responses", "chat_completions", "messages"]


class ServicePreset(_Definition):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    auth: str = Field(min_length=1)
    # 按协议的请求基址，请求路径由各协议适配器拼接
    base_urls: Mapping[Protocol, str]
    models_url: str
    docs_url: str
    header_profile: str
    source: str
    notes: str

    freeze_base_urls = _frozen("base_urls")


class ServicePresets(_Definition):
    # 服务方案预置表（ADR-0003）：整张表的 revision 与来源随界面显示；每个服务方案一项
    revision: str = Field(min_length=1)
    source: str = Field(min_length=1)
    presets: tuple[ServicePreset, ...]


class StopReason(_Definition):
    # 运行以这个原因结束的方式：done 放行结束，paused 暂停，failed 失败
    outcome: Literal["done", "paused", "failed"]
    # 写进暂停或失败事件的处理说明；没有说明时为 null
    human_action: str | None


PhaseName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z_]*$")]


class DepartmentWork(_Definition):
    # 事项种类为某个部门写的说明：本种类内的角色说明、可以使用的工具与提案合同的注意事项。
    # 某个部门没有写明时，这个种类沿用 roles.json 中部门自己的角色说明与工具清单。
    prompt: str = Field(min_length=1)
    tools: tuple[Identifier, ...] = Field(min_length=1)
    notes: tuple[str, ...] = ()


class WorkItemKind(_Definition):
    # 事项种类（ADR-0014）：部门说明、工具清单与阶段迁移按种类定义
    label: str = Field(min_length=1)
    # 本种类的 run 进入完成状态时的停止原因，必须是 stop_reasons.json 中的编号
    stop_reason: Identifier
    # 各部门在本种类中的说明，键是部门编号
    departments: Mapping[Identifier, DepartmentWork] = Field(default_factory=dict)
    # 阶段迁移：提案种类 -> 接纳结果 -> 迁移的路径，每段是（来源阶段，目标阶段）；
    # 迁移本身仍由控制核心写成事件，定义只给出接纳以后应当走哪条路
    transitions: Mapping[Identifier, Mapping[Identifier, tuple[tuple[PhaseName, PhaseName], ...]]] = \
        Field(default_factory=dict)

    freeze_work_items = _frozen("departments", "transitions")

    @model_validator(mode="after")
    def _connected(self) -> "WorkItemKind":
        for kind, outcomes in self.transitions.items():
            for outcome, path in outcomes.items():
                if not path:
                    raise ValueError(f"transitions.{kind}.{outcome} 至少需要一段迁移")
                for previous, following in zip(path, path[1:]):
                    if previous[1] != following[0]:
                        raise ValueError(f"transitions.{kind}.{outcome} 的迁移不相接：{previous[1]} 与 {following[0]}")
        return self


class OverviewCategory(_Definition):
    # 仓库概况的一类：识别用的文件名模式与列出的条目上限，超出部分写明数量
    patterns: tuple[str, ...] = Field(min_length=1)
    limit: int = Field(gt=0)


class WorkItems(_Definition):
    # work_items.json：事项种类的清单与仓库概况的文件名模式表
    kinds: Mapping[Identifier, WorkItemKind] = Field(min_length=1)
    repository_overview: Mapping[Identifier, OverviewCategory] = Field(min_length=1)

    freeze_work_items = _frozen("kinds", "repository_overview")


class Definitions(_Definition):
    version: str
    organization: Organization
    # 角色定义，键是角色编号
    roles: Mapping[Identifier, Role]
    # 工具定义，键是工具名称
    tools: Mapping[Identifier, Tool]
    proposal_contracts: ProposalContracts
    limits: Limits
    # 停止原因的封闭清单，键是停止原因
    stop_reasons: Mapping[Identifier, StopReason]
    service_presets: ServicePresets
    # 事项种类与仓库概况的模式表，来自 work_items.json
    work_items: WorkItems

    freeze_collections = _frozen("roles", "tools", "stop_reasons", "work_items")

    @property
    def departments(self) -> tuple[str, ...]:
        return tuple(department.id for department in self.organization.departments)

    def role(self, department: str) -> Role:
        # 部门的角色（现在每个部门一个角色，编号与部门相同）
        return self.roles[department]

    def work_item(self, kind: str) -> WorkItemKind:
        # 事项种类的定义；普通事项没有部门说明与阶段迁移，沿用 roles.json
        definition = self.work_items.kinds.get(kind)
        if definition is None:
            raise ValueError(f"work item kind {kind!r} is not defined in work_items.json")
        return definition

    def department_work(self, department: str, kind: str) -> DepartmentWork | None:
        # 部门在本事项种类中的说明；没有定义时交回 None，由调用方使用 roles.json 的角色说明
        return self.work_item(kind).departments.get(department)

    def transitions(self, kind: str, proposal: str, result: str) -> tuple[tuple[str, str], ...]:
        # 事项种类中一次接纳的阶段迁移：种类没有写明这条路径时没有迁移
        return self.work_item(kind).transitions.get(proposal, {}).get(result, ())

    def tools_for(self, department: str, kind: str = "change") -> tuple[Identifier, ...]:
        # 部门在事项种类中的工具清单：种类写明时以它为准，未写明时是角色自己的清单
        work = self.department_work(department, kind)
        return work.tools if work is not None else self.roles[department].tools

    def proposal_contract(self, department: str, kind: str = "change") -> dict[str, Any]:
        # 部门在事项种类中的提案合同：角色自己的部分接上共同的部分，再按本种类的工具清单筛选，
        # 交回普通的 JSON 结构；建档中的部门因此看不到普通事项的提交工具与提案说明
        own, shared = self.proposal_contracts.roles[department], self.proposal_contracts.shared
        available = {self.tools[tool].proposal for tool in self.tools_for(department, kind)
                     if tool in self.tools and self.tools[tool].kind == "host" and self.tools[tool].proposal is not None}
        submit_tools = [tool for tool in [*own.submit_tools, *shared.submit_tools]
                        if self.tools[tool].proposal in available]
        kinds = {name: description for name, description in {**own.kinds, **shared.kinds}.items() if name in available}
        work = self.department_work(department, kind)
        # 建档等事项种类的角色说明写在种类里，普通事项的注意事项来自角色自己的部分
        own_notes = () if work is not None else own.notes
        notes = [*own_notes, *(work.notes if work is not None else ()), *shared.notes]
        return {"submit_tools": submit_tools, "kinds": thaw(kinds), "notes": notes}

    def stop_reason(self, reason: str) -> StopReason:
        # 停止原因只来自定义中的清单
        definition = self.stop_reasons.get(reason)
        if definition is None:
            raise UnknownStopReason(reason)
        return definition


# 定义文件与它在 Definitions 中的字段、类型
_FILES: dict[str, tuple[str, TypeAdapter[Any]]] = {
    "organization.json": ("organization", TypeAdapter(Organization)),
    "roles.json": ("roles", TypeAdapter(dict[Identifier, Role])),
    "tools.json": ("tools", TypeAdapter(dict[Identifier, Tool])),
    "proposal_contracts.json": ("proposal_contracts", TypeAdapter(ProposalContracts)),
    "limits.json": ("limits", TypeAdapter(Limits)),
    "stop_reasons.json": ("stop_reasons", TypeAdapter(dict[Identifier, StopReason])),
    "service_presets.json": ("service_presets", TypeAdapter(ServicePresets)),
    "work_items.json": ("work_items", TypeAdapter(WorkItems)),
}


class _DuplicateKey(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    for key in keys:
        if keys.count(key) > 1:
            raise _DuplicateKey(key)
    return dict(pairs)


def _location(loc: tuple[Any, ...]) -> str:
    text = ""
    for part in loc:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text or "（整个文件）"


def load_definitions(directory: Path = DEFINITIONS_DIR) -> Definitions:
    # 读取并校验 directory 中的全部定义文件；不合法时抛出 DefinitionError
    issues: list[tuple[str, str, str]] = []
    contents: dict[str, Any] = {}
    parts: dict[str, Any] = {}
    for file, (field, adapter) in _FILES.items():
        path = directory / file
        if not path.is_file():
            issues.append((file, "（整个文件）", "定义文件不存在"))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            issues.append((file, f"第 {exc.start} 个字节", "不是 UTF-8 编码的文本"))
            continue
        except OSError as exc:
            issues.append((file, "（整个文件）", f"无法读取：{exc.strerror or exc}"))
            continue
        try:
            contents[file] = json.loads(text, object_pairs_hook=_unique_keys)
        except json.JSONDecodeError as exc:
            issues.append((file, f"第 {exc.lineno} 行第 {exc.colno} 列", f"不是合法的 JSON：{exc.msg}"))
            continue
        except _DuplicateKey as exc:
            issues.append((file, exc.key, "重复的键"))
            continue
        try:
            parts[field] = adapter.validate_json(text, strict=True)
        except ValidationError as exc:
            issues.extend((file, _location(error["loc"]), error["msg"]) for error in exc.errors())
    if issues:
        raise DefinitionError(issues)
    issues = _references(parts)
    if issues:
        raise DefinitionError(issues)
    return Definitions(version=_version(contents), **parts)


def _references(parts: dict[str, Any]) -> list[tuple[str, str, str]]:
    # 类型以外的核对：部门与角色一一对应，角色与事项种类的工具都有定义且不重复，一种提案只由一个工具提交，
    # 提案合同与各事项种类可以使用的主机工具相符，事项种类的停止原因在清单中，服务方案的编号不重复
    issues: list[tuple[str, str, str]] = []
    organization: Organization = parts["organization"]
    roles: dict[str, Role] = parts["roles"]
    tools: dict[str, Tool] = parts["tools"]
    seen: set[str] = set()
    for index, department in enumerate(organization.departments):
        if department.id in seen:
            issues.append(("organization.json", f"departments[{index}].id", f"重复的部门 {department.id}"))
        seen.add(department.id)
        if department.roles != (department.id,):
            issues.append(("organization.json", f"departments[{index}].roles",
                           "每个部门现在只有一个角色，角色编号与部门编号相同"))
    members = {role for department in organization.departments for role in department.roles}
    for role in sorted(members - set(roles)):
        issues.append(("roles.json", role, "组织中的角色没有定义"))
    for role in sorted(set(roles) - members):
        issues.append(("roles.json", role, "角色不属于任何部门"))
    for name, role in roles.items():
        repeated = sorted({tool for tool in role.tools if role.tools.count(tool) > 1})
        if repeated:
            issues.append(("roles.json", f"{name}.tools", "重复的工具 " + "、".join(repeated)))
        for index, tool in enumerate(role.tools):
            if tool not in tools:
                issues.append(("roles.json", f"{name}.tools[{index}]", f"工具 {tool} 没有定义"))
    issues.extend(_work_item_references(parts["work_items"], organization, tools, parts["stop_reasons"]))
    submitters: dict[str, str] = {}
    for name, tool in tools.items():
        if tool.proposal is not None and tool.proposal in submitters:
            issues.append(("tools.json", f"{name}.proposal",
                           f"提案种类 {tool.proposal} 已经由 {submitters[tool.proposal]} 提交"))
        elif tool.proposal is not None:
            submitters[tool.proposal] = name
    issues.extend(_contract_references(parts["proposal_contracts"], roles, tools, parts["work_items"]))
    presets: ServicePresets = parts["service_presets"]
    identities = [preset.id for preset in presets.presets]
    for index, identity in enumerate(identities):
        if identities.index(identity) != index:
            issues.append(("service_presets.json", f"presets[{index}].id", f"重复的服务方案 {identity}"))
    return issues


def _work_item_references(work_items: WorkItems, organization: Organization, tools: dict[str, Tool],
                          stop_reasons: dict[str, StopReason]) -> list[tuple[str, str, str]]:
    # 事项种类：键是部门，工具都有定义且不重复，停止原因在清单中，阶段迁移的路径相接（类型已经核对）
    issues: list[tuple[str, str, str]] = []
    file = "work_items.json"
    members = {department.id for department in organization.departments}
    for name, kind in work_items.kinds.items():
        if kind.stop_reason not in stop_reasons:
            issues.append((file, f"kinds.{name}.stop_reason", f"停止原因 {kind.stop_reason} 没有定义"))
        for department in sorted(set(kind.departments) - members):
            issues.append((file, f"kinds.{name}.departments.{department}", "部门不属于任何组织"))
        for department, work in kind.departments.items():
            if department not in members:
                continue
            repeated = sorted({tool for tool in work.tools if work.tools.count(tool) > 1})
            if repeated:
                issues.append((file, f"kinds.{name}.departments.{department}.tools",
                               "重复的工具 " + "、".join(repeated)))
            for index, tool in enumerate(work.tools):
                if tool not in tools:
                    issues.append((file, f"kinds.{name}.departments.{department}.tools[{index}]",
                                   f"工具 {tool} 没有定义"))
    return issues


def _contract_references(contracts: ProposalContracts, roles: dict[str, Role], tools: dict[str, Tool],
                         work_items: WorkItems) -> list[tuple[str, str, str]]:
    # 每个角色都有提案合同；合同的提交工具正是这个角色在各事项种类中可以使用的主机工具合起来的范围
    # （普通事项取 roles.json 的清单，建档等事项取种类自己的清单），合同说明的提案种类正是这些工具提交的种类
    issues: list[tuple[str, str, str]] = []
    file = "proposal_contracts.json"
    for role in sorted(set(roles) - set(contracts.roles)):
        issues.append((file, f"roles.{role}", "角色没有提案合同"))
    for role in sorted(set(contracts.roles) - set(roles)):
        issues.append((file, f"roles.{role}", "提案合同不属于任何角色"))
    for name, own in contracts.roles.items():
        if name not in roles:
            continue
        usable = [tool for tool in roles[name].tools if tool in tools and tools[tool].kind == "host"]
        for kind, definition in work_items.kinds.items():
            work = definition.departments.get(name)
            if work is None:
                continue
            usable.extend(tool for tool in work.tools if tool in tools and tools[tool].kind == "host")
        host_tools = sorted(set(usable))
        submit_tools = [*own.submit_tools, *contracts.shared.submit_tools]
        if len(submit_tools) != len(set(submit_tools)) or sorted(submit_tools) != host_tools:
            issues.append((file, f"roles.{name}.submit_tools",
                           "与共同部分合起来必须恰好是各事项种类可以使用的主机工具：" + "、".join(host_tools)))
            continue
        kinds = {tools[tool].proposal for tool in submit_tools}
        described = set(own.kinds) | set(contracts.shared.kinds)
        overlap = sorted(set(own.kinds) & set(contracts.shared.kinds))
        if overlap:
            issues.append((file, f"roles.{name}.kinds", "与共同部分重复说明 " + "、".join(overlap)))
        elif described != kinds:
            issues.append((file, f"roles.{name}.kinds",
                           "与共同部分合起来必须恰好说明这些提案种类：" + "、".join(sorted(kinds))))
    return issues


def _version(contents: dict[str, Any]) -> str:
    canonical = json.dumps({file: contents[file] for file in sorted(contents)},
                           ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


DEFINITIONS = load_definitions()

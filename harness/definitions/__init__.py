# 带版本的定义（ADR-0014）：随系统发布的 JSON 数据文件，放在本目录。
# 导入本模块时读取并校验全部定义文件：标准库解析 JSON（重复的键不合法），pydantic 类型校验每个文件的结构，
# 任何一项不合法都抛出 DefinitionError，写明文件与字段，导入本模块的程序因此无法启动。
# 定义的版本是全部定义文件内容的摘要：每个文件解析以后按原来的键顺序写成紧凑的 JSON，只改格式不改变版本。
# 运行中任何代码都不修改定义：类型不可改写，可变的结构交回副本；项目部门设置中的 Prompt 与模型属于设置，不在这里。

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError, model_validator

DEFINITIONS_DIR = Path(__file__).parent

# 定义中的编号：小写字母开头，由小写字母、数字与下划线组成
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]


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


class Limits(_Definition):
    # 运行时间上限（秒）：达到时运行失败（time_limit）
    run_time_limit_sec: int = Field(gt=0)
    # 部门激活次数上限：达到时运行暂停（max_cycles）
    max_cycles: int = Field(gt=0)
    # 一次激活的模型步数上限，重试同样计入：达到时运行暂停（model_steps_exhausted）
    max_model_steps: int = Field(gt=0)
    # 一次模型调用的最多尝试次数，与重试的初始间隔、最大间隔（秒）
    max_provider_attempts: int = Field(gt=0)
    retry_initial_delay_sec: float = Field(gt=0)
    retry_max_delay_sec: float = Field(gt=0)
    # 连续没有调用工具的回复最多追加说明的次数，再出现一次运行暂停（no_tool_call）
    tool_call_required_limit: int = Field(gt=0)
    # 检查的时限（秒），也是登记命令没有写明时限时的默认值
    check_timeout_sec: int = Field(gt=0)
    # 一次工具结果的输出上限（字符），也是登记命令没有写明输出上限时的默认值
    tool_output_limit: int = Field(gt=0)
    # 登记命令时限的最大值（秒）
    command_timeout_max_sec: int = Field(gt=0)


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
    visibility: tuple[Literal["current_delivery_spec", "prior_delivery", "qa_defects"], ...]


class Tool(_Definition):
    # host：主机工具，由控制核心执行（现在只有提交类工具）；environment：环境工具，每次调用是一个动作，
    # 经过工具许可以后在执行环境中执行
    kind: Literal["host", "environment"]
    # 环境工具的动作类别：读取、写入、检查、登记的本地命令；许可规则按动作类别适用（写入要在工程计划的范围之内等）
    action: Literal["read", "write", "check", "command"] | None = None
    # 提交类主机工具提交的提案种类
    proposal: Identifier | None = None
    # 许可规则：因待处理指导被提前安排、只能回应指导的激活可以使用
    guidance_only: bool
    # 提供给模型的描述与参数（JSON Schema），原样放进请求
    description: str = Field(min_length=1)
    parameters: dict[str, Any]

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
    kinds: dict[Identifier, dict[str, Any]]
    notes: tuple[str, ...]


class ProposalContracts(_Definition):
    # 各角色自己的部分；shared 是每个角色都有的部分（协作请求、回应与指导的回应），接在角色自己的部分之后
    roles: dict[Identifier, ProposalContract]
    shared: ProposalContract


class StopReason(_Definition):
    # 运行以这个原因结束的方式：done 放行结束，paused 暂停，failed 失败
    outcome: Literal["done", "paused", "failed"]
    # 写进暂停或失败事件的处理说明；没有说明时为 null
    human_action: str | None


class Definitions(_Definition):
    version: str
    organization: Organization
    # 角色定义，键是角色编号
    roles: dict[Identifier, Role]
    # 工具定义，键是工具名称
    tools: dict[Identifier, Tool]
    proposal_contracts: ProposalContracts
    limits: Limits
    # 停止原因的封闭清单，键是停止原因
    stop_reasons: dict[Identifier, StopReason]

    @property
    def departments(self) -> tuple[str, ...]:
        return tuple(department.id for department in self.organization.departments)

    def role(self, department: str) -> Role:
        # 部门的角色（现在每个部门一个角色，编号与部门相同）
        return self.roles[department]

    def proposal_contract(self, department: str) -> dict[str, Any]:
        # 部门的角色的提案合同：角色自己的部分接上共同的部分；交回副本
        own, shared = self.proposal_contracts.roles[department], self.proposal_contracts.shared
        return copy.deepcopy({"submit_tools": [*own.submit_tools, *shared.submit_tools],
                              "kinds": {**own.kinds, **shared.kinds},
                              "notes": [*own.notes, *shared.notes]})

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
        text = path.read_text(encoding="utf-8")
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
    # 文件之间的引用：部门与角色一一对应，角色的工具都有定义且不重复，一种提案只由一个工具提交
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
    submitters: dict[str, str] = {}
    for name, tool in tools.items():
        if tool.proposal is not None and tool.proposal in submitters:
            issues.append(("tools.json", f"{name}.proposal",
                           f"提案种类 {tool.proposal} 已经由 {submitters[tool.proposal]} 提交"))
        elif tool.proposal is not None:
            submitters[tool.proposal] = name
    issues.extend(_contract_references(parts["proposal_contracts"], roles, tools))
    return issues


def _contract_references(contracts: ProposalContracts, roles: dict[str, Role],
                         tools: dict[str, Tool]) -> list[tuple[str, str, str]]:
    # 每个角色都有提案合同；合同的提交工具正是角色可以使用的主机工具，合同说明的提案种类正是这些工具提交的种类
    issues: list[tuple[str, str, str]] = []
    file = "proposal_contracts.json"
    for role in sorted(set(roles) - set(contracts.roles)):
        issues.append((file, f"roles.{role}", "角色没有提案合同"))
    for role in sorted(set(contracts.roles) - set(roles)):
        issues.append((file, f"roles.{role}", "提案合同不属于任何角色"))
    for name, own in contracts.roles.items():
        if name not in roles:
            continue
        submit_tools = [*own.submit_tools, *contracts.shared.submit_tools]
        host_tools = [tool for tool in roles[name].tools if tool in tools and tools[tool].kind == "host"]
        if len(submit_tools) != len(set(submit_tools)) or set(submit_tools) != set(host_tools):
            issues.append((file, f"roles.{name}.submit_tools",
                           "与共同部分合起来必须恰好是角色可以使用的主机工具：" + "、".join(host_tools)))
            continue
        kinds = {tools[tool].proposal for tool in submit_tools}
        described = set(own.kinds) | set(contracts.shared.kinds)
        if described != kinds:
            issues.append((file, f"roles.{name}.kinds",
                           "与共同部分合起来必须恰好说明这些提案种类：" + "、".join(sorted(kinds))))
    return issues


def _version(contents: dict[str, Any]) -> str:
    canonical = json.dumps({file: contents[file] for file in sorted(contents)},
                           ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


DEFINITIONS = load_definitions()

# 带版本的定义（总图第四节「定义」的缝）：随系统发布的 JSON 数据文件，放在本目录。
# 导入本模块时读取并校验全部定义文件：标准库解析 JSON（重复的键不合法），pydantic 类型校验每个文件的结构，
# 任何一项不合法都抛出 DefinitionError，写明文件与字段，导入本模块的程序因此无法启动。
# 定义的版本是全部定义文件内容的摘要：每个文件解析以后按原来的键顺序写成紧凑的 JSON，只改格式不改变版本。
# 运行中任何代码都不能修改定义：类型不可改写，映射是只读映射、列表是元组；请求等需要普通 JSON 结构的地方用 thaw
# 取得副本。项目部门设置中的 Prompt 与模型属于设置，不在这里。

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, get_args

from pydantic import (BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError,
                      field_validator, model_validator)

DEFINITIONS_DIR = Path(__file__).parent

# 定义中的编号：小写字母开头，由小写字母、数字与下划线组成
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]

# 环境工具的动作类别（tools.json 的 action 一栏）：读取、写入、检查、本地命令，以及网络取回、MCP 工具、
# 试用会话、浏览器与屏幕动作。动作合同（harness/actions.py）从这里取这一份取值；反方向不导入：
# 本模块不依赖动作合同，只导入本模块的 Provider 模块因此不会带上动作层（工单 #1275）
ActionKind = Literal["read", "write", "check", "command", "fetch", "mcp", "trial", "browser"]

# 核实方法（恢复契约第 4 节「结果未知时向哪里查」）：none 不查询外部结果，snapshot 以动作前后的公开树快照
# 核对实际效果，query 按尝试身份查询执行环境的动作记录、检查回执或试用会话记录
Verification = Literal["none", "snapshot", "query"]

# 每类动作的既定合同：（核实方法，取消能否确认停止）。None 表示这一类里随工具不同，必须由定义写明。
# 前四类是在这份合同之前就有的动作：读取与命令没有可以查询的外部结果，写入以树快照核实，检查的结果是检查回执、
# 经执行环境的查询取得；它们的定义可以省略这两项，按这里的值解释（恢复契约第 4 节「动作分类与处置」）
ESTABLISHED_CONTRACTS: dict[ActionKind, tuple[Verification | None, bool | None]] = {
    "read": ("none", True),
    "write": ("snapshot", True),
    "check": ("query", True),
    "command": ("none", True),
    "fetch": ("none", True),
    "mcp": ("none", None),
    "trial": (None, True),
    "browser": (None, True),
}

# 新增的四类动作：静态环境工具的定义里必须写明核实方法与能否取消；旧类别可以省略（网络取回与 MCP 设计说明第 18 节）
ADDED_KINDS: frozenset[str] = frozenset({"fetch", "mcp", "trial", "browser"})

# 取回工具（网络与 MCP 设计说明第 5.1、12.4 节）：部门按定义都有这两个工具；以关闭取回的启动参数
# （`--no-fetch`）运行的服务里，这个进程的部门都没有它们。清单只有这一份，工具定义留在 tools.json 里
# 不动：取舍发生在「给部门哪几个工具」这一步，工具许可、提案合同与请求里的工具清单都经 tools_for，
# 因此一处生效。评测运行器用它启动被测的 Yudao，两边都不联网（评测场景设计说明第 3 节）
FETCH_TOOLS: tuple[str, ...] = ("fetch_url", "read_external_source")

# 取回是否可用：进程范围的启动设置，默认可用；只在启动时由命令行改一次（工单 #1172）
_fetch_enabled = True


def configure_fetch(enabled: bool) -> None:
    """设置这个进程的取回是否可用（启动参数 `--no-fetch` 关掉取回）。"""
    global _fetch_enabled
    _fetch_enabled = bool(enabled)


def established_verification(kind: ActionKind) -> Verification | None:
    # 这一类动作的既定核实方法；None 表示这一类里随工具不同，必须写明
    return ESTABLISHED_CONTRACTS[kind][0]


def established_cancellable(kind: ActionKind) -> bool | None:
    # 这一类动作的既定取消合同；None 表示这一类里随工具不同，必须写明
    return ESTABLISHED_CONTRACTS[kind][1]


def check_contract(kind: ActionKind, verification: Verification | None, cancellable: bool | None) -> None:
    # 定义与动作请求里的两项元数据按类别的既定合同核对：写错的值立刻拒绝，新类别缺少这两项也拒绝
    expected_verification = established_verification(kind)
    if verification is not None and expected_verification is not None and verification != expected_verification:
        raise ValueError(f"a {kind} action is verified by {expected_verification!r}, not {verification!r}")
    expected_cancellable = established_cancellable(kind)
    if cancellable is not None and expected_cancellable is not None and cancellable != expected_cancellable:
        raise ValueError(f"cancelling a {kind} action can be confirmed: {expected_cancellable!r}, "
                         f"not {cancellable!r}")
    if kind in ADDED_KINDS and (verification is None or cancellable is None):
        raise ValueError(f"a {kind} action requires verification and cancellable")

# 规则登记中的条目名：由点号连接的小写标识，每一段与 Identifier 相同（设计说明第 2、8 节）。
# 前一段是领域，最后一段是条目；等待的时长上限与栏目上限因此写作 wait.desktop.max_sec、
# context.column_limit.catalog
RuleName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")]

# 可见范围的封闭词表（roles.json 的 visibility 一栏）：三条 roles.<部门>.visibility 参数的取值只能是其中的子集
# （工单 #1189）。词表只在这里写一份，参数的取值核对与角色定义共用它
VisibilityValue = Literal["current_delivery_spec", "prior_delivery", "qa_defects", "existing_structure"]
VISIBILITY_VALUES: frozenset[str] = frozenset(get_args(VisibilityValue))


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
    # 停止原因不在定义的清单中：内核的清单（stop_reasons.json）与组织定义所选的路由自己声明的
    # 结束原因（routings.json 的 end_reasons，工单 #861）都没有它
    def __init__(self, reason: str, routing: str | None = None) -> None:
        places = "the stop reason definitions (stop_reasons.json)"
        if routing is not None:
            places = f"{places} nor the end reasons the routing {routing!r} declares (routings.json end_reasons)"
        super().__init__(f"stop reason {reason!r} is not in {places}")
        self.reason = reason


class _Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _frozen(*fields: str) -> Any:
    # 这些字段校验以后逐层换成只读结构
    return field_validator(*fields, mode="after")(lambda cls, value: _freeze(value))


class Rule(_Definition):
    # 规则登记的一个条目（设计说明第 2 节）：在现值之外带四项记录与取值界限，
    # 全部条目合起来就是规则登记，不另建系统
    # 现值的类型：数值（int 或 float，取值与界限都是有限的数）、开关（bool）、
    # 可见范围（字符串列表，界限约束条目数）、档位名（字符串，界限给的是档位表的长度）
    value: int | float | bool | list[str] | str
    # 取值界限：上下界一对，value 必须落在界限之内；界限以内才是可调整的范围。
    # 数值与开关的比界限写法把值转成数来比，档位名按档位表的下标比较
    bounds: tuple[int | float, int | float]
    # kind：parameter 在界限以内由用户直接修改；structure 走候选、结构校验与用户批准
    kind: Literal["parameter", "structure"]
    # form：规则只能写成这三种形式之一，表达顺序的规则没有对应的形式
    form: Literal["permission", "boundary", "admission"]
    # 四项记录：拦截什么、花费多少、放松的证据、收紧的证据；缺任何一项都不算登记
    guards: str = Field(min_length=1)
    cost: str = Field(min_length=1)
    relax_when: str = Field(min_length=1)
    tighten_when: str = Field(min_length=1)
    # 来源：这条数值与它的理由写在哪一份文档或哪一条需求里
    origin: str = Field(min_length=1)

    @model_validator(mode="after")
    def _within_bounds(self) -> "Rule":
        # 现值与界限的类型不对由字段声明拒绝；这里核对现值落在界限之内
        low, high = self.bounds
        if low > high:
            raise ValueError(f"bounds {self.bounds!r} are not in increasing order")
        if isinstance(self.value, list):
            # 可见范围：界限约束的是条目数
            if not low <= len(self.value) <= high:
                raise ValueError(f"{len(self.value)} items are outside the bounds {self.bounds!r}")
            return self
        # 开关与档位名：界限给出的是所属类别的规模（0..1 表示开关，1..N 表示第 N 档）；
        # 数值约束实际数值。数值与界限都必须有限
        if not all(math.isfinite(number) for number in (low, high)):
            raise ValueError(f"bounds {self.bounds!r} must be finite")
        if isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
            if not math.isfinite(self.value):
                raise ValueError(f"value {self.value!r} must be finite")
            if not low <= self.value <= high:
                raise ValueError(f"value {self.value!r} is outside the bounds {self.bounds!r}")
        return self


class Department(_Definition):
    id: Identifier
    # 部门的中文名：等待说明、协作说明与模型提示按部门写给用户看，机器标识不直接出现在说明里。
    # 缺少或为空时由引用检查报错并写明部门（字段路径里只有序号）
    label: str = ""
    # 部门的角色：现在每个部门一个角色，角色编号与部门编号相同（事件的 role 字段记录部门）
    roles: tuple[Identifier, ...] = Field(min_length=1)
    # 本部门模型的建议能力（设计说明第 5.6 节）：取值来自模型访问定义的输入方式。
    # 建议能力只用于提醒，不阻止保存或请求；部门内的角色继承部门的建议能力
    suggested_capabilities: tuple[Literal["text", "image"], ...] = ()
    # 部门关注的成果（三部门的循环结构第 2 节）：关注的成果有了新版本、部门在等待工作时开始一轮工作。
    # 关注关系写在定义里，代码里只有一条通用规则
    watched: tuple[Literal["user_input", "guidance", "product_spec", "defect_record", "delivery",
                          "structure", "baseline_review"], ...] = ()


class OrganizationRules(_Definition):
    # 全体角色共同的规则文字，每次请求原样放进上下文：输入的处理、专业补全、协作规则
    input_handling: str = Field(min_length=1)
    professional_completion: str = Field(min_length=1)
    collaboration_rules: str = Field(min_length=1)


class Organization(_Definition):
    # 部门按这个顺序排列
    departments: tuple[Department, ...] = Field(min_length=1)
    # 路由实现的名称（骨架与应用设计说明第 5.1 节、工单 #825）：启动时按这个名称接上实现，
    # 名称必须是 routings.json 里登记的其中一个。默认是成果驱动
    routing: Identifier = "watched_outputs"
    rules: OrganizationRules


class Role(_Definition):
    # 内置默认 Prompt：项目部门设置没有写入时使用；用户在项目部门设置中写入的 Prompt 属于设置
    prompt: str = Field(min_length=1)
    # 可以使用的工具，按这个顺序提供给模型
    tools: tuple[Identifier, ...]
    # 可见范围：除全体角色共同的材料以外，本角色还能看到的材料
    visibility: tuple[VisibilityValue, ...]


class Tool(_Definition):
    # host：主机工具，由控制核心执行（现在只有提交类工具）；environment：环境工具，每次调用是一个动作，
    # 经过工具许可以后在执行环境中执行
    kind: Literal["host", "environment"]
    # 环境工具的动作类别：读取、写入、检查、本地命令与新增的四类（网络取回、MCP、试用会话、浏览器）；
    # 许可规则与执行环境的分派按动作类别适用，实际工具名仍供许可、提案与装配读取
    action: ActionKind | None = None
    # 这一类动作的核实方法与取消能否确认停止（恢复契约第 4 节）：旧类别可以省略，按类别的既定值解释；
    # 新增的类别必须写明（动作合同：harness/actions.py 的 check_contract）
    verification: Verification | None = None
    cancellable: bool | None = None
    # 提交类主机工具提交的提案种类
    proposal: Identifier | None = None
    # 声明这个工具需要图像输入（设计说明第 5.6 节与浏览器设计第 6.1 节）：调用目标不含图像时
    # 步骤驱动不在这次请求的工具定义中提供它。现在声明为需要的工具由 3.2D 的浏览器与 computer use 提供
    requires_image_input: bool = False
    # 提供给模型的描述与参数（JSON Schema），原样放进请求
    description: str = Field(min_length=1)
    parameters: Mapping[str, Any]

    freeze_parameters = _frozen("parameters")

    @model_validator(mode="after")
    def _category(self) -> Tool:
        if self.kind == "environment" and (self.action is None or self.proposal is not None):
            raise ValueError("an environment tool requires action and has no proposal")
        if self.kind == "host":
            if self.action is not None:
                raise ValueError("a host tool requires proposal and has no action")
            if self.verification is not None or self.cancellable is not None:
                raise ValueError("a host tool has no action metadata")
            return self
        check_contract(self.action, self.verification, self.cancellable)
        return self


class ProposalContract(_Definition):
    # 提供给模型的提案合同：提交工具、各提案种类的说明与注意事项，整份写成 JSON 放进请求
    submit_tools: tuple[Identifier, ...]
    kinds: Mapping[Identifier, Mapping[str, Any]]
    notes: tuple[str, ...]

    freeze_kinds = _frozen("kinds")


# 提案合同里的通用条件（设计说明第 5.5 节）：内核按合同核对，成果驱动写死的关系规则改写成这几种。
# 条件名与参数是封闭清单，装载定义时逐条核对；写错的条件在程序启动时以 DefinitionError 报出。
ConditionName = Literal["basis_current", "referenced_current", "check_receipts", "tree_matches",
                        "author_separation", "no_duplicate_content"]
# 条件读的成果：名称与运行状态投影里的当前版本一一对应（validation.py 的条件实现）
ArtifactName = Literal["product_spec", "delivery_spec", "contract", "structure", "snapshot", "product_decisions"]


class ConditionBinding(_Definition):
    # 绑定到当前版本的一处：field 是登记在回执或内容摘要上的字段名，target 是取当前版本的成果
    field: Identifier
    target: ArtifactName


class ReferencedField(_Definition):
    # 被引用的成果里要等于当前版本的字段，与不相等时的拒绝理由；错误指向哪一字段可以另写
    field: Identifier
    target: ArtifactName
    message: str = Field(min_length=1)
    error_field: Identifier | None = None


class ConditionFailure(_Definition):
    # 被引用的成果不存在时的错误字段与理由
    field: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ConditionNames(_Definition):
    # 列出的检查名在提案里的位置：field 是字符串列表，items + item 是对象列表里的名称字段
    field: Identifier | None = None
    items: Identifier | None = None
    item: Identifier | None = None
    # 名称去掉首尾空白以后再核对（两种提交工具的提案合同写法不同）
    trim: bool = False

    @model_validator(mode="after")
    def _shape(self) -> "ConditionNames":
        if self.field is not None and (self.items is not None or self.item is not None):
            raise ValueError("names names either a string list field or an object list with an item field")
        if self.field is None and (self.items is None or self.item is None):
            raise ValueError("names requires field, or items together with item")
        return self


# 每种条件用到哪些参数：装载时按它核对，多写的参数与缺少的参数各自报出（设计说明第 5.5 节）
_CONDITION_PARAMETERS: dict[str, frozenset[str]] = {
    "basis_current": frozenset({"field", "target"}),
    "referenced_current": frozenset({"artifact", "referenced", "missing"}),
    "check_receipts": frozenset({"department", "names", "bind", "activation", "message"}),
    "tree_matches": frozenset({"recorded_in", "field", "message", "missing"}),
    "author_separation": frozenset({"evaluated", "field", "message"}),
    "no_duplicate_content": frozenset({"collection", "content", "bind", "field", "message"}),
}
# 其中必须写出的参数：引用的成果一定存在时（例如有前置检查保证）可以不写 missing
_CONDITION_REQUIRED: dict[str, frozenset[str]] = {
    "basis_current": frozenset({"field", "target"}),
    "referenced_current": frozenset({"artifact", "referenced"}),
    "check_receipts": frozenset({"department", "names", "bind"}),
    "tree_matches": frozenset({"recorded_in", "field", "message"}),
    "author_separation": frozenset({"evaluated", "field", "message"}),
    "no_duplicate_content": frozenset({"collection", "content", "bind", "field", "message"}),
}


class ProposalCondition(_Definition):
    # 一条通用条件：条件名决定用到哪些参数，其余字段留空
    condition: ConditionName
    # basis_current：提案里声明依据版本的字段；tree_matches、author_separation：错误指向的字段；
    # no_duplicate_content：错误指向的提案字段
    field: str = ""
    # basis_current：依据的是哪一份成果
    target: ArtifactName | None = None
    # referenced_current：引用的是哪一份成果
    artifact: ArtifactName | None = None
    # referenced_current：被引用的成果里要求等于当前版本的字段
    referenced: tuple[ReferencedField, ...] = ()
    # referenced_current：被引用的成果不存在时怎么写错误
    missing: ConditionFailure | None = None
    # tree_matches：树摘要是哪一份成果记下的（建档时的快照或当前交付）
    recorded_in: Literal["snapshot", "delivery_spec"] | None = None
    # author_separation：评价的是哪一份成果
    evaluated: ArtifactName | None = None
    # check_receipts：列出的检查名在提案里的位置、在哪个部门取回执、回执绑定哪些当前版本、是否必须是这一轮
    names: ConditionNames | None = None
    department: Identifier | None = None
    bind: tuple[ConditionBinding, ...] = ()
    activation: bool = False
    # no_duplicate_content：与哪一份已接纳成果的历史比较，内容由哪些提案字段组成
    collection: ArtifactName | None = None
    content: tuple[str, ...] = ()
    # 不满足时的拒绝理由（check_receipts 里 {name} 换成检查名）
    message: str = ""

    @model_validator(mode="after")
    def _parameters(self) -> "ProposalCondition":
        parameters = _CONDITION_PARAMETERS[self.condition]
        provided = set(self.model_fields_set) - {"condition"}
        unknown = sorted(provided - parameters)
        if unknown:
            raise ValueError(f"{self.condition} does not take {', '.join(unknown)}")
        absent = sorted(_CONDITION_REQUIRED[self.condition] - provided)
        if absent:
            raise ValueError(f"{self.condition} requires {', '.join(absent)}")
        if "message" in parameters and not self.message.strip():
            raise ValueError("message must be a non-empty string")
        if "field" in parameters and not self.field.strip():
            raise ValueError("field must be a non-empty string")
        return self


class ProposalContracts(_Definition):
    # 各角色自己的部分；shared 是每个角色都有的部分（协作请求、回应与指导的回应），接在角色自己的部分之后
    roles: Mapping[Identifier, ProposalContract]
    shared: ProposalContract
    # 各提案种类的通用条件（设计说明第 5.5 节）：键是提案种类，值是按顺序核对的条件
    conditions: Mapping[Identifier, tuple[ProposalCondition, ...]] = Field(default_factory=dict)

    freeze_roles = _frozen("roles")
    freeze_conditions = _frozen("conditions")


Protocol = Literal["responses", "chat_completions", "messages"]


class ServicePreset(_Definition):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    auth: str = Field(min_length=1)
    # 获取模型列表与连接测试使用的认证方式（设计说明第 4.3 节）；默认协议：模型没有单独声明协议时预填（设计说明第 4.1 节）
    default_protocol: Protocol
    # 按协议的请求基址，请求路径由各协议适配器拼接
    base_urls: Mapping[Protocol, str]
    models_url: str
    docs_url: str
    header_profile: str
    source: str
    notes: str
    # 这个服务方案在 models.dev 中对应的 provider ID，模型能力表的提取脚本据此取材；
    # 「自定义」不使用预置表，在能力表中没有条目，不填这一项
    models_dev_id: str = ""

    freeze_base_urls = _frozen("base_urls")


class ServicePresets(_Definition):
    # 服务方案预置表（设计说明第 4.1 节）：整张表的 revision 与来源随界面显示；每个服务方案一项
    revision: str = Field(min_length=1)
    source: str = Field(min_length=1)
    presets: tuple[ServicePreset, ...]


class ModelCapability(_Definition):
    # 模型能力表中的一条：取自 models.dev 的快照，只保留设计说明第 4.1 节的字段。
    # models.dev 中 modalities 可以缺少，缺少时不记录输入方式与输出方式（空元组）
    model: str = Field(min_length=1)
    # 调用协议：取自这个模型的 provider.npm，没有单独声明时取服务商接入包。
    # 接入包没有对应的协议时为空（None）：容量与输入方式照常记录。
    protocol: Protocol | None = None
    # 模型自己声明的接入包（provider.npm）；没有声明时不记录（空串）。
    npm: str = ""
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    context_window: int | None = None
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
    tool_call: bool = False
    reasoning: bool = False


class CapabilityProvider(_Definition):
    # 服务商的接口地址与接入包；接口地址取自 models.dev，官方服务商由提取脚本的补充表补上。
    api: str = ""
    npm: str = Field(min_length=1)
    models: tuple[ModelCapability, ...]


class ModelCapabilities(_Definition):
    # 版本 2 增加全部服务商资料；presets 保留原服务方案的模型，旧文件按版本 1 读取。
    version: int = Field(default=1, ge=1, le=2)
    providers: Mapping[str, CapabilityProvider] = Field(default_factory=dict)
    presets: Mapping[str, tuple[ModelCapability, ...]]
    revision: str = Field(min_length=1)
    snapshot_date: str = Field(min_length=1)
    source: str = Field(min_length=1)
    # 来源文件（取回的 models.dev api.json，或用本地文件生成时的那份）的 SHA-256。
    source_sha256: str = ""

    freeze_presets = _frozen("presets")
    freeze_providers = _frozen("providers")


class StopReason(_Definition):
    # 停止原因的中文名：等待说明与事件说明按中文写，机器标识不直接出现在给用户看的文字里
    label: str = Field(min_length=1)
    # 运行以这个原因结束的方式：done 放行结束，paused 暂停，failed 失败
    outcome: Literal["done", "paused", "failed"]
    # 写进暂停或失败事件的处理说明；没有说明时为 null
    human_action: str | None


class DepartmentWork(_Definition):
    # 事项种类为某个部门写的说明：本种类内的角色说明、可以使用的工具与提案合同的注意事项。
    # 某个部门没有写明时，这个种类沿用 roles.json 中部门自己的角色说明与工具清单。
    prompt: str = Field(min_length=1)
    tools: tuple[Identifier, ...] = Field(min_length=1)
    notes: tuple[str, ...] = ()


class WorkItemKind(_Definition):
    # 事项种类（总图第四节「定义」的缝）：部门说明与工具清单按种类定义
    label: str = Field(min_length=1)
    # 本种类的 run 进入完成状态时的停止原因，必须是 stop_reasons.json 中的编号
    stop_reason: Identifier
    # 各部门在本种类中的说明，键是部门编号
    departments: Mapping[Identifier, DepartmentWork] = Field(default_factory=dict)

    freeze_work_items = _frozen("departments")


class OverviewCategory(_Definition):
    # 仓库概况的一类：识别用的文件名模式与列出的条目上限，超出部分写明数量
    patterns: tuple[str, ...] = Field(min_length=1)
    limit: int = Field(gt=0)


class WorkItems(_Definition):
    # work_items.json：事项种类的清单与仓库概况的文件名模式表
    kinds: Mapping[Identifier, WorkItemKind] = Field(min_length=1)
    repository_overview: Mapping[Identifier, OverviewCategory] = Field(min_length=1)

    freeze_work_items = _frozen("kinds", "repository_overview")


class RoutingEndReason(_Definition):
    # 路由自己的结束原因（设计说明第 5.4 节第 7 条）：属于那份路由定义版本的封闭清单，与内核的停止原因分开；
    # 内核的停止原因（上限、取消、升级等）对所有路由相同
    label: str = Field(min_length=1)
    outcome: Literal["done", "paused", "failed"]
    human_action: str | None = None


# 事件的主要事实从哪里来（应用层与接口层设计说明第 5.2 节「事件对象」）：确定规则的判定、决策模型的判定、
# 角色的陈述、主机的测量、用户。事件载荷不带来源字段，来源由 event_sources.json 按事件种类给出
SourceKind = Literal["rule", "decision_model", "role_statement", "host_measurement", "user"]


class EventSource(_Definition):
    # 一种事件的来源（工单 #396）：这条事件的主要事实的来源种类，以及按字段的覆盖。
    # 按字段的覆盖用于「主要事实与字段来源不同」的条目：事件里的测量值（已用时间、已用次数与步数、
    # 检查回执的结果）来自主机测量，其余字段按这条事件的主要事实
    source: SourceKind
    # 载荷字段名 → 这个字段的来源种类
    fields: Mapping[Identifier, SourceKind] = Field(default_factory=dict)



class Routing(_Definition):
    # 一种路由实现（routings.json，工单 #825），下面一段是它自己的一份定义（设计说明第 5.4 节第 2 条）：
    # 部门、成果种类、提议方式、路由自己的上限与结束原因。内核只核对这份定义的结构（字段、类型与非空），
    # 名称指向的内容由路由实现自己校验（routing_contract.select）；成果驱动的这一份按名称引用现有的定义文件，
    # 内容不搬动（工单 #861）。组织定义的 routing 写的名称就是这里的 id
    id: Identifier
    # 中文名，给用户看
    label: str = ""
    # 这一种路由是什么：开始一轮工作、一轮怎么结束、事项怎么结束的口径
    why: str = ""
    # 部门：按名称引用组织定义里的部门
    departments: tuple[Identifier, ...] = Field(min_length=1)
    # 成果种类：这种路由认得的正式成果，按名称引用提交类工具提交的提案种类
    outcome_kinds: tuple[Identifier, ...] = Field(min_length=1)
    # 提议方式：提交类工具的名称，按名称引用工具定义
    proposal_methods: tuple[Identifier, ...] = Field(min_length=1)
    # 路由自己的上限（例如任务数、打回次数）：数值，归路由，不进最小投影
    limits: Mapping[Identifier, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    # 路由自己的结束原因：编号到这个原因的中文名、结束方式与处理说明，封闭清单
    end_reasons: Mapping[Identifier, RoutingEndReason] = Field(min_length=1)

    freeze_routing = _frozen("limits", "end_reasons")


class Routings(_Definition):
    # routings.json：可用的路由实现是封闭的清单，组织定义的 routing 不在里面时加载失败
    routings: tuple[Routing, ...] = Field(min_length=1)

    freeze_routings = _frozen("routings")


class Definitions(_Definition):
    version: str
    organization: Organization
    # 角色定义，键是角色编号
    roles: Mapping[Identifier, Role]
    # 工具定义，键是工具名称
    tools: Mapping[Identifier, Tool]
    proposal_contracts: ProposalContracts
    # 规则登记（设计说明第 2 节）：键是条目名，全部条目合起来就是登记，不另建系统
    rules: Mapping[RuleName, Rule]
    # 停止原因的封闭清单，键是停止原因
    stop_reasons: Mapping[Identifier, StopReason]
    service_presets: ServicePresets
    # 模型能力表：models.dev 快照，带 revision、快照日期与来源，只用于预填（设计说明第 4.1 节）
    model_capabilities: ModelCapabilities
    # 事项种类与仓库概况的模式表，来自 work_items.json
    work_items: WorkItems
    # 可用的路由实现，来自 routings.json（工单 #825）
    routings: Routings
    # 事件种类的来源表，来自 event_sources.json（工单 #396）：键是事件种类
    event_sources: Mapping[Identifier, EventSource]

    freeze_collections = _frozen("roles", "tools", "stop_reasons", "work_items", "rules", "event_sources")

    @property
    def routing(self) -> str:
        # 路由实现的名称（组织定义里的 routing）：加载时核对过它在 routings.json 里
        return self.organization.routing

    @property
    def departments(self) -> tuple[str, ...]:
        return tuple(department.id for department in self.organization.departments)

    @property
    def department_labels(self) -> dict[str, str]:
        # 部门编号到中文名
        return {department.id: department.label for department in self.organization.departments}

    def role(self, department: str) -> Role:
        # 部门的角色（现在每个部门一个角色，编号与部门相同）
        return self.roles[department]

    def suggested_capabilities(self, department: str) -> tuple[str, ...]:
        # 部门的建议能力（设计说明第 5.6 节）：部门内的角色继承部门的建议能力
        for item in self.organization.departments:
            if item.id == department:
                return item.suggested_capabilities
        raise ValueError(f"unknown department {department!r}")

    def watched_outputs(self, department: str) -> tuple[str, ...]:
        """部门关注的成果（循环结构第 2 节）：关注关系写在组织定义里，代码里只有一条通用规则。"""
        for item in self.organization.departments:
            if item.id == department:
                return item.watched
        raise ValueError(f"unknown department {department!r}")

    def work_item(self, kind: str) -> WorkItemKind:
        # 事项种类的定义；普通事项没有部门说明，沿用 roles.json
        definition = self.work_items.kinds.get(kind)
        if definition is None:
            raise ValueError(f"work item kind {kind!r} is not defined in work_items.json")
        return definition

    def department_work(self, department: str, kind: str) -> DepartmentWork | None:
        # 部门在本事项种类中的说明；没有定义时交回 None，由调用方使用 roles.json 的角色说明
        return self.work_item(kind).departments.get(department)

    def tools_for(self, department: str, kind: str = "change") -> tuple[Identifier, ...]:
        # 部门在事项种类中的工具清单：种类写明时以它为准，未写明时是角色自己的清单。
        # 以关闭取回的启动参数运行时去掉取回工具（工单 #1172）：定义里留着工具本身，部门的清单里没有
        work = self.department_work(department, kind)
        names = work.tools if work is not None else self.roles[department].tools
        if not _fetch_enabled:
            return tuple(name for name in names if name not in FETCH_TOOLS)
        return names

    def proposal_contract(self, department: str, kind: str = "change") -> dict[str, Any]:
        # 部门在事项种类中的提案合同：角色自己的部分接上共同的部分，再按本种类的工具清单筛选，
        # 交回普通的 JSON 结构；建档中的部门因此看不到普通事项的提交工具与提案说明
        own, shared = self.proposal_contracts.roles[department], self.proposal_contracts.shared
        available = {self.tools[tool].proposal for tool in self.tools_for(department, kind)
                     if tool in self.tools and self.tools[tool].kind == "host" and self.tools[tool].proposal is not None}
        submit_tools = [tool for tool in [*own.submit_tools, *shared.submit_tools]
                        if self.tools[tool].proposal in available]
        kinds = {name: description for name, description in {**own.kinds, **shared.kinds}.items() if name in available}
        # 事实与解释的划分是主机装配时用的（工单 #554），不进模型看到的合同：模型按字段填写即可
        kinds = {name: {key: value for key, value in description.items() if key != "parts"}
                 for name, description in kinds.items()}
        work = self.department_work(department, kind)
        # 建档等事项种类的角色说明写在种类里，普通事项的注意事项来自角色自己的部分
        own_notes = () if work is not None else own.notes
        notes = [*own_notes, *(work.notes if work is not None else ()), *shared.notes]
        return {"submit_tools": submit_tools, "kinds": thaw(kinds), "notes": notes}

    def proposal_conditions(self, kind: str) -> tuple[ProposalCondition, ...]:
        # 一种提案的通用条件（设计说明第 5.5 节）：按合同里列出的顺序由内核核对；没有列出时没有通用条件
        return self.proposal_contracts.conditions.get(kind, ())

    def routing_definition(self) -> Routing:
        # 组织定义写明的路由自己的一份定义（设计说明第 5.4 节第 2 条）：加载时核对过它在 routings.json 里
        return next(item for item in self.routings.routings if item.id == self.routing)

    def stop_reason(self, reason: str) -> StopReason:
        # 停止原因来自定义中的清单；组织定义所选的路由自己声明的结束原因同样可以写入（设计说明第 5.4 节第 7 条）
        definition = self.stop_reasons.get(reason)
        if definition is not None:
            return definition
        declared = self.routing_definition().end_reasons.get(reason)
        if declared is None:
            raise UnknownStopReason(reason, self.routing)
        return StopReason(label=declared.label, outcome=declared.outcome, human_action=declared.human_action)

    def rule(self, name: str) -> Rule:
        # 规则登记中的一个条目；条目不在登记里直接报错，调用方不留回退取值
        definition = self.rules.get(name)
        if definition is None:
            raise ValueError(f"rule {name!r} is not in the rule registry (rules.json)")
        return definition

    def rule_value(self, name: str) -> Any:
        # 规则登记中一个条目的现值；条目不在登记里直接报错
        return self.rule(name).value

    def event_source(self, event_type: str) -> EventSource:
        # 一种事件的来源；种类不在表里直接报错，调用方不留回退取值（缺行由测试与加载核对）
        definition = self.event_sources.get(event_type)
        if definition is None:
            raise ValueError(
                f"event type {event_type!r} is not in the event source table (event_sources.json)")
        return definition


# 定义文件与它在 Definitions 中的字段、类型
_FILES: dict[str, tuple[str, TypeAdapter[Any]]] = {
    "organization.json": ("organization", TypeAdapter(Organization)),
    "roles.json": ("roles", TypeAdapter(dict[Identifier, Role])),
    "tools.json": ("tools", TypeAdapter(dict[Identifier, Tool])),
    "proposal_contracts.json": ("proposal_contracts", TypeAdapter(ProposalContracts)),
    "rules.json": ("rules", TypeAdapter(dict[RuleName, Rule])),
    "stop_reasons.json": ("stop_reasons", TypeAdapter(dict[Identifier, StopReason])),
    "service_presets.json": ("service_presets", TypeAdapter(ServicePresets)),
    "model_capabilities.json": ("model_capabilities", TypeAdapter(ModelCapabilities)),
    "work_items.json": ("work_items", TypeAdapter(WorkItems)),
    "routings.json": ("routings", TypeAdapter(Routings)),
    "event_sources.json": ("event_sources", TypeAdapter(dict[Identifier, EventSource])),
    # 生成的浏览器工具定义（浏览器与 computer use 设计说明第 4.1 节，工单 #147）：与 tools.json 合并成工具清单
    "browser_tools.json": ("browser_tools", TypeAdapter(dict[Identifier, Tool])),
}
# 可以不存在的定义文件：浏览器工具是随系统发布的一份生成定义，只用于测试的另一份完整定义里没有它时
# 这份定义就没有浏览器工具（发布的那一份由 harness/tests/test_browser_tool_definitions.py 核对确实加载得到）
_OPTIONAL_FILES = frozenset({"browser_tools.json"})


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
            if file in _OPTIONAL_FILES:
                # 可选的生成定义缺省为空：这份定义里没有那批工具
                parts[field] = {}
                continue
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
    # 浏览器工具是单独一份生成的文件：与手写的工具清单合并，同名工具即定义不合法（工单 #147）
    browser_tools = parts.pop("browser_tools", {})
    if "tools" in parts:
        merged = dict(parts["tools"])
        for name in browser_tools:
            if name in merged:
                issues.append(("browser_tools.json", name, "工具名与 tools.json 重复"))
        merged.update(browser_tools)
        parts["tools"] = merged
    if issues:
        raise DefinitionError(issues)
    issues = _references(parts)
    if issues:
        raise DefinitionError(issues)
    return Definitions(version=_version(contents), **parts)


def _references(parts: dict[str, Any]) -> list[tuple[str, str, str]]:
    # 类型以外的核对：部门与角色一一对应，角色与事项种类的工具都有定义且不重复，一种提案只由一个工具提交，
    # 提案合同与各事项种类可以使用的主机工具相符，事项种类的停止原因在清单中，服务方案的编号不重复，
    # 模型能力表与服务方案预置表互相对得上
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
        if not department.label:
            issues.append(("organization.json", f"departments[{index}].label", f"部门 {department.id} 缺少中文名"))
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
    issues.extend(_routing_references(organization, parts["routings"]))
    issues.extend(_rule_references(parts["rules"], roles))
    submitters: dict[str, str] = {}
    for name, tool in tools.items():
        if tool.proposal is not None and tool.proposal in submitters:
            issues.append(("tools.json", f"{name}.proposal",
                           f"提案种类 {tool.proposal} 已经由 {submitters[tool.proposal]} 提交"))
        elif tool.proposal is not None:
            submitters[tool.proposal] = name
    issues.extend(_contract_references(parts["proposal_contracts"], roles, tools, parts["work_items"]))
    issues.extend(_condition_references(parts["proposal_contracts"], organization))
    presets: ServicePresets = parts["service_presets"]
    identities = [preset.id for preset in presets.presets]
    for index, identity in enumerate(identities):
        if identities.index(identity) != index:
            issues.append(("service_presets.json", f"presets[{index}].id", f"重复的服务方案 {identity}"))
    capabilities: ModelCapabilities = parts["model_capabilities"]
    preset_ids = {preset.id for preset in presets.presets}
    for preset_id in sorted(set(capabilities.presets) - preset_ids):
        issues.append(("model_capabilities.json", f"presets.{preset_id}", "能力表中有预置表没有的服务方案"))
    for index, preset_id in enumerate(capabilities.presets):
        if preset_id not in preset_ids:
            continue
        models = [capability.model for capability in capabilities.presets[preset_id]]
        for position, model in enumerate(models):
            if models.index(model) != position:
                issues.append(("model_capabilities.json", f"presets.{preset_id}[{position}].model",
                               f"同一个服务方案中模型 {model} 重复"))
    for index, preset in enumerate(presets.presets):
        if preset.models_dev_id and preset.id not in capabilities.presets:
            issues.append(("model_capabilities.json", f"presets.{preset.id}",
                           f"预置表第 {index + 1} 项（{preset.id}）记录了 models_dev_id，能力表却缺少这个服务方案"))
        if capabilities.version == 2 and preset.models_dev_id:
            provider = capabilities.providers.get(preset.models_dev_id)
            if provider is None:
                issues.append(("model_capabilities.json", f"providers.{preset.models_dev_id}", "能力表缺少预置方案对应的服务商"))
            elif capabilities.presets.get(preset.id) != provider.models:
                issues.append(("model_capabilities.json", f"presets.{preset.id}", "服务方案与对应服务商的模型资料不一致"))
    for provider_id, provider in capabilities.providers.items():
        models = [entry.model for entry in provider.models]
        for position, model in enumerate(models):
            if models.index(model) != position:
                issues.append(("model_capabilities.json", f"providers.{provider_id}.models[{position}].model",
                               f"同一个服务商中模型 {model} 重复"))
    return issues


def _rule_references(rules: dict[str, Rule], roles: dict[str, Role]) -> list[tuple[str, str, str]]:
    # 规则登记：可见范围的条目与 roles.json 的现值相同，条目引用的部门都有角色定义
    issues: list[tuple[str, str, str]] = []
    file = "rules.json"
    for name in sorted(name for name in rules if name.startswith("roles.")):
        department = name.split(".")[1]
        if department not in roles:
            issues.append((file, name, "可见范围条目引用的部门没有角色定义"))
            continue
        if list(rules[name].value) != list(roles[department].visibility):
            issues.append((file, f"{name}.value", "可见范围的现值与 roles.json 不相同"))
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


def _routing_references(organization: Organization, routings: Routings) -> list[tuple[str, str, str]]:
    # 组织定义写明的路由实现必须在 routings.json 里（工单 #825）：不在里面时加载失败，
    # 写明是哪个字段、写了什么名称、有哪些可用的名称
    available = [item.id for item in routings.routings]
    if organization.routing in available:
        return []
    return [("organization.json", "routing",
             f"路由实现 {organization.routing} 不存在；可用的是：{'、'.join(available)}")]


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
        usable = [tool for tool in roles[name].tools if tool in tools and tools[tool].kind == "host" and tools[tool].proposal is not None]
        for kind, definition in work_items.kinds.items():
            work = definition.departments.get(name)
            if work is None:
                continue
            usable.extend(tool for tool in work.tools if tool in tools and tools[tool].kind == "host" and tools[tool].proposal is not None)
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


def _condition_references(contracts: ProposalContracts, organization: Organization) -> list[tuple[str, str, str]]:
    # 提案合同里的通用条件（设计说明第 5.5 节）：取回执的部门在组织里。条件的种类与提案字段
    # 与其他定义的关系不在这里核对：条件只在内核核对一种提案时按名字查，取不到时提交被拒绝，不会静默放过
    issues: list[tuple[str, str, str]] = []
    file = "proposal_contracts.json"
    members = {department.id for department in organization.departments}
    for kind, conditions in contracts.conditions.items():
        for index, condition in enumerate(conditions):
            if condition.department is not None and condition.department not in members:
                issues.append((file, f"conditions.{kind}[{index}].department",
                               f"部门 {condition.department} 不属于任何组织"))
    return issues


def _version(contents: dict[str, Any]) -> str:
    canonical = json.dumps({file: contents[file] for file in sorted(contents)},
                           ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


DEFINITIONS = load_definitions()

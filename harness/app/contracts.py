# 应用层的合同：客户端与服务之间交换的数据类型（设计说明第 3.1、4.1、5.2、5.6、6.1 节）。
# 只含可以序列化的数据；OpenAPI 与客户端的接口类型都由这里的 pydantic 类型生成。

from typing import Annotated, Any, Generic, Literal, TypeVar, Union, get_args

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, create_model

from .payloads import PAYLOADS, Department


class Contract(BaseModel):
    # 合同类型的共同设置：不接受合同之外的字段，创建以后不再修改
    model_config = ConfigDict(extra="forbid", frozen=True)


def _not_blank(value: str) -> str:
    # 与控制核心的判断相同：去掉首尾空白（str.strip）以后不能为空
    if not value.strip():
        raise ValueError("must contain a non-whitespace character")
    return value


# 至少含一个非空白字符的文字
Text = Annotated[str, StringConstraints(min_length=1), AfterValidator(_not_blank)]
# 命令身份：客户端生成的 UUID，小写的标准形式；响应与事件中原样出现
CommandId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]


# 拒绝原因的封闭清单（第 3.1 节）；每个命令在注册表中声明自己可能返回的原因
RejectionReason = Literal[
    "stale_base", "not_found", "already_exists", "project_archived", "work_item_in_progress", "run_terminal",
    "busy", "provider_unavailable", "catalog_invalid", "in_use", "decision_closed", "option_invalid",
    "not_allowed", "command_id_reused",
]
REJECTION_REASONS: tuple[str, ...] = get_args(RejectionReason)


# ---------------------------------------------------------------------------
# 命令


class CommandRequest(Contract):
    # 每个命令请求的公共字段：命令身份由客户端生成，重试使用同一个值；经接口提交时必须带身份。
    # 基准版本是用户作出操作时所依据对象的版本，新建类命令没有依据的对象，把 base_version 限定为空
    command_id: CommandId
    base_version: int | None = None


Refs = TypeVar("Refs", bound=BaseModel)


class Accepted(Contract, Generic[Refs]):
    # 命令被接受：事件已经追加。position 是这次命令最后一条事件的全局位置（没有追加事件时是接受时的日志末尾）；
    # refs 是新建对象的标识；duplicate 表示同一命令身份以前已经被接受，这次没有再执行
    command_id: CommandId
    position: int
    refs: Refs
    duplicate: bool


class Rejected(Contract):
    # 命令被拒绝：什么也没有写入，也没有登记命令身份；修改类命令版本不符时带当前版本
    command_id: CommandId
    reason: RejectionReason
    message: str
    current_version: int | None = None


class NoRefs(Contract):
    # 没有新建对象的命令的 refs
    pass


# ---------------------------------------------------------------------------
# 查询

Data = TypeVar("Data")


class Snapshot(Contract, Generic[Data]):
    # 查询的结果：position 是这份快照已经包含的最大全局位置，事件流从它之后续上
    position: int
    data: Data


# ---------------------------------------------------------------------------
# 事件流


class EventEnvelope(Contract):
    # 事件对象的公共字段（第 5.2 节）：全局位置、本连接上一条消息的位置、所属的流与对象、提出者与引起它的命令、
    # 应用层生成的一句中文说明；type 与 payload 由各事件种类确定
    position: int
    previous: int
    event_id: str
    at: AwareDatetime
    stream: str
    stream_version: int
    project_id: str | None
    work_item_id: str | None
    run_id: str | None
    department: Department | None
    role: str | None
    actor: str
    command_id: CommandId | None
    label: str


def _event_model(event_type: str, payload: Any) -> type[EventEnvelope]:
    name = "".join(part.capitalize() for part in event_type.split("_")) + "Event"
    return create_model(name, __base__=EventEnvelope, type=(Literal[event_type], ...), payload=(payload, ...))


EVENT_TYPES: tuple[str, ...] = tuple(PAYLOADS)
# 事件对象：以 type 区分的联合，每个事件种类带自己的载荷类型
EventObject = Annotated[Union[tuple(_event_model(name, payload) for name, payload in PAYLOADS.items())],
                        Field(discriminator="type")]


class OutputDelta(Contract):
    # 模型输出片段（第 5.6 节）：不写入事件日志，SSE 事件名为 delta，不带 id
    attempt_id: str
    logical_call_id: str
    project_id: str | None
    work_item_id: str | None
    run_id: str
    department: Department
    role: str | None
    channel: Literal["output", "reasoning", "tool_arguments"]
    offset: int
    text: str


# ---------------------------------------------------------------------------
# 能力清单


# 访问方式（第 6.2 节）：本机只能监听回环地址；局域网监听任意地址
AccessMode = Literal["local", "lan"]


class Deployment(Contract):
    # 日志身份在换数据目录时改变，本次启动的身份在服务重启时改变；合同摘要是 OpenAPI 文档的摘要；
    # 访问方式由启动设置给出（第 6.2 节）
    log_id: str
    boot_id: str
    version: str
    contract_digest: str
    access: AccessMode


class QueryCapability(Contract):
    name: str
    changed_by: list[str]


class CommandCapability(Contract):
    name: str
    reasons: list[RejectionReason]


class OverlayCapability(Contract):
    # 一个覆盖层：名称与它依赖的查询（设计说明第 6.1 节）；依赖的查询都已登记时才列出
    name: str
    queries: list[str]


class Capabilities(Contract):
    # 能力清单（第 6.1 节），由注册表生成：查询与改变它结果的事件种类、命令与可能的拒绝原因、
    # 当前部署会发出的决定种类、会写入的事件种类与可用的覆盖层
    deployment: Deployment
    queries: list[QueryCapability]
    commands: list[CommandCapability]
    decisions: list[str]
    event_types: list[str]
    overlays: list[OverlayCapability]

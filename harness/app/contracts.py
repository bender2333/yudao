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
    "not_allowed", "command_id_reused", "source_invalid", "out_of_bounds", "not_wired",
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


# 接口版本（第 6.1 节）：删除或改变已有的查询、命令、事件种类及其字段时提高；增加查询、命令、
# 事件种类或字段时不变。客户端在构建时记录生成类型所用的接口版本，与它核对。
# 版本 3：调用协议从连接移到模型访问定义（#382）：CatalogProvider 去掉 protocol，
# CatalogModel 增加 protocol，保存连接的命令在每个访问定义上带 protocol
# 版本 4：删除工作依据、调用记录、上下文清单与正式成果里的协作请求编号（#637）
# 版本 5：删除协作请求与协作回答的事件种类（#552）
# 版本 6：删除动作回执里的登记名与登记参数，动作列表显示命令原文（#658）
# 版本 7：删除 run_created 载荷里不再生效的事项级窗口字段（#669）
API_VERSION = 7


class Deployment(Contract):
    # 日志身份在换数据目录时改变，本次启动的身份在服务重启时改变；服务版本是发布版本号，接口版本
    # 由客户端构建时的接口版本核对；合同摘要是 OpenAPI 文档的摘要；访问方式由启动设置给出（第 6.2 节）
    log_id: str
    boot_id: str
    version: str
    # example 让接口类型的生成脚本读到这个版本，写进客户端构建时记录的接口版本
    api_version: int = Field(json_schema_extra={"example": API_VERSION})
    contract_digest: str
    access: AccessMode


class QueryCapability(Contract):
    name: str
    changed_by: list[str]
    # 是否接受第 4.1 节的 at（按位置读取，回放）；由注册表的 replayable 给出
    replayable: bool = False


class CommandCapability(Contract):
    name: str
    reasons: list[RejectionReason]


class OverlayCapability(Contract):
    # 一个覆盖层：名称与它依赖的查询（设计说明第 6.1 节）；依赖的查询都已登记时才列出
    name: str
    queries: list[str]


class StreamCapability(Contract):
    # 事件流的片段能力（第 6.1 节）：是否提供模型输出片段、连接可以使用的范围参数
    deltas: bool
    scopes: list[str]


class Capabilities(Contract):
    # 能力清单（第 6.1 节），由注册表生成：查询与改变它结果的事件种类、命令与可能的拒绝原因、
    # 当前部署会发出的决定种类、会写入的事件种类、可用的覆盖层与事件流的片段能力
    deployment: Deployment
    queries: list[QueryCapability]
    commands: list[CommandCapability]
    decisions: list[str]
    event_types: list[str]
    overlays: list[OverlayCapability]
    stream: StreamCapability

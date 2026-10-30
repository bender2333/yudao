# 应用层的入口：在控制核心之上执行已登记的命令与查询，生成能力清单。接口层与命令行都经过它（设计说明第 2 节）。
# 修改只经过控制核心的写入口与流程编排；查询只读取。只读的打开供命令行使用：以只读方式打开数据目录，
# 不写保存的投影，不需要进程锁。

from __future__ import annotations

import asyncio
from importlib.metadata import version
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..artifacts import ArtifactStore
from ..decisions import DECISION_KINDS
from ..deltas import DeltaPump
from ..event_store import EventStore, catalog_stream
from ..git_versions import GitVersionStore
from ..models import new_id, utc_now
from ..runtime import LoopSystem
from .catalog_commands import (
    CATALOG_CANDIDATES_COLLECT,
    CATALOG_CONNECT,
    CATALOG_CONNECTION_DELETE,
    CATALOG_CONNECTION_SAVE,
    CATALOG_CONNECTION_TEST,
    CATALOG_DEPARTMENT_DEFAULTS_SAVE,
    CATALOG_DOCUMENT_SAVE,
    CATALOG_MODEL_REMOVE,
    CATALOG_MODEL_SELECT,
    CATALOG_MODEL_TEST,
    CATALOG_RELOAD,
    CREDENTIAL_CLEAR_OVERRIDE,
    CREDENTIAL_REMOVE_PERSISTED,
    CREDENTIAL_SET,
)
from .catalog_queries import CATALOG_CHANGE_IMPACT_QUERY, CATALOG_DOCUMENT_QUERY, CATALOG_QUERY
from .commands import execute
from .contracts import API_VERSION, AccessMode, Accepted, Capabilities, CommandRequest, Deployment, Rejected, Snapshot
from .decision_commands import DECISION_ANSWER
from .decision_queries import DECISIONS_LIST
from .event_stream import EventScope, EventStream
from .home import HOME_AWAY_REPORT, HOME_MARK_SEEN
from .parameter_commands import PARAMETER_SET
from .project_commands import ONBOARDING_RESTART, PROJECT_CREATE, PROJECT_ONBOARD
from .project_and_work_item_commands import (
    DEPARTMENT_SETTINGS_SAVE,
    GUIDANCE_SEND,
    MATERIAL_RECORD,
    PROJECT_ARCHIVE,
    PROJECT_PIN,
    PROJECT_RENAME,
    PROJECT_RESTORE,
    PROJECT_SET_GOAL,
    SOURCE_DIRECTORY_SAVE,
    WRITEBACK_EXECUTE,
    WORK_ITEM_APPEND_INPUT,
    WORK_ITEM_CANCEL,
    WORK_ITEM_CREATE,
)
from .runtime_commands import RUNTIME_FORCE_UPGRADE, RUNTIME_START_DRAIN

from .system_queries import ATTEMPT_LIVE, SYSTEM_STATUS
from .project_queries import PROJECT_QUERIES
from .read_models import ReadModels
from .registry import Registry
from .rules_queries import RULES_REGISTRY


class ReadOnlyError(RuntimeError):
    # 只读的打开不支持的操作：命令、模型目录与就绪状态
    pass


class ReadOnlyCore:
    # 只读打开的控制核心：事件日志、工件与 Git 版本都以只读方式打开，不建立目录，也不写保存的投影
    read_only = True

    def __init__(self, data_dir: str | Path) -> None:
        # 数据目录可能以 8.3 短路径给出（工单 #250）：与可写打开一致，在这里解析一次再派生其余路径
        self.data_dir = Path(data_dir).absolute().resolve()
        self.store = EventStore(self.data_dir / "events.sqlite", read_only=True)
        self.artifacts = ArtifactStore(self.data_dir / "artifacts", read_only=True)
        self.git_versions = GitVersionStore(self.data_dir / "git", read_only=True)

    def close(self) -> None:
        self.store.close()

    def provider_status(self) -> dict[str, Any]:
        raise ReadOnlyError("provider status is not available in a read-only open")

    @property
    def home_seen(self) -> tuple[int, str] | None:
        # 用户查看过的全局位置与它的写入时间（工单 #127）；从未查看过时为空。
        # 从目录流保存的投影读取，只读打开也可以读取
        saved = self.store.projection(catalog_stream())
        if saved is None:
            return None
        from ..project_projection import catalog_handler
        state = catalog_handler().load(saved)
        if state.last_seen_position is None:
            return None
        return state.last_seen_position, state.last_seen_at

    @property
    def facade(self) -> Any:
        raise ReadOnlyError("the provider catalog is not available in a read-only open")


# 能力清单的 decisions 取自决定合同中的种类：当前部署会发出的决定请求
DEFAULT_REGISTRY = Registry(
    commands=[PROJECT_CREATE, PROJECT_ONBOARD, ONBOARDING_RESTART, PROJECT_RENAME, PROJECT_SET_GOAL, PROJECT_PIN, PROJECT_ARCHIVE, PROJECT_RESTORE,
              MATERIAL_RECORD, WORK_ITEM_CREATE, WORK_ITEM_APPEND_INPUT, WORK_ITEM_CANCEL, GUIDANCE_SEND,
              DEPARTMENT_SETTINGS_SAVE, SOURCE_DIRECTORY_SAVE, WRITEBACK_EXECUTE,
              DECISION_ANSWER, CATALOG_CONNECTION_SAVE, CATALOG_CONNECT, CATALOG_CONNECTION_DELETE,
              CATALOG_MODEL_REMOVE, CATALOG_MODEL_SELECT, CATALOG_DOCUMENT_SAVE, CATALOG_RELOAD, CATALOG_CANDIDATES_COLLECT,
              CATALOG_CONNECTION_TEST,
              CATALOG_MODEL_TEST, CATALOG_DEPARTMENT_DEFAULTS_SAVE, CREDENTIAL_SET, CREDENTIAL_CLEAR_OVERRIDE,
              CREDENTIAL_REMOVE_PERSISTED, RUNTIME_START_DRAIN, RUNTIME_FORCE_UPGRADE, HOME_MARK_SEEN,
              PARAMETER_SET],
    queries=[SYSTEM_STATUS, ATTEMPT_LIVE, DECISIONS_LIST, *PROJECT_QUERIES, CATALOG_QUERY,
             CATALOG_DOCUMENT_QUERY, CATALOG_CHANGE_IMPACT_QUERY, HOME_AWAY_REPORT, RULES_REGISTRY],
    decisions=tuple(DECISION_KINDS))


class Application:
    def __init__(self, system: LoopSystem | ReadOnlyCore, *, registry: Registry = DEFAULT_REGISTRY) -> None:
        self.system = system
        self.registry = registry
        # 本次启动的身份与时间：服务重启以后改变，客户端据此重新读取能力清单并重新同步
        self.boot_id = new_id("boot")
        self.started_at = utc_now()
        self.version = version("yudao-harness")
        # 应用层保存的读取模型：调用尝试表与流转记录。可写打开时保存在数据目录里，只读打开时在内存中重建
        path = None if system.read_only else Path(system.data_dir) / "read-models.sqlite"
        self.read_models = ReadModels(system.store, system.artifacts, path)
        # 输出片段通道的订阅方（第 5.6 节）：按 100 毫秒合并一次片段，转发给带 live=1 的连接，
        # 并保存每个进行中调用尝试已收到的文字供 attempt.live 查询。只读打开没有通道，也没有片段。
        # 订阅在应用层建立时登记：片段在调用进行中持续到达，客户端可能在调用开始以后才连上连接
        self.deltas: DeltaPump | None = None if system.read_only else DeltaPump(channel=system.deltas)
        if self.deltas is not None:
            self.deltas.start()
        # 需要以后以事件出现结果的命令（获取模型列表与两种测试）作为任务运行
        self._tasks: set[asyncio.Task[Any]] = set()
        # 打开的事件流连接：停止请求到达时先让它们干净结束，再退出（工单 #301）
        self._streams: set[EventStream] = set()

    @classmethod
    def open(cls, data_dir: str | Path, *, provider_config: Path | None, dotenv: Path) -> Application:
        # 服务进程使用的控制核心：读取模型目录与凭据文件，并在文件被外部修改时重新读取
        system = LoopSystem(data_dir, provider_config_path=provider_config, dotenv_path=dotenv)
        # 启动时目录修订号与最后一条 catalog_revised 不同则补写（设计说明第 10 节第 1 项）
        system.sync_catalog_revision(operation="startup")
        system.start_provider_watching()
        return cls(system)

    @classmethod
    def open_readonly(cls, data_dir: str | Path) -> Application:
        # 命令行使用的只读打开：不建立目录、不写保存的投影、不取进程锁；读取模型从事件重放重建
        return cls(ReadOnlyCore(data_dir))

    def close(self) -> None:
        if self.deltas is not None:
            self.deltas.stop()
        if not self.system.read_only:
            self.system.facade.selections.cancel_all()
        self.read_models.close()
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        self.system.close()

    def schedule(self, coroutine) -> asyncio.Task[Any]:
        # 结果以后以事件出现的命令：在服务的事件循环中作为任务运行
        task = asyncio.get_running_loop().create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def rebuild_read_models(self) -> None:
        # 删除调用尝试表与流转记录以后从事件重放重建；不调用模型与工具
        self.read_models.rebuild()

    async def command(self, name: str, request: CommandRequest, *, actor: str) -> Accepted | Rejected:
        if self.system.read_only:
            raise ReadOnlyError("commands are not available in a read-only open")
        result = await execute(self, self.registry.commands[name], request, actor=actor)
        if name == "parameter.set":
            self.system.facade.selections.wake()
        return result

    def query(self, name: str, request: BaseModel | None) -> Snapshot[Any]:
        definition = self.registry.queries[name]
        if (request is None) != (definition.request is None) or (
                request is not None and type(request) is not definition.request):
            raise TypeError(f"query {name} takes {definition.request}, not {type(request).__name__}")
        return definition.handle(self, request)

    def capabilities(self, contract_digest: str, *, access: AccessMode) -> Capabilities:
        return self.registry.capabilities(Deployment(
            log_id=self.system.store.log_id, boot_id=self.boot_id, version=self.version,
            api_version=API_VERSION, contract_digest=contract_digest, access=access,
        ))

    def open_event_stream(self, scope: EventScope, *, after: int, live: bool, **options: Any) -> EventStream:
        # 一个事件流连接（第 5 节）。带 live=1 时连接接收模型输出片段（订阅在应用层建立时已登记）。
        # options 透传批次大小、队列长度与检查点参数（默认值见 event_stream 模块）
        stream = EventStream(self.system.store, scope, after=after, live=live and self.deltas is not None,
                             pump=self.deltas,
                             selections=None if self.system.read_only else self.system.facade.selections.snapshot,
                             on_close=self._streams.discard, **options)
        self._streams.add(stream)
        return stream

    def close_event_streams(self) -> None:
        # 停止请求已经到达：让全部等待中的事件流连接干净结束；连接结束时从登记中移除
        for stream in list(self._streams):
            stream.close()

    def live_attempt(self, attempt_id: str) -> dict[str, str]:
        # 一个进行中调用尝试各通道已收到的文字（第 5.6 节）；没有进行中的尝试时为空
        if self.deltas is None:
            return {}
        return self.deltas.live_text(attempt_id)

    def home_seen(self) -> tuple[int, str] | None:
        # 用户查看过的全局位置与它的写入时间（工单 #127）；从未查看过时为空。
        # 保存在目录流（部署流）中，可写与只读打开都从投影读取
        return self.system.home_seen

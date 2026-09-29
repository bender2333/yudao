# 应用层的入口：在控制核心之上执行已登记的命令与查询，生成能力清单。接口层与命令行都经过它（设计说明第 2 节）。
# 修改只经过控制核心的写入口与流程编排；查询只读取。

from __future__ import annotations

import asyncio
from importlib.metadata import version
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..decisions import DECISION_KINDS
from ..models import new_id, utc_now
from ..runtime import LoopSystem
from .catalog_commands import (
    CATALOG_CANDIDATES_COLLECT,
    CATALOG_CONNECTION_DELETE,
    CATALOG_CONNECTION_SAVE,
    CATALOG_CONNECTION_TEST,
    CATALOG_DEPARTMENT_DEFAULTS_SAVE,
    CATALOG_DOCUMENT_SAVE,
    CATALOG_MODEL_TEST,
    CATALOG_RELOAD,
    CREDENTIAL_CLEAR_OVERRIDE,
    CREDENTIAL_REMOVE_PERSISTED,
    CREDENTIAL_SET,
)
from .catalog_queries import CATALOG_DOCUMENT_QUERY, CATALOG_QUERY
from .commands import execute
from .contracts import Accepted, Capabilities, CommandRequest, Deployment, Rejected, Snapshot
from .decision_commands import DECISION_ANSWER
from .decision_queries import DECISIONS_LIST
from .project_commands import PROJECT_CREATE
from .registry import Registry
from .system_queries import SYSTEM_STATUS

# 能力清单的 decisions 取自决定合同中的种类：当前部署会发出的决定请求
DEFAULT_REGISTRY = Registry(
    commands=[PROJECT_CREATE, DECISION_ANSWER, CATALOG_CONNECTION_SAVE, CATALOG_CONNECTION_DELETE,
              CATALOG_DOCUMENT_SAVE, CATALOG_RELOAD, CATALOG_CANDIDATES_COLLECT, CATALOG_CONNECTION_TEST,
              CATALOG_MODEL_TEST, CATALOG_DEPARTMENT_DEFAULTS_SAVE, CREDENTIAL_SET, CREDENTIAL_CLEAR_OVERRIDE,
              CREDENTIAL_REMOVE_PERSISTED],
    queries=[SYSTEM_STATUS, DECISIONS_LIST, CATALOG_QUERY, CATALOG_DOCUMENT_QUERY],
    decisions=tuple(DECISION_KINDS))


class Application:
    def __init__(self, system: LoopSystem, *, registry: Registry = DEFAULT_REGISTRY) -> None:
        self.system = system
        self.registry = registry
        # 本次启动的身份与时间：服务重启以后改变，客户端据此重新读取能力清单并重新同步
        self.boot_id = new_id("boot")
        self.started_at = utc_now()
        self.version = version("yudao-harness")
        # 需要以后以事件出现结果的命令（获取模型列表与两种测试）作为任务运行
        self._tasks: set[asyncio.Task[Any]] = set()

    @classmethod
    def open(cls, data_dir: str | Path, *, provider_config: Path | None, dotenv: Path) -> Application:
        # 服务进程使用的控制核心：读取模型目录与凭据文件，并在文件被外部修改时重新读取
        system = LoopSystem(data_dir, provider_config_path=provider_config, dotenv_path=dotenv)
        # 启动时目录修订号与最后一条 catalog_revised 不同则补写（设计说明第 10 节第 1 项）
        system.sync_catalog_revision(operation="startup")
        system.start_provider_watching()
        return cls(system)

    def close(self) -> None:
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

    async def command(self, name: str, request: CommandRequest, *, actor: str) -> Accepted | Rejected:
        return await execute(self, self.registry.commands[name], request, actor=actor)

    def query(self, name: str, request: BaseModel | None) -> Snapshot[Any]:
        definition = self.registry.queries[name]
        if (request is None) != (definition.request is None) or (
                request is not None and type(request) is not definition.request):
            raise TypeError(f"query {name} takes {definition.request}, not {type(request).__name__}")
        return definition.handle(self, request)

    def capabilities(self, contract_digest: str) -> Capabilities:
        return self.registry.capabilities(Deployment(
            log_id=self.system.store.log_id, boot_id=self.boot_id, version=self.version,
            contract_digest=contract_digest,
        ))

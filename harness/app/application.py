# 应用层的入口：在控制核心之上执行已登记的命令与查询，生成能力清单。接口层与命令行都经过它（设计说明第 2 节）。
# 修改只经过控制核心的写入口与流程编排；查询只读取。

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..decisions import DECISION_KINDS
from ..models import new_id, utc_now
from ..runtime import LoopSystem
from .commands import execute
from .contracts import AccessMode, Accepted, Capabilities, CommandRequest, Deployment, Rejected, Snapshot
from .decision_commands import DECISION_ANSWER
from .decision_queries import DECISIONS_LIST
from .project_commands import PROJECT_CREATE
from .registry import Registry
from .system_queries import SYSTEM_STATUS

# 能力清单的 decisions 取自决定合同中的种类：当前部署会发出的决定请求
DEFAULT_REGISTRY = Registry(commands=[PROJECT_CREATE, DECISION_ANSWER], queries=[SYSTEM_STATUS, DECISIONS_LIST],
                            decisions=tuple(DECISION_KINDS))


class Application:
    def __init__(self, system: LoopSystem, *, registry: Registry = DEFAULT_REGISTRY) -> None:
        self.system = system
        self.registry = registry
        # 本次启动的身份与时间：服务重启以后改变，客户端据此重新读取能力清单并重新同步
        self.boot_id = new_id("boot")
        self.started_at = utc_now()
        self.version = version("yudao-harness")

    @classmethod
    def open(cls, data_dir: str | Path, *, provider_config: Path | None, dotenv: Path) -> Application:
        # 服务进程使用的控制核心：读取模型目录与凭据文件，并在文件被外部修改时重新读取
        system = LoopSystem(data_dir, provider_config_path=provider_config, dotenv_path=dotenv)
        system.start_provider_watching()
        return cls(system)

    def close(self) -> None:
        self.system.close()

    async def command(self, name: str, request: CommandRequest, *, actor: str) -> Accepted | Rejected:
        return await execute(self, self.registry.commands[name], request, actor=actor)

    def query(self, name: str, request: BaseModel | None) -> Snapshot[Any]:
        definition = self.registry.queries[name]
        if (request is None) != (definition.request is None) or (
                request is not None and type(request) is not definition.request):
            raise TypeError(f"query {name} takes {definition.request}, not {type(request).__name__}")
        return definition.handle(self, request)

    def capabilities(self, contract_digest: str, *, access: AccessMode) -> Capabilities:
        return self.registry.capabilities(Deployment(
            log_id=self.system.store.log_id, boot_id=self.boot_id, version=self.version,
            contract_digest=contract_digest, access=access,
        ))

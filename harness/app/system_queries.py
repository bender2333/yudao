# 外壳的查询（设计说明第 4.3 节「外壳」）。

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .contracts import Contract, Snapshot
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application


class ProviderReadiness(Contract):
    # 能否新建事项：三个部门都能解析调用目标时可用；不可用时给出原因与说明
    available: bool
    reason: str
    message: str


class CatalogState(Contract):
    # 模型目录当前生效的修订号与最近一次重新读取的错误
    revision: int
    reload_error: str | None


class DrainStatus(Contract):
    # 排空状态（ADR-0019）：未排空、排空中或已排空可以升级；排空中的剩余 run 数与期间排队的事项数。
    # version 是排空状态的版本，命令的基准版本与它记录在一起
    state: Literal["idle", "draining", "ready"]
    version: int
    running_runs: int
    queued_work_items: int

class SystemStatus(Contract):
    # 部署身份（日志身份）、本次启动的身份与启动时间、Provider 就绪摘要、目录修订号与重读错误
    log_id: str
    boot_id: str
    started_at: AwareDatetime
    provider: ProviderReadiness
    catalog: CatalogState
    # 排空状态（ADR-0019，3.1）：未排空、排空中与剩余的 run 数、已排空可以升级
    drain: DrainStatus

def _system_status(application: Application, _request: None) -> Snapshot[SystemStatus]:
    system = application.system
    position = system.store.end_position()
    readiness = system.provider_status()
    catalog = system.facade.config_status()
    drain = system.drain
    return Snapshot[SystemStatus](position=position, data=SystemStatus(
        log_id=system.store.log_id, boot_id=application.boot_id, started_at=application.started_at,
        provider=ProviderReadiness(available=readiness["available"], reason=readiness["reason"],
                                   message=readiness["message"]),
        catalog=CatalogState(revision=catalog["revision"], reload_error=catalog["reload_error"]),
        drain=DrainStatus(state=drain.state, version=drain.version, running_runs=drain.running_runs,
                          queued_work_items=drain.queued_work_items),
    ))


SYSTEM_STATUS = QueryDefinition(name="system.status", request=None, result=SystemStatus, handle=_system_status)

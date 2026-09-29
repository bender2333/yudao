# 外壳的查询（设计说明第 4.3 节「外壳」）。

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import AwareDatetime

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


class SystemStatus(Contract):
    # 部署身份（日志身份）、本次启动的身份与启动时间、Provider 就绪摘要、目录修订号与重读错误
    log_id: str
    boot_id: str
    started_at: AwareDatetime
    provider: ProviderReadiness
    catalog: CatalogState


def _system_status(application: Application, _request: None) -> Snapshot[SystemStatus]:
    system = application.system
    position = system.store.end_position()
    readiness = system.provider_status()
    catalog = system.facade.config_status()
    return Snapshot[SystemStatus](position=position, data=SystemStatus(
        log_id=system.store.log_id, boot_id=application.boot_id, started_at=application.started_at,
        provider=ProviderReadiness(available=readiness["available"], reason=readiness["reason"],
                                   message=readiness["message"]),
        catalog=CatalogState(revision=catalog["revision"], reload_error=catalog["reload_error"]),
    ))


SYSTEM_STATUS = QueryDefinition(name="system.status", request=None, result=SystemStatus, handle=_system_status)

class LiveAttempt(Contract):
    # 进行中的调用尝试（设计说明第 5.6 节）：是否在进行中，以及各通道已收到的文字。
    # 调用尝试结束或失败以后 live 为假，客户端改用 run.attempt 的输出
    attempt_id: str
    live: bool
    channels: dict[str, str]

class LiveAttemptRequest(Contract):
    attempt_id: str

def _attempt_live(application: Application, request: LiveAttemptRequest) -> Snapshot[LiveAttempt]:
    channels = application.live_attempt(request.attempt_id)
    return Snapshot[LiveAttempt](
        position=application.system.store.end_position(),
        data=LiveAttempt(attempt_id=request.attempt_id, live=bool(channels), channels=channels),
    )

ATTEMPT_LIVE = QueryDefinition(
    name="attempt.live", request=LiveAttemptRequest, result=LiveAttempt, handle=_attempt_live, changed_by=(),
)

# 外壳的查询（设计说明第 4.3 节「外壳」）。

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime

from ..models import EventType
from ..projection import saved_decisions
from .contracts import Contract, Snapshot
from .registry import QueryDefinition
from .replay import ReplayRequest, catalog_through, check_position, decisions_through

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

class HomeStatus(Contract):
    # 首页顶部的状态项（设计说明第 4.3 节「系统首页」，工单 #127）：待你决定的数量与磁盘可用空间。
    # 结果未知的动作数（3.1）、离线的机器数（3.2C）、等待模型服务的 run 数与正在修复的故障数（Stage 4）
    # 由所属工作包在这里加入字段；没有来源的项不返回，不写成零
    waiting_decisions: int
    disk_free_bytes: int | None

class SystemStatus(Contract):
    # 部署身份（日志身份）、本次启动的身份与启动时间、Provider 就绪摘要、目录修订号与重读错误
    log_id: str
    boot_id: str
    started_at: AwareDatetime
    provider: ProviderReadiness
    catalog: CatalogState
    # 排空状态（ADR-0019，3.1）：未排空、排空中与剩余的 run 数、已排空可以升级
    drain: DrainStatus
    # 首页状态项（工单 #127）
    home: HomeStatus

# 这个文件用了 from __future__ import annotations，SystemStatus 引用 DrainStatus 时需要重建模型
SystemStatus.model_rebuild()

class SystemStatusRequest(ReplayRequest):
    # 可回放（设计说明第 4.1 节）：at 是全局位置，省略时读取现在的快照
    pass

def _system_status(application: Application, request: SystemStatusRequest) -> Snapshot[SystemStatus]:
    system = application.system
    store = system.store
    through = check_position(application, request.at)
    # 首页状态项里与时间有关的项按位置读取：待你决定的数量取到 at 为止的决定请求；磁盘可用空间是本机的实时值
    if through is None:
        _, decisions = saved_decisions(store)
        catalog = system.facade.config_status()
        position = store.end_position()
    else:
        decisions = decisions_through(store, through)
        catalog = _catalog_state(catalog_through(store, through))
        position = through
    readiness = system.provider_status()
    drain = system.drain
    return Snapshot[SystemStatus](position=position, data=SystemStatus(
        log_id=store.log_id, boot_id=application.boot_id, started_at=application.started_at,
        provider=ProviderReadiness(available=readiness["available"], reason=readiness["reason"],
                                   message=readiness["message"]),
        catalog=CatalogState(revision=catalog["revision"], reload_error=catalog["reload_error"]),
        drain=DrainStatus(state=drain.state, version=drain.version, running_runs=drain.running_runs,
                          queued_work_items=drain.queued_work_items),
        home=HomeStatus(
            waiting_decisions=sum(1 for item in decisions if item.status == "open"),
            disk_free_bytes=_disk_free_bytes(system.data_dir),
        ),
    ))

def _catalog_state(state) -> dict:
    # 从重放到 at 的目录投影取出查询需要的修订号与重读错误；重读错误只存在于当前生效的配置，按位置读取时为空
    return {"revision": state.revision, "reload_error": None}

def _disk_free_bytes(data_dir) -> int | None:
    # 控制主机上数据目录所在卷的可用空间；读取失败时为空（没有来源的项不返回，不写成零）
    try:
        return shutil.disk_usage(str(data_dir)).free
    except OSError:
        return None

SYSTEM_STATUS = QueryDefinition(
    name="system.status", request=SystemStatusRequest, result=SystemStatus, handle=_system_status,
    changed_by=(EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN),
    replayable=True,
)

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

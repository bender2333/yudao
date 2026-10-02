# 按位置读取（回放，设计说明第 4.1 节，工单 #127）：可回放的查询接受 at（全局位置），
# 在内存中从事件重放到该位置，不写入、不调用模型与工具。折叠是纯函数（projection.py 的 replay /
# project_events / replay_decisions 不读时钟、不读工件），喂给它 position <= at 的事件前缀就得到
# 该位置时的投影；前缀单调性由写入口在同一个事务中折叠保存的投影与 replay_check 保证。
# 宿主是只读打开（Application.open_readonly），不写保存的投影。

from __future__ import annotations

from ..event_store import Event, EventStore, ProjectEvent, catalog_stream
from ..models import CatalogEvent, CatalogProjection, DecisionRequest
from ..projection import apply_catalog_event, replay_decisions
from .contracts import Contract

class ReplayOutOfRange(Exception):
    # at 大于日志末尾：接口层把它转成 422（设计说明第 4.1 节）
    def __init__(self, at: int, end_position: int) -> None:
        super().__init__(f"position {at} is beyond the log end {end_position}")
        self.at = at
        self.end_position = end_position

class ReplayRequest(Contract):
    # 可回放查询的请求基类：at 是全局位置，省略时读取现在的快照（设计说明第 4.1 节）
    at: int | None = None

def check_position(application, at: int | None) -> int | None:
    # 核对 at 不超过日志末尾，返回它（省略时返回 None）；超过时抛出 ReplayOutOfRange，由接口层转成 422（第 4.1 节）
    if at is None:
        return None
    end = application.system.store.end_position()
    if at > end:
        raise ReplayOutOfRange(at, end)
    return at

def all_events_through(store: EventStore, through: int) -> list[Event | ProjectEvent]:
    # 位置不大于 through 的全部事件，按位置排列；决定请求可能写在 run 流或项目流中，这里取跨流的全部
    collected: list[Event | ProjectEvent] = []
    cursor = 0
    while True:
        batch = store.read(after=cursor, through=through, limit=1000)
        if not batch:
            break
        collected.extend(batch)
        cursor = batch[-1].position
    return collected

def decisions_through(store: EventStore, through: int) -> list[DecisionRequest]:
    # 从事件重放到 through 为止的全部决定请求，按请求的先后排列（工单 #127）。
    # 决定请求由所在流中的请求、回答与撤销事件折叠而成，与投影保存的规则相同
    events = all_events_through(store, through)
    decisions = replay_decisions(events)
    positions = {event.event_id: event.position for event in events}
    return sorted(decisions.values(), key=lambda item: positions[item.decision_id])

def catalog_through(store: EventStore, through: int) -> CatalogProjection:
    # 目录流（部署流）重放到 through 为止的投影：用于回放系统状态与用户查看的位置（工单 #127）
    events: list[CatalogEvent] = [event for event in store.stream_events(catalog_stream())
                                  if event.position <= through]
    state = CatalogProjection()
    for event in events:
        apply_catalog_event(state, event)
    return state

# 控制核心的输出片段通道（应用层与接口层设计说明第 5.6 节）：步骤驱动从模型调用合同的流式输出中
# 取得片段，发布到这条进程内的通道；应用层订阅它，每 100 毫秒合并一次并按范围转发给带 live=1 的连接。
# 片段不写入事件日志；调用尝试结束或失败以后由步骤驱动关闭它，订阅方据此释放已收到的文字。
#
# 通道只做进程内的分发：发布与关闭在步骤驱动所在的事件循环中同步完成，订阅方很快返回。

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from .providers.call import ModelDelta

@dataclass(frozen=True)
class DeltaScope:
    # 一个调用尝试的范围：片段转发按这些字段与连接的范围筛选比对
    attempt_id: str
    logical_call_id: str
    run_id: str
    department: str
    project_id: str | None = None
    work_item_id: str | None = None
    role: str | None = None

@dataclass(frozen=True)
class DeltaFragment:
    # 发布到通道的一段片段：范围、通道名、起始字数与文字
    scope: DeltaScope
    channel: str
    offset: int
    text: str

@dataclass(frozen=True)
class AttemptClosed:
    # 一次调用尝试结束或失败；订阅方据此释放这个调用尝试已收到的文字
    attempt_id: str

class DeltaChannel:
    # 进程内的输出片段通道：订阅方登记一个同步回调，发布方按调用尝试发布片段与关闭通知
    def __init__(self) -> None:
        self._listeners: list[Callable[[DeltaFragment | AttemptClosed], None]] = []

    def subscribe(self, listener: Callable[[DeltaFragment | AttemptClosed], None]) -> Callable[[], None]:
        # 登记订阅方，返回取消订阅的函数；回调在发布方的执行流程中同步调用，应当很快返回
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def publish(self, scope: DeltaScope, deltas: tuple[ModelDelta, ...]) -> None:
        # 一次调用尝试的一段流式输出里的全部片段，按通道与顺序发布
        for delta in deltas:
            if not delta.text:
                continue
            item = DeltaFragment(scope=scope, channel=delta.channel, offset=delta.offset, text=delta.text)
            for listener in list(self._listeners):
                listener(item)

    def close_attempt(self, attempt_id: str) -> None:
        # 调用尝试结束或失败：订阅方释放它保存的文字
        closed = AttemptClosed(attempt_id=attempt_id)
        for listener in list(self._listeners):
            listener(closed)

class DeltaBuffers:
    # 订阅方一侧的缓冲：按调用尝试与通道累计已收到的文字与下一段片段的位置。
    # 「已收到的文字」供 attempt.live 查询，片段按 offset 连续；重复或乱序的片段丢弃
    def __init__(self) -> None:
        self._channels: dict[str, dict[str, _ChannelText]] = {}

    def absorb(self, fragment: DeltaFragment) -> bool:
        # 收取一段片段；位置不连续（重复、乱序或跳到之后）时丢弃并返回 False
        channels = self._channels.setdefault(fragment.scope.attempt_id, {})
        current = channels.get(fragment.channel)
        if current is None:
            current = _ChannelText(text="", next_offset=0)
            channels[fragment.channel] = current
        if fragment.offset != current.next_offset:
            return False
        current.text += fragment.text
        current.next_offset = fragment.offset + len(fragment.text)
        return True

    def texts(self, attempt_id: str) -> dict[str, str]:
        # 这个调用尝试每个通道已收到的文字；没有时为空
        return {name: item.text for name, item in self._channels.get(attempt_id, {}).items()}

    def release(self, attempt_id: str) -> None:
        # 调用尝试结束或失败：释放它保存的文字
        self._channels.pop(attempt_id, None)

@dataclass
class _ChannelText:
    text: str = ""
    next_offset: int = 0

@dataclass
class DeltaPump:
    # 应用层的一侧：订阅通道，按 100 毫秒合并一次，交给转发函数；同时保存每个进行中调用尝试已收到的文字。
    # 片段分发给全部登记的连接（第 5.6 节：发给带 live=1、范围匹配的连接）：每个连接一份待发队列，
    # 先到的连接取走片段不影响其他连接；位置不连续的片段在合并时按缓冲丢弃，各连接收到同一份结果
    channel: DeltaChannel
    buffers: DeltaBuffers = field(default_factory=DeltaBuffers)
    _pending: list[DeltaFragment] = field(default_factory=list)
    # 进行中调用尝试已接受的片段，按尝试编号保存：后建立的连接订阅时种子进它的队列（第 5.6 节）
    _fragments: dict[str, list[DeltaFragment]] = field(default_factory=dict)
    _queues: list[deque[DeltaFragment]] = field(default_factory=list)
    _unsubscribe: Callable[[], None] | None = None

    def start(self) -> None:
        # 登记订阅：片段与关闭通知先落入缓冲，由 drain() 按合并周期处理
        if self._unsubscribe is None:
            self._unsubscribe = self.channel.subscribe(self._receive)

    def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._queues.clear()
        self._fragments.clear()

    def subscribe(self) -> deque[DeltaFragment]:
        # 一个 live 连接登记自己的待发队列，交出它；取消订阅用 unsubscribe(队列)。
        # 进行中调用尝试已接受的片段先种子进这个队列：订阅在片段之后建立的连接同样收到全部片段
        events: deque[DeltaFragment] = deque()
        for fragments in self._fragments.values():
            events.extend(fragments)
        self._queues.append(events)
        return events

    def unsubscribe(self, events: deque[DeltaFragment]) -> Callable[[], None]:
        # 取消一个连接的订阅：从分发清单移除队列；连接结束时调用
        def cancel() -> None:
            try:
                self._queues.remove(events)
            except ValueError:
                pass
        return cancel

    def _receive(self, item: DeltaFragment | AttemptClosed) -> None:
        if isinstance(item, DeltaFragment):
            self._pending.append(item)
        else:
            self.buffers.release(item.attempt_id)
            self._fragments.pop(item.attempt_id, None)

    def drain(self) -> list[DeltaFragment]:
        # 取出这一周期收到的片段：按调用尝试与通道累计，位置不连续的片段丢弃；
        # 被接受的片段进入每个登记连接的待发队列，并按调用尝试保留（供后来订阅的连接补齐）
        pending, self._pending = self._pending, []
        accepted: list[DeltaFragment] = []
        for fragment in pending:
            if self.buffers.absorb(fragment):
                accepted.append(fragment)
        for fragment in accepted:
            self._fragments.setdefault(fragment.scope.attempt_id, []).append(fragment)
        for events in self._queues:
            events.extend(accepted)
        return accepted

    def live_text(self, attempt_id: str) -> dict[str, str]:
        # 一个进行中调用尝试各通道已收到的文字
        return self.buffers.texts(attempt_id)

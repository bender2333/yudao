# 边界的核对（可信内核）：时间、轮次上限的判断。
# 纯函数：只读最小投影里的已用量与上限、调用方传入的已用秒数，不写事件、不读时钟、不持有进程状态。
# 轮次读的是最小投影的已激活次数（设计说明第 4 节，S1d 工单 #860），与事件里记下的轮次一致，
# 重启以后接着算；时钟的起点与事件写入仍在流程编排；
# 嵌套深度的计数在代码中尚不存在，子循环落地时在这里增加。

from __future__ import annotations

from .minimal_projection import MinimalProjection

# 达到上限时的停止原因：与 stop_reasons.json 的编号一致
CYCLE_BOUND = "max_cycles"
TIME_BOUND = "time_limit"


def activation_bound(projection: MinimalProjection, elapsed_sec: float) -> str | None:
    # 激活开始前与步骤结束后的上限判断：先轮次，后时间；都没有达到时为空
    if projection.used.activations >= projection.max_cycles:
        return CYCLE_BOUND
    if elapsed_sec >= projection.run_time_limit_sec:
        return TIME_BOUND
    return None


def time_used_up(projection: MinimalProjection, elapsed_sec: float) -> bool:
    # 安全节点的停止判断：运行时间是否用完
    return time_left_sec(projection, elapsed_sec) <= 0


def time_left_sec(projection: MinimalProjection, elapsed_sec: float) -> float:
    # 剩余运行时间（秒）：安全节点等待重试时最多再等这么久
    return projection.run_time_limit_sec - elapsed_sec


def time_limit_message(projection: MinimalProjection, elapsed_sec: float) -> str:
    # 运行时间用完的停止说明：与原来的措辞一致
    return f"run wall-clock time {int(elapsed_sec)}s exceeded limit of {projection.run_time_limit_sec}s"

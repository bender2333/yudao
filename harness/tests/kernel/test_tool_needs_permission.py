# 基础规则第三条的后半：每个工具开始事件之前有一条允许的许可记录。
#
# 工具许可（adjudication.tool_permission）本身不写入，只在内存里判断；它允许以后才开始执行，
# 许可留下的痕迹就是同一次调用里写在工具开始事件之前的那条记录。因此可断言的命题是：
# 每次工具开始都能在同一调用上找到允许它的许可判断——执行环境工具的记录是 tool_started，
# 主机提交类工具的记录在同一次调用里有提交类提案事件；被拒绝的调用没有工具开始事件，
# 只有带拒绝原因的调用结果或跳过记录。
#
# 对全部事件序列基准执行：基准是真实运行录下来的事件序列（44 个场景），
# 读静态文件，不重跑运行，属于单元层。

import json
from pathlib import Path

BASELINE_DIR = Path(__file__).resolve().parents[1] / "event_sequences"
# 计费用的 provider_usage 不是一次工具调用，没有许可判断，也没有工具开始事件
_ACCOUNTING = "provider_usage"
# 被拒绝的调用留下的痕迹：调用结果带原因，或调用被跳过
_STARTED = "tool_started"
_CALLED = "tool_called"
_SKIPPED = "tool_skipped"


def _baselines():
    files = sorted(BASELINE_DIR.glob("*.json"))
    assert files, f"{BASELINE_DIR} 里没有事件序列基准"
    return files


def _payload(event: dict) -> dict:
    return event.get("payload") or {}


def _call_key(payload: dict) -> tuple:
    # 同一次逻辑调用：部门激活、步骤与调用编号（工单 #307 的逻辑调用编号跨重试不变）
    return (payload.get("activation_id"), payload.get("step_id"), payload.get("id"))


def test_every_baseline_recorded_tool_calls():
    # 有些场景在第一次工具调用以前就结束（上下文超限、模型服务故障），没有工具开始事件是正常的；
    # 这里核对全部基线都录到事件，并且至少有一个场景确实被允许过工具调用
    started_any = False
    for path in _baselines():
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["events"], f"{path.name} 没有录到事件"
        started_any = started_any or _STARTED in {event["type"] for event in document["events"]}
    assert started_any, f"{BASELINE_DIR} 里没有一次被允许的工具调用"


def test_no_tool_call_outside_the_current_work_starts_without_a_permission():
    # 逐个事件顺序核对：任何没有工具开始事件的调用结果都必须是被拒绝（有原因）或被跳过，
    # 不存在「执行了却没有许可」的调用
    for path in _baselines():
        document = json.loads(path.read_text(encoding="utf-8"))
        started: set[tuple] = set()
        for event in document["events"]:
            payload = _payload(event)
            if event["type"] == _STARTED:
                started.add(_call_key(payload))
                continue
            if event["type"] == _SKIPPED:
                assert _call_key(payload) not in started, \
                    f"{path.name} 的 {_SKIPPED} {payload.get('name')!r} 之前已经有工具开始事件"
                continue
            if event["type"] != _CALLED or payload.get("name") == _ACCOUNTING:
                continue
            if _call_key(payload) in started:
                continue
            # 没有许可记录：只能是拒绝并说明原因，或者调用结果本身没有成功
            assert payload.get("error"), (
                f"{path.name} 的调用 {payload.get('name')!r}（调用编号 {payload.get('id')!r}）"
                f"之前没有工具开始事件，也没有拒绝原因；ok={payload.get('ok')!r}"
            )
            assert payload.get("ok") is False, \
                f"{path.name} 的调用 {payload.get('name')!r} 没有许可记录却报告成功"


def test_every_started_tool_call_reports_its_result():
    # 反向核对：每个工具开始都有对应的调用结果；执行中途被取消时是跳过记录
    for path in _baselines():
        document = json.loads(path.read_text(encoding="utf-8"))
        started: list[tuple] = []
        settled: set[tuple] = set()
        for event in document["events"]:
            payload = _payload(event)
            if event["type"] == _STARTED:
                started.append(_call_key(payload))
            elif event["type"] in (_CALLED, _SKIPPED) and payload.get("name") != _ACCOUNTING:
                key = _call_key(payload)
                if key in started:
                    settled.add(key)
        unsettled = [key for key in started if key not in settled]
        assert not unsettled, f"{path.name} 的工具开始没有对应的调用结果或跳过记录：{unsettled}"
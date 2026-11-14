# 跨多职能推进停止时保留上报的模型服务商与模型名（与适配器名分离）：调用 run_until_stop 驱动多职能循环，
# 登记为集成层（docs/design/test-pyramid.md「三层的定义」）；单次激活的实时观测与取消隔离见
# test_activation_accounting_module.py。守 R3（模型尝试与停止记录）。

import pytest

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, json_dumps
from harness.proposals import product_spec
from harness.providers.call import CallUsage, ModelResponse
from harness.runtime import LoopSystem


@pytest.mark.parametrize("reason", ["provider_error", "max_cycles"])
def test_stop_preserves_reported_vendor_and_model_separately_from_adapter(tmp_path, reason):
    response = ModelResponse(
        output=[{"id": "submit", "call_id": "submit", "type": "function_call", "name": "submit_product_spec",
                 "arguments": json_dumps(product_spec())}],
        usage=CallUsage(total_tokens=10000, reported=True),
        provider="actual-vendor", model="actual-model",
    )
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    failing = ProviderError("late failure")
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [response],
        "engineering": [failing],
        "quality": [failing],
    }))
    result = system.run_until_stop(system.create_run("echo", max_cycles=1 if reason == "max_cycles" else 8))
    assert result.stop_reason == reason
    assert result.provider == "actual-vendor"
    if reason == "provider_error":
        assert result.model is None and result.actual_model is None
    else:
        assert result.model == "actual-model" and result.actual_model == "actual-model"
    assert result.adapter == "fake"
    stop = next(event for event in system.store.list_events(result.run_id)
                if event.type in {EventType.RUN_FAILED, EventType.RUN_PAUSED})
    assert stop.provider == "actual-vendor"
    if reason == "provider_error":
        assert stop.model is None
    else:
        assert stop.model == "actual-model"

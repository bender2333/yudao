import json
from dataclasses import dataclass
from pathlib import Path

from harness.adapters.fake import FakeAdapter
from harness.context import ContextPart
from harness.engine import StepLimits
from harness.models import ArtifactRef, ContextManifest, json_dumps
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.providers.call import ModelCall, ModelResponse
from harness.runtime import LoopSystem

# 测试中的重试间隔缩短到毫秒级，其余参数与正式运行相同
FAST_RETRIES = StepLimits(retry_initial_delay_sec=0.01, retry_max_delay_sec=0.02)


def system_with(data_dir: Path, script) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(script))


def run_scripted(data_dir: Path, script, task: str = "build echo", **kwargs):
    system = system_with(data_dir, script)
    run_id = system.create_run(task, **kwargs)
    return system, system.run_until_stop(run_id)


def happy_script():
    return [
        product_spec(),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]


def list_files_turn(call: ModelCall) -> ModelResponse:
    # 三个部门都能调用的只读工具，用来构造不提交提案的工作步骤
    identity = f"list-{call.activation_id}-{call.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                  "name": "list_files", "arguments": json_dumps({})}])


@dataclass(frozen=True)
class RecordedContext:
    manifest: ContextManifest
    parts: list[ContextPart]


def recorded_context(system: LoopSystem, call: ModelCall) -> RecordedContext:
    # 一次模型调用的上下文清单与各段材料，取自主机的记录（投影中的清单与它引用的 context_parts 工件）
    manifest = next(item for item in system.project(call.run_id).manifests
                    if item.activation_id == call.activation_id and item.step_id == call.step_id)
    raw = json.loads(system.artifacts.get_for_run(call.run_id, ArtifactRef(**manifest.parts_ref)))
    return RecordedContext(manifest, [ContextPart(item["source"], item["version"], item["text"]) for item in raw])


def developer_text(call: ModelCall) -> str:
    # 工作请求的第一条消息：本步装配的全部部门材料
    return call.input_items[0]["content"]

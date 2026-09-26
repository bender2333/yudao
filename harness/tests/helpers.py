from pathlib import Path

from harness.adapters.base import ModelRequest, ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.models import json_dumps
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.runtime import LoopSystem


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


def list_files_turn(request: ModelRequest) -> ModelResponse:
    # 三个部门都能调用的只读工具，用来构造不提交提案的工作步骤
    identity = f"list-{request.activation_id}-{request.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                  "name": "list_files", "arguments": json_dumps({})}])

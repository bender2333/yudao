import json
from dataclasses import asdict

from harness.adapters.fake import FakeAdapter
from harness.assembly import ContextAssembly, ModelLimits, StepFrame, model_limits
from harness.models import ArtifactRef, EventType, RunProjection
from harness.projection import apply_event
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import list_files_turn
from harness.tests.test_compaction_engine import _runner


def test_model_limits_use_the_call_target_window_and_reserve_half_of_a_narrow_one():
    # 阈值只用本次调用目标的窗口；宽窗口保留 15%，窄窗口最多保留一半给回复
    assert model_limits(32000, 4096) == ModelLimits(32000, 4096, 4800)
    assert model_limits(8000, 4096) == ModelLimits(8000, 4096, 4000)
    assert model_limits(6000, 1000) == ModelLimits(6000, 1000, 1000)
    assert model_limits(32000, None) == ModelLimits(32000, None, 4800)


def _rebuild_recorded_steps(system, run_id):
    # 按记录下来的事件逐步重新装配：每个请求与它之前的事件重建的结果一致，每次压缩的检查点与重建的请求加上
    # 记录下来的回答生成的检查点一致
    def artifact(ref):
        return json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**ref)))

    events = system.store.list_events(run_id)
    assembly = ContextAssembly(system.artifacts)
    projection = RunProjection()
    frames, steps, outputs = {}, {}, {}
    counts = {"work": 0, "compaction": 0, "recorded": 0}
    for index, event in enumerate(events):
        payload = event.payload
        if event.type == EventType.DEPARTMENT_ACTIVATED:
            frames[payload["activation_id"]] = StepFrame(
                department=event.role, session_id=event.session_id, activation_id=payload["activation_id"],
                prompt=projection.department_prompts[event.role], guidance_only=payload["guidance_only"],
                effective_contract_hash=payload["effective_contract_hash"],
                engineering_plan_hash=payload["engineering_plan_hash"], input_version=payload["input_version"],
            )
        elif event.type == EventType.CONTEXT_ASSEMBLED:
            before = events[:index]
            limits = model_limits(payload["context_window"], payload["configured_max_output_tokens"])
            pinned = assembly.pin(projection, frames[payload["activation_id"]], limits,
                                  step_id=payload["step_id"], events=before, snapshot_hash=payload["snapshot_hash"])
            step = assembly.request(pinned, assembly.department_history(before, event.role))
            assert step.payload == artifact(payload["request_ref"])
            assert step.parts == artifact(payload["parts_ref"])
            assert step.context.manifest.digest == event.context_digest
            assert (step.input_token_estimate, step.output_reserve_tokens, step.admitted) == (
                payload["input_token_estimate"], payload["output_reserve_tokens"], payload["admitted"])
            steps[(payload["activation_id"], payload["step_id"])] = step
            counts[step.context.manifest.purpose] += 1
        elif event.type == EventType.MODEL_MESSAGE:
            outputs.setdefault((payload["activation_id"], payload["step_id"]), []).append(artifact(payload["message_ref"]))
        elif event.type == EventType.COMPACTION_RECORDED:
            key = (payload["activation_id"], payload["step_id"])
            result = assembly.finish_compaction(steps[key], outputs[key])
            assert asdict(result.checkpoint) == payload["checkpoint"]
            assert asdict(result.plan) == artifact(payload["plan_ref"])
            assert result.previous_compaction_event_id == payload["previous_compaction_event_id"]
            counts["recorded"] += 1
        apply_event(projection, event)
    return counts


def test_each_recorded_request_is_rebuilt_from_the_events_before_it(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([list_files_turn, product_spec()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    assert _rebuild_recorded_steps(system, run_id) == {"work": 2, "compaction": 0, "recorded": 0}


def test_compaction_requests_and_checkpoints_are_rebuilt_from_recorded_events(tmp_path):
    system, _, run_id, _ = _runner(tmp_path)
    assert system.activate_once(run_id).phase == "ENGINEERING"
    counts = _rebuild_recorded_steps(system, run_id)
    assert counts["compaction"] == counts["recorded"] > 1 and counts["work"] > 1

import json

from harness.adapters.fake import FakeAdapter
from harness.assembly import ContextAssembly, ModelLimits, StepFrame, model_limits
from harness.models import ArtifactRef, EventType, RunProjection
from harness.projection import apply_event
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import list_files_turn


def test_model_limits_keep_the_wide_window_and_reserve_half_of_a_narrow_one():
    # 有效窗口取 run 与调用目标中较小的一个；宽窗口保留 15%，窄窗口最多保留一半给回复
    assert model_limits(32000, 32000, 4096) == ModelLimits(32000, 4096, 4800)
    assert model_limits(32000, 8000, 4096) == ModelLimits(8000, 4096, 4000)
    assert model_limits(32000, 6000, 1000) == ModelLimits(6000, 1000, 1000)
    assert model_limits(32000) == ModelLimits(32000, None, 4800)


def test_each_recorded_request_is_rebuilt_from_the_events_before_it(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([list_files_turn, product_spec()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    events = system.store.list_events(run_id)
    activated = next(event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED)
    assembly = ContextAssembly(system.artifacts)
    projection = RunProjection()
    rebuilt = 0
    for index, event in enumerate(events):
        if event.type == EventType.DEPARTMENT_ACTIVATED:
            frame = StepFrame(
                department=event.role, session_id=event.session_id, activation_id=event.payload["activation_id"],
                prompt=projection.department_prompts[event.role], guidance_only=event.payload["guidance_only"],
                effective_contract_hash=event.payload["effective_contract_hash"],
                engineering_plan_hash=event.payload["engineering_plan_hash"],
                input_version=event.payload["input_version"],
            )
        if event.type == EventType.CONTEXT_ASSEMBLED:
            before = events[:index]
            pinned = assembly.pin(projection, frame, model_limits(projection.context_window),
                                  step_id=event.payload["step_id"], events=before,
                                  snapshot_hash=event.payload["snapshot_hash"])
            step = assembly.request(pinned, assembly.department_history(before, event.role))
            recorded = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["request_ref"])))
            parts = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["parts_ref"])))
            assert step.payload == recorded
            assert step.parts == parts
            assert step.context.manifest.digest == event.context_digest
            assert (step.input_token_estimate, step.output_reserve_tokens, step.admitted) == (
                event.payload["input_token_estimate"], event.payload["output_reserve_tokens"], event.payload["admitted"])
            rebuilt += 1
        apply_event(projection, event)
    assert activated.role == "product" and rebuilt == 2

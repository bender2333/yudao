from dataclasses import replace


from harness.context import ContextAssembler
from harness.definitions import DEFINITIONS
from harness.models import DEPARTMENTS, ArtifactRef, DepartmentPrompt, json_dumps
from harness.proposals import delivery_turn, product_spec
from harness.tests.helpers import quality_turns, recorded_context, run_scripted

def rework_script():
    # 质检的结论只有缺陷记录与放行（工单 #555）：缺陷记录之后工程返工一轮，候选记的是这次结论
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）：
    # 质检在交付到达以前还有一轮预测性探索，脚本项给足几轮
    return {
        "product": [product_spec()],
        "engineering": [
            delivery_turn(),
            delivery_turn(summary="handle empty input"),
        ],
        "quality": quality_turns("rework_engineering", "QA reported missing empty-input handling", defects=[
            {"severity": "minor", "summary": "Empty input needs review"},
        ]),
    }


def test_candidate_is_never_injected_into_department_context(tmp_path):
    rules = {department: DEFINITIONS.role(department).prompt for department in DEPARTMENTS}
    system, result = run_scripted(tmp_path, rework_script())
    candidate = result.lesson_candidates[0]
    for department in DEPARTMENTS:
        assembler = ContextAssembler()
        prompt = DepartmentPrompt(department, 0, DEFINITIONS.role(department).prompt,
                                  ArtifactRef(kind="department_prompt", content_hash="", path=""), "")
        args = {"department": department, "session_id": "test-session", "activation_id": "test-activation",
                "prompt": prompt}
        with_candidate = assembler.assemble(result, **args)
        without_candidate = assembler.assemble(replace(result, lesson_candidates=[]), **args)
        assert with_candidate == without_candidate
    for invocation in system.test_adapter.invocations:
        assert candidate.id not in json_dumps(invocation.input_items)
        assert candidate.suggestion not in json_dumps(invocation.input_items)
        injected = recorded_context(system, invocation).manifest.injected
        assert all("lesson" not in item.source for item in injected)
    assert {department: DEFINITIONS.role(department).prompt for department in DEPARTMENTS} == rules
    assert (system.test_adapter.name, system.test_adapter.model) == ("fake", "fake-script")



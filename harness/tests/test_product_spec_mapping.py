# 要求与验收标准的对应声明（工单 #1178；验证的独立性设计说明第 7 节第 1 点；总图第一节「产品」「独立的证据」；
# 第四节「定义」缝的字段只增）：产品交上来的合同里，每条要求都要在 requirement_mapping 里写出它对应的验收标准
# （AC<序号>，约定见 #151）；写不出验收标准的要求显式标注原因。收紧检查核对这张表，对应关系进入 ProductSpec、
# 上下文里的当前要求材料与接纳事件载荷；旧事件没有这个字段时为空，仍能读取。
#
# 层：模块层（一次或两次部门激活、事件库与工作区）。守 R1（边界：每条要求都要有说法）与 R2（提案合同与接纳载荷的交换字段）。

import json

from harness.adapters.fake import FakeAdapter, prompt_part
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec
from harness.runtime import LoopSystem

GOAL = "print the argument in uppercase"


def _system(tmp_path, script):
    return LoopSystem.for_testing(tmp_path, FakeAdapter(script))


def _rejections(system: LoopSystem, run_id: str) -> list[dict]:
    return [event.payload.get("errors", []) for event in system.writes.read(f"run:{run_id}").events()
            if event.type == EventType.PROPOSAL_REJECTED]


def _accepted(system: LoopSystem, run_id: str) -> dict:
    accepted = [event for event in system.writes.read(f"run:{run_id}").events()
                if event.type == EventType.SPEC_ACCEPTED]
    assert accepted, "这次提交没有被接纳"
    return accepted[-1].payload


def test_a_requirement_without_an_acceptance_criterion_is_rejected_naming_the_requirement(tmp_path):
    missing = product_spec(requirements=["a", "b"], acceptance=["x"],
                           requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]}])
    complete = product_spec(requirements=["a", "b"], acceptance=["x"],
                            requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]},
                                                 {"requirement": 2, "gap": "cannot be checked on this host yet"}])
    system = _system(tmp_path, {"product": [missing, complete]})
    run_id = system.create_run(GOAL)

    system.activate_once(run_id)
    [errors] = _rejections(system, run_id)
    assert any(error["field"] == "requirement_mapping" and "requirement 2" in error["message"] for error in errors), errors

    system.activate_once(run_id)
    assert _accepted(system, run_id)["requirement_mapping"] == [
        {"requirement": 1, "criteria": ["AC1"], "gap": None},
        {"requirement": 2, "criteria": [], "gap": "cannot be checked on this host yet"},
    ]
    system.close()


def test_a_requirement_with_neither_a_criterion_nor_a_gap_is_rejected(tmp_path):
    empty = product_spec(requirements=["only requirement"], acceptance=["x"],
                         requirement_mapping=[{"requirement": 1, "criteria": []}])
    complete = product_spec(requirements=["only requirement"], acceptance=["x"],
                            requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]}])
    system = _system(tmp_path, {"product": [empty, complete]})
    run_id = system.create_run(GOAL)

    system.activate_once(run_id)
    [errors] = _rejections(system, run_id)
    assert any(error["field"] == "requirement_mapping[0]"
               and "requirement 1 has no acceptance criterion and no gap note" in error["message"]
               for error in errors), errors

    system.activate_once(run_id)
    assert _accepted(system, run_id)["requirement_mapping"] == [
        {"requirement": 1, "criteria": ["AC1"], "gap": None}]
    system.close()


def test_a_criterion_reference_to_a_missing_acceptance_criterion_is_rejected(tmp_path):
    dangling = product_spec(requirements=["only requirement"], acceptance=["x"],
                            requirement_mapping=[{"requirement": 1, "criteria": ["AC2"]}])
    complete = product_spec(requirements=["only requirement"], acceptance=["x"],
                            requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]}])
    system = _system(tmp_path, {"product": [dangling, complete]})
    run_id = system.create_run(GOAL)

    system.activate_once(run_id)
    [errors] = _rejections(system, run_id)
    assert any(error["field"] == "requirement_mapping[0].criteria[0]"
               and "AC2 does not exist" in error["message"]
               and "1 acceptance criteria" in error["message"] for error in errors), errors

    system.activate_once(run_id)
    assert _accepted(system, run_id)["requirement_mapping"] == [
        {"requirement": 1, "criteria": ["AC1"], "gap": None}]
    system.close()


def test_a_requirement_with_both_a_criterion_and_a_gap_is_rejected(tmp_path):
    both = product_spec(requirements=["only requirement"], acceptance=["x"],
                        requirement_mapping=[{"requirement": 1, "criteria": ["AC1"], "gap": "also a reason"}])
    complete = product_spec(requirements=["only requirement"], acceptance=["x"],
                            requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]}])
    system = _system(tmp_path, {"product": [both, complete]})
    run_id = system.create_run(GOAL)

    system.activate_once(run_id)
    [errors] = _rejections(system, run_id)
    assert any(error["field"] == "requirement_mapping[0]"
               and "either acceptance criteria or a gap note" in error["message"] for error in errors), errors

    system.activate_once(run_id)
    assert _accepted(system, run_id)["requirement_mapping"] == [
        {"requirement": 1, "criteria": ["AC1"], "gap": None}]
    system.close()


def test_a_mapping_entry_for_a_requirement_that_does_not_exist_is_rejected(tmp_path):
    unknown = product_spec(requirements=["only requirement"], acceptance=["x"],
                           requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]},
                                                {"requirement": 2, "gap": "not a real requirement"}])
    complete = product_spec(requirements=["only requirement"], acceptance=["x"],
                            requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]}])
    system = _system(tmp_path, {"product": [unknown, complete]})
    run_id = system.create_run(GOAL)

    system.activate_once(run_id)
    [errors] = _rejections(system, run_id)
    assert any(error["field"] == "requirement_mapping" and "does not have: 2" in error["message"]
               for error in errors), errors
    system.activate_once(run_id)
    assert _accepted(system, run_id)["requirement_mapping"] == [
        {"requirement": 1, "criteria": ["AC1"], "gap": None}]
    system.close()


def test_listing_the_same_requirement_twice_is_rejected(tmp_path):
    repeated = product_spec(requirements=["one", "two"], acceptance=["x"],
                            requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]},
                                                 {"requirement": 1, "criteria": ["AC1"]}])
    complete = product_spec(requirements=["one", "two"], acceptance=["x"],
                            requirement_mapping=[{"requirement": 1, "criteria": ["AC1"]},
                                                 {"requirement": 2, "gap": "no host check yet"}])
    system = _system(tmp_path, {"product": [repeated, complete]})
    run_id = system.create_run(GOAL)

    system.activate_once(run_id)
    [errors] = _rejections(system, run_id)
    assert any(error["field"] == "requirement_mapping" and "lists the same requirement twice" in error["message"]
               for error in errors), errors
    system.activate_once(run_id)
    assert len(_accepted(system, run_id)["requirement_mapping"]) == 2
    system.close()


def test_the_mapping_reaches_the_product_spec_and_the_projection(tmp_path):
    mapping = [{"requirement": 1, "criteria": ["AC1", "AC2"]},
               {"requirement": 2, "gap": "only observable by a human, no host check yet"}]
    spec = product_spec(requirements=["print the argument", "feel pleasant to use"],
                        acceptance=["prints the argument", "exits with 0"], requirement_mapping=mapping)
    system = _system(tmp_path, {"product": [spec]})
    run_id = system.create_run(GOAL)

    projection = system.activate_once(run_id)

    assert projection.product_spec is not None
    assert projection.product_spec.requirement_mapping == [
        {"requirement": 1, "criteria": ["AC1", "AC2"], "gap": None},
        {"requirement": 2, "criteria": [], "gap": "only observable by a human, no host check yet"},
    ]
    assert len(_accepted(system, run_id)["requirement_mapping"]) == 2
    system.close()


def test_the_current_product_spec_material_carries_the_mapping(tmp_path):
    mapping = [{"requirement": 1, "criteria": ["AC1"]}]
    spec = product_spec(requirements=["print the argument"], acceptance=["prints the argument"],
                        requirement_mapping=mapping)
    adapter = FakeAdapter({"product": [spec], "engineering": [delivery_turn()]})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run(GOAL)
    system.activate_once(run_id)
    system.activate_once(run_id)

    engineering = [call for call in adapter.invocations if call.department == "engineering"]
    assert engineering, "工程没有被激活"
    material = json.loads(prompt_part(engineering[0], "current_product_spec"))
    assert material["requirement_mapping"] == [{"requirement": 1, "criteria": ["AC1"], "gap": None}]
    system.close()


def test_an_old_spec_without_the_mapping_still_reads_as_an_empty_mapping(tmp_path):
    # 旧事件没有这个字段：接纳载荷缺省为空，读取不失败（字段只增）
    from harness.app.payloads import SpecAcceptedPayload

    system = _system(tmp_path, {"product": [product_spec()]})
    run_id = system.create_run(GOAL)
    system.activate_once(run_id)
    legacy = dict(_accepted(system, run_id))
    legacy.pop("requirement_mapping", None)

    assert SpecAcceptedPayload.model_validate(legacy).requirement_mapping == []
    system.close()

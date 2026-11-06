# 可见范围的词表扩到交付说明的事实与解释（工单 #357；验证的独立性设计说明「共享的与隔开的」、「可见范围作为参数」；总图第四节「装配」缝）：
# 词表从「整份当前交付说明」扩到「交付事实」与「交付解释」两项，按事实与解释分开提供；工程保留整份
# current_delivery_spec，质检默认用隔离的一套（事实与解释），共享的一套再在它上面加既有结构、上一份交付与质检缺陷。
#
# 这个文件查三件事：
# 1. 封闭词表正好七项（工单 #1401 加了修改轮的常驻材料），各角色的取值都在词表里；
# 2. 质检的两套取值都能加载，共享的一套只在隔离的一套上加材料，条目数在规则的界限以内；
# 3. 装配按词表给材料：可见范围里只有事实这一项的角色看不到解释，连独立判断提交以后也看不到。
#
# 层：模块层（定义副本、真实存储与一次部门激活），守 R2（定义文件的格式与词表）与 R3（先判断后看解释的默认取值）。

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harness.adapters.fake import FakeAdapter, prompt_part
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, VISIBILITY_VALUES, load_definitions
from harness.proposals import delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import LoopSystem

# 质检的两套取值（docs/design/independent-verification.md「可见范围作为参数」）：现值的隔离一套，共享的一套在它上面加三项共享材料
ISOLATED = ("delivery_facts", "delivery_explanation")
SHARED = ("delivery_facts", "delivery_explanation", "existing_structure", "prior_delivery", "qa_defects")

DELIVERY_SUMMARY = "SECRET_DELIVERY_SUMMARY"


def test_the_visibility_vocabulary_is_the_seven_materials():
    # 守 R2：封闭词表是定义文件格式的一部分，各角色的取值只能是这七项
    assert VISIBILITY_VALUES == {"current_delivery_spec", "delivery_facts", "delivery_explanation",
                                 "existing_structure", "prior_delivery", "qa_defects", "prior_round"}
    for role, definition in DEFINITIONS.roles.items():
        assert set(definition.visibility) <= VISIBILITY_VALUES, role


@pytest.mark.parametrize("values", [ISOLATED, SHARED])
def test_both_quality_visibility_sets_load(tmp_path, values):
    # 守 R2 与验收：两套取值都是定义文件里能写的值，换一份定义就换一套，不修改代码
    directory = _copy(tmp_path)
    _set_quality_visibility(directory, values)
    loaded = load_definitions(directory)
    assert loaded.role("quality").visibility == values
    assert loaded.rule_value("roles.quality.visibility") == list(values)


def test_a_definition_with_the_old_quality_value_still_loads(tmp_path):
    # 守 R2（旧文件新版本能读）：词表只增，旧的取值（整份当前交付说明）还在词表里，此前写的角色定义照旧加载
    directory = _copy(tmp_path)
    _set_quality_visibility(directory, ("current_delivery_spec",))
    assert load_definitions(directory).role("quality").visibility == ("current_delivery_spec",)


def test_a_role_that_sees_only_the_facts_never_sees_the_explanation(tmp_path):
    # 守 R2 与 R3：可见范围的取值决定装配给什么。把质检的可见范围收成只有事实一项以后，交付的材料里有事实、
    # 没有解释，独立判断提交以后的请求里也没有；默认的一套由内核不变式的用例守着（先判断后看解释）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(_script()))
    system.set_parameter("roles.quality.visibility", ["delivery_facts"], reason="核对只有事实的取值",
                         modified_by="user:test")
    run_id = system.create_run("build echo")
    for _ in range(4):
        system.activate_once(run_id)
    assert system.project(run_id).status == "done"
    calls = [item for item in system.test_adapter.invocations if item.department == "quality"]
    assert len(calls) == 2, [item.session_id for item in calls]
    for call in calls:
        delivery = json.loads(prompt_part(call, "current_delivery_spec"))
        assert "src/echo.py" in delivery["files"] and delivery["check_names"] == ["smoke"]
        assert "summary" not in delivery and "known_risks" not in delivery
        assert DELIVERY_SUMMARY not in _text(call)


def _copy(tmp_path: Path) -> Path:
    # 发布的定义文件的一份副本，测试在副本上改质检的可见范围
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        shutil.copyfile(path, directory / path.name)
    return directory


def _set_quality_visibility(directory: Path, values) -> None:
    # 质检的取值写在两处：角色的取值与规则登记的同一项（加载时核对两处相同）
    roles = json.loads((directory / "roles.json").read_text(encoding="utf-8"))
    roles["quality"]["visibility"] = list(values)
    (directory / "roles.json").write_text(json.dumps(roles, ensure_ascii=False, indent=2), encoding="utf-8")
    rules = json.loads((directory / "rules.json").read_text(encoding="utf-8"))
    rules["roles.quality.visibility"]["value"] = list(values)
    (directory / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def _script() -> dict:
    # 产品提交 PRD、工程交付（交付说明带解释）、质检先交独立判断再核验放行
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(summary=DELIVERY_SUMMARY)],
        "quality": [judgement_turn(), review_turn("release", "the judgement stands")],
    }


def _text(call) -> str:
    parts: list[str] = []
    for item in call.input_items:
        if isinstance(item.get("content"), str):
            parts.append(item["content"])
        elif isinstance(item.get("output"), str):
            parts.append(item["output"])
    return "\n".join(parts)

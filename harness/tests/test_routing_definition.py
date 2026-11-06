# 路由自己的一份定义与它自己的结束原因（工单 #861；骨架与应用设计说明「路由契约」、「其他路由：骨架要满足的条件」第 2、7 条）。
#
# 守的是 R2：定义文件的格式——routings.json 里一种路由自己的一份定义（部门、成果种类、提议方式、路由自己的
# 上限与结束原因）由内核核对结构，按名称指向的内容由路由实现自己校验；以及 R3：路由声明的结束原因可以
# 作为事项的停止原因写入，既没有声明、也不在内核清单里的被拒绝并写明原因。
#
# 复制发布的定义文件到临时目录再改，加载定义、写事件，属于模块层（docs/design/skeleton-and-application.md「两层的判据」：临时目录与事件库）。

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from harness import models, routing_contract
from harness.definitions import DEFINITIONS_DIR, DefinitionError, load_definitions
from harness.watched_outputs import ROUTING


def _copy(tmp_path: Path) -> Path:
    # 发布的定义文件的一份副本，测试在副本上修改
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        shutil.copyfile(path, directory / path.name)
    return directory


def _read(directory: Path, name: str):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def _write(directory: Path, name: str, content) -> None:
    (directory / name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def _routing(directory: Path) -> dict:
    # 副本里成果驱动那个路由自己的定义
    return _read(directory, "routings.json")["routings"][0]


def _rewrite_routing(directory: Path, entry: dict) -> Path:
    _write(directory, "routings.json", {"routings": [entry]})
    return directory


def test_the_kernel_loads_a_routing_definition_with_names_and_structure_only(tmp_path):
    # R2：内核只核对名称与结构（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」中「每种路由有自己的一份定义」）：名称指向的东西都不存在也照常加载，
    # 内容由路由实现自己校验
    directory = _copy(tmp_path)
    entry = _routing(directory)
    entry.pop("outcomes", None)  # 旧写法：成果种类直接列在路由那一段里（字段只增，工单 #1456）
    entry.update({
        "departments": ["risks"], "outcome_kinds": ["audit_note"], "proposal_methods": ["submit_audit_note"],
        "limits": {"max_tasks": 3},
        "end_reasons": {"queue_empty": {"label": "任务池是空的", "outcome": "paused", "human_action": None}},
    })
    loaded = load_definitions(_rewrite_routing(directory, entry))
    definition = loaded.routing_definition()
    assert (definition.id, definition.departments, definition.outcome_kinds) == (
        "watched_outputs", ("risks",), ("audit_note",))
    assert dict(definition.limits) == {"max_tasks": 3}
    # 它自己声明的结束原因按定义查得到，与内核的清单分开
    assert loaded.stop_reason("queue_empty").outcome == "paused"
    assert loaded.stop_reason("queue_empty").label == "任务池是空的"


@pytest.mark.parametrize(("change", "field"), [
    (lambda entry: {**{k: v for k, v in entry.items() if k != "outcomes"}, "outcome_kinds": "audit_note"},
     "routings[0].outcome_kinds"),
    (lambda entry: {**entry, "outcome_kinds": ["audit_note"]}, "routings[0]"),
    (lambda entry: {k: v for k, v in entry.items() if k != "outcomes"}, "routings[0]"),
    (lambda entry: {**entry, "limits": {"max_tasks": -1}}, "routings[0].limits.max_tasks"),
    (lambda entry: {**entry, "end_reasons": {"queue_empty": {"label": "任务池是空的", "outcome": "halted"}}},
     "routings[0].end_reasons.queue_empty.outcome"),
])
def test_a_routing_definition_with_the_wrong_structure_fails_and_names_the_item(tmp_path, change, field):
    # R2：结构不合法的定义在加载时失败，写明文件与字段：部门、成果种类、提议方式与结束原因都要有
    directory = _copy(tmp_path)
    _rewrite_routing(directory, change(_routing(directory)))
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert any(issue[0] == "routings.json" and issue[1] == field for issue in raised.value.issues), \
        raised.value.issues


def test_the_routing_rejects_content_that_is_not_in_the_definitions(tmp_path):
    # R2：按名称指向的内容由路由实现自己校验，逐项写明是哪一项（工单 #861）
    directory = _copy(tmp_path)
    entry = _routing(directory)
    entry.pop("outcomes", None)
    entry.update({"departments": ["risks"], "outcome_kinds": ["audit_note"],
                  "proposal_methods": ["submit_audit_note"]})
    loaded = load_definitions(_rewrite_routing(directory, entry))
    with pytest.raises(routing_contract.InvalidRoutingDefinition) as raised:
        ROUTING.check_definition(loaded)
    issues = "\n".join(raised.value.issues)
    assert "departments[0]：部门 risks 不在组织定义里" in issues
    assert "departments：组织定义里的部门 product 没有列进路由的部门清单" in issues
    assert "proposal_methods[0]：工具 submit_audit_note 不是定义里的提交类工具" in issues
    assert "outcomes[0]：成果种类 audit_note 没有由这里列出的提议方式提交" in issues
    assert "outcomes：提交类工具提交的成果种类 product_spec 没有列进成果种类" in issues


def test_a_final_outcome_outside_the_outcome_kinds_is_rejected(tmp_path):
    # R2：事项最后采纳的成果种类（开环的标记按它判断，工单 #1394）必须是这份路由认得的成果种类之一；
    # 写在成果种类以外时校验失败，写明是哪一项
    directory = _copy(tmp_path)
    entry = _routing(directory)
    entry["final_outcome"] = "audit_note"
    loaded = load_definitions(_rewrite_routing(directory, entry))
    with pytest.raises(routing_contract.InvalidRoutingDefinition) as raised:
        ROUTING.check_definition(loaded)
    assert "final_outcome：成果种类 audit_note 不是这份路由认得的成果种类" in "\n".join(raised.value.issues)
    # 不写这一项不算错：这样的路由不标开环，结束原因由它自己给
    entry.pop("final_outcome")
    ROUTING.check_definition(load_definitions(_rewrite_routing(directory, entry)))


def test_a_watched_name_the_routing_does_not_know_fails_the_routing_own_check(tmp_path):
    # R2：关注的成果（organization.json 的 watched）松开成字符串以后，名称的含义归路由（工单 #1456）：
    # 写错的名称在启动时被拒绝并写明哪一项，不会等到运行到 has_new_work 才抛 KeyError
    directory = _copy(tmp_path)
    organization = _read(directory, "organization.json")
    organization["departments"][1]["watched"] = ["product_spce", "guidance"]
    _write(directory, "organization.json", organization)
    loaded = load_definitions(directory)
    with pytest.raises(routing_contract.InvalidRoutingDefinition) as raised:
        ROUTING.check_definition(loaded)
    issues = "\n".join(raised.value.issues)
    assert "departments[engineering].watched[0]：关注的成果 product_spce 没有这一种" in issues
    assert "watched[1]" not in issues


def test_a_routing_that_does_not_declare_its_item_end_reason_is_rejected(tmp_path):
    # R3：事项结束用的原因要写在它自己的一份定义里（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」中「一定会停对任何路由都成立」）
    directory = _copy(tmp_path)
    entry = _routing(directory)
    entry["end_reasons"] = {"queue_empty": {"label": "任务池是空的", "outcome": "paused", "human_action": None}}
    loaded = load_definitions(_rewrite_routing(directory, entry))
    with pytest.raises(routing_contract.InvalidRoutingDefinition) as raised:
        ROUTING.check_definition(loaded)
    assert any("no_new_work" in issue for issue in raised.value.issues), raised.value.issues


def test_an_end_reason_named_like_a_kernel_stop_reason_is_rejected(tmp_path):
    # R2：路由自己的结束原因与内核的停止原因分开（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」中「一定会停对任何路由都成立」）：同名时校验失败，写明是哪一项
    directory = _copy(tmp_path)
    entry = _routing(directory)
    entry["end_reasons"]["released"] = {"label": "放行", "outcome": "done", "human_action": None}
    loaded = load_definitions(_rewrite_routing(directory, entry))
    with pytest.raises(routing_contract.InvalidRoutingDefinition) as raised:
        ROUTING.check_definition(loaded)
    assert "end_reasons.released：与内核的停止原因同名" in "\n".join(raised.value.issues)


# 提案合同里按名字引用成果的七处（工单 #1456 的审查要求逐个守住）：每处写错一个字母时都要在加载时被拒绝
_MISSPELLED_REFERENCES = [
    (("qa_review", 0, "target"), "conditions.qa_review[0].target"),
    (("qa_review", 1, "artifact"), "conditions.qa_review[1].artifact"),
    (("qa_review", 1, "referenced", 0, "target"), "conditions.qa_review[1].referenced[0].target"),
    (("qa_review", 2, "recorded_in"), "conditions.qa_review[2].recorded_in"),
    (("qa_review", 3, "bind", 0, "target"), "conditions.qa_review[3].bind[0].target"),
    (("qa_review", 4, "evaluated"), "conditions.qa_review[4].evaluated"),
    (("product_decision", 0, "collection"), "conditions.product_decision[0].collection"),
]


def _misspell(contracts: dict, path: tuple) -> None:
    # 把这条路径上的成果名改错一个字母：product_spec → product_spce
    node: Any = contracts["conditions"]
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = "product_spce"


@pytest.mark.parametrize(("path", "field"), _MISSPELLED_REFERENCES)
def test_a_condition_naming_an_outcome_kind_that_is_not_defined_fails_at_load(tmp_path, path, field):
    # R2：提案合同按名字引用成果种类，加载时按成果种类那一项核对（工单 #1456 的审查发现）：
    # 写错一个字母时整份拒绝并写明是哪一条条件的哪个字段，不留「一处手误把内核的判断静默关掉」。
    # 七处各来一条：target、artifact、referenced[]、recorded_in、bind[]、evaluated、collection
    runner = tmp_path / "condition"
    runner.mkdir()
    directory = _copy(runner)
    contracts = _read(directory, "proposal_contracts.json")
    _misspell(contracts, path)
    _write(directory, "proposal_contracts.json", contracts)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[:2] == ("proposal_contracts.json", field)
    assert "product_spce" in issue[2] and "product_spec" in issue[2]


def test_an_old_definitions_directory_without_the_outcome_kinds_item_still_loads(tmp_path):
    # R2：字段只增——旧的定义目录没有 outcome_kinds.json 时照旧加载（那时没有词表可对），路由那一段
    # 按旧写法直接列出成果种类（工单 #1456）
    directory = _copy(tmp_path)
    (directory / "outcome_kinds.json").unlink()
    routings = _read(directory, "routings.json")
    routings["routings"][0].pop("outcomes")
    routings["routings"][0]["outcome_kinds"] = ["product_spec", "product_decision", "delivery_spec",
                                                "independent_judgement", "qa_review", "structure",
                                                "baseline_review"]
    _write(directory, "routings.json", routings)
    loaded = load_definitions(directory)
    assert loaded.routings.routings[0].outcome_kinds[0] == "product_spec"
    assert loaded.outcomes_of("watched_outputs")[0] == "product_spec"


def test_the_skeleton_outcome_kinds_can_be_named_by_a_contract(tmp_path):
    # R2：骨架自己产生的那两种成果（有效合同、代码树快照）写在成果种类那一项的 skeleton 里，
    # 提案合同照样可以按名字引用它们：快照记着树摘要，tree_matches 用它
    (tmp_path / "skeleton").mkdir()
    directory = _copy(tmp_path / "skeleton")
    contracts = _read(directory, "proposal_contracts.json")
    contracts["conditions"]["qa_review"][2]["recorded_in"] = "snapshot"
    _write(directory, "proposal_contracts.json", contracts)
    assert load_definitions(directory).routing == "watched_outputs"


def test_the_label_of_a_routing_end_reason_comes_from_the_definition(tmp_path, monkeypatch):
    # R2：中文名不再写在代码里的表里（models.py，工单 #861）：内核的清单与路由自己的结束原因都在定义里
    directory = _copy(tmp_path)
    entry = _routing(directory)
    entry["end_reasons"]["queue_empty"] = {"label": "任务池是空的", "outcome": "paused", "human_action": None}
    loaded = load_definitions(_rewrite_routing(directory, entry))
    monkeypatch.setattr(models, "DEFINITIONS", loaded)
    assert models.stop_reason_name("queue_empty") == "任务池是空的"
    assert models.stop_reason_name("released") == "已完成并放行"
    # 没有登记的取值原样返回，说明里不丢掉这个事实
    assert models.stop_reason_name("not_a_reason") == "not_a_reason"


def test_outcome_kind_references_are_checked_at_load(tmp_path):
    # 成果种类这一项（outcome_kinds.json，工单 #1456）：种类不重复，分组里的名称都有定义，
    # 每份路由定义引用的那一组存在；不满足时整份拒绝并写明文件与字段
    (tmp_path / "duplicate").mkdir()
    directory = _copy(tmp_path / "duplicate")
    kinds = _read(directory, "outcome_kinds.json")
    kinds["kinds"].append({"id": "product_spec", "label": "重复的一种"})
    _write(directory, "outcome_kinds.json", kinds)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert ("outcome_kinds.json", "kinds[7].id", "重复的成果种类 product_spec") in raised.value.issues

    (tmp_path / "group").mkdir()
    directory = _copy(tmp_path / "group")
    kinds = _read(directory, "outcome_kinds.json")
    kinds["groups"][0]["kinds"].append("no_such_kind")
    _write(directory, "outcome_kinds.json", kinds)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert any(issue[:2] == ("outcome_kinds.json", "groups[0].kinds[7]") and "no_such_kind" in issue[2]
               for issue in raised.value.issues), raised.value.issues

    (tmp_path / "routing").mkdir()
    directory = _copy(tmp_path / "routing")
    routings = _read(directory, "routings.json")
    routings["routings"][0]["outcomes"] = "no_such_group"
    _write(directory, "routings.json", routings)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[:2] == ("routings.json", "routings[0].outcomes")
    assert "no_such_group" in issue[2]

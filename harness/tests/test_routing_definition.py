# 路由自己的一份定义与它自己的结束原因（工单 #861；骨架与应用设计说明第 5.1、5.4 节第 2、7 条、第 12 节 S2b）。
#
# 守的是 R2：定义文件的格式——routings.json 里一种路由自己的一份定义（部门、成果种类、提议方式、路由自己的
# 上限与结束原因）由内核核对结构，按名称指向的内容由路由实现自己校验；以及 R3：路由声明的结束原因可以
# 作为事项的停止原因写入，既没有声明、也不在内核清单里的被拒绝并写明原因。
#
# 复制发布的定义文件到临时目录再改，加载定义、写事件，属于模块层（第 2 节：临时目录与事件库）。

import json
import shutil
from pathlib import Path

import pytest

from harness import models, routing_contract
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, DefinitionError, UnknownStopReason, load_definitions
from harness.event_store import run_stream
from harness.models import EventType, stop_reason_name
from harness.runtime import LoopSystem
from harness.watched_outputs import ROUTING
from harness.write_path import NewEvent


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


def _system(tmp_path: Path) -> tuple[LoopSystem, str]:
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({}))
    return system, system.create_run("print the argument in uppercase")


def _fail(transaction, reason: str) -> None:
    transaction.append(NewEvent(
        EventType.RUN_FAILED, actor="system", state_before="running", state_after="failed",
        stop_reason=reason, payload={"stop_reason": reason, "human_action": None},
    ))


def test_the_kernel_loads_a_routing_definition_with_names_and_structure_only(tmp_path):
    # R2：内核只核对名称与结构（设计说明第 5.4 节第 2 条）：名称指向的东西都不存在也照常加载，
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


def test_the_shipped_routing_definition_passes_the_routing_own_check():
    # R2：发布的成果驱动定义与现有的定义文件对得上，内容校验通过
    assert ROUTING.check_definition(DEFINITIONS) is None


def test_a_routing_that_does_not_declare_its_item_end_reason_is_rejected(tmp_path):
    # R3：事项结束用的原因要写在它自己的一份定义里（设计说明第 5.4 节第 7 条）
    directory = _copy(tmp_path)
    entry = _routing(directory)
    entry["end_reasons"] = {"queue_empty": {"label": "任务池是空的", "outcome": "paused", "human_action": None}}
    loaded = load_definitions(_rewrite_routing(directory, entry))
    with pytest.raises(routing_contract.InvalidRoutingDefinition) as raised:
        ROUTING.check_definition(loaded)
    assert any("no_new_work" in issue for issue in raised.value.issues), raised.value.issues


def test_an_end_reason_named_like_a_kernel_stop_reason_is_rejected(tmp_path):
    # R2：路由自己的结束原因与内核的停止原因分开（设计说明第 5.4 节第 7 条）：同名时校验失败，写明是哪一项
    directory = _copy(tmp_path)
    entry = _routing(directory)
    entry["end_reasons"]["released"] = {"label": "放行", "outcome": "done", "human_action": None}
    loaded = load_definitions(_rewrite_routing(directory, entry))
    with pytest.raises(routing_contract.InvalidRoutingDefinition) as raised:
        ROUTING.check_definition(loaded)
    assert "end_reasons.released：与内核的停止原因同名" in "\n".join(raised.value.issues)


def test_a_condition_naming_an_outcome_kind_that_is_not_defined_fails_at_load(tmp_path):
    # R2：提案合同按名字引用成果种类，加载时按成果种类那一项核对（工单 #1456 的审查发现）：
    # 写错一个字母时整份拒绝并写明是哪一条条件的哪个字段，不留「一处手误把内核的判断静默关掉」
    (tmp_path / "condition").mkdir()
    directory = _copy(tmp_path / "condition")
    contracts = _read(directory, "proposal_contracts.json")
    contracts["conditions"]["qa_review"][0]["target"] = "product_spce"
    _write(directory, "proposal_contracts.json", contracts)
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    [issue] = raised.value.issues
    assert issue[:2] == ("proposal_contracts.json", "conditions.qa_review[0].target")
    assert "product_spce" in issue[2] and "product_spec" in issue[2]

    # 骨架自己产生的那两种成果（有效合同、代码树快照）也可以按名字引用：它们写在成果种类那一项的 skeleton 里
    (tmp_path / "skeleton").mkdir()
    directory = _copy(tmp_path / "skeleton")
    contracts = _read(directory, "proposal_contracts.json")
    contracts["conditions"]["qa_review"][2]["recorded_in"] = "contract"
    _write(directory, "proposal_contracts.json", contracts)
    assert load_definitions(directory).routing == "watched_outputs"


def test_a_routing_declared_end_reason_is_written_as_an_item_stop_reason(tmp_path):
    # R3：路由声明的结束原因可以作为事项的停止原因写入，中文名与处理说明来自它自己的一份定义
    system, run_id = _system(tmp_path)
    system.writes.transact(run_stream(run_id), lambda transaction: _fail(transaction, "no_new_work"))
    projection = system.project(run_id)
    assert (projection.status, projection.stop_reason) == ("failed", "no_new_work")
    assert stop_reason_name("no_new_work") == "没有部门有新的工作"
    [failed] = [event for event in system.writes.read(run_stream(run_id)).events()
                if event.type == EventType.RUN_FAILED]
    assert failed.stop_reason == "no_new_work"


def test_an_undeclared_stop_reason_is_rejected_and_says_where_to_declare_it(tmp_path):
    # R3：既没有声明、也不在内核清单里的停止原因写不进去，说明里写明两处定义
    system, run_id = _system(tmp_path)
    with pytest.raises(UnknownStopReason) as raised:
        system.writes.transact(run_stream(run_id), lambda transaction: _fail(transaction, "policy_expired"))
    message = str(raised.value)
    assert "policy_expired" in message
    assert "stop_reasons.json" in message and "routings.json" in message
    assert system.project(run_id).status == "running"


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

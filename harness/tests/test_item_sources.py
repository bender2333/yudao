"""工单 #1455：事项的来源写进定义，项目开始时先由接这个来源的部门开始一轮工作。

一份测试定义里工程接你的输入、产品也关注成果（不看用户输入）：事项开始时工程开始第一轮，
新的输入先进工程的工作，核验角色的放行等工程把输入处理完——产品只回答询问才接得对。
另一份不写 sources 的旧定义照旧加载，两种来源都由关注用户输入的部门接。

守 R2（定义文件的格式：来源与接它的部门是定义里的数据，旧定义照旧能读）与
R3（直做与开环完成这一段写明的行为：事项开始时开始第一轮的是接来源的部门，新的输入先进它的工作）。
定义要落在临时目录里（load_definitions 读文件），所以整个文件属于模块层。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from harness import watched_outputs
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, load_definitions
from harness.kernel_events import Event
from harness.models import (
    ArtifactRef, DeliverySpec, EffectiveContract, EventType, ProductSpec, RunProjection, SessionRecord, UserInput,
)
from harness.tightening import WATCHED_OUTPUTS, input_department, pending_product_input
from harness.validation import TightenRequest

# 这份测试定义里的三个部门：与默认定义同一批名字，只有接来源的部门与产品关注的东西不同
PRODUCT, ENGINEERING, QUALITY = "product", "engineering", "quality"


def _definitions_with_engineering_receiving(tmp_path: Path, *, sources: bool = True) -> Any:
    """发布定义的一份副本：工程接两种来源，产品也关注成果（交付）但不看用户输入。

    sources 为 False 时不写 sources，留一份旧定义：两种来源按关注用户输入的部门解释。
    """
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        shutil.copyfile(path, directory / path.name)
    organization = json.loads((directory / "organization.json").read_text(encoding="utf-8"))
    product = next(item for item in organization["departments"] if item["id"] == PRODUCT)
    if sources:
        organization["sources"] = {"user_input": ENGINEERING, "onboarding": ENGINEERING}
        # 工程接输入，产品也关注成果（交付）但不看用户输入
        product["watched"] = ["delivery", "guidance"]
    else:
        # 旧定义：没有 sources，两种来源都按关注用户输入的部门解释，产品仍关注用户输入
        del organization["sources"]
        product["watched"] = ["user_input", "delivery", "guidance"]
    (directory / "organization.json").write_text(
        json.dumps(organization, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def _event(event_type: str, *, department: str, payload: dict[str, Any],
           session_id: str | None = None, state_after: str = "running") -> Event:
    # 一条构造的事件：只用到事件类型、写它的部门、会话与载荷
    return Event(
        event_id="evt-1", run_id="run", type=event_type, role=None, parent_event_id=None,
        state_before="running", state_after=state_after, payload=payload, artifact_hashes=[],
        session_id=session_id, provider=None, model=None, context_digest=None, stop_reason=None, error=None,
        created_at="2026-11-04T00:00:00Z", position=1, stream="run:run", stream_version=1,
        project_id=None, work_item_id=None, department=department)


def _input(version: int) -> UserInput:
    # 一版用户的输入：pending_product_input 按它判断还有没有没处理完的输入
    return UserInput(
        id=f"input-{version}", run_id="run", version=version, text="Build a CLI.", kind="text",
        input_ref=ArtifactRef("user_input", "input-hash", f"inputs/{version}"),
        intend_ref=ArtifactRef("intend", "intend-hash", "intend.md"),
        byte_start=0, byte_end=12, created_event_id="created")


def _projection(*, kind: str = "change", input_version: int = 1, processed: int = 0,
                inputs: bool = True, delivery: bool = False) -> RunProjection:
    """一份构造的运行投影：三个部门各有一个在等待的会话。"""
    projection = RunProjection(run_id="run", task="Build a CLI.", kind=kind)
    for department in (PRODUCT, ENGINEERING, QUALITY):
        projection.sessions[department] = SessionRecord(
            session_id=f"ses_{department}", department=department, status="idle")
    projection.input_version = input_version
    projection.processed_input_version = processed
    if inputs:
        projection.inputs.append(_input(input_version))
    if delivery:
        projection.product_spec = ProductSpec(
            id="spec", run_id="run", revision=1, parent_hash=None, content_hash="spec-hash", issuer=PRODUCT,
            status="active", created_event_id="spec-event", goal="CLI", requirements=["Print text"],
            boundaries=[], constraints=[], acceptance_criteria=["Text appears"], fatal_conditions=[],
            non_goals=[], decision_changes=[], change_record=None, input_version=0)
        projection.effective_contract = EffectiveContract(
            "contract-hash", 1, "spec-hash", 0, [], "contract-event", ArtifactRef("prd", "prd-hash", "PRD.md"))
        projection.delivery_spec = DeliverySpec(
            id="delivery", run_id="run", revision=1, parent_hash=None, content_hash="delivery-hash",
            issuer=ENGINEERING, status="active", created_event_id="delivery-event",
            product_spec_hash="spec-hash", effective_contract_hash="contract-hash", summary="CLI",
            files=["cli.py"], check_names=[], checks=[], known_risks=[], code_tree_digest="tree-hash",
            tree_ref=ArtifactRef("tree", "tree-ref", "tree.json"))
    return projection


def test_the_department_that_receives_the_input_starts_the_first_round(tmp_path):
    # 验收第 2 条：事项开始时工程开始第一轮；产品关注成果，但不是它开始
    definitions = _definitions_with_engineering_receiving(tmp_path)
    projection = _projection()

    assert watched_outputs.ready_departments(projection, definitions=definitions) == [ENGINEERING]
    assert watched_outputs.has_new_work(projection, ENGINEERING, definitions)
    assert not watched_outputs.has_new_work(projection, PRODUCT, definitions)
    # 部门名单也按这份定义取
    assert definitions.departments == (PRODUCT, ENGINEERING, QUALITY)


def test_new_input_is_new_work_for_the_department_that_receives_it(tmp_path):
    # 验收第 2 条：新的输入先进工程的工作；产品不因为新输入开始一轮
    definitions = _definitions_with_engineering_receiving(tmp_path)
    projection = _projection(input_version=2, processed=1)

    assert watched_outputs.watched_new_work(projection, ENGINEERING, definitions) == ["user_input"]
    assert watched_outputs.ready_departments(projection, definitions=definitions) == [ENGINEERING]
    assert not watched_outputs.has_new_work(projection, PRODUCT, definitions)
    # 输入分派给接它的部门：product_input_assigned 带的是它
    assert input_department(definitions) == ENGINEERING


def test_a_watcher_of_user_input_does_not_start_a_round_for_it(tmp_path):
    # 验收第 2 条：关注用户输入不再是「开始第一轮」的依据；产品盯的是交付，
    # 给它一条没处理完的用户输入也不会让它开始
    definitions = _definitions_with_engineering_receiving(tmp_path)
    product = definitions.organization.departments[0]
    assert product.watched == ("delivery", "guidance")
    projection = _projection()

    assert "user_input" not in watched_outputs.watched_new_work(projection, PRODUCT, definitions)
    # 同一份投影交给默认定义：默认定义里接输入的是产品，所以它开始
    assert watched_outputs.ready_departments(projection) == [PRODUCT]


def test_the_onboarding_source_starts_with_the_department_that_receives_it(tmp_path):
    # 验收第 2 条同一条规矩用在建档的来源上：事项的种类决定来源，接它的部门开始第一轮
    definitions = _definitions_with_engineering_receiving(tmp_path)
    projection = _projection(kind="onboarding")

    assert definitions.item_source("onboarding") == "onboarding"
    assert watched_outputs.ready_departments(projection, definitions=definitions) == [ENGINEERING]
    # 产品关注交付：没有交付时它不开始，也不因为建档的输入开始
    assert not watched_outputs.has_new_work(projection, PRODUCT, definitions)


def test_a_release_waits_for_the_department_that_receives_the_input(tmp_path):
    # 验收第 2 条：放行判断按工程——工程还没处理完输入时，核验角色的放行在安全节点上等
    definitions = _definitions_with_engineering_receiving(tmp_path)
    projection = _projection(delivery=True)
    release = TightenRequest(
        department=QUALITY, state=projection, definitions=definitions,
        tool={"id": "call", "name": "submit_review", "args": {"verdict": "release"}})

    assert pending_product_input(projection, [], definitions=definitions)
    assert WATCHED_OUTPUTS.tool(release).wait

    # 工程的一轮正常结束并带走了这一版输入：放行不再等
    events = [
        _event(EventType.DEPARTMENT_ACTIVATED, department=ENGINEERING,
               payload={"activation_id": "act"}, session_id=f"ses_{ENGINEERING}"),
        _event(EventType.DEPARTMENT_INPUT, department=ENGINEERING,
               payload={"activation_id": "act", "input_version": 1}, session_id=f"ses_{ENGINEERING}"),
        _event(EventType.ACTIVATION_FINISHED, department=ENGINEERING,
               payload={"activation_id": "act"}, session_id=f"ses_{ENGINEERING}", state_after="done"),
    ]
    assert not pending_product_input(projection, events, definitions=definitions)
    processed = TightenRequest(
        department=QUALITY, state=projection, definitions=definitions, events=tuple(events),
        tool={"id": "call", "name": "submit_review", "args": {"verdict": "release"}})
    assert not WATCHED_OUTPUTS.tool(processed).wait


def test_an_old_definition_reads_both_sources_as_the_department_that_watches_user_input(tmp_path):
    # 验收第 4 条：不写新字段的旧定义加载成功，两种来源都由关注用户输入的部门接
    old = _definitions_with_engineering_receiving(tmp_path, sources=False)
    assert old.organization.sources is None
    assert old.source_department("user_input") == PRODUCT
    assert old.source_department("onboarding") == PRODUCT
    assert input_department(old) == PRODUCT
    # 旧定义下事项开始时的第一轮仍是产品：与今天的行为相同
    assert watched_outputs.ready_departments(_projection(), definitions=old) == [PRODUCT]
    assert DEFINITIONS.source_department("user_input") == PRODUCT

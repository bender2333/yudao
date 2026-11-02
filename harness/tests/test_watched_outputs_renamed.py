"""工单 #1391：路由、投影与查询的部门名从定义读。

一份把部门改了名的定义与默认定义跑同一件事：核验角色是谁、谁收用户的输入、谁能交要求，全部按定义判断；
部门状态与流转记录里的部门名跟着定义走，代码里不再出现 `quality`、`VERIFIER_OF`、`product`、`engineering`、
`operations` 这几处写死的名字。默认定义下的行为不变（事件序列基准与请求快照由 test_event_sequence.py 守着）。

守 R2（定义的格式：定义是数据，部门名不进代码，换一份定义不改代码）与 R3（形态随事项冻结、核验角色是
角色的性质：改名后的定义跑出同样的判断，除名字外与默认定义相同）。
改名的那份定义要落在临时目录里（load_definitions 读文件），所以整个文件属于模块层。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from harness import watched_outputs
from harness.app import project_queries, read_models
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, load_definitions
from harness.kernel_events import Event
from harness.models import (
    ArtifactRef, DeliverySpec, EffectiveContract, EventType, ProductSpec, RunProjection, SessionRecord, UserInput,
)
from harness.tightening import WATCHED_OUTPUTS
from harness.validation import TightenRequest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 改名后的部门编号与中文名：都不是默认定义里的名字
RENAMED_VERIFIER = "inspection"
RENAMED_PRODUCT = "requirements"
RENAMED_ENGINEERING = "build"
RENAMED_LABELS = {RENAMED_VERIFIER: "检验", RENAMED_PRODUCT: "需求", RENAMED_ENGINEERING: "构建"}

# 默认定义里的三个部门编号：检索这些名字在代码里出现
DEFAULT_NAMES = ("product", "engineering", "quality")

# 检索的名字：部门编号（改名的定义用别的名字）与核验关系的常量名
WHOLE_WORD_NAMES = (*DEFAULT_NAMES, "operations", "VERIFIER_OF")


# ---------------------------------------------------------------------------
# 一份改了名的定义


def _renamed(value: Any, old: str, new: str) -> Any:
    # 定义文件里表示部门的那个字符串全部换掉，其余内容照旧；规则登记的条目名按部门分段，一起换
    if isinstance(value, dict):
        return {_renamed_key(key, old, new): _renamed(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed(item, old, new) for item in value]
    return new if value == old else value


def _renamed_key(key: Any, old: str, new: str) -> Any:
    if not isinstance(key, str):
        return key
    return ".".join(new if part == old else part for part in key.split("."))


def _renamed_definitions(tmp_path: Path, names: dict[str, str]) -> Any:
    """发布的那份定义的一份副本：按 names 把部门编号换成新的（中文名一起换）。"""
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))
        for old, new in names.items():
            content = _renamed(content, old, new)
        (directory / path.name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    organization = json.loads((directory / "organization.json").read_text(encoding="utf-8"))
    for department in organization["departments"]:
        department["label"] = RENAMED_LABELS.get(department["id"], department["label"])
    (directory / "organization.json").write_text(
        json.dumps(organization, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def _all_renamed(tmp_path: Path) -> Any:
    # 三个部门都改名：核验角色、收输入的部门、交要求的部门都不再是默认的名字
    return _renamed_definitions(tmp_path, {
        "product": RENAMED_PRODUCT, "engineering": RENAMED_ENGINEERING, "quality": RENAMED_VERIFIER})


# ---------------------------------------------------------------------------
# 构造的事实：一份带 PRD、有效合同与交付的 run


def _projection(product: str = "product", engineering: str = "engineering", verifier: str = "quality",
                *, delivery: bool = True, active: str | None = None) -> RunProjection:
    """一份构造的 run 投影：写了 PRD 与有效合同，默认还有一份交付，三个部门各有一个会话。"""
    projection = RunProjection(run_id="run", task="Build a CLI.")
    for department in (product, engineering, verifier):
        projection.sessions[department] = SessionRecord(
            session_id=f"ses_{department}", department=department,
            status="active" if department == active else "idle")
    projection.product_spec = ProductSpec(
        id="spec", run_id="run", revision=1, parent_hash=None, content_hash="spec-hash", issuer=product,
        status="active", created_event_id="spec-event", goal="CLI", requirements=["Print text"], boundaries=[],
        constraints=[], acceptance_criteria=["Text appears"], fatal_conditions=[], non_goals=[],
        decision_changes=[], change_record=None, input_version=0)
    projection.effective_contract = EffectiveContract(
        "contract-hash", 1, "spec-hash", 0, [], "contract-event", ArtifactRef("prd", "prd-hash", "PRD.md"))
    if delivery:
        projection.delivery_spec = DeliverySpec(
            id="delivery", run_id="run", revision=1, parent_hash=None, content_hash="delivery-hash",
            issuer=engineering, status="active", created_event_id="delivery-event",
            product_spec_hash="spec-hash", effective_contract_hash="contract-hash", summary="CLI",
            files=["cli.py"], check_names=[], checks=[], known_risks=[], code_tree_digest="tree-hash",
            tree_ref=ArtifactRef("tree", "tree-ref", "tree.json"))
    return projection


def _event(event_type: str, *, department: str, payload: dict[str, Any],
           session_id: str | None = None) -> Event:
    # 一条构造的事件：只用到事件类型、写它的部门与载荷
    return Event(
        event_id="evt-1", run_id="run", type=event_type, role=None, parent_event_id=None,
        state_before="running", state_after="running", payload=payload, artifact_hashes=[],
        session_id=session_id, provider=None, model=None, context_digest=None, stop_reason=None, error=None,
        created_at="2026-11-03T00:00:00Z", position=1, stream="run:run", stream_version=1,
        project_id=None, work_item_id=None, department=department)


def _back_to_default(names: list[str]) -> list[str]:
    # 改名后的部门换回默认的名字：两边的判断除名字外相同才比得上
    renamed = {RENAMED_PRODUCT: "product", RENAMED_ENGINEERING: "engineering", RENAMED_VERIFIER: "quality"}
    result: list[str] = []
    for value in names:
        for new, old in renamed.items():
            value = value.replace(new, old).replace(new.capitalize(), old.capitalize())
        result.append(value)
    return result


# ---------------------------------------------------------------------------
# 检索验收：这三个应用模块里不再写部门名与核验关系的常量


def _source(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _whole_word(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")


def _hits(source: str, names: tuple[str, ...]) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    for number, line in enumerate(source.splitlines(), start=1):
        for name in names:
            if _whole_word(name).search(line):
                found.append((number, name, line.strip()))
    return found


def test_the_search_finds_the_names_where_they_still_belong():
    # 检索本身要能失败：默认定义里确实有这三个部门，改名的那份用另外的名字
    assert set(DEFINITIONS.departments) == set(DEFAULT_NAMES)
    assert set(RENAMED_LABELS) == {RENAMED_PRODUCT, RENAMED_ENGINEERING, RENAMED_VERIFIER}


def test_the_route_tightening_and_read_models_name_no_department_from_the_definition():
    for relative in ("harness/watched_outputs.py", "harness/tightening.py", "harness/app/read_models.py"):
        offenders = _hits(_source(relative), WHOLE_WORD_NAMES)
        assert offenders == [], (
            f"{relative} 里还在写死部门名与核验关系的常量，这些应当从定义取（工单 #1391）：\n"
            + "\n".join(f"{number}: {name} — {line}" for number, name, line in offenders))


def test_the_project_queries_name_no_verifier_and_keep_no_verifier_map():
    offenders = _hits(_source("harness/app/project_queries.py"), ("quality", "VERIFIER_OF"))
    assert offenders == [], (
        "harness/app/project_queries.py 里还在写死核验角色，这些应当按定义的核验声明取（工单 #1391）：\n"
        + "\n".join(f"{number}: {name} — {line}" for number, name, line in offenders))


def test_the_projection_names_a_department_only_as_the_default_issuer_of_an_old_event():
    # 投影只剩读旧事件时缺省作者的那几处：旧的 PRD、交付、结论事件没有写作者，按默认定义的部门读
    offenders = _hits(_source("harness/projection.py"), WHOLE_WORD_NAMES)
    assert offenders, "projection.py 里应当还有读旧事件时的缺省作者，检索没有找到说明这一条已经过时"
    for number, name, line in offenders:
        assert 'payload.get("issuer", ' in line, (
            f"projection.py 第 {number} 行的 {name} 不是读旧事件的缺省作者：{line}")


# ---------------------------------------------------------------------------
# 核验角色改名：部门状态、流转记录与放行判断都认改名后的部门


def test_the_department_state_names_the_renamed_verifier(tmp_path, monkeypatch):
    # 验收第 2 条前半：核验角色改名以后，部门状态的「核验中」与原因写改名后的部门
    renamed = _renamed_definitions(tmp_path, {"quality": RENAMED_VERIFIER})
    monkeypatch.setattr(project_queries, "DEFINITIONS", renamed)
    projection = _projection(verifier=RENAMED_VERIFIER)
    progress = project_queries._work_item_progress(projection)

    states = project_queries._departments(projection, progress, None, {})

    assert states["engineering"].state == "verifying"
    assert states["engineering"].note == f"等{RENAMED_LABELS[RENAMED_VERIFIER]}核验交付 r1"
    # 核验角色自己不在核验中：没有人核验它的交付
    assert states[RENAMED_VERIFIER].state == "waiting"


def test_the_flow_records_send_work_to_the_renamed_verifier(tmp_path, monkeypatch):
    # 验收第 2 条中段：流转记录的去向写改名后的部门（交付送到谁、返工回到谁、PRD 新版本送到谁）
    renamed = _renamed_definitions(tmp_path, {"quality": RENAMED_VERIFIER})
    monkeypatch.setattr(read_models, "DEFINITIONS", renamed)

    delivery = read_models.flow_rows(_event(
        EventType.DELIVERY_ACCEPTED, department="engineering", payload={"summary": "implemented"}))
    assert [(row["direction_from"], row["direction_to"]) for row in delivery] == [
        ("engineering", RENAMED_VERIFIER)]
    assert delivery[0]["flow_id"] == "evt-1"

    rework = read_models.flow_rows(_event(
        EventType.QA_SUBMITTED, department=RENAMED_VERIFIER,
        payload={"verdict": "rework_engineering", "rationale": "缺少检查"}))
    assert [(row["direction_from"], row["direction_to"]) for row in rework] == [
        (RENAMED_VERIFIER, "engineering")]

    spec = read_models.flow_rows(_event(
        EventType.SPEC_ACCEPTED, department="product", payload={"revision": 1}))
    assert [(row["direction_from"], row["direction_to"]) for row in spec] == [
        ("product", "engineering"), ("product", RENAMED_VERIFIER)]


def test_a_release_by_the_renamed_verifier_waits_for_the_input(tmp_path, monkeypatch):
    # 验收第 2 条后半：放行判断认改名后的核验角色（放行等收输入的部门处理完输入）
    renamed = _renamed_definitions(tmp_path, {"quality": RENAMED_VERIFIER})
    monkeypatch.setattr(watched_outputs, "DEFINITIONS", renamed)
    projection = _projection(verifier=RENAMED_VERIFIER, active=RENAMED_VERIFIER)
    projection.inputs.append(UserInput(
        id="input", run_id="run", version=1, text="再加一条要求", kind="user",
        input_ref=ArtifactRef("input", "input-hash", "input/1"), intend_ref=ArtifactRef("intent", "i", "i"),
        byte_start=0, byte_end=1, created_event_id="input-event"))
    projection.input_version = 1

    tightened = WATCHED_OUTPUTS.tool(TightenRequest(
        department=RENAMED_VERIFIER, state=projection, definitions=renamed,
        tool={"id": "call", "name": "submit_review", "args": {"verdict": "release"}}))

    assert tightened.wait and not tightened.accepted and not tightened.deferred
    # 缺陷记录不等输入处理完：同一份事实里改名后的核验角色提交退回，不在安全节点上等
    tightened = WATCHED_OUTPUTS.tool(TightenRequest(
        department=RENAMED_VERIFIER, state=projection, definitions=renamed,
        tool={"id": "call", "name": "submit_review", "args": {"verdict": "rework_engineering"}}))
    assert not tightened.wait


# ---------------------------------------------------------------------------
# 三个部门都改名：路由的开工、一轮结束、事项结束与收紧检查的判断与默认定义除名字外相同


def test_the_route_and_the_tightening_decide_the_same_way_under_a_fully_renamed_definition(
        tmp_path, monkeypatch):
    # 验收第 3 条：三个部门改名以后，路由与收紧检查的判断和默认定义下除名字外相同
    renamed = _all_renamed(tmp_path)
    assert renamed.departments == (RENAMED_PRODUCT, RENAMED_ENGINEERING, RENAMED_VERIFIER)

    results: dict[str, list[str]] = {}
    for label, definitions in (("default", DEFINITIONS), ("renamed", renamed)):
        monkeypatch.setattr(watched_outputs, "DEFINITIONS", definitions)
        product, engineering, _verifier = definitions.departments
        projection = _projection(*definitions.departments, delivery=False)
        # 收输入的部门有一条还没有处理的输入；三个部门因此都有新的工作
        projection.input_version = 1
        # 一轮工作：工程在这个会话里交上了正式成果
        events = [
            _event(EventType.DEPARTMENT_ACTIVATED, department=engineering,
                   payload={"activation_id": "act"}, session_id=f"ses_{engineering}"),
            _event(EventType.TOOL_CALLED, department=engineering,
                   payload={"name": "submit_delivery"}, session_id=f"ses_{engineering}"),
        ]
        results[label] = [
            # 开工：三个部门都有新的工作
            *watched_outputs.ready_departments(projection),
            # 一轮结束：提交了正式成果
            watched_outputs.round_end(projection, events, department=engineering,
                                      session_id=f"ses_{engineering}", activation_id="act").outcome,
            # 事项结束：没有部门有新的工作了
            watched_outputs.item_end(projection).stop_reason,
            # 收紧检查：能交要求的那个部门在询问分支里只能回答
            WATCHED_OUTPUTS.tool(TightenRequest(
                department=product, state=_in_branch(projection), session_id="ses_ask",
                definitions=definitions,
                tool={"id": "call", "name": "submit_product_spec", "args": {}})).reason or "",
        ]

    assert _back_to_default(results["renamed"]) == results["default"]
    assert results["default"][:3] == ["product", "engineering", "quality"]
    assert results["default"][3] == "proposal_accepted"
    assert results["default"][4] == "no_new_work"
    assert results["renamed"][5].lower().startswith(f"{RENAMED_PRODUCT} ")


def _in_branch(projection: RunProjection) -> RunProjection:
    # 请求在一个询问分支里发生：分支会话 ses_ask 正在回答一个还没结束的询问
    projection.ask_stack.append({
        "requester": "someone", "recipient": "nobody", "question": "?", "branch_session_id": "ses_ask",
        "origin_session_id": "ses_origin"})
    projection.branch_sessions.append("ses_ask")
    return projection


def test_the_flow_records_and_the_states_under_a_fully_renamed_definition_use_the_renamed_departments(
        tmp_path, monkeypatch):
    # 验收第 3 条后半：三个部门都改名时，流转记录的去向与部门状态写改名后的部门
    renamed = _all_renamed(tmp_path)
    monkeypatch.setattr(read_models, "DEFINITIONS", renamed)
    monkeypatch.setattr(project_queries, "DEFINITIONS", renamed)

    delivery = read_models.flow_rows(_event(
        EventType.DELIVERY_ACCEPTED, department=RENAMED_ENGINEERING, payload={"summary": "implemented"}))
    assert [(row["direction_from"], row["direction_to"]) for row in delivery] == [
        (RENAMED_ENGINEERING, RENAMED_VERIFIER)]

    spec = read_models.flow_rows(_event(
        EventType.SPEC_ACCEPTED, department=RENAMED_PRODUCT, payload={"revision": 1}))
    assert [(row["direction_from"], row["direction_to"]) for row in spec] == [
        (RENAMED_PRODUCT, RENAMED_ENGINEERING), (RENAMED_PRODUCT, RENAMED_VERIFIER)]

    projection = _projection(RENAMED_PRODUCT, RENAMED_ENGINEERING, RENAMED_VERIFIER)
    states = project_queries._departments(
        projection, project_queries._work_item_progress(projection), None, {})
    assert states[RENAMED_ENGINEERING].state == "verifying"
    assert states[RENAMED_ENGINEERING].note == f"等{RENAMED_LABELS[RENAMED_VERIFIER]}核验交付 r1"

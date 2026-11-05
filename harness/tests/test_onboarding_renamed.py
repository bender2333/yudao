"""工单 #1410：建档按定义走，决定请求的部门取自定义。

一份把三个部门都改了名的定义（真实的定义加载，不替换模块级定义）下，建档结算写出的决定请求写交定义里的
部门：确认初始 PRD 的请求写交写下初始 PRD 的部门（按提案合同），内核修改的请求写交这份交付的部门（按交付的
作者）；基线检查的命令取自核验角色这一轮的检查回执，不取别的部门的同名调用。默认三部门下的事件、候选、
决定请求与材料不变（`test_onboarding.py` 与事件序列基准守着）。

守 R2（定义是数据：部门名不进代码）与 R3（形态随事项冻结：换一份把部门改了名的定义，建档写出的请求跟着
那份定义里的部门走）。

两个用例各真实跑完一轮（建档一轮、普通事项一轮），按第 2 节的分层登记为集成层；改名的那份定义落在
临时目录里（`load_definitions` 读文件）。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, load_definitions
from harness.kernel_events import Event
from harness.models import EventType, ProjectEventType, ProductSpec
from harness.projects import _check_commands, _review_department
from harness.proposals import (baseline_review_turn, delivery_turn, judgement_turn, product_spec, review_turn,
                               structure_turn)
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn, python_snippet
from harness.tests.onboarding_project import (ONBOARDING_GOAL as GOAL, ONBOARDING_REQUIREMENT as REQUIREMENT,
                                              onboarding_source)
from harness.tests.saved_rewrite import rewrite_saved_projection

# 改名后的三个部门：都不是默认定义里的名字。核验角色是定义里声明的那一个，这里叫检验
RENAMED_PRODUCT = "requirements"
RENAMED_ENGINEERING = "build"
RENAMED_VERIFIER = "inspection"
RENAMED_LABELS = {RENAMED_PRODUCT: "需求", RENAMED_ENGINEERING: "构建", RENAMED_VERIFIER: "检验"}
NAME_MAP = {"product": RENAMED_PRODUCT, "engineering": RENAMED_ENGINEERING, "quality": RENAMED_VERIFIER}

# 两个部门运行同名的检查时用的命令：基线检查记下的命令必须是核验角色的那一条
VERIFIER_COMMAND = python_snippet("print('verifier ran this check')")
OTHER_COMMAND = python_snippet("print('the delivering department ran this check')")


# ---------------------------------------------------------------------------
# 一份部门改了名的定义：发布的那份定义的一份副本，三个部门换名字（中文名一起换）


def _renamed(value: Any, old: str, new: str) -> Any:
    # 定义文件里表示部门的那段字符串全部换掉，其余内容照旧；规则登记的条目名按部门分段，一起换
    if isinstance(value, dict):
        return {_renamed_key(key, old, new): _renamed(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed(item, old, new) for item in value]
    return new if value == old else value


def _renamed_key(key: Any, old: str, new: str) -> Any:
    if not isinstance(key, str):
        return key
    return ".".join(new if part == old else part for part in key.split("."))


def _renamed_definitions(tmp_path: Path) -> Any:
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))
        for old, new in NAME_MAP.items():
            content = _renamed(content, old, new)
        (directory / path.name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    organization = json.loads((directory / "organization.json").read_text(encoding="utf-8"))
    for department in organization["departments"]:
        department["label"] = RENAMED_LABELS.get(department["id"], department["label"])
    (directory / "organization.json").write_text(
        json.dumps(organization, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


# ---------------------------------------------------------------------------
# 一次真实建档记下的作者部门，按定义的名字改名


def _renamed_record(record: dict[str, Any]) -> dict[str, Any]:
    # 基线核验这类记录：作者部门写在 issuer 与接纳事件的 artifact_issuer 上
    return {key: (NAME_MAP.get(value, value) if key in ("issuer", "artifact_issuer") else value)
            for key, value in record.items()}


def _renamed_spec(spec: ProductSpec) -> ProductSpec:
    return replace(spec, issuer=NAME_MAP[spec.issuer])


def _renamed_facts(system: LoopSystem, run_id: str) -> None:
    # 这份定义下的事件与记录：部门是定义里的名字，不是默认的三个。
    # 本进程的写入口按启动时加载的定义核对 run 事件的部门（harness/write_path.py），所以改名的部门写不进事件；
    # 用例把一次真实运行记下的作者部门按定义的名字改名再结算——生产上换成那份定义以后事件一开始就写这些名字。
    # 换形态的命令与查询见工单 #1392、#1402、#1403，三个部门都改名跑完一整轮见 #1404
    run = system.project(run_id)
    if run.product_spec is not None:
        run.product_spec = _renamed_spec(run.product_spec)
    run.product_specs = [_renamed_spec(item) for item in run.product_specs]
    if run.baseline_review is not None:
        run.baseline_review = _renamed_record(run.baseline_review)
    run.baseline_reviews = [_renamed_record(item) for item in run.baseline_reviews]
    if run.delivery_spec is not None:
        run.delivery_spec = replace(run.delivery_spec, issuer=NAME_MAP[run.delivery_spec.issuer])
    run.delivery_specs = [replace(item, issuer=NAME_MAP[item.issuer]) for item in run.delivery_specs]
    run.reviews = [replace(item, issuer=NAME_MAP[item.issuer]) for item in run.reviews]
    rewrite_saved_projection(system.store, run_id, run)


def _project_event(system: LoopSystem, project_id: str, event_type: str) -> Any:
    return next(event for event in system.store.list_project_events(project_id) if event.type == event_type)


# ---------------------------------------------------------------------------
# 验收：确认初始 PRD 的请求写交写下初始 PRD 的部门（按提案合同）


def _onboarding_script() -> dict:
    # 一轮建档的三个部门（按部门给出脚本，工单 #557、#879）：核验角色备两条同一内容的回答（工单 #1255）
    def review() -> FakeTurn:
        return baseline_review_turn(
            conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
            checks={"smoke": {"command": VERIFIER_COMMAND}})

    return {
        "product": [FakeTurn(proposal=product_spec(requirements=[REQUIREMENT],
                                                   acceptance=["run the CLI with a word"]))],
        "engineering": [structure_turn(checks={"smoke": {"command": OTHER_COMMAND}},
                                       requirement_locations=[{"requirement": REQUIREMENT,
                                                               "locations": ["src/echo.py"]}])],
        "quality": [review(), review()],
    }


def test_the_initial_prd_request_goes_to_the_department_that_wrote_the_prd(tmp_path):
    # 验收第 2 条的一半：改名的定义下，确认初始 PRD 的请求写交写下初始 PRD 的那个部门（这里叫需求）。
    # 候选照旧带着这一轮的三份产物，基线检查的命令取自核验角色自己的 run_check 调用
    definitions = _renamed_definitions(tmp_path)
    assert definitions.departments == (RENAMED_PRODUCT, RENAMED_ENGINEERING, RENAMED_VERIFIER)
    assert RENAMED_PRODUCT not in DEFINITIONS.departments, "不替换模块级定义"
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter(_onboarding_script()))
    try:
        source = onboarding_source(tmp_path / "source")
        project_id, _work_item_id, run_id = system.projects.onboard(
            "已有项目", GOAL, "src", str(source))
        result = system.run_until_stop(run_id)
        assert (result.status, result.stop_reason) == ("done", "baseline_verified"), result.error
        _renamed_facts(system, run_id)
        assert system.projects.settle(run_id) is not None

        request = _project_event(system, project_id, ProjectEventType.PROJECT_DECISION_REQUESTED)
        assert request.payload["kind"] == "initial_prd"
        assert request.payload["department"] == RENAMED_PRODUCT
        assert request.payload["department"] in definitions.departments
        # 材料不变：候选的初始 PRD、结构说明、快照与基线检查照旧来自这一轮
        candidate = _project_event(system, project_id, ProjectEventType.INITIAL_PRD_PROPOSED)
        recorded = system.project(run_id)
        assert candidate.payload["prd"]["content_hash"] == recorded.product_spec.content_hash
        assert candidate.payload["structure"]["content_hash"] == recorded.structure["content_hash"]
        assert candidate.payload["snapshot"]["tree_digest"] == recorded.snapshot["tree_digest"]
        checks = candidate.payload["baseline_review"]["checks"]
        assert [check["name"] for check in checks] == ["smoke"]
        assert checks[0]["exit_code"] == 0
        assert checks[0]["command"] == VERIFIER_COMMAND, "命令取自核验角色自己的调用，不取交付部门的同名调用"
        assert candidate.payload["baseline_review"]["checks"] == request.payload["baseline_review"]["checks"]
    finally:
        system.close()


# ---------------------------------------------------------------------------
# 验收：内核修改的请求写交这份交付的部门（按交付的作者）


def _kernel_release_script() -> dict:
    # 交付改动了内核清单里的路径：结算不自动采纳，发出内核修改的决定请求
    files = {"src/echo.py": "import sys\nprint(sys.argv[1])\n", "harness/bounds.py": "# 交付改动的内核文件\n"}
    return {
        "product": [FakeTurn(proposal=product_spec())],
        "engineering": [delivery_turn(summary="改一处内核文件", files=files)],
        "quality": [explore_turn(), judgement_turn(), review_turn("release", "checks passed")],
    }


def test_the_kernel_modification_request_goes_to_the_department_that_delivered(tmp_path):
    # 验收第 2 条的另一半：改名的定义下，内核修改的请求写交这份交付的部门（这里叫构建），材料照旧
    definitions = _renamed_definitions(tmp_path)
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter(_kernel_release_script()))
    try:
        project_id = system.projects.register("改一处内核文件", GOAL)
        _work_item_id, run_id = system.projects.start_work_item(project_id, "改一处内核文件")
        result = system.run_until_stop(run_id)
        assert result.status == "done", result.error
        _renamed_facts(system, run_id)
        request = system.projects.settle(run_id)
        assert request is not None and request.type == ProjectEventType.PROJECT_DECISION_REQUESTED
        assert request.payload["kind"] == "kernel_modification"
        assert request.payload["department"] == RENAMED_ENGINEERING
        assert request.payload["department"] in definitions.departments
        assert request.payload["kernel_paths"] == ["harness/bounds.py"]
        assert request.payload["delivery_run_id"] == run_id
    finally:
        system.close()


# ---------------------------------------------------------------------------
# 验收：基线检查的命令取自核验角色这一轮的检查回执


def _run_check_event(department: str, name: str, command: str, position: int) -> Event:
    # 一条 run_check 的 tool_called 事件：这里只用事件类型、写它的部门与载荷
    return Event(
        event_id=f"evt_{position}", run_id="run_renamed", type=EventType.TOOL_CALLED, role=None,
        parent_event_id=None, state_before="running", state_after="running",
        payload={"name": "run_check", "args": {"name": name, "command": command}},
        artifact_hashes=[], session_id=f"ses_{department}", provider=None, model=None, context_digest=None,
        stop_reason=None, error=None, created_at="2026-11-03T00:00:00Z", position=position,
        stream="run:run_renamed", stream_version=position, project_id=None, work_item_id=None,
        department=department,
    )


def test_the_baseline_check_commands_come_from_the_verifier_role():
    # 验收第 2 条的最后一句：两个部门运行了同名的检查时，基线检查的命令只取核验角色这一次；
    # 别的部门后写的同名调用不改它——不按固定的部门名取，也不跨部门按「以后一次为准」取
    events = [
        _run_check_event(RENAMED_VERIFIER, "smoke", VERIFIER_COMMAND, 1),
        _run_check_event(RENAMED_ENGINEERING, "smoke", OTHER_COMMAND, 2),
    ]
    assert _check_commands(events, RENAMED_VERIFIER) == {"smoke": VERIFIER_COMMAND}
    assert _check_commands(events, RENAMED_ENGINEERING) == {"smoke": OTHER_COMMAND}
    # 旧事件没有记下核验角色（部门为空）时按原有的取法取全部调用：同一个检查以后一次调用为准
    assert _check_commands(events, None) == {"smoke": OTHER_COMMAND}
    # 核验角色的部门：接纳事件信封上的部门优先，旧事件的信封没有时取内容里的作者部门，两者都没有时为空
    accepted = replace(events[0], type=EventType.BASELINE_REVIEW_ACCEPTED)
    assert _review_department(accepted, {"issuer": RENAMED_PRODUCT}) == RENAMED_VERIFIER
    assert _review_department(None, {"artifact_issuer": RENAMED_VERIFIER}) == RENAMED_VERIFIER
    assert _review_department(None, {"issuer": RENAMED_PRODUCT}) == RENAMED_PRODUCT
    assert _review_department(None, {}) is None

# 集成测试：初始 PRD 决定请求与候选事件带上 PRD 摘要（工单 #572，接入已有项目设计说明第 3.2 节）
# 真实启动 FastAPI 应用，经 HTTP 接入已有项目并提交修改意见，模型由 FakeAdapter 回答。
# 核对第一轮与第二轮的 request.prd.summary 与 initial_prd_proposed 事件中的 prd.summary。

import uuid

from harness.adapters.fake import FakeTurn
from harness.models import ProjectEventType
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.tests.api_helpers import running_api
from harness.tests.onboarding_project import (
    OpenedFake as _Opened,
    onboarding_source as _source,
    open_initial_prd as _open_initial_prd,
    post_command as _post,
    wait_until as _wait_for,
)

GOAL = "build an echo CLI"
NOTE = "现有 CLI 还没有 --help，初始 PRD 要把这个用法说明写进去"
FIRST_REQUIREMENTS = ["print the given argument to stdout"]
FIRST_BOUNDARIES = ["do not read files"]
SECOND_REQUIREMENTS = [
    "print the given argument to stdout",
    "the CLI explains its usage when started with --help",
]
SECOND_BOUNDARIES = ["do not read files"]


def _turn_round(goal: str, requirements: list[str], boundaries: list[str]) -> list:
    return [
        FakeTurn(proposal=product_spec(goal=goal, requirements=requirements, boundaries=boundaries,
                                      acceptance=["run the CLI with a word"])),
        structure_turn(requirement_locations=[{"requirement": item, "locations": ["src/echo.py"]}
                                               for item in requirements]),
        baseline_review_turn(conclusions=[{"requirement": item, "status": "verified", "evidence": "smoke"}
                                          for item in requirements]),
    ]


def _answer(client, decision: dict, option: str, note: str | None = None):
    return client.post("/api/commands/decision.answer",
                       json={"command_id": str(uuid.uuid4()), "decision_id": decision["decision_id"],
                             "option": option, "note": note, "base_version": decision["version"]})


def test_initial_prd_decision_request_and_proposed_event_carry_summary(data_dir, tmp_path):
    # 第一轮：1 条要求、1 条边界
    # 第二轮：2 条要求、1 条边界
    turns = [
        *_turn_round(GOAL, FIRST_REQUIREMENTS, FIRST_BOUNDARIES),
        *_turn_round(GOAL, SECOND_REQUIREMENTS, SECOND_BOUNDARIES),
    ]
    opened = _Opened(data_dir, turns=turns)
    with running_api(opened) as client:
        source = _source(tmp_path / "src")
        accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                         source_name="src", source_path=str(source))
        assert accepted.status_code == 200, accepted.text
        project_id = accepted.json()["refs"]["project_id"]

        # 第一轮：等待 initial_prd 决定请求发出
        assert _wait_for(lambda: _open_initial_prd(client, project_id) is not None), \
            "第一轮 initial_prd 决定请求未发出"
        decision_1 = _open_initial_prd(client, project_id)
        assert decision_1["request"]["round"] == 1

        expected_summary_1 = f"目标：{GOAL}；要求 {len(FIRST_REQUIREMENTS)} 条；边界 {len(FIRST_BOUNDARIES)} 条"
        assert decision_1["request"]["prd"]["summary"] == expected_summary_1

        # 第一轮：核对 initial_prd_proposed 事件的 prd.summary 与请求相同
        events_1 = [e for e in opened.system.store.list_project_events(project_id)
                    if e.type == ProjectEventType.INITIAL_PRD_PROPOSED]
        assert len(events_1) == 1
        assert events_1[0].payload["prd"]["summary"] == expected_summary_1

        # 提出修改意见，触发第二轮建档
        revised = _answer(client, decision_1, "revise", NOTE)
        assert revised.status_code == 200, revised.text

        # 等待第二轮建档 run 完成
        revision_events = [e for e in opened.system.store.list_project_events(project_id)
                           if e.type == ProjectEventType.ONBOARDING_REVISION_STARTED]
        assert len(revision_events) == 1
        second_run_id = revision_events[0].payload["run_id"]
        assert _wait_for(lambda: opened.system.project(second_run_id).status == "done"), \
            "第二轮建档 run 未结束"
        assert opened.system.project(second_run_id).error is None

        # 第二轮：等待 initial_prd 决定请求发出，摘要来自第二轮 ProductSpec（要求条数变为 2）
        assert _wait_for(lambda: _open_initial_prd(client, project_id) is not None
                         and _open_initial_prd(client, project_id)["request"]["round"] == 2), \
            "第二轮 initial_prd 决定请求未发出"
        decision_2 = _open_initial_prd(client, project_id)
        assert decision_2["request"]["round"] == 2

        expected_summary_2 = f"目标：{GOAL}；要求 {len(SECOND_REQUIREMENTS)} 条；边界 {len(SECOND_BOUNDARIES)} 条"
        assert decision_2["request"]["prd"]["summary"] == expected_summary_2
        assert expected_summary_2 != expected_summary_1

        # 第二轮：核对 initial_prd_proposed 事件的 prd.summary 与请求相同
        events_2 = [e for e in opened.system.store.list_project_events(project_id)
                    if e.type == ProjectEventType.INITIAL_PRD_PROPOSED]
        assert len(events_2) == 2
        assert events_2[1].payload["prd"]["summary"] == expected_summary_2

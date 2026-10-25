# 工单 #317：建档在升级与取消时的行为（docs/design/existing-project-onboarding.md 第 6 节最后一行，
# 第 10 节第 11 项的后四段）。四个场景不用真实进程终止：run 事件版本较早的数据目录由改写事件得到
# （旧事件没有 run_event_version 字段），强制升级由真实 HTTP 命令发起，取消由 work_item.cancel 提交。
# 系统整体运行：真实启动 FastAPI 应用（uvicorn），模型回答由 FakeAdapter 给出，不使用 mock。

import uuid

from harness.collaboration import has_new_work
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeTurn
from harness.models import EventType, ProjectEventType
from harness.projection import saved_decisions
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.streams import PRIORITY_UPGRADE_RESTART, STOP_REASON_UPGRADE
from harness.tests.api_helpers import running_api
from harness.tests.helpers import merge_scripts
from harness.tests.onboarding_project import (
    ONBOARDING_GOAL as GOAL,
    ONBOARDING_REQUIREMENT as REQUIREMENT,
    OpenedFake as _Opened,
    onboarding_source as _source,
    open_initial_prd as _open_initial_prd,
    post_command as _post,
    wait_until as _wait_for,
    wait_until as _wait_run,
)

NOTE = "现有 CLI 还没有 --help，初始 PRD 要把这个用法说明写进去"
SECOND_REQUIREMENT = "the CLI explains its usage when started with --help"


def _round(requirements: list[str]) -> dict:
    # 一轮建档的三个部门：产品写初始 PRD、工程写结构说明、质检核验
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    conclusions = [{"requirement": item, "status": "verified", "evidence": "smoke"} for item in requirements]
    return {
        "product": [FakeTurn(proposal=product_spec(requirements=requirements,
                                                   acceptance=["run the CLI with a word"]))],
        "engineering": [structure_turn(requirement_locations=[{"requirement": item, "locations": ["src/echo.py"]}
                                                            for item in requirements])],
        # 质检在 PRD 被接纳以后与工程同时开始一轮工作（工单 #557）：这一轮还没有结构说明可以核验，
        # 提交的结论被拒绝（结论覆盖的不是当前 PRD 的要求）；结构说明被接纳以后质检开始新一轮核验
        "quality": [
            baseline_review_turn(conclusions=[{"requirement": "a requirement that is not in the PRD",
                                               "status": "verified", "evidence": "smoke"}]),
            baseline_review_turn(conclusions=conclusions),
        ],
    }


def _blocked_onboarding(requirements: list[str]) -> dict:
    # 建档第一轮的前半：产品提交规格以后工程部门的请求失败，run 停在非终态，可以发起强制升级
    return {
        "product": [FakeTurn(proposal=product_spec(requirements=requirements,
                                                   acceptance=["run the CLI with a word"]))],
        "engineering": [ProviderError("Missing configuration: provider credential", reason="provider_unavailable")],
        # 质检在 PRD 被接纳以后与工程同时开始一轮工作（工单 #557）：这一轮没有结构说明可以核验，结论被拒绝
        "quality": [baseline_review_turn(conclusions=[{"requirement": item, "status": "verified", "evidence": "smoke"}
                                                      for item in requirements])],
    }


def _answer(client, decision: dict, option: str, note: str | None = None):
    return client.post("/api/commands/decision.answer",
                       json={"command_id": str(uuid.uuid4()), "decision_id": decision["decision_id"],
                             "option": option, "note": note, "base_version": decision["version"]})


def _onboard(client, tmp_path):
    # 经接口层接入已有项目，等第一轮结束、结算出候选与确认请求
    source = _source(tmp_path / "src")
    accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                     source_name="src", source_path=str(source))
    assert accepted.status_code == 200, accepted.text
    refs = accepted.json()["refs"]
    assert _wait_for(lambda: _open_initial_prd(client, refs["project_id"]) is not None), \
        "第一轮没有发出确认请求"
    return refs


def test_force_upgrade_restarts_the_revision_round_with_the_same_candidate_and_note(data_dir, tmp_path):
    # 验收五（修改轮）：强制升级时进行中的建档修改轮 run 记为因升级停止，新 run 带同一份上一轮候选与修改意见，
    # 轮次不变（仍为 2）
    opened = _Opened(data_dir, turns=merge_scripts(_round([REQUIREMENT]), _blocked_onboarding([SECOND_REQUIREMENT])))
    with running_api(opened) as client:
        refs = _onboard(client, tmp_path)
        first_candidate = next(event for event in opened.system.store.list_project_events(refs["project_id"])
                               if event.type == ProjectEventType.INITIAL_PRD_PROPOSED)
        assert _answer(client, _open_initial_prd(client, refs["project_id"]), "revise", NOTE).status_code == 200
        revision = next(event for event in opened.system.store.list_project_events(refs["project_id"])
                        if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED)
        revision_run_id = revision.payload["run_id"]
        assert _wait_run(lambda: has_new_work(opened.system.project(revision_run_id), "engineering"))
        assert _post(client, "runtime.start_drain").status_code == 200
        assert _post(client, "runtime.force_upgrade").status_code == 200

        stopped = opened.system.project(revision_run_id)
        assert (stopped.status, stopped.stop_reason) == ("failed", STOP_REASON_UPGRADE)
        created = [event for event in opened.system.store.list_project_events(refs["project_id"])
                   if event.type == ProjectEventType.WORK_ITEM_CREATED]
        assert created[-1].payload["priority"] == PRIORITY_UPGRADE_RESTART
        assert created[-1].payload["kind"] == "onboarding"
        assert created[-1].payload["work_item_id"] == refs["work_item_id"], "仍然是同一个建档事项"
        restarted_run_id = created[-1].payload["run_id"]
        assert restarted_run_id != revision_run_id

        # 新 run 带同一份上一轮候选与修改意见，轮次仍是 2
        projection = opened.system.project(restarted_run_id)
        assert projection.kind == "onboarding"
        assert projection.round == 2, "修改轮重新开始以后轮次仍为 2"
        basis = projection.onboarding_basis
        assert basis is not None and basis["candidate_event_id"] == first_candidate.event_id, \
            "重新开始以后带上一轮候选"
        inputs = [event.payload["text"] for event in opened.system.store.list_events(restarted_run_id)
                  if event.type == EventType.USER_INPUT_RECEIVED]
        assert inputs == [NOTE], "修改意见仍然是这一轮的用户输入"
        assert projection.baseline is None, "建档 run 没有基线"


def test_cancelling_while_waiting_keeps_the_request_withdrawn_after_a_restart(data_dir, tmp_path):
    # 验收七：取消等待确认的建档事项以后重启，决定请求仍然是已撤销的，项目保持没有基线
    opened = _Opened(data_dir, turns=_round([REQUIREMENT]))
    with running_api(opened) as client:
        refs = _onboard(client, tmp_path)
        decision = _open_initial_prd(client, refs["project_id"])
        cancelled = _post(client, "work_item.cancel", work_item_id=refs["work_item_id"])
        assert cancelled.status_code == 200, cancelled.text
        opened.system.close()

    restarted = _Opened(data_dir, turns=[])
    with running_api(restarted) as client:
        _position, decisions = saved_decisions(restarted.system.store,
                                               projects=(refs["project_id"],), kinds=("initial_prd",))
        assert [item.status for item in decisions] == ["withdrawn"], "重启以后请求仍然是已撤销的"
        project = restarted.system.projects.projection(refs["project_id"])
        assert project.current_adoption is None, "项目保持没有基线"
        assert project.work_item(refs["work_item_id"]).status == "stopped"



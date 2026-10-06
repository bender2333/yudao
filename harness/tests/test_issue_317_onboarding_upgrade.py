# 工单 #317：建档在升级与取消时的行为（docs/design/existing-project-onboarding.md 第 6 节最后一行，
# 第 10 节第 11 项的后四段）。四个场景不用真实进程终止：run 事件版本较早的数据目录由改写事件得到
# （旧事件没有 run_event_version 字段），强制升级由真实 HTTP 命令发起，取消由 work_item.cancel 提交。
# 系统整体运行：真实启动 FastAPI 应用（uvicorn），模型回答由 FakeAdapter 给出，不使用 mock。

import json
import sqlite3
import uuid

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import EventType, ProjectEventType
from harness.projection import saved_decisions
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.streams import PRIORITY_UPGRADE_RESTART, STOP_REASON_UPGRADE
from harness.tests.api_helpers import running_api
from harness.tests.test_issue_16_recovery import _reload_without_saved_projection
from harness.tests.test_onboarding import REQUIREMENT, _source
from harness.tests.test_onboarding_confirmation_queries import _Opened, _open_initial_prd, _post, _wait_for

GOAL = "把已有项目接入 Yudao，写出初始 PRD 并核验现有行为"
NOTE = "现有 CLI 还没有 --help，初始 PRD 要把这个用法说明写进去"
SECOND_REQUIREMENT = "the CLI explains its usage when started with --help"


def _round(requirements: list[str]) -> list:
    # 一轮建档的三个部门：产品写初始 PRD、工程写结构说明、质检核验
    return [
        FakeTurn(proposal=product_spec(requirements=requirements, acceptance=["run the CLI with a word"])),
        structure_turn(requirement_locations=[{"requirement": item, "locations": ["src/echo.py"]}
                                               for item in requirements]),
        baseline_review_turn(conclusions=[{"requirement": item, "status": "verified", "evidence": "smoke"}
                                          for item in requirements]),
    ]


def _blocked_onboarding(requirements: list[str]) -> list:
    # 建档第一轮的前半：产品提交规格以后工程部门的请求失败，run 停在非终态，可以发起强制升级
    return [FakeTurn(proposal=product_spec(requirements=requirements,
                                           acceptance=["run the CLI with a word"])),
            ProviderError("Missing configuration: provider credential", reason="provider_unavailable")]


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


def _older_run_event_version(data_dir) -> None:
    # 得到一份由较早 run 事件版本写入的数据目录：run_created 事件里没有 run 事件版本字段，
    # 保存的投影也一并删掉——启动时由事件重放补建，这与较早版本留下的数据目录一致
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        rows = connection.execute(
            "SELECT event_id, payload_json FROM events WHERE type = ?", (EventType.RUN_CREATED,)).fetchall()
        assert rows, "no run_created events"
        for event_id, payload in rows:
            document = json.loads(payload)
            document.pop("run_event_version", None)
            connection.execute("UPDATE events SET payload_json = ? WHERE event_id = ?",
                               (json.dumps(document, ensure_ascii=False, sort_keys=True), event_id))
        connection.commit()
    finally:
        connection.close()
    _reload_without_saved_projection(data_dir)


def test_starting_from_an_older_version_can_confirm_the_candidate(data_dir, tmp_path):
    # 验收四（确认）：用较早 run 事件版本写入的数据目录启动，等待确认的建档候选照常显示与回答：
    # 确认以后采纳的是这一轮候选的基线
    opened = _Opened(data_dir, turns=_round([REQUIREMENT]))
    with running_api(opened) as client:
        refs = _onboard(client, tmp_path)
        opened.system.close()
    _older_run_event_version(data_dir)

    restarted = _Opened(data_dir, turns=[])
    with running_api(restarted) as client:
        decision = _open_initial_prd(client, refs["project_id"])
        assert decision is not None, "旧版本数据目录里的确认请求照常显示"
        assert _answer(client, decision, "confirm").status_code == 200
        project = restarted.system.projects.projection(refs["project_id"])
        assert project.current_adoption is not None, "确认以后项目有了基线"
        assert project.current_adoption.run_id == refs["run_id"]
        assert _open_initial_prd(client, refs["project_id"]) is None, "确认以后没有仍然打开的请求"


def test_starting_from_an_older_version_can_ask_for_a_revision(data_dir, tmp_path):
    # 验收四（提出修改）：同样用较早 run 事件版本的数据目录启动，提出修改以后开始第二轮 run，
    # 第二轮带这一轮的候选与修改意见
    opened = _Opened(data_dir, turns=[*_round([REQUIREMENT]), *_round([SECOND_REQUIREMENT])])
    with running_api(opened) as client:
        refs = _onboard(client, tmp_path)
        opened.system.close()
    _older_run_event_version(data_dir)

    restarted = _Opened(data_dir, turns=_round([SECOND_REQUIREMENT]))
    with running_api(restarted) as client:
        decision = _open_initial_prd(client, refs["project_id"])
        assert decision is not None, "旧版本数据目录里的确认请求照常显示"
        assert _answer(client, decision, "revise", NOTE).status_code == 200
        revision = next(event for event in restarted.system.store.list_project_events(refs["project_id"])
                        if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED)
        second_run_id = revision.payload["run_id"]
        assert _wait_for(lambda: restarted.system.project(second_run_id).phase == "DONE"), \
            "第二轮没有结束"
        assert restarted.system.project(second_run_id).error is None
        assert _wait_for(lambda: _open_initial_prd(client, refs["project_id"]) is not None), \
            "第二轮没有发出确认请求"


def test_force_upgrade_restarts_the_first_onboarding_round_from_the_snapshot(data_dir, tmp_path):
    # 验收五（第一轮）：强制升级时进行中的建档 run 记为因升级停止，建档事项重新开始一个 run，
    # 它从事项记录的快照开始，种类仍是建档、轮次仍是 1、没有基线
    opened = _Opened(data_dir, turns=_blocked_onboarding([REQUIREMENT]))
    with running_api(opened) as client:
        refs = _onboard_partial(client, tmp_path)
        run_id = refs["run_id"]
        assert _wait_run(lambda: opened.system.project(run_id).phase == "ENGINEERING")
        assert _post(client, "runtime.start_drain").status_code == 200
        assert _post(client, "runtime.force_upgrade").status_code == 200

        stopped = opened.system.project(run_id)
        assert (stopped.phase, stopped.stop_reason) == ("FAILED", STOP_REASON_UPGRADE)
        created = [event for event in opened.system.store.list_project_events(refs["project_id"])
                   if event.type == ProjectEventType.WORK_ITEM_CREATED]
        assert created[-1].payload["priority"] == PRIORITY_UPGRADE_RESTART
        assert created[-1].payload["kind"] == "onboarding", "重新开始的是建档事项"
        restarted_run_id = created[-1].payload["run_id"]
        assert restarted_run_id != run_id
        projection = opened.system.project(restarted_run_id)
        assert projection.kind == "onboarding"
        assert projection.round == 1, "第一轮重新开始以后轮次仍为 1"
        assert projection.baseline is None, "建档 run 没有基线"
        assert projection.snapshot is not None, "重新开始以后从快照开始"
        assert projection.snapshot == created[0].payload["snapshot"]
        assert projection.workspace_digest == projection.snapshot["tree_digest"], \
            "重新开始以后工作区摘要等于快照摘要"


def test_force_upgrade_restarts_the_revision_round_with_the_same_candidate_and_note(data_dir, tmp_path):
    # 验收五（修改轮）：强制升级时进行中的建档修改轮 run 记为因升级停止，新 run 带同一份上一轮候选与修改意见，
    # 轮次不变（仍为 2）
    opened = _Opened(data_dir, turns=[*_round([REQUIREMENT]), *_blocked_onboarding([SECOND_REQUIREMENT])])
    with running_api(opened) as client:
        refs = _onboard(client, tmp_path)
        first_candidate = next(event for event in opened.system.store.list_project_events(refs["project_id"])
                               if event.type == ProjectEventType.INITIAL_PRD_PROPOSED)
        assert _answer(client, _open_initial_prd(client, refs["project_id"]), "revise", NOTE).status_code == 200
        revision = next(event for event in opened.system.store.list_project_events(refs["project_id"])
                        if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED)
        revision_run_id = revision.payload["run_id"]
        assert _wait_run(lambda: opened.system.project(revision_run_id).phase == "ENGINEERING")
        assert _post(client, "runtime.start_drain").status_code == 200
        assert _post(client, "runtime.force_upgrade").status_code == 200

        stopped = opened.system.project(revision_run_id)
        assert (stopped.phase, stopped.stop_reason) == ("FAILED", STOP_REASON_UPGRADE)
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


def _onboard_partial(client, tmp_path):
    # 接入已有项目但不等第一轮结束：run 停在工程部门请求失败的非终态
    source = _source(tmp_path / "src")
    accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                     source_name="src", source_path=str(source))
    assert accepted.status_code == 200, accepted.text
    return accepted.json()["refs"]
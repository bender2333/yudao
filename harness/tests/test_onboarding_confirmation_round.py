# 建档确认的往返行为（工单 #136 第 3 轮，docs/design/existing-project-onboarding.md 第 3.1、3.3、3.4、
# 4.6、4.7、6 节）：修改轮经 HTTP 提交与第二轮自动运行、第三轮仍然允许、确认以后新建事项并采纳基线、
# 等待确认时取消、重启与新建与归档被拒绝、决定列表带建档材料与「说明必填」标记、查询不写事件、
# 等待确认的决定不占执行槽位也不挡住排空。系统整体运行：真实启动 FastAPI 应用（uvicorn），
# 经 HTTP 提交命令与读取查询，事件日志是真实的 SQLite 文件，模型回答由 FakeAdapter 给出。

import uuid

from harness.adapters.fake import FakeTurn
from harness.event_store import project_stream
from harness.models import EventType, ProjectEventType
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.tests.api_helpers import running_api
from harness.tests.onboarding_project import (
    ONBOARDING_GOAL as GOAL,
    ONBOARDING_REQUIREMENT as REQUIREMENT,
    OpenedFake as _Opened,
    onboarding_source as _source,
    open_initial_prd as _open_initial_prd,
    post_command as _post,
    wait_until as _wait_for,
)

NOTE = "现有 CLI 还没有 --help，初始 PRD 要把这个用法说明写进去"
SECOND_REQUIREMENT = "the CLI explains its usage when started with --help"
THIRD_REQUIREMENT = "the CLI reports its version"


def _round(requirements: list[str]) -> list:
    # 一轮建档的三个部门：产品写初始 PRD、工程写结构说明、质检核验（结论全部为已验证）
    return [
        FakeTurn(proposal=product_spec(requirements=requirements, acceptance=["run the CLI with a word"])),
        structure_turn(requirement_locations=[{"requirement": item, "locations": ["src/echo.py"]}
                                               for item in requirements]),
        baseline_review_turn(conclusions=[{"requirement": item, "status": "verified", "evidence": "smoke"}
                                          for item in requirements]),
    ]


def _two_rounds() -> list:
    return [*_round([REQUIREMENT]), *_round([REQUIREMENT, SECOND_REQUIREMENT])]


def _three_rounds() -> list:
    return [*_two_rounds(), *_round([REQUIREMENT, SECOND_REQUIREMENT, THIRD_REQUIREMENT])]


def _answer(client, decision: dict, option: str, note: str | None = None):
    return client.post("/api/commands/decision.answer",
                       json={"command_id": str(uuid.uuid4()), "decision_id": decision["decision_id"],
                             "option": option, "note": note, "base_version": decision["version"]})


def _onboard(client, tmp_path, source_name="src"):
    # 经接口层接入已有项目，等 run 结束、结算出候选与确认请求
    source = _source(tmp_path / source_name)
    accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                     source_name=source_name, source_path=str(source))
    assert accepted.status_code == 200, accepted.text
    return accepted.json()["refs"]


def _run_onboarding_http(data_dir, tmp_path, script, *, rounds: int = 0):
    # 起服务、接入已有项目、按顺序回答 rounds 次「提出修改」，每轮都等 run 结束。
    # 返回服务上下文管理器、HTTP 客户端、系统与最后一轮接入的 refs
    opened = _Opened(data_dir, turns=script)
    context = running_api(opened)
    client = context.__enter__()
    refs = _onboard(client, tmp_path)
    assert _wait_for(lambda: _request_opened(client, refs["project_id"])), "the initial PRD was not requested"
    for _ in range(rounds):
        answered = _answer(client, _open_initial_prd(client, refs["project_id"]), "revise", NOTE)
        assert answered.status_code == 200, answered.text
        run_id = next(event.payload["run_id"] for event in opened.system.store.list_project_events(
            refs["project_id"]) if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED)
        assert _wait_for(lambda: opened.system.project(run_id).phase == "DONE"), "the revision run did not stop"
        assert opened.system.project(run_id).error is None
        assert _wait_for(lambda: _request_opened(client, refs["project_id"])), "the next round was not requested"
    return context, client, opened, refs


def _request_opened(client, project_id) -> bool:
    # 确认请求是否已经发出：只用查询读取，不写事件
    decisions = client.get(f"/api/queries/decisions.list?project_id={project_id}").json()["data"]["decisions"]
    return any(item["kind"] == "initial_prd" and item["status"] == "open" for item in decisions)


def test_revision_round_trip_over_http(data_dir, tmp_path):
    # 验收（4.7 节）：修改意见经 decision.answer 提交后，同一个建档事项开始第二轮 run，
    # 第二轮 run 流的第一项输入是事项原文、第二项是修改意见，两项在 run 创建的同一步写入
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _two_rounds(), rounds=1)
    try:
        revision = [event for event in opened.system.store.list_project_events(refs["project_id"])
                    if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED]
        second_run_id = revision[0].payload["run_id"]
        events = opened.system.store.list_events(second_run_id)
        inputs = [event for event in events if event.type == EventType.USER_INPUT_RECEIVED]
        assert [event.payload["version"] for event in inputs] == [2]
        assert inputs[0].payload["text"] == NOTE
        created = next(event for event in events if event.type == EventType.RUN_CREATED)
        assert created.payload["round"] == 2
        assert created.payload["onboarding_basis"]["round"] == 2
        assert created.payload["onboarding_basis"]["note_ref"]
        # 第二轮提出的候选带着修改意见，确认请求仍然是项目流中的请求，不属于任何 run
        decision = _open_initial_prd(client, refs["project_id"])
        assert decision["run_id"] is None
        assert decision["request"]["candidate_run_id"] == second_run_id
        assert decision["request"]["round"] == 2
        assert decision["request"]["revision_note_ref"]
    finally:
        context.__exit__(None, None, None)


def test_third_revision_round_is_allowed(data_dir, tmp_path):
    # 验收（3.3 节）：修改轮没有次数上限，回答两次修改以后第三轮照常运行并给出候选
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _three_rounds(), rounds=2)
    try:
        rounds = [event.payload["round"] for event in opened.system.store.list_project_events(refs["project_id"])
                  if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED]
        assert rounds == [2, 3]
        decision = _open_initial_prd(client, refs["project_id"])
        assert decision["request"]["round"] == 3
        assert len(decision["request"]["prd"]) >= 2
    finally:
        context.__exit__(None, None, None)


def test_confirming_the_first_round_adopts_the_snapshot_as_the_baseline(data_dir, tmp_path):
    # 验收（5 节）：第一轮确认以后采纳成果就是快照本身，代码树摘要等于快照摘要，
    # 文件清单是快照里的全部文件，检查名称来自质检自己的运行，基线文本说明快照来源
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _round([REQUIREMENT]))
    try:
        decision = _open_initial_prd(client, refs["project_id"])
        assert _answer(client, decision, "confirm").status_code == 200
        overview = client.get(f"/api/queries/project.overview?project_id={refs['project_id']}").json()["data"]
        adoption = overview["current_adoption"]
        assert adoption["onboarding_baseline"] is True
        assert adoption["files"]
        assert adoption["check_names"] == ["smoke"]
        assert adoption["previous_adoption_id"] is None
        item = next(entry for entry in client.get(
            f"/api/queries/project.loop?project_id={refs['project_id']}").json()["data"]["work_items"]
            if entry["work_item_id"] == refs["work_item_id"])
        assert item["status"] == "adopted"
        # 采纳的代码树就是建档快照：快照工件的目录属于建档 run，树摘要与快照一致
        baseline = opened.system.projects.projection(refs["project_id"]).current_adoption
        assert baseline.tree_ref["path"].split("/", 1)[0] == refs["run_id"]
        assert baseline.code_tree_digest == baseline.snapshot["tree_digest"]
    finally:
        context.__exit__(None, None, None)


def test_non_git_source_records_no_provenance(data_dir, tmp_path):
    # 验收（4.1 节）：源目录不是 git 仓库时快照没有 provenance，基线文本仍然可以写出来，不因此报错
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _round([REQUIREMENT]))
    try:
        decision = _open_initial_prd(client, refs["project_id"])
        assert _answer(client, decision, "confirm").status_code == 200
        adoption = opened.system.projects.projection(refs["project_id"]).current_adoption
        assert not (adoption.snapshot.get("provenance") or {})
    finally:
        context.__exit__(None, None, None)


def test_confirming_the_second_round_adopts_and_a_new_work_item_starts(data_dir, tmp_path):
    # 验收（5 节、第 10 节第 10 项）：第二轮候选确认以后采纳的是第二轮的快照工件（属于第二轮 run），
    # 采纳以后可以新建普通事项，它的 run 从这个基线的快照开始
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _two_rounds(), rounds=1)
    try:
        decision = _open_initial_prd(client, refs["project_id"])
        assert _answer(client, decision, "confirm").status_code == 200
        revision = next(event for event in opened.system.store.list_project_events(refs["project_id"])
                        if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED)
        second_run_id = revision.payload["run_id"]
        adoption = opened.system.projects.projection(refs["project_id"]).current_adoption
        assert adoption.run_id == second_run_id
        # 快照工件属于采集它的那一轮 run：修改轮复用同一个快照，采纳时按工件路径取所属 run
        assert adoption.tree_ref["path"].split("/", 1)[0] == refs["run_id"]
        created = _post(client, "work_item.create", project_id=refs["project_id"], text="照基线改一处输出")
        assert created.status_code == 200, created.text
        run_id = created.json()["refs"]["run_id"]
        baseline = opened.system.project(run_id).baseline
        assert baseline["code_tree_digest"] == adoption.code_tree_digest
    finally:
        context.__exit__(None, None, None)


def test_cancel_while_waiting_withdraws_the_request_and_keeps_no_baseline(data_dir, tmp_path):
    # 验收（3.1 节）：等待确认时取消建档事项，写出 project_decision_withdrawn 并保留原因，
    # 事项状态为 stopped，项目没有基线采纳，也没有仍然打开的初始 PRD 请求
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _round([REQUIREMENT]))
    try:
        decision = _open_initial_prd(client, refs["project_id"])
        cancelled = _post(client, "work_item.cancel", work_item_id=refs["work_item_id"])
        assert cancelled.status_code == 200, cancelled.text
        events = [event for event in opened.system.store.list_project_events(refs["project_id"])
                  if event.type == ProjectEventType.PROJECT_DECISION_WITHDRAWN]
        assert [event.payload["reason"] for event in events] == ["user_cancelled"]
        assert events[0].payload["decision_id"] == decision["decision_id"]
        project = opened.system.projects.projection(refs["project_id"])
        assert project.current_adoption is None
        assert project.work_item(refs["work_item_id"]).status == "stopped"
        remaining = client.get(f"/api/queries/decisions.list?project_id={refs['project_id']}").json()["data"]["decisions"]
        assert [item for item in remaining if item["status"] == "open"] == []
        row = next(entry for entry in client.get("/api/queries/projects.list").json()["data"]["projects"]
                   if entry["project_id"] == refs["project_id"])
        assert row["onboarding_status"] == "awaiting_onboarding"
    finally:
        context.__exit__(None, None, None)


def test_awaiting_confirmation_blocks_restart_create_and_archive(data_dir, tmp_path):
    # 验收（3.1 节）：等待确认时重新开始建档、新建事项与归档项目都被拒绝
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _round([REQUIREMENT]))
    try:
        restarted = _post(client, "onboarding.restart", project_id=refs["project_id"], source_name="src")
        assert restarted.status_code == 409, restarted.text
        assert restarted.json()["reason"] == "not_allowed"
        created = _post(client, "work_item.create", project_id=refs["project_id"], text="等待确认时新建")
        assert created.status_code == 409, created.text
        assert created.json()["reason"] == "work_item_in_progress"
        archived = _post(client, "project.archive", project_id=refs["project_id"],
                         base_version=opened.system.writes.read(project_stream(refs["project_id"])).version)
        assert archived.status_code == 409, archived.text
        assert archived.json()["reason"] == "work_item_in_progress"
    finally:
        context.__exit__(None, None, None)


def test_decisions_list_carries_the_initial_prd_materials_and_the_note_mark(data_dir, tmp_path):
    # 验收（3.4 节）：决定列表里的建档请求带初始 PRD、结构说明、基线核验、快照与仓库概况的工件引用，
    # 「提出修改」标记说明必填，确认不要求说明
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _round([REQUIREMENT]))
    try:
        decision = _open_initial_prd(client, refs["project_id"])
        request = decision["request"]
        assert request["prd"]["prd_ref"] and request["structure"]["structure_ref"]
        assert request["overview_ref"] and request["snapshot"]["tree_ref"]
        assert request["baseline_review"]["checks"][0]["name"] == "smoke"
        assert request["snapshot"]["bytes"] > 0
        options = {item["id"]: item for item in request["options"]}
        assert options["revise"]["note_required"] is True
        assert options["confirm"]["note_required"] is False
        before = opened.system.writes.read(project_stream(refs["project_id"])).version
        rejected = _answer(client, decision, "revise")
        assert rejected.status_code == 409, rejected.text
        assert opened.system.writes.read(project_stream(refs["project_id"])).version == before
    finally:
        context.__exit__(None, None, None)


def test_queries_do_not_write_events(data_dir, tmp_path):
    # 验收（3.4 节）：确认初始 PRD 以来的查询全部只读，重复读取不写出任何事件
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _round([REQUIREMENT]))
    try:
        project_id = refs["project_id"]
        stream = project_stream(project_id)
        before = opened.system.writes.read(stream).version
        queries = ["/api/queries/projects.list",
                   f"/api/queries/project.overview?project_id={project_id}",
                   f"/api/queries/project.loop?project_id={project_id}",
                   f"/api/queries/decisions.list?project_id={project_id}",
                   f"/api/queries/work_item.materials?project_id={project_id}&work_item={refs['work_item_id']}"]
        for _ in range(2):
            for path in queries:
                assert client.get(path).status_code == 200, path
        assert opened.system.writes.read(stream).version == before
    finally:
        context.__exit__(None, None, None)


def test_waiting_decision_holds_no_slot_and_does_not_block_drain(data_dir, tmp_path):
    # 验收（3.1 节、ADR-0019）：等待确认的决定请求不占执行槽位（可以立刻建档别的项目），
    # 排空期间等待确认的决定继续挂着，解除排空以后仍然可以回答
    context, client, opened, refs = _run_onboarding_http(data_dir, tmp_path, _round([REQUIREMENT]))
    try:
        assert opened.system.orchestrator.busy() is False
        other = _post(client, "project.create", name="第二个项目", goal=GOAL)
        assert other.status_code == 200, other.text
        drain = _post(client, "runtime.start_drain")
        assert drain.status_code == 200, drain.text
        assert _wait_for(lambda: opened.system.drain.version >= 1)
        decision = _open_initial_prd(client, refs["project_id"])
        assert decision["status"] == "open"
        assert decision["blocked"]["work_item_id"] == refs["work_item_id"]
        assert opened.system.orchestrator.busy() is False
    finally:
        context.__exit__(None, None, None)

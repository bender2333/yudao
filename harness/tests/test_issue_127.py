# 工单 #127：系统首页的后端（离开期间的报告、已看过、决定列表与状态项、接口版本、按位置读取）。
# 数据目录是真实的 SQLite 事件日志，运行经真实的 LoopSystem，模型回答由 FakeAdapter 脚本给出；
# 事件日志、工件与工作区都是真实实现，不使用模拟对象。查询不写入事件这一点在模块层与接口层都核对。

import uuid

import pytest
from pydantic import ValidationError

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.decision_queries import DecisionsList
from harness.app.home import AwayReportRequest
from harness.app.project_queries import ProjectLoop, ProjectsList
from harness.app.system_queries import LiveAttemptRequest, SystemStatusRequest
from harness.models import CatalogEventType, Usage
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import happy_script

GOAL = "把文本按行处理清楚"

def _system(data_dir, script=None):
    return LoopSystem.for_testing(data_dir, FakeAdapter(script if script is not None else happy_script()))

def _run_once(system) -> tuple[str, str, str]:
    project_id = system.projects.register("首页", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    return project_id, work_item_id, run_id

def _unavailable_script():
    # 产品提交规格以后，工程部门的请求被报告为不可用；run 停在这次请求上，产生一个等待回答的决定请求
    return [FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20)),
            ProviderError("model reference is unavailable", reason="provider_unavailable")]

# ---------------------------------------------------------------------------
# 按位置读取（回放）

def test_replaying_to_a_position_returns_that_position_and_excludes_later_objects(data_dir):
    system = _system(data_dir)
    project_id, _work_item_id, _run_id = _run_once(system)
    application = Application(system)
    position = application.query("projects.list", ProjectsList()).position
    # 这个位置以后才出现的项目：由真实写入口再建一个（它落在 position 之后）
    later_project = system.projects.register("更晚的项目", GOAL)
    assert system.store.end_position() > position
    replayed = application.query("projects.list", ProjectsList(at=position))
    assert replayed.position == position
    ids = {row.project_id for row in replayed.data.projects}
    assert later_project not in ids and project_id in ids

def test_the_same_position_reads_the_same_result_and_writes_nothing(data_dir):
    system = _system(data_dir)
    _run_once(system)
    application = Application(system)
    at = application.query("projects.list", ProjectsList()).position
    first = application.query("projects.list", ProjectsList(at=at))
    again = application.query("projects.list", ProjectsList(at=at))
    assert first.model_dump() == again.model_dump()
    assert first.position == at
    assert system.store.end_position() == at  # 回放没有写入

def test_at_beyond_the_log_end_is_refused(data_dir):
    system = _system(data_dir)
    _run_once(system)
    application = Application(system)
    end = system.store.end_position()
    for name, request in (("projects.list", ProjectsList(at=end + 1)),
                          ("decisions.list", DecisionsList(at=end + 1)),
                          ("project.loop", ProjectLoop(project_id="missing", at=end + 1))):
        with pytest.raises(Exception) as caught:
            application.query(name, request)
        assert type(caught.value).__name__ == "ReplayOutOfRange", name

def test_a_query_that_is_not_replayable_refuses_at_by_its_contract(data_dir):
    # attempt.live 的请求合同不接受 at：多出的字段被 pydantic 拒绝
    with pytest.raises(ValidationError):
        LiveAttemptRequest(attempt_id="x", at=1)

# ---------------------------------------------------------------------------
# 离开期间的报告与已看过

def test_away_report_summarises_real_events_with_sources_and_omits_empty_items(data_dir):
    system = _system(data_dir)
    project_id, work_item_id, _run_id = _run_once(system)
    application = Application(system)
    report = application.query("home.away_report", AwayReportRequest(range="24h")).data
    released = next(item for item in report.summary if item.id == "released")
    assert released.value == 1 and released.refs
    ends = {event.position for event in system.store.read(after=0, limit=100000)}
    for item in report.summary:
        assert item.refs and all(ref in ends for ref in item.refs)
    # 没有来源的项不返回：本工单没有 Stage 4 的事件，故障等项不出现
    assert {item.id for item in report.summary} == {"released"}
    assert all(fact.project_id in (None, project_id) for fact in report.facts)
    assert any(fact.work_item_id == work_item_id for fact in report.facts)

def test_mark_seen_updates_the_since_seen_range_and_survives_a_restart(data_dir):
    system = _system(data_dir)
    _run_once(system)
    application = Application(system)
    end = system.store.end_position()
    assert system.mark_seen(end) == end
    report = application.query("home.away_report", AwayReportRequest(range="since_seen")).data
    assert report.last_seen.position == end
    assert report.range.from_position == end
    assert all(fact.position > end for fact in report.facts)
    system.close()
    reopened = Application(LoopSystem.for_testing(data_dir, FakeAdapter([])))
    again = reopened.query("home.away_report", AwayReportRequest(range="since_seen")).data
    assert again.last_seen.position == end and again.range.from_position == end
    reopened.close()

# ---------------------------------------------------------------------------
# 决定列表与状态项

def test_system_status_home_items_match_the_waiting_decisions(data_dir):
    system = _system(data_dir, _unavailable_script())
    project_id = system.projects.register("待决定", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = Application(system)
    status = application.query("system.status", SystemStatusRequest()).data
    decisions = application.query("decisions.list", DecisionsList(status=["open"])).data
    assert status.home.waiting_decisions == len(decisions.decisions) == 1
    blocked = decisions.decisions[0].blocked
    assert blocked is not None and blocked.work_item_id == work_item_id and blocked.queued_after == 0

def test_system_status_replays_the_waiting_count_to_a_position(data_dir):
    system = _system(data_dir, _unavailable_script())
    project_id = system.projects.register("待决定", GOAL)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    before = system.store.end_position()
    system.run_until_stop(run_id)
    application = Application(system)
    now = application.query("system.status", SystemStatusRequest()).data
    past = application.query("system.status", SystemStatusRequest(at=before)).data
    assert now.home.waiting_decisions == 1 and past.home.waiting_decisions == 0

# ---------------------------------------------------------------------------
# 接口层：路由、422 与能力清单

class _Opened:
    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, FakeAdapter([])),
                                  registry=DEFAULT_REGISTRY)
        self.applications.append(application)
        return application

    @property
    def store(self):
        return self.applications[-1].system.store

def _post(client, command, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})

def test_replayable_queries_accept_at_over_http_and_refuse_values_beyond_the_end(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        created = _post(client, "project.create", name="回放", goal=GOAL)
        assert created.status_code == 200, created.text
        end = opened.store.end_position()
        for name in ("projects.list", "decisions.list", "system.status"):
            response = client.get(f"/api/queries/{name}", params={"at": end})
            assert response.status_code == 200, (name, response.text)
            assert response.json()["position"] == end
        assert client.get("/api/queries/projects.list", params={"at": end + 1}).status_code == 422
        # 不可回放的查询带 at：请求合同 extra=forbid，接口返回 422
        assert client.get("/api/queries/attempt.live",
                          params={"attempt_id": "x", "at": 1}).status_code == 422

def test_mark_seen_is_a_command_and_updates_the_away_report(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        created = _post(client, "project.create", name="首页", goal=GOAL)
        project_id = created.json()["refs"]["project_id"]
        _post(client, "work_item.create", project_id=project_id, text="做一件事")
        end = opened.store.end_position()
        marked = client.post("/api/commands/home.mark_seen",
                             json={"command_id": str(uuid.uuid4()), "position": end})
        assert marked.status_code == 200, marked.text
        assert marked.json()["refs"] == {}
        report = client.get("/api/queries/home.away_report", params={"range": "since_seen"}).json()["data"]
        assert report["last_seen"]["position"] == end
        assert report["range"]["from_position"] == end

def test_capabilities_mark_replayable_queries_and_expose_the_interface_version(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        capabilities = client.get("/api/capabilities").json()
        document = client.get("/openapi.json").json()
    assert {item["name"] for item in capabilities["queries"] if item["replayable"]} == {
        "system.status", "projects.list", "decisions.list", "project.loop"}
    for name in ("system.status", "projects.list", "decisions.list", "project.loop"):
        parameters = document["paths"][f"/api/queries/{name}"]["get"]["parameters"]
        assert any(item["name"] == "at" for item in parameters), name
    deployment = capabilities["deployment"]
    assert deployment["api_version"] == 1
    assert deployment["access"] == "local"
    assert deployment["contract_digest"]
    assert "home.away_report" in {item["name"] for item in capabilities["queries"]}
    assert "home.mark_seen" in {item["name"] for item in capabilities["commands"]}
    assert CatalogEventType.HOME_SEEN in capabilities["event_types"]

# 修改项目的长期目标（工单 #203，应用层与接口层设计说明第 3.2 节与第 10 节第 12 项）：
# 经 project.set_goal 把修改写成项目流事件 project_goal_changed；基准版本过期时拒绝。
# 创建 run 时在 run_created 中记下当时的长期目标（钉住的项目上下文），之后开始的事项使用新目标，
# 进行中的事项按开始时的目标做完。项目概览、项目列表与项目设置返回修改以后的目标。

import uuid

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.models import ArtifactRef, ProjectEventType
from harness.projects import project_projection
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import quality_turns

OLD_GOAL = "最初的长期目标。"
NEW_GOAL = "修改以后的长期目标。"

def _post(client, command: str, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})

class _Opened:
    # 服务生命周期中建立的应用层：模型回答由测试给出的脚本提供，事件日志是真实的 SQLite 文件
    def __init__(self, data_dir, adapter) -> None:
        self.data_dir = data_dir
        self.adapter = adapter
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        system = LoopSystem.for_testing(self.data_dir, self.adapter)
        application = Application(system)
        self.applications.append(application)
        return application

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system

    @property
    def store(self):
        return self.applications[-1].system.store

def _request_has_goal(adapter, run_id, goal):
    matched = []
    for invocation in adapter.invocations:
        if invocation.run_id != run_id:
            continue
        text = invocation.input_items[0]["content"]
        if f"长期目标：{goal}" in text:
            matched.append(invocation)
    return matched

def test_set_goal_writes_the_project_event_and_updates_the_queries(data_dir):
    opened = _Opened(data_dir, FakeAdapter([]))
    with running_api(opened) as client:
        created = _post(client, "project.create", name="目标项目", goal=OLD_GOAL)
        assert created.status_code == 200
        project_id = created.json()["refs"]["project_id"]

        # 基准版本过期：返回 409、stale_base 与当前版本，没有写入事件
        stale = client.post("/api/commands/project.set_goal", json={
            "command_id": str(uuid.uuid4()), "base_version": 999, "project_id": project_id, "goal": NEW_GOAL})
        assert stale.status_code == 409
        assert stale.json()["reason"] == "stale_base"
        assert stale.json()["current_version"] == 1
        assert [event.type for event in opened.store.list_project_events(project_id)] == [
            ProjectEventType.PROJECT_REGISTERED]

        accepted = client.post("/api/commands/project.set_goal", json={
            "command_id": str(uuid.uuid4()), "base_version": 1, "project_id": project_id, "goal": NEW_GOAL})
        assert accepted.status_code == 200

        events = opened.store.list_project_events(project_id)
        assert [event.type for event in events] == [
            ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_GOAL_CHANGED]
        changed = events[-1].payload
        assert changed["goal"] == NEW_GOAL
        assert opened.system.artifacts.get_for_run(
            project_id, ArtifactRef(**changed["goal_ref"])).decode("utf-8") == NEW_GOAL

        # 保存的投影与从事件重放的投影一致
        saved = opened.system.projects.projection(project_id)
        assert saved.goal == NEW_GOAL
        replayed = project_projection(opened.store, opened.system.artifacts, project_id)
        assert replayed.goal == NEW_GOAL
        assert replayed.canonical_state() == saved.canonical_state()

        # 项目列表、项目概览与项目设置返回修改以后的目标
        listing = client.get("/api/queries/projects.list", params={}).json()["data"]["projects"]
        assert [row for row in listing if row["project_id"] == project_id][0]["goal"] == NEW_GOAL
        overview = client.get("/api/queries/project.overview", params={"project_id": project_id}).json()["data"]
        assert overview["goal"] == NEW_GOAL
        settings = client.get("/api/queries/project.settings", params={"project_id": project_id}).json()["data"]
        assert settings["goal"] == NEW_GOAL


def test_archived_project_refuses_set_goal(data_dir):
    opened = _Opened(data_dir, FakeAdapter([]))
    with running_api(opened) as client:
        created = _post(client, "project.create", name="归档项目", goal=OLD_GOAL)
        project_id = created.json()["refs"]["project_id"]
        archived = client.post("/api/commands/project.archive", json={
            "command_id": str(uuid.uuid4()), "base_version": 1, "project_id": project_id})
        assert archived.status_code == 200
        refused = client.post("/api/commands/project.set_goal", json={
            "command_id": str(uuid.uuid4()), "base_version": 2, "project_id": project_id, "goal": NEW_GOAL})
        assert refused.status_code == 409
        assert refused.json()["reason"] == "project_archived"


def _mixed_script():
    # 事项 A 的产品规格提交以后，工程的请求被提供方报告为不可用：run A 停在这次请求之前（未终态）。
    # 事项 B 的脚本与 A 相同，用来核对 B 的请求使用修改以后的目标
    from harness.adapters.base import ProviderError
    from harness.adapters.fake import FakeTurn
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "product": [FakeTurn(proposal=product_spec())],
        "engineering": [ProviderError("Missing configuration: provider credential",
                                       reason="provider_unavailable")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def test_new_work_items_use_the_new_goal_and_in_progress_items_keep_the_old(data_dir):
    adapter = FakeAdapter({
        "product": [*_mixed_script()["product"], *_mixed_script()["product"]],
        "engineering": [*_mixed_script()["engineering"], *_mixed_script()["engineering"]],
        "quality": [*_mixed_script()["quality"], *_mixed_script()["quality"]],
    })
    system = LoopSystem.for_testing(data_dir, adapter)
    project_id = system.projects.register("目标项目", OLD_GOAL)

    # 事项 A 开始并停在进行中，它的请求使用开始时的目标
    _work_a, run_a = system.projects.start_work_item(project_id, "事项 A")
    assert has_new_work(system.run_until_stop(run_a), "engineering")
    assert _request_has_goal(adapter, run_a, OLD_GOAL)
    assert not _request_has_goal(adapter, run_a, NEW_GOAL)

    # 修改长期目标
    system.projects.set_goal(project_id, NEW_GOAL)

    # 修改之前已经开始的事项：钉住的项目上下文仍是开始时的目标
    run_a_after = system.project(run_a)
    assert run_a_after.project_context_ref is not None
    context_text = system.artifacts.get_for_run(
        run_a, ArtifactRef(**run_a_after.project_context_ref)).decode("utf-8")
    assert f"长期目标：{OLD_GOAL}" in context_text
    assert f"长期目标：{NEW_GOAL}" not in context_text

    # 修改以后新建的事项：部门请求中的项目上下文是新目标
    _work_b, run_b = system.projects.start_work_item(project_id, "事项 B")
    assert has_new_work(system.run_until_stop(run_b), "engineering")
    assert _request_has_goal(adapter, run_b, NEW_GOAL)
    assert not _request_has_goal(adapter, run_b, OLD_GOAL)


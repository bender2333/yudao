# 项目的起始文件夹（工单 #321，项目的起始文件夹设计说明第 2 至 4、7、8 节）：
# project.create 带 initial_directory 时项目流中的 project_registered 带 initial_snapshot；
# 采集失败以 source_invalid 拒绝且没有项目与事件；没有采纳成果时事项从起始文件夹快照开始，
# 第一次采纳以后起点是采纳成果；因升级重新开始的事项带着起始文件夹重新开始；
# 起点的求法只在 ProjectService._work_item_start_point 一处，三种情形各一个用例。

import time
import uuid

import pytest

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.models import ArtifactRef, ProjectEventType
from harness.projection import project_run
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.public_tree import TreeError, capture_public_tree
from harness.event_store import run_stream
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import happy_script

GOAL = "把起点文件夹里的数据用到第一个事项的交付里。"
TEXT = "用起始文件夹里的数据文件改一处代码"


def _initial_directory(tmp_path, files=None):
    root = tmp_path / "initial"
    root.mkdir()
    (root / "data.json").write_text('{"rows": 3}\n', encoding="utf-8")
    (root / "README.md").write_text("起点文件夹\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('start')\n", encoding="utf-8")
    for name, text in (files or {}).items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def _blocked_script():
    # 产品提交规格以后工程部门的请求失败：run 停在非终态，用来检查排空期间排队的事项
    from harness.adapters.base import ProviderError
    return [product_spec(), ProviderError("Missing configuration: provider credential",
                                          reason="provider_unavailable")]

def _opened(data_dir, script=None):
    return LoopSystem.for_testing(data_dir, FakeAdapter(script or happy_script()))


class _Opened:
    # 服务生命周期中建立的应用层：真实启动 FastAPI 应用，经 HTTP 提交命令与读取查询
    def __init__(self, data_dir, adapter=None) -> None:
        self.data_dir = data_dir
        self.adapter = adapter if adapter is not None else FakeAdapter(happy_script())
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, self.adapter))
        self.applications.append(application)
        return application

    @property
    def store(self):
        return self.applications[-1].system.store


def _adopt(system, project_id, run_id):
    # 把一个跑到 DONE 的 run 结算到采纳：结算写在 RUN_DONE 之后，这里显式补做
    assert system.run_until_stop(run_id).phase == "DONE"
    system.projects.settle_pending(project_id)


def _post(client, command, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})


def _overview(client, project_id):
    body = client.get("/api/queries/project.overview", params={"project_id": project_id}).json()
    return body["data"]


# ---------------------------------------------------------------------------
# 命令：project.create 的 initial_directory

def test_create_with_initial_directory_records_the_snapshot_in_the_project_stream(data_dir, tmp_path):
    source = _initial_directory(tmp_path)
    expected = capture_public_tree(source).digest
    system = _opened(data_dir)
    project_id = system.projects.register("带起点的项目", GOAL, initial_directory=str(source))
    events = system.store.list_project_events(project_id)
    assert [event.type for event in events] == [ProjectEventType.PROJECT_REGISTERED]
    snapshot = events[0].payload["initial_snapshot"]
    assert snapshot["tree_digest"] == expected
    assert snapshot["source"] == str(source.absolute())
    assert sorted(snapshot["files"]) == ["README.md", "data.json", "src/app.py"]
    # 快照的工件所属范围是项目（与 project_goal 相同），不属于任何 run
    assert snapshot["tree_ref"]["path"].startswith(f"{project_id}/")
    system.close()


def test_create_without_initial_directory_leaves_the_event_as_it_was(data_dir, tmp_path):
    system = _opened(data_dir)
    project_id = system.projects.register("普通项目", GOAL)
    event = system.store.list_project_events(project_id)[0]
    assert "initial_snapshot" not in event.payload
    assert system.projects.projection(project_id).initial_snapshot is None
    assert system.projects.projection(project_id).source == "idea"
    system.close()


def test_a_project_registered_event_without_the_field_reads_back_as_no_initial_directory(data_dir):
    # 旧版本写入的 project_registered 没有 initial_snapshot：读回为没有起始文件夹（ADR-0019）
    from dataclasses import asdict
    from harness.artifacts import ArtifactStore
    from harness.event_store import EventStore, project_stream
    from harness.models import new_id
    from harness.project_projection import handler_for, saved_project
    from harness.write_path import NewProjectEvent, WritePath

    store = EventStore(data_dir / "events.sqlite")
    artifacts = ArtifactStore(data_dir / "artifacts")
    writes = WritePath(store, handler_for)
    try:
        project_id = new_id("proj")
        goal_ref = artifacts.put(project_id, "project_goal", GOAL, media_type="text/markdown")

        def legacy(transaction):
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_REGISTERED, {
                "name": "旧项目", "goal": GOAL, "goal_ref": asdict(goal_ref), "source": "idea",
            }, actor="user:local"))

        writes.transact(project_stream(project_id), legacy, expected_version=0)
        state = saved_project(store, project_id)
        assert state.initial_snapshot is None
    finally:
        store.close()


@pytest.mark.parametrize("broken", ["private_path", "missing_directory"])
def test_an_unusable_initial_directory_is_rejected_and_writes_nothing(data_dir, tmp_path, broken):
    source = _initial_directory(tmp_path)
    target = str(source)
    if broken == "private_path":
        (source / ".checks").mkdir()
    else:
        target = str(tmp_path / "does_not_exist")
    system = _opened(data_dir)
    before = system.store.list_project_ids()
    with pytest.raises(TreeError):
        system.projects.register("被拒绝的项目", GOAL, initial_directory=target)
    # 没有建立项目，也没有写入任何事件
    assert system.store.list_project_ids() == before
    system.close()


# ---------------------------------------------------------------------------
# 起点：没有采纳成果时是起始文件夹快照

def test_the_first_work_item_starts_from_the_initial_directory(data_dir, tmp_path):
    source = _initial_directory(tmp_path)
    expected = capture_public_tree(source).digest
    system = _opened(data_dir)
    project_id = system.projects.register("带起点的项目", GOAL, initial_directory=str(source))
    _work_item_id, run_id = system.projects.start_work_item(project_id, TEXT)
    item = system.projects.projection(project_id).work_items[0]
    # 事项种类仍是 change，基线为空，快照记录随 work_item_created 写入
    assert item.kind == "change"
    assert item.baseline is None
    assert item.snapshot["tree_digest"] == expected
    # run 的工作区含起始文件夹的全部文件
    workspace = system.workspace(run_id)
    assert (workspace.root / "data.json").read_text(encoding="utf-8") == '{"rows": 3}\n'
    assert (workspace.root / "README.md").read_text(encoding="utf-8") == "起点文件夹\n"
    assert (workspace.root / "src" / "app.py").read_text(encoding="utf-8") == "print('start')\n"
    system.close()


def test_after_the_first_adoption_the_start_point_is_the_adopted_tree(data_dir, tmp_path):
    source = _initial_directory(tmp_path)
    system = _opened(data_dir)
    project_id = system.projects.register("带起点的项目", GOAL, initial_directory=str(source))
    # 第一个事项开始以后删掉起始文件夹里的一个文件：交付的代码树不带它，
    # 采纳以后下一个事项的起点是采纳成果，因此工作区里没有这个文件
    first_work_item, first_run = system.projects.start_work_item(project_id, TEXT)
    (system.workspace(first_run).root / "data.json").unlink()
    _adopt(system, project_id, first_run)
    assert system.projects.projection(project_id).current_adoption is not None
    _second_work_item, second_run = system.projects.start_work_item(project_id, "第二件事项")
    item = next(entry for entry in system.projects.projection(project_id).work_items
                if entry.run_id == second_run)
    assert item.baseline is not None
    assert item.baseline["source_run_id"] == first_run
    assert item.snapshot is None
    workspace = system.workspace(second_run)
    assert not (workspace.root / "data.json").exists()
    assert (workspace.root / "src" / "app.py").exists()
    system.close()


def test_the_start_point_function_serves_the_three_call_sites(data_dir, tmp_path):
    # 三种情形各一个用例：有采纳成果、没有采纳成果且有起始文件夹快照、两者都没有
    source = _initial_directory(tmp_path)
    system = _opened(data_dir)
    # 情形一：两者都没有 → 空树
    empty_project = system.projects.register("空项目", GOAL)
    empty_point = system.projects._work_item_start_point(system.projects.projection(empty_project))
    assert empty_point.baseline is None and empty_point.initial_tree is None and empty_point.snapshot is None
    # 情形二：没有采纳成果且有起始文件夹快照 → 快照记录与它的初始树，基线为空
    snapshot_project = system.projects.register("带起点的项目", GOAL, initial_directory=str(source))
    snapshot_point = system.projects._work_item_start_point(system.projects.projection(snapshot_project))
    assert snapshot_point.baseline is None and snapshot_point.source_run is None
    assert snapshot_point.snapshot["tree_digest"] == capture_public_tree(source).digest
    assert snapshot_point.initial_tree.digest == capture_public_tree(source).digest
    # 情形三：有采纳成果 → 采纳成果的基线与代码树，不用起始文件夹快照
    adopted_work_item, adopted_run = system.projects.start_work_item(snapshot_project, TEXT)
    _adopt(system, snapshot_project, adopted_run)
    adopted_point = system.projects._work_item_start_point(system.projects.projection(snapshot_project))
    assert adopted_point.snapshot is None
    assert adopted_point.baseline["source_run_id"] == adopted_run
    assert adopted_point.initial_tree.digest == adopted_point.baseline["code_tree_digest"]
    system.close()


def test_the_first_item_restarts_for_upgrade_with_the_initial_directory(data_dir, tmp_path):
    # 因升级重新开始的第一个事项（没有采纳成果）带着起始文件夹重新开始（排空期间的强制升级）
    source = _initial_directory(tmp_path)
    script = [product_spec(), ProviderError("Missing configuration: provider credential",
                                           reason="provider_unavailable")]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    project_id = system.projects.register("带起点的项目", GOAL, initial_directory=str(source))
    _work_item_id, run_id = system.projects.start_work_item(project_id, TEXT)
    system.run_until_stop(run_id)
    system.start_drain()
    system.force_upgrade()
    restarted = [item for item in system.projects.projection(project_id).work_items if item.run_id != run_id]
    assert len(restarted) == 1
    workspace = system.workspace(restarted[0].run_id)
    assert (workspace.root / "data.json").exists()
    assert (workspace.root / "src" / "app.py").exists()
    system.close()


# ---------------------------------------------------------------------------
# 中断：run 创建之前终止进程

def test_a_run_missing_after_an_interruption_is_rebuilt_from_the_record(data_dir, tmp_path):
    # work_item_created 已提交而 run 还没有创建时进程中断：事务提交以后 run 流仍然为空，
    # 重启以后按事项的快照记录建立缺少的 run，它含起始文件夹的文件
    source = _initial_directory(tmp_path)
    expected = capture_public_tree(source).digest
    system = _opened(data_dir)
    project_id = system.projects.register("带起点的项目", GOAL, initial_directory=str(source))
    real_create_run = system.orchestrator.create_run

    def crash_before_run(*args, **kwargs):
        raise RuntimeError("进程在 run 创建之前终止")

    system.orchestrator.create_run = crash_before_run
    with pytest.raises(RuntimeError, match="进程在 run 创建之前终止"):
        system.projects.start_work_item(project_id, TEXT)
    system.orchestrator.create_run = real_create_run
    item = system.projects.projection(project_id).work_items[0]
    work_item_id, run_id = item.work_item_id, item.run_id
    assert system.store.stream_events(run_stream(run_id), after_version=0) == []
    system.close()
    reopened = _opened(data_dir)
    assert reopened.recovered_work_item_runs == [run_id]
    workspace = reopened.workspace(run_id)
    assert (workspace.root / "data.json").read_text(encoding="utf-8") == '{"rows": 3}\n'
    assert (workspace.root / "src" / "app.py").read_text(encoding="utf-8") == "print('start')\n"
    run = project_run(reopened.store, run_id)
    assert run.phase != "FAILED"
    assert reopened.projects.projection(project_id).work_item(work_item_id).snapshot["tree_digest"] == expected
    reopened.close()

def test_a_queued_work_item_is_not_treated_as_a_run_missing_after_an_interruption(data_dir, tmp_path):
    # 排空期间排队的事项登记在项目流里而 run 流为空，与进程中断留下的事项在数据上相同。
    # 区别在于排空：排空没有结束时启动核对不补建排队事项的 run，它们按设计等升级完成以后才开始
    source = _initial_directory(tmp_path)
    system = _opened(data_dir, _blocked_script())
    project_id = system.projects.register("排空项目", GOAL, initial_directory=str(source))
    _first_item, running_run = system.projects.start_work_item(project_id, TEXT)
    system.activate_once(running_run)
    assert system.running_runs == 1
    assert system.start_drain().state == "draining"
    queued_work_item = system.projects.queue_work_item(project_id, "排队的事项")
    queued_run = system.projects.projection(project_id).work_item(queued_work_item).run_id
    assert system.store.stream_events(run_stream(queued_run), after_version=0) == []
    system.close()

    reopened = _opened(data_dir, _blocked_script())
    # 排队的事项仍然排队：没有被补建的 run，也没有开始执行
    assert reopened.recovered_work_item_runs == []
    assert reopened.store.stream_events(run_stream(queued_run), after_version=0) == []
    assert reopened.projects.projection(project_id).work_item(queued_work_item).status == "not_started"
    reopened.close()


# ---------------------------------------------------------------------------
# 查询与接口

def test_project_overview_reports_the_start_point_until_the_first_adoption(data_dir, tmp_path):
    source = _initial_directory(tmp_path)
    system = _opened(data_dir)
    project_id = system.projects.register("带起点的项目", GOAL, initial_directory=str(source))
    system.close()

    opened = _Opened(data_dir)
    with running_api(opened) as client:
        overview = _overview(client, project_id)
        assert overview["start_point"] == "起点：起始文件夹（3 个文件）"
        assert opened.store.list_project_events(project_id)[0].payload["initial_snapshot"]["tree_digest"] \
            == capture_public_tree(source).digest


def test_the_create_command_rejects_an_unreadable_directory_with_source_invalid(data_dir, tmp_path):
    with running_api(_Opened(data_dir)) as client:
        missing = tmp_path / "nope"
        response = _post(client, "project.create", name="被拒绝的项目", goal=GOAL,
                         initial_directory=str(missing))
        assert response.status_code == 409
        assert response.json()["reason"] == "source_invalid"
        assert response.json()["message"]
        # 没有建立项目
        assert client.get("/api/queries/projects.list").json()["data"]["projects"] == []


def test_the_create_command_accepts_an_initial_directory_over_http(data_dir, tmp_path):
    source = _initial_directory(tmp_path)
    with running_api(_Opened(data_dir)) as client:
        response = _post(client, "project.create", name="带起点的项目", goal=GOAL,
                         initial_directory=str(source))
        assert response.status_code == 200
        project_id = response.json()["refs"]["project_id"]
        overview = _overview(client, project_id)
        assert overview["start_point"] == "起点：起始文件夹（3 个文件）"
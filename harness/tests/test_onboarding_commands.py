# 接入已有项目的命令与建档事项的开始（3.8，工单 #135，设计说明第 2、3.1、3.3、3.4、4.6 节）。
# 测试从运行的系统整体进行：真实启动 FastAPI 应用（uvicorn），经 HTTP 提交命令、读取查询；
# 控制核心在服务生命周期中建立，事件日志是真实的 SQLite 文件，模型回答由 FakeAdapter 给出。

import os
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.models import TERMINAL_STATUSES, ProjectEventType
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

GOAL = "把已有项目接入 Yudao，写出初始 PRD 并核验现有行为"
REQUIREMENT = "print the given argument to stdout"

def _source(root: Path) -> Path:
    # 一份最小的已有项目：一个可运行的脚本、一个说明文件与一个通过的测试
    (root / "src").mkdir(parents=True)
    (root / "src" / "echo.py").write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    (root / "README.md").write_text("# Echo\n\nPrint the given argument.\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_echo.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    return root

def _onboarding_script(rounds: int = 4):
    # 三个部门的建档脚本；脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）。
    # rounds 是每个部门准备几条回答：同一部门的回答相同，条数只决定「够不够用」。
    # 一次建档 run 里同一部门可能被唤醒不止一次（工单 #1250）：质检的基线核验要覆盖工程的现有结构说明，
    # 工程的结构说明还没被接纳时先做的那一次不被接受，结构说明到了以后质检再被唤醒一次。
    # 这个先后由调度决定，不总是同一边。用例里有两次建档（project.onboard 与 onboarding.restart），
    # 所以按 2 次 run × 2 次质检唤醒准备 4 条；用不完的留在脚本里，不影响任何断言。
    def round_turns():
        return {
            "product": [FakeTurn(proposal=product_spec(requirements=[REQUIREMENT],
                                                       acceptance=["run the CLI with a word"]))],
            "engineering": [structure_turn(requirement_locations=[{"requirement": REQUIREMENT,
                                                                 "locations": ["src/echo.py"]}])],
            "quality": [baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "verified",
                                                           "evidence": "smoke"}])],
        }
    script: dict[str, list] = {}
    for _ in range(rounds):
        for department, turns in round_turns().items():
            script.setdefault(department, []).extend(turns)
    return script

class _Opened:
    def __init__(self, data_dir, adapter=None) -> None:
        self.data_dir = data_dir
        self.adapter = FakeAdapter(_onboarding_script()) if adapter is None else adapter
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        system = LoopSystem.for_testing(self.data_dir, self.adapter)
        application = Application(system)
        self.applications.append(application)
        return application

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system

def _post(client, command, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})

# 等待一次建档 run 结束（`_wait_for`）的墙钟界限只用来防止测试一直等待，按 #107 的裁定
# （架构师 2026-09-27 16:55，docs/archive/architecture-issues-2026-09-10.md）设为远大于正常用时的值。
# 建档 run 含多次版本存储写入，正常用时数秒、并发负载下更慢；
# run 是否按预期结束由等待之后的阶段与停止原因断言核对。
#
# 上限取集中的等待上限（harness/tests/wait_limits.py）：它比集成层给每条用例的上限短，
# 卡住时在这里报成一条失败，不等 pytest-timeout 结束整个进程（工单 #1250 的登记）
_WAIT_LIMIT = WAIT_FOR_HOST_WORK_SEC


def _wait_for(predicate, timeout=_WAIT_LIMIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _wait_for_run_end(opened, run_id, timeout=_WAIT_LIMIT) -> bool:
    # 等一次 run 走到终点（done / paused / failed），它按预期结束与否由调用方随后的断言核对。
    # 不只等 done：run 以失败或暂停结束时，只等 done 的那条会一直空转到 _WAIT_LIMIT。
    return _wait_for(lambda: opened.system.project(run_id).status in TERMINAL_STATUSES, timeout)


def _git_init(root: Path) -> None:
    environment = {
        **{key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")},
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    }
    for argv in (["git", "-C", str(root), "init", "-q"],
                 ["git", "-C", str(root), "add", "-A"],
                 ["git", "-C", str(root), "commit", "-q", "-m", "init"]):
        subprocess.run(argv, check=True, capture_output=True, env=environment, shell=False)

def _idle(client) -> bool:
    return client.get("/api/queries/system.status").json()["data"]["drain"]["running_runs"] == 0


def _awaiting_initial_prd(client, project_id) -> bool:
    # 建档 run 结束以后，结算在另一个事务里写入初始 PRD 的候选与确认请求（工单 #337）。
    # 两个事务之间事项的状态是 released_unsettled，此时 work_item.create 返回 not_allowed；
    # 状态为 awaiting_initial_prd 才是「建档结束、等待用户确认」。
    loop = client.get(f"/api/queries/project.loop?project_id={project_id}").json()["data"]
    return any(item["kind"] == "onboarding" and item["status"] == "awaiting_initial_prd"
               for item in loop["work_items"])

def test_project_onboard_reaches_baseline_verified_over_http(data_dir, tmp_path):
    # 验收：经 HTTP 命令 project.onboard 完成从接入到建档 run 以 baseline_verified 结束；源目录内容与修改时间不变
    source = _source(tmp_path / "source")
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                         source_name="src", source_path=str(source))
        assert accepted.status_code == 200, accepted.text
        refs = accepted.json()["refs"]
        project_id, run_id = refs["project_id"], refs["run_id"]
        assert _wait_for_run_end(opened, run_id), opened.system.project(run_id)
        assert _wait_for(lambda: _idle(client)), opened.system.project(run_id)
        run = opened.system.project(run_id)
        assert run.status == "done"
        assert run.stop_reason == "baseline_verified"
        assert run.kind == "onboarding"
        assert run.workspace_digest == run.snapshot["tree_digest"]
        # 项目流的登记：project_registered 的 source 为 existing，work_item_created 的 kind 为 onboarding，带快照
        events = {event.type: event for event in opened.system.store.list_project_events(project_id)}
        assert events[ProjectEventType.PROJECT_REGISTERED].payload["source"] == "existing"
        created = events[ProjectEventType.WORK_ITEM_CREATED].payload
        assert created["kind"] == "onboarding"
        assert created["snapshot"]["tree_digest"] == run.snapshot["tree_digest"]
        # 源目录只被读取：内容与修改时间在建档前后相同
        assert (source / "src" / "echo.py").read_text(encoding="utf-8").startswith("import sys")
        # 项目的源目录登记同时建立
        settings = client.get(f"/api/queries/project.settings?project_id={project_id}").json()["data"]
        assert settings["source_directories"]["src"]["path"] == str(source)

def test_git_provenance_recorded_when_the_source_is_a_repository(data_dir, tmp_path):
    # 验收（第 10 节第 8 项）：源目录是 git 仓库时快照带提交、分支与是否有未提交的修改；不是 git 仓库时为空
    source = _source(tmp_path / "repo")
    _git_init(source)
    (source / "src" / "echo.py").write_text("import sys\nprint('dirty')\n", encoding="utf-8")
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        accepted = _post(client, "project.onboard", name="git 项目", goal=GOAL,
                         source_name="src", source_path=str(source))
        assert accepted.status_code == 200, accepted.text
        run_id = accepted.json()["refs"]["run_id"]
        provenance = opened.system.project(run_id).snapshot["provenance"]
        assert provenance["branch"] in {"master", "main"}
        assert len(provenance["commit"]) == 40
        assert provenance["dirty"] is True
        assert _wait_for_run_end(opened, run_id), opened.system.project(run_id)
        assert _wait_for(lambda: _idle(client)), opened.system.project(run_id)
        assert opened.system.project(run_id).status == "done", opened.system.project(run_id)

        plain = _source(tmp_path / "plain")
        accepted = _post(client, "project.onboard", name="非 git 项目", goal=GOAL,
                         source_name="src", source_path=str(plain))
        assert accepted.status_code == 200, accepted.text
        plain_run = accepted.json()["refs"]["run_id"]
        assert opened.system.project(plain_run).snapshot["provenance"] == {}
        assert _wait_for_run_end(opened, plain_run), opened.system.project(plain_run)
        assert opened.system.project(plain_run).status == "done", opened.system.project(plain_run)

def test_source_invalid_rejects_without_building_the_project(data_dir, tmp_path):
    # 验收（第 10 节第 9 项）：源目录不存在、含宿主私有路径或公开树有无法表示的条目时返回 source_invalid，
    # 没有建立项目，也没有写入任何事件
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        missing = _post(client, "project.onboard", name="不存在", goal=GOAL,
                        source_name="src", source_path=str(tmp_path / "nope"))
        assert missing.status_code == 409, missing.text
        assert missing.json()["reason"] == "source_invalid"

        private = _source(tmp_path / "private")
        (private / ".checks").mkdir()
        (private / ".checks" / "state").write_text("x", encoding="utf-8")
        rejected = _post(client, "project.onboard", name="私有", goal=GOAL,
                         source_name="src", source_path=str(private))
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["reason"] == "source_invalid"

        system = opened.system
        assert system.store.list_project_ids() == []

def test_new_work_item_is_rejected_before_the_baseline(data_dir, tmp_path):
    # 验收（第 10 节第 10 项）：建档进行中与等待确认初始 PRD 时新建事项都被拒绝（work_item_in_progress）；
    # 建档事项被取消、撤销以后返回 not_allowed，onboarding.restart 可用并开始新的建档事项
    source = _source(tmp_path / "source")
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                         source_name="src", source_path=str(source))
        project_id = accepted.json()["refs"]["project_id"]
        # 建档进行中（run 已经创建，还没有结束）
        rejected = _post(client, "work_item.create", project_id=project_id, text="建档中新建")
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["reason"] == "work_item_in_progress"
        assert _wait_for(lambda: _awaiting_initial_prd(client, project_id)), \
            "the onboarding item did not reach awaiting_initial_prd"
        # 建档结束、等待用户确认：普通事项仍然被拒绝
        waiting = _post(client, "work_item.create", project_id=project_id, text="等待确认时新建")
        assert waiting.status_code == 409, waiting.text
        assert waiting.json()["reason"] == "work_item_in_progress"
        # 取消等待确认的建档事项以后：普通事项返回 not_allowed
        cancelled = _post(client, "work_item.cancel",
                          work_item_id=opened.system.projects.projection(project_id).work_items[0].work_item_id)
        assert cancelled.status_code == 200, cancelled.text
        after = _post(client, "work_item.create", project_id=project_id, text="建档后新建")
        assert after.status_code == 409, after.text
        assert after.json()["reason"] == "not_allowed"
        # onboarding.restart 可用并开始新的建档事项
        restarted = _post(client, "onboarding.restart", project_id=project_id, source_name="src")
        assert restarted.status_code == 200, restarted.text
        second_run = restarted.json()["refs"]["run_id"]
        assert _wait_for_run_end(opened, second_run), opened.system.project(second_run)
        assert opened.system.project(second_run).status == "done", opened.system.project(second_run)
        assert opened.system.project(second_run).stop_reason == "baseline_verified"

def test_projects_list_and_loop_show_onboarding_status_and_kind(data_dir, tmp_path):
    # 验收（3.4 节）：projects.list 的建档状态标记「建档中」「等待建档」；project.loop 返回事项的种类
    source = _source(tmp_path / "source")
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        accepted = _post(client, "project.onboard", name="已有项目", goal=GOAL,
                         source_name="src", source_path=str(source))
        project_id = accepted.json()["refs"]["project_id"]
        # 建档进行中：状态为 onboarding（建档中）
        row = next(entry for entry in client.get("/api/queries/projects.list").json()["data"]["projects"]
                   if entry["project_id"] == project_id)
        assert row["source"] == "existing"
        assert row["onboarding_status"] == "onboarding"
        loop = client.get(f"/api/queries/project.loop?project_id={project_id}").json()["data"]
        assert loop["work_items"][0]["kind"] == "onboarding"
        # 建档结束、等待用户确认初始 PRD：状态为 awaiting_initial_prd（等待确认）
        assert _wait_for(lambda: _awaiting_initial_prd(client, project_id)), \
            "the onboarding item did not reach awaiting_initial_prd"
        row = next(entry for entry in client.get("/api/queries/projects.list").json()["data"]["projects"]
                   if entry["project_id"] == project_id)
        assert row["onboarding_status"] == "awaiting_initial_prd"
        created = _post(client, "project.create", name="想法项目", goal=GOAL)
        idea_id = created.json()["refs"]["project_id"]
        row = next(entry for entry in client.get("/api/queries/projects.list").json()["data"]["projects"]
                   if entry["project_id"] == idea_id)
        assert row["onboarding_status"] is None

def test_time_limit_stops_the_onboarding_item_and_restart_is_available(data_dir, tmp_path):
    # 验收：建档 run 运行时间用完以后事项停止，没有发出确认请求，onboarding.restart 可用
    source = _source(tmp_path / "source")
    def slow_spec(request):
        # 运行时间在产品部门的模型调用期间用完：调用本身等待到限制之后，收尾在调用边界发现
        time.sleep(1.5)
        return FakeTurn(proposal=product_spec(requirements=[REQUIREMENT], acceptance=["run the CLI with a word"]))
    # 脚本按部门给出（工单 #878）：产品这一轮的模型调用慢，运行时间在这一次调用里用完
    script = _onboarding_script()
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [slow_spec, *script["product"][1:]],
        "engineering": script["engineering"],
        "quality": script["quality"],
    }))
    project_id, work_item_id, run_id = system.projects.onboard(
        "已有项目", GOAL, "src", str(source), run_time_limit_sec=1)
    result = system.run_until_stop(run_id)
    assert result.status == "failed"
    assert result.stop_reason == "time_limit"
    item = system.projects.projection(project_id).work_item(work_item_id)
    assert item.status == "stopped"
    # onboarding.restart 可用并开始新的建档事项
    second_work_item, second_run = system.projects.restart_onboarding(project_id, "src")
    assert second_run != run_id
    assert system.projects.projection(project_id).work_item(second_work_item).kind == "onboarding"

def test_old_project_stream_reads_kind_change_and_empty_provenance(data_dir, tmp_path):
    # 验收：旧事件没有 kind 与 provenance 字段时读作 kind 为 change、provenance 为空（ADR-0019）
    from harness.artifacts import ArtifactStore
    from harness.event_store import EventStore, project_stream
    from harness.models import new_id
    from harness.project_projection import handler_for, saved_project
    from harness.public_tree import capture_public_tree
    from harness.snapshot import restore_snapshot
    from harness.tree_archive import store_tree
    from harness.write_path import NewProjectEvent, WritePath

    source = _source(tmp_path / "source")
    store = EventStore(data_dir / "events.sqlite")
    artifacts = ArtifactStore(data_dir / "artifacts")
    writes = WritePath(store, handler_for)
    try:
        project_id = new_id("proj")
        goal_ref = artifacts.put(project_id, "project_goal", GOAL, media_type="text/markdown")
        tree = capture_public_tree(source)
        ref = store_tree(artifacts, "run_legacy", tree)
        # 较早版本写入的 work_item_created：没有 kind，snapshot 记录没有 provenance
        legacy_snapshot = {
            "source": str(source.absolute()), "tree_digest": tree.digest,
            "files": [item.path for item in tree.files], "directories": list(tree.directories),
            "tree_ref": asdict(ref),
        }

        def legacy(transaction):
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_REGISTERED, {
                "name": "旧项目", "goal": GOAL, "goal_ref": asdict(goal_ref), "source": "idea",
            }, actor="user:local"))
            transaction.append(NewProjectEvent(ProjectEventType.WORK_ITEM_CREATED, {
                "work_item_id": "wi_legacy", "title": "旧事项", "text": "旧事项", "run_id": "run_legacy",
                "baseline": None, "snapshot": legacy_snapshot,
                "project_context_ref": asdict(artifacts.put("run_legacy", "project_context", "项目：旧项目",
                                                            media_type="text/markdown")),
                "prompt_config_versions": {"product": 0, "engineering": 0, "quality": 0},
                "max_cycles": 2, "run_time_limit_sec": 7200, "context_window": 32000,
                "definitions_version": "sha256:legacy",
            }, actor="user:local"))

        writes.transact(project_stream(project_id), legacy, expected_version=0)
        state = saved_project(store, project_id)
        item = state.work_items[0]
        assert item.kind == "change"
        assert item.snapshot.get("provenance") is None
        # 快照仍可恢复：恢复只依据 tree_ref 与 tree_digest，不要求 provenance
        restored = restore_snapshot(artifacts, "run_legacy", item.snapshot, tmp_path / "legacy")
        assert capture_public_tree(restored).digest == tree.digest
    finally:
        store.close()

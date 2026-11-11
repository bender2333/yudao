# 工单 #1699：直做交完成的那一版进流转记录与事项资料，两份形态经页面的路走到开环完成。
# 事项经页面的那两条命令建起来（project.create 带形态、work_item.create），假模型交完成以后以开环完成结束；
# 这一版在两处是同一个原始事件：project.flow 里一条版本交付（来源是交完成的角色，没有核验角色时没有去向，
# 内容是交完成的摘要），work_item.materials 的交付各版本里一行（带版本、摘要与改了的文件），
# project.loop 的进度里有这一版。直做加独立核验角色时，同一版交付的去向是核验它的角色。
# 依据：形态与核验角色 docs/design/forms-and-verifier-role.md「开环完成」第 7 条，应用层与接口层
# docs/design/app-and-interface.md「项目页四层读哪个查询」第 7 条（main 96680bcf）。
#
# 守 R3（测试分层 docs/design/test-pyramid.md「测试按三环留」）：直做与开环完成是路线图已经走到的行为，
# 页面要的那一版交付由这三份对外查询给出；记录的种类、来源、去向、内容、版本与文件都经查询看，不看内部行。
# 也有 R2 的一面：这一版在资料里仍是一条交付，查询与事件的字段都没有加（验收第 4 条）。

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from harness import direct
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.contracts import Accepted
from harness.app.project_and_work_item_commands import WorkItemCreate
from harness.app.project_commands import ProjectCreate
from harness.app.project_queries import ProjectFlow, ProjectLoop, WorkItemMaterials
from harness.definitions import load_definitions
from harness.models import EventType
from harness.proposals import completion_turn
from harness.providers.call import ModelResponse
from harness.runtime import FORM_REGISTRY, SEVERAL_ROLES_DIRECT, SINGLE_ROLE_DIRECT, LoopSystem
from harness.watched_outputs import OPEN_LOOP_STOP_REASON

GOAL = "做一个可以长期演进的逐行文本处理工具。"
WORK_ITEM = "补一份用法说明"
SUMMARY = "写好了逐行文本处理工具"
WRITTEN = {"src/echo.py": "import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else '')\n"}

ENGINEERING = "engineering"
QUALITY = "quality"

# 直做加一个核验角色的形态：与 #1396 用同一份测试定义（质检核验工程交完成的那一份），
# 实例里同时加载发布带的那份登记表（三部门、单角色直做、几个角色直做）
FORM = "direct_with_verifier"
FORM_DIRECTORY = Path(__file__).parent / "direct_with_verifier_definitions"
WITH_VERIFIER = load_definitions(FORM_DIRECTORY)
FORMS = {**FORM_REGISTRY, FORM: (WITH_VERIFIER, direct.DIRECT_TIGHTENING)}
SUBMIT_REVIEW = "submit_completion_review"


def _system(data_dir: Path, script: dict[str, list[Any]], *, forms: dict | None = None) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(script), forms=forms or FORMS,
                                  resume_on_startup=False)


def _created(application: Application, form: str, name: str) -> str:
    # 页面上新建项目走的就是这条命令：带形态一起定下来
    created = asyncio.run(application.command("project.create", ProjectCreate(
        command_id=str(uuid.uuid4()), name=name, goal=GOAL, form=form), actor="user:local"))
    assert isinstance(created, Accepted), created
    return created.refs.project_id


def _started(application: Application, project_id: str) -> tuple[str, str]:
    started = asyncio.run(application.command("work_item.create", WorkItemCreate(
        command_id=str(uuid.uuid4()), project_id=project_id, text=WORK_ITEM), actor="user:local"))
    assert isinstance(started, Accepted), started
    return started.refs.work_item_id, started.refs.run_id


def _records(application: Application, project_id: str, work_item_id: str) -> list[Any]:
    return application.query("project.flow",
                             ProjectFlow(project_id=project_id, work_item=work_item_id)).data.records


def _versions(application: Application, project_id: str, work_item_id: str) -> list[Any]:
    return application.query("work_item.materials",
                             WorkItemMaterials(project_id=project_id,
                                               work_item=work_item_id)).data.deliveries


def _loop(application: Application, project_id: str, work_item_id: str) -> Any:
    rows = application.query("project.loop",
                             ProjectLoop(project_id=project_id, work_item=work_item_id)).data.work_items
    [row] = rows
    return row


def _completion(system: LoopSystem, run_id: str) -> Any:
    # 交完成的那条成果接纳事件：这一版交付的原始事件，页面上的两处都对到它
    [event] = [event for event in system.store.list_events(run_id)
               if event.type == EventType.ARTIFACT_ACCEPTED
               and (event.payload or {}).get("artifact_kind") == direct.COMPLETION_KIND]
    return event


def review_turn(verdict: str, rationale: str):
    # 核验角色的一轮：用直做加核验角色这份定义里的提交工具交结论（与 #1396 的写法相同）
    proposal = {"verdict": verdict, "rationale": rationale}

    def factory(call: Any) -> ModelResponse:
        identity = f"review-{call.activation_id}-{call.step_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": SUBMIT_REVIEW, "arguments": json.dumps(proposal),
        }])

    return factory


def _direct_script() -> dict[str, list[Any]]:
    return {ENGINEERING: [FakeTurn(writes=WRITTEN, checks={}), completion_turn(SUMMARY)]}


def test_one_role_direct_item_ends_open_loop_with_its_version_on_the_page(tmp_path):
    # 验收第 1 条（工程）：经页面的两条命令建起来，跑到开环完成，这一版在三份查询里都在
    system = _system(tmp_path / "loop", _direct_script())
    application = Application(system)
    project_id = _created(application, SINGLE_ROLE_DIRECT, "直做一个事项")
    work_item_id, run_id = _started(application, project_id)
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", OPEN_LOOP_STOP_REASON)
    completion = _completion(system, run_id)
    assert completion.payload["artifact_version"] == 1

    # 流转记录：一条版本交付，来源是交完成的角色，没有核验角色时没有去向，内容是交完成的摘要，带原始事件
    [delivery] = [record for record in _records(application, project_id, work_item_id)
                  if record.kind == "版本交付"]
    assert (delivery.direction_from, delivery.direction_to) == (ENGINEERING, None)
    assert delivery.status == "已完成"
    assert delivery.content == SUMMARY
    assert delivery.event_id == completion.event_id

    # 事项的资料：交付各版本有这一版，与上一条是同一个原始事件，带版本、摘要与改了的文件
    [version] = _versions(application, project_id, work_item_id)
    assert version.event_id == completion.event_id
    assert (version.kind, version.revision) == ("delivery", 1)
    assert version.summary == SUMMARY
    assert version.files == ["src/echo.py"]

    # 事项的进度：有这一版；没有核验角色，没有结论（开环完成不写成放行）
    row = _loop(application, project_id, work_item_id)
    assert row.progress.delivery_revision == 1
    assert row.progress.conclusion is None
    system.close()


def test_two_role_direct_item_also_ends_open_loop_with_one_version(tmp_path):
    # 验收第 1 条（产品 · 工程）：两份形态走同一条路，这一版仍是同一条版本交付
    system = _system(tmp_path / "loop", _direct_script())
    application = Application(system)
    project_id = _created(application, SEVERAL_ROLES_DIRECT, "两个角色直做一个事项")
    work_item_id, run_id = _started(application, project_id)
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", OPEN_LOOP_STOP_REASON)
    completion = _completion(system, run_id)

    [delivery] = [record for record in _records(application, project_id, work_item_id)
                  if record.kind == "版本交付"]
    assert (delivery.direction_from, delivery.direction_to) == (ENGINEERING, None)
    assert delivery.content == SUMMARY
    assert delivery.event_id == completion.event_id
    [version] = _versions(application, project_id, work_item_id)
    assert version.event_id == completion.event_id
    assert version.files == ["src/echo.py"]
    assert _loop(application, project_id, work_item_id).progress.delivery_revision == 1
    system.close()


def test_a_direct_item_with_a_verifier_records_the_completion_towards_it(tmp_path):
    # 验收第 3 条：直做加独立核验（质检核验工程交的完成）时去向是质检；放行以后进度里有结论
    script = {**_direct_script(), QUALITY: [review_turn("release", "看过了")]}
    system = _system(tmp_path / "loop", script)
    application = Application(system)
    project_id = _created(application, FORM, "直做加一个核验角色")
    work_item_id, run_id = _started(application, project_id)
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", "released")
    completion = _completion(system, run_id)

    [delivery] = [record for record in _records(application, project_id, work_item_id)
                  if record.kind == "版本交付"]
    assert (delivery.direction_from, delivery.direction_to) == (ENGINEERING, QUALITY)
    assert delivery.event_id == completion.event_id
    [version] = _versions(application, project_id, work_item_id)
    assert version.event_id == completion.event_id
    row = _loop(application, project_id, work_item_id)
    assert row.progress.delivery_revision == 1
    assert row.progress.conclusion == "release"

    # 去向按这个事项冻结的定义取：重建读取模型（从事件重放）以后仍是这一条
    application.rebuild_read_models()
    [again] = [record for record in _records(application, project_id, work_item_id)
               if record.kind == "版本交付"]
    assert (again.direction_from, again.direction_to) == (ENGINEERING, QUALITY)
    assert again.event_id == completion.event_id
    system.close()


def test_a_completion_without_a_workspace_action_has_no_files(tmp_path):
    # 这一版的文件清单取自记下的公开树快照：交完成以前没有任何工作区动作时，清单是空的，这一版仍在
    system = _system(tmp_path / "loop", {ENGINEERING: [completion_turn(SUMMARY)]})
    application = Application(system)
    project_id = _created(application, SINGLE_ROLE_DIRECT, "只交了完成的事项")
    work_item_id, run_id = _started(application, project_id)
    assert system.run_until_stop(run_id).stop_reason == OPEN_LOOP_STOP_REASON
    completion = _completion(system, run_id)

    [version] = _versions(application, project_id, work_item_id)
    assert version.event_id == completion.event_id
    assert version.files == []
    assert version.summary == SUMMARY
    system.close()


def test_a_reworked_completion_has_its_own_version_and_a_conclusion(tmp_path):
    # 验收第 2、3 条合起来看：打回以后这一版仍有结论，交出新的一版以后资料与进度按新的这一版算
    script = {
        ENGINEERING: [FakeTurn(writes=WRITTEN, checks={}), completion_turn("先交一版"),
                      FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1:])\n"}, checks={}),
                      completion_turn("补好了")],
        QUALITY: [review_turn("rework", "再看一遍"), review_turn("release", "这次可以")],
    }
    system = _system(tmp_path / "loop", script)
    application = Application(system)
    project_id = _created(application, FORM, "打回一次以后再放行")
    work_item_id, run_id = _started(application, project_id)
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", "released")

    # 打回以后、交出新的一版以前：进度里有第 1 版与它的结论
    rework = next(event for event in system.store.list_events(run_id)
                  if event.type == EventType.ARTIFACT_ACCEPTED
                  and (event.payload or {}).get("artifact_kind") == direct.REVIEW_KIND
                  and event.payload.get("verdict") == direct.REWORK_VERDICT)
    replayed = application.query("project.loop", ProjectLoop(
        project_id=project_id, work_item=work_item_id, at=rework.position)).data.work_items
    [before] = replayed
    assert (before.progress.delivery_revision, before.progress.conclusion) == (1, direct.REWORK_VERDICT)

    # 交出新的一版以后按新的这一版算
    row = _loop(application, project_id, work_item_id)
    assert (row.progress.delivery_revision, row.progress.conclusion) == (2, direct.RELEASE_VERDICT)

    # 资料里两版都在，各是同一个原始事件、各带这一版的文件
    versions = _versions(application, project_id, work_item_id)
    assert [(version.revision, version.summary) for version in versions] == [(1, "先交一版"), (2, "补好了")]
    assert all(version.files == ["src/echo.py"] for version in versions)
    assert [(record.direction_from, record.direction_to)
            for record in _records(application, project_id, work_item_id) if record.kind == "版本交付"] \
        == [(ENGINEERING, QUALITY), (ENGINEERING, QUALITY)]
    system.close()


def test_the_input_of_a_direct_item_goes_to_the_engineering_role(tmp_path):
    # 验收第 2 条：两份直做形态里「你的输入」都送给工程（进程里加载的默认定义送给产品）
    for form, name in ((SINGLE_ROLE_DIRECT, "一个角色直做"), (SEVERAL_ROLES_DIRECT, "两个角色直做")):
        system = _system(tmp_path / form, {})
        application = Application(system)
        project_id = _created(application, form, name)
        work_item_id, _run_id = _started(application, project_id)
        [first] = _records(application, project_id, work_item_id)[:1]
        assert (first.kind, first.direction_to) == ("你的输入", ENGINEERING)
        system.close()


def test_the_completing_role_waits_in_verification_until_the_reviewer_concludes(tmp_path):
    # 验收第 3 条：工程交完成以后、质检给结论以前，工程的状态是核验中并写明在等质检；
    # 放行以后事项结束，职能状态不再给出
    script = {**_direct_script(), QUALITY: [review_turn("release", "看过了")]}
    system = _system(tmp_path / "loop", script)
    application = Application(system)
    project_id = _created(application, FORM, "直做加一个核验角色")
    work_item_id, run_id = _started(application, project_id)
    assert system.run_until_stop(run_id).stop_reason == "released"

    # 质检被叫起来的那一刻：它的核验声明来自这个事项冻结的定义，不是进程里加载的默认定义
    reviewing = next(event.position for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_ACTIVATED and event.department == QUALITY)
    during = application.query("project.loop", ProjectLoop(
        project_id=project_id, work_item=work_item_id, at=reviewing)).data.work_items[0]
    assert list(during.departments) == [ENGINEERING, QUALITY]
    assert (during.departments[ENGINEERING].state, during.departments[ENGINEERING].note) == (
        "verifying", "等质检核验交付 r1")
    assert during.departments[QUALITY].state == "working"
    assert (during.progress.delivery_revision, during.progress.conclusion) == (1, None)

    ended = _loop(application, project_id, work_item_id)
    assert ended.departments is None
    assert ended.progress.conclusion == direct.RELEASE_VERDICT
    system.close()

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
import base64
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from harness import direct
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.contracts import Accepted
from harness.app.decision_commands import DecisionAnswer
from harness.app.decision_queries import DecisionsList
from harness.app.project_and_work_item_commands import WorkItemCreate
from harness.app.project_commands import ProjectCreate
from harness.app.project_queries import (
    DeliveryFile, NotFound, ProjectFlow, ProjectLoop, ProjectOverview, WorkItemMaterials,
)
from harness.definitions import load_definitions
from harness.event_store import run_stream
from harness.models import ArtifactRef, EventType, ProjectEventType, hash_bytes
from harness.proposals import completion_turn
from harness.providers.call import ModelResponse
from harness.runtime import FORM_REGISTRY, SEVERAL_ROLES_DIRECT, SINGLE_ROLE_DIRECT, LoopSystem
from harness.watched_outputs import OPEN_LOOP_STOP_REASON
from harness.write_path import NewEvent

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


def _created(application: Application, form: str, name: str, *,
             initial_directory: str | None = None) -> str:
    # 页面上新建项目走的就是这条命令：带形态与可选的起始文件夹一起定下来
    created = asyncio.run(application.command("project.create", ProjectCreate(
        command_id=str(uuid.uuid4()), name=name, goal=GOAL, form=form,
        initial_directory=initial_directory), actor="user:local"))
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


# ---------------------------------------------------------------------------
# 工单 #1742：直做交完成封存代码树，接通文件读取与事项采纳结算
# ---------------------------------------------------------------------------

INITIAL_TEXT = "# 逐行工具\n起始说明\n"
INITIAL_BYTES = b"\x89PNG\r\n\x1a\n\x00\x01"
SECOND_WRITTEN = {"docs/guide.md": "补充使用指南\n"}


def _seed_initial_directory(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_bytes(INITIAL_TEXT.encode("utf-8"))
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "icon.bin").write_bytes(INITIAL_BYTES)
    return root


@pytest.mark.parametrize("form", [SINGLE_ROLE_DIRECT, SEVERAL_ROLES_DIRECT])
def test_direct_forms_with_initial_directory_settle_into_adopted_and_seed_next_item(tmp_path, form):
    # 守 R3（路线图已走到的直做与开环完成采纳闭环）与 R2（对外查询与事件字段只复用既有统一字段）：
    # 两份直做形态带起始文件夹新建项目并跑完事项加结算后，事项进入 adopted、stop_reason 保持 open_loop，
    # 项目流写 deliverable_adopted（qa_event_id 为空串），项目概览可读到当前成果，delivery.file 按交完成事件
    # 读回起始文件夹带入的文件与本轮新写文件，后续新建事项继承这一版基线代码树
    initial_dir = _seed_initial_directory(tmp_path / "seed")
    script = {
        ENGINEERING: [
            FakeTurn(writes=WRITTEN, checks={}),
            completion_turn(SUMMARY, known_risks=["暂未覆盖超大单行输入"]),
            FakeTurn(writes=SECOND_WRITTEN, checks={}),
            completion_turn("补充了使用指南"),
        ],
    }
    system = _system(tmp_path / form, script)
    application = Application(system)
    project_id = _created(application, form, f"带起始文件夹的{form}", initial_directory=str(initial_dir))
    work_item_id, run_id = _started(application, project_id)
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", OPEN_LOOP_STOP_REASON)

    completion = _completion(system, run_id)
    assert isinstance(completion.payload.get("artifact_ref"), dict)
    assert completion.payload["artifact_ref"]["content_hash"] in completion.artifact_hashes

    settled = system.projects.settle(run_id)
    assert settled is not None and settled.type == ProjectEventType.DELIVERABLE_ADOPTED
    assert settled.payload["delivery_event_id"] == completion.event_id
    assert settled.payload["qa_event_id"] == ""
    expected_files = ["README.md", "assets/icon.bin", "src/echo.py"]
    assert settled.payload["files"] == expected_files
    assert settled.payload["known_risks"] == ["暂未覆盖超大单行输入"]

    overview = application.query("project.overview", ProjectOverview(project_id=project_id)).data
    [card] = overview.work_items
    assert (card.work_item_id, card.status, card.stop_reason) == (work_item_id, "adopted", OPEN_LOOP_STOP_REASON)
    assert (overview.stats.adopted, overview.stats.open_loop, overview.stats.released_unsettled) == (1, 0, 0)
    assert overview.current_adoption is not None
    assert overview.current_adoption.summary == SUMMARY
    assert overview.current_adoption.files == expected_files
    assert overview.current_adoption.code_tree_digest == completion.payload["artifact_tree_digest"]

    # 事项资料与 delivery.file：起始文件（含文本与二进制）与本轮写入文件全部可读回完整内容与摘要
    [version] = _versions(application, project_id, work_item_id)
    assert version.files == expected_files

    readme = application.query(
        "delivery.file", DeliveryFile(event_id=completion.event_id, path="README.md")).data
    assert readme.content == INITIAL_TEXT and readme.base64 is None
    assert readme.content_hash == hash_bytes(INITIAL_TEXT.encode("utf-8"))

    icon = application.query(
        "delivery.file", DeliveryFile(event_id=completion.event_id, path="assets/icon.bin")).data
    assert icon.content is None and icon.base64 is not None
    assert base64.b64decode(icon.base64) == INITIAL_BYTES
    assert icon.content_hash == hash_bytes(INITIAL_BYTES)

    echo = application.query(
        "delivery.file", DeliveryFile(event_id=completion.event_id, path="src/echo.py")).data
    assert echo.content == WRITTEN["src/echo.py"] and echo.base64 is None
    assert echo.content_hash == hash_bytes(WRITTEN["src/echo.py"].encode("utf-8"))

    # 后续新建事项继承这一版基线代码树
    first_adoption_id = overview.current_adoption.adoption_id
    second_item_id, second_run_id = _started(application, project_id)
    second_workspace = system.workspace_root / second_run_id
    assert (second_workspace / "README.md").read_text(encoding="utf-8") == INITIAL_TEXT
    assert (second_workspace / "assets" / "icon.bin").read_bytes() == INITIAL_BYTES
    assert (second_workspace / "src" / "echo.py").read_text(encoding="utf-8") == WRITTEN["src/echo.py"]

    second_ended = system.run_until_stop(second_run_id)
    assert (second_ended.status, second_ended.stop_reason) == ("done", OPEN_LOOP_STOP_REASON)
    second_settled = system.projects.settle(second_run_id)
    assert second_settled is not None and second_settled.type == ProjectEventType.DELIVERABLE_ADOPTED
    assert second_settled.payload["previous_adoption_id"] == first_adoption_id
    assert second_settled.payload["files"] == ["README.md", "assets/icon.bin", "docs/guide.md", "src/echo.py"]
    after_second = application.query("project.overview", ProjectOverview(project_id=project_id)).data
    assert after_second.current_adoption is not None
    assert after_second.current_adoption.work_item_id == second_item_id
    system.close()


def test_a_direct_item_with_a_verifier_settles_with_the_release_event_id(tmp_path):
    # 守 R3（直做加独立核验放行的采纳闭环）与 R1（采纳记录绑定当前这一版的放行结论事件）：
    # 第一版被打回、第二版经核验角色放行以后，结算写入 deliverable_adopted，qa_event_id 为第二版放行结论事件编号，
    # 两版交完成各自封存的文件均可经 delivery.file 按各自的 event_id 读回
    first_code = "import sys\nprint(sys.argv[1])\n"
    second_code = "import sys\nprint(sys.argv[1] if len(sys.argv) > 1 else '')\n"
    script = {
        ENGINEERING: [
            FakeTurn(writes={"src/echo.py": first_code}, checks={}),
            completion_turn("第一版完成"),
            FakeTurn(writes={"src/echo.py": second_code}, checks={}),
            completion_turn("第二版修复缺参"),
        ],
        QUALITY: [
            review_turn("rework", "缺少无参数保护"),
            review_turn("release", "无参数与带参数均通过"),
        ],
    }
    system = _system(tmp_path / "loop", script)
    application = Application(system)
    project_id = _created(application, FORM, "直做加独立核验采纳")
    work_item_id, run_id = _started(application, project_id)
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", "released")

    completions = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.ARTIFACT_ACCEPTED
                   and (event.payload or {}).get("artifact_kind") == direct.COMPLETION_KIND]
    assert len(completions) == 2
    release_event = next(event for event in reversed(system.store.list_events(run_id))
                         if event.type == EventType.ARTIFACT_ACCEPTED
                         and (event.payload or {}).get("artifact_kind") == direct.REVIEW_KIND
                         and (event.payload or {}).get("verdict") == direct.RELEASE_VERDICT)

    settled = system.projects.settle(run_id)
    assert settled is not None and settled.type == ProjectEventType.DELIVERABLE_ADOPTED
    assert settled.payload["delivery_event_id"] == completions[1].event_id
    assert settled.payload["qa_event_id"] == release_event.event_id

    overview = application.query("project.overview", ProjectOverview(project_id=project_id)).data
    [card] = overview.work_items
    assert (card.work_item_id, card.status, card.stop_reason) == (work_item_id, "adopted", "released")
    assert overview.current_adoption is not None
    assert overview.current_adoption.summary == "第二版修复缺参"

    first_file = application.query(
        "delivery.file", DeliveryFile(event_id=completions[0].event_id, path="src/echo.py")).data
    second_file = application.query(
        "delivery.file", DeliveryFile(event_id=completions[1].event_id, path="src/echo.py")).data
    assert first_file.content == first_code
    assert second_file.content == second_code
    system.close()


def test_a_direct_completion_touching_a_kernel_path_requests_approval_before_adoption(tmp_path):
    # 守 R1（受控内核路径守卫对任何形态一致生效）：直做交完成改动内核清单路径时，结算发出 kernel_modification
    # 决定请求且暂不采纳；用户批准以后写入 deliverable_adopted，事项进入 adopted
    kernel_file = "harness/thin_driver.py"
    kernel_content = "# 经用户批准的薄驱动改动\n"
    script = {
        ENGINEERING: [
            FakeTurn(writes={kernel_file: kernel_content}, checks={}),
            completion_turn("更新薄驱动"),
        ],
    }
    system = _system(tmp_path / "loop", script)
    application = Application(system)
    project_id = _created(application, SINGLE_ROLE_DIRECT, "直做触及内核路径")
    work_item_id, run_id = _started(application, project_id)
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", OPEN_LOOP_STOP_REASON)

    requested = system.projects.settle(run_id)
    assert requested is not None and requested.type == ProjectEventType.PROJECT_DECISION_REQUESTED
    assert requested.payload["kind"] == "kernel_modification"
    assert requested.payload["kernel_paths"] == [kernel_file]
    assert requested.payload["department"] == ENGINEERING
    assert system.projects.projection(project_id).current_adoption is None

    [decision] = application.query(
        "decisions.list", DecisionsList(project_id=project_id, status=["open"])).data.decisions
    assert decision.kind == "kernel_modification"
    answered = asyncio.run(application.command("decision.answer", DecisionAnswer(
        command_id=str(uuid.uuid4()),
        base_version=decision.version,
        decision_id=decision.decision_id,
        option="approve",
    ), actor="user:local"))
    assert isinstance(answered, Accepted), answered

    overview = application.query("project.overview", ProjectOverview(project_id=project_id)).data
    [card] = overview.work_items
    assert (card.work_item_id, card.status) == (work_item_id, "adopted")
    assert overview.current_adoption is not None
    assert overview.current_adoption.files == [kernel_file]
    system.close()


def test_legacy_completion_without_archive_ref_falls_back_in_materials_and_404s_delivery_file(tmp_path):
    # 守 R2（旧事件无 artifact_ref 时的向后兼容）：旧事件只带 artifact_tree_digest、不带 artifact_ref 时，
    # work_item.materials 仍回退扫描工作区动作快照列出文件，delivery.file 对无封存树的事件返回 NotFound
    system = _system(tmp_path / "loop", {ENGINEERING: [FakeTurn(writes=WRITTEN, checks={})]})
    application = Application(system)
    project_id = _created(application, SINGLE_ROLE_DIRECT, "旧格式交完成回退")
    work_item_id, run_id = _started(application, project_id)
    # 先跑一轮写入动作留下带 after_snapshot_ref 的 TOOL_CALLED 事件，再追加一条无 artifact_ref 的旧式交完成事件
    system.run_until_stop(run_id)
    tool_event = next(event for event in reversed(system.store.list_events(run_id))
                      if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("after_snapshot_ref"))
    snapshot = json.loads(system.artifacts.get_for_run(
        run_id, ArtifactRef(**tool_event.payload["after_snapshot_ref"]),
    ))
    legacy = system.writes.append(run_stream(run_id), NewEvent(
        EventType.ARTIFACT_ACCEPTED,
        actor=f"department:{ENGINEERING}",
        department=ENGINEERING,
        state_before="running",
        state_after="running",
        payload={
            "id": "artifact_legacy",
            "kind": direct.COMPLETION_KIND,
            "summary": "旧事件摘要",
            "uncertain": [],
            "known_risks": [],
            "revision": 1,
            "status": "active",
            "issuer": ENGINEERING,
            "parent_hash": None,
            "content_hash": "0" * 64,
            "tree_digest": snapshot["digest"],
            "artifact_kind": direct.COMPLETION_KIND,
            "artifact_version": 1,
            "artifact_basis": {},
            "artifact_issuer": ENGINEERING,
            "artifact_tree_digest": snapshot["digest"],
        },
        artifact_hashes=["0" * 64],
    ))[0]

    [version] = _versions(application, project_id, work_item_id)
    assert version.event_id == legacy.event_id
    assert version.files == ["src/echo.py"]
    with pytest.raises(NotFound):
        application.query("delivery.file", DeliveryFile(event_id=legacy.event_id, path="src/echo.py"))
    system.close()

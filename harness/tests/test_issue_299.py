# 工单 #299：运行一个 run 直到停止的入口都要在停止以后结算。
# 三条入口各自跑完以后都不再停在已放行：事项开始（start_work_item）、回答待恢复以后继续（start）、
# 启动时自动继续（LoopSystem.resume_startup_runs）；已经结算过的 run 再次经过这些入口不重复写采纳。
# 测试从运行中的系统整体驱动：事件日志是真实的 SQLite 文件，模型回答由 FakeAdapter 脚本给出，
# 回答决定经真实运行的服务与命令接口，不用替身。

import asyncio
import time
import uuid

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.models import ProjectEventType, TERMINAL_STATUSES, Usage
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.projection import saved_decisions
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import quality_turns
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

UNAVAILABLE = "Missing configuration: provider credential"

class _Service:
    # 服务的生命周期中建立应用层；每次启动取一份模型回答脚本
    def __init__(self, data_dir, scripts) -> None:
        self.data_dir = data_dir
        self.scripts = list(scripts)
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, FakeAdapter(self.scripts.pop(0))))
        self.applications.append(application)
        return application

    @property
    def system(self) -> LoopSystem:
        return self.applications[-1].system

def _blocked_script():
    # 产品提交规格以后工程部门的请求被提供方报告为不可用：run 停在等待用户回答的待恢复状态，
    # 回答以后从这次请求接着进行到放行，交付与放行评审齐备，结算才有可采纳的成果
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "product": [FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20))],
        "engineering": [ProviderError(UNAVAILABLE, reason="provider_unavailable"), delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def _release_script():
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def _completion_script():
    # 产品已经提交规格以后剩下的回答：交付与放行评审
    return {
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def _open_decision(system, run_id):
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    [decision] = [decision for decision in decisions if decision.run_id == run_id]
    assert decision.request["kind"] == "model_unavailable" and decision.request["blocks"] == "run"
    return decision

def _adoptions(system, project_id):
    return [event for event in system.store.list_project_events(project_id)
            if event.type == ProjectEventType.DELIVERABLE_ADOPTED]

def _wait_for_terminal(system, run_id):
    # run 在服务的事件循环中作为任务继续运行：等到它到了终态并且任务已从任务表摘除
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        projection = system.project(run_id)
        if projection.status in TERMINAL_STATUSES and system.orchestrator.execution(run_id) is None:
            return projection
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} was not finished by its task within {WAIT_FOR_HOST_WORK_SEC}s")

def test_answering_the_resume_decision_settles_the_run_it_finishes(data_dir):
    # 事项因模型引用无法使用停在待恢复；回答「继续执行」以后 run 跑完，项目流出现采纳，
    # 当前成果更新，事项状态为已采纳，不需要另外新建事项
    service = _Service(data_dir, [_blocked_script()])
    with running_api(service) as client:
        system = service.system
        created = client.post("/api/commands/project.create", json={
            "command_id": str(uuid.uuid4()), "name": "文本工具", "goal": "逐行处理文本"})
        assert created.status_code == 200, created.text
        project_id = created.json()["refs"]["project_id"]
        # 事项经控制核心的公开接口开始，run 在测试进程里跑到待恢复；回答以后由命令经 start 继续运行
        work_item_id, run_id = system.projects.start_work_item(project_id, "build an echo CLI")
        assert system.run_until_stop(run_id).status == "running"
        decision = _open_decision(system, run_id)

        answered = client.post("/api/commands/decision.answer", json={
            "command_id": str(uuid.uuid4()), "decision_id": decision.decision_id, "option": "continue",
            "base_version": decision.version})
        assert answered.status_code == 200, answered.text

        finished = _wait_for_terminal(system, run_id)
        assert (finished.status, finished.stop_reason) == ("done", "released")

        # 采纳由这次继续运行的结算写入：一个事项、一条采纳事件、事项状态已采纳
        [adopted] = _adoptions(system, project_id)
        assert adopted.payload["run_id"] == run_id and adopted.payload["work_item_id"] == work_item_id
        project = system.projects.projection(project_id)
        assert [item.work_item_id for item in project.work_items] == [work_item_id]
        assert project.work_items[0].status == "adopted"
        assert project.current_adoption.run_id == run_id
        assert project.current_adoption.adoption_id == adopted.payload["adoption_id"]

def test_a_run_resumed_on_startup_is_settled_when_it_stops(data_dir):
    # 进程在模型步骤之间退出；重新打开数据目录时启动自动继续这个 run，跑完以后同样被结算
    interrupted = LoopSystem.for_testing(data_dir, FakeAdapter([product_spec()]))
    project_id = interrupted.projects.register("恢复结算", "核对启动时自动继续的结算")
    work_item_id, run_id = interrupted.projects.start_work_item(project_id, "被中断的事项")
    interrupted.activate_once(run_id)
    assert interrupted.project(run_id).status not in TERMINAL_STATUSES
    interrupted.close()

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_completion_script()))
    try:
        assert run_id in restarted.resumed_runs
        assert (restarted.project(run_id).status, restarted.project(run_id).stop_reason) == ("done", "released")
        [adopted] = _adoptions(restarted, project_id)
        assert adopted.payload["run_id"] == run_id and adopted.payload["work_item_id"] == work_item_id
        project = restarted.projects.projection(project_id)
        assert project.work_items[0].status == "adopted"
        assert project.current_adoption.run_id == run_id
    finally:
        restarted.close()

def test_a_settled_run_does_not_write_another_adoption(data_dir):
    # 已经结算过的 run 再次经过运行到停止的入口：不写第二条采纳，成果与事项状态保持
    system = LoopSystem.for_testing(data_dir, FakeAdapter(_release_script()))
    project_id = system.projects.register("重复结算", "核对结算幂等")
    work_item_id, run_id = system.projects.start_work_item(project_id, "第一个事项")
    assert system.run_until_stop(run_id).status == "done"
    assert system.projects.settle(run_id).type == ProjectEventType.DELIVERABLE_ADOPTED
    before = [event.event_id for event in system.store.list_project_events(project_id)]

    # 再次经回答决定以后的入口把同一个 run 运行到停止
    projection = asyncio.run(_start_again(system, run_id))

    assert projection.status == "done"
    assert [event.event_id for event in system.store.list_project_events(project_id)] == before
    assert system.projects.settle(run_id) is None
    project = system.projects.projection(project_id)
    assert len(project.adoptions) == 1 and project.adoptions[0].run_id == run_id
    assert project.work_items[0].status == "adopted" and project.work_item(work_item_id).status == "adopted"
    assert project.current_adoption.run_id == run_id
    system.close()

async def _start_again(system, run_id):
    # 经回答决定以后使用的入口再运行一次这个已经结算的 run
    return await system.orchestrator.start(run_id)
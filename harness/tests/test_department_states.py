# 三个部门各自的状态与原因（三部门的循环结构第 2.1 节，工单 #903）。
#
# 部门的状态不单独记录，由已经记录的事实现算：会话的状态、进行中的询问、没有回答的决定请求与成果。
# 场景按部门给出脚本（工单 #557 以后工程与质检同时工作）：每个部门自己的一串步骤是固定的，
# 断言在事件提交的时点上做订阅（与 helpers.after_event 相同的做法），不靠两个部门谁先谁后碰运气。

import uuid
from typing import Any

from harness.adapters.fake import FakeAdapter, prompt_part
from harness.app.application import Application
from harness.app.project_queries import (
    DEPARTMENT_WORKSPACE,
    PROJECT_LOOP,
    PROJECT_OVERVIEW,
    RUN_ASKS,
    DepartmentState,
    DepartmentWorkspace,
    ProjectLoop,
    ProjectOverview,
    RunAsks,
)
from harness.definitions import DEFINITIONS
from harness.event_store import Command, run_stream
from harness.models import EventType
from harness.projection import saved_decisions
from harness.proposals import answer_turn, ask_turn, delivery_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn
from harness.write_path import NewEvent

GOAL = "把文本按行处理清楚"
PREDICTIVE = "预测性探索：按 PRD r1 起草测试用例"


def _system(data_dir, script) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(script))


def _application(system: LoopSystem) -> Application:
    return Application(system)


def _departments(application: Application, project_id: str, work_item_id: str) -> dict[str, DepartmentState] | None:
    # 同一时点三个查询给出的部门状态相同：概览、事项的循环与部门工作间
    overview = application.query(
        "project.overview", ProjectOverview(project_id=project_id, work_item=work_item_id)).data.work_items[0]
    loop = application.query(
        "project.loop", ProjectLoop(project_id=project_id, work_item=work_item_id)).data.work_items[0]
    workspace = application.query(
        "department.workspace",
        DepartmentWorkspace(project_id=project_id, department="quality", work_item=work_item_id)).data
    assert overview.departments == loop.departments == workspace.departments
    return overview.departments


def _capture(system: LoopSystem, predicate, take) -> None:
    # 某种事件提交以后在提交它的线程里取一份快照（事件日志的提交通知）
    def notify(events: list[Any]) -> None:
        for event in events:
            if predicate(event):
                take(event)

    system.store.subscribe(notify)


def _happy_script() -> dict[str, list[Any]]:
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [explore_turn(), review_turn("release", "checks passed on the current snapshot")],
    }


def test_working_departments_and_predictive_exploration(data_dir):
    # 验收第 1 条：工程在写入，质检在做预测性探索（事项还没有交付），产品在等待工作
    system = _system(data_dir, _happy_script())
    project_id = system.projects.register("部门状态", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    application = _application(system)
    captured: dict[str, Any] = {}

    def take(event: Any) -> None:
        if "departments" not in captured:
            captured["departments"] = _departments(application, project_id, work_item_id)

    # 质检的第一次主线激活与工程的同一步写出：这时还没有交付
    _capture(system, lambda event: (event.type == EventType.DEPARTMENT_ACTIVATED
                                    and event.department == "quality"), take)
    system.run_until_stop(run_id)

    departments = captured["departments"]
    assert departments["engineering"] == DepartmentState(state="working", note=None)
    assert departments["quality"] == DepartmentState(state="working", note=PREDICTIVE)
    assert departments["product"] == DepartmentState(state="waiting", note=None)


def _reask_script() -> dict[str, list[Any]]:
    # 工程询问产品，产品在自己的分支里回问工程，然后回答并修订 PRD
    return {
        "product": [product_spec()],
        "engineering": [
            ask_turn("product", "输出要保留换行吗？", call_id="ask-1"),
            delivery_turn(),
        ],
        "product:ask": [
            ask_turn("engineering", "现有的入口在哪里？", call_id="ask-2"),
            answer_turn("保留换行。", requirements=["print the given argument to stdout"],
                        change_record={"changed": [], "retained": ["print the given argument to stdout"]},
                        call_id="ans-1"),
        ],
        "engineering:ask": [answer_turn("入口是 src/echo.py。", call_id="ans-2")],
        "quality": [explore_turn(), review_turn("release", "checks passed on the current snapshot")],
    }


def test_answering_in_a_branch_comes_before_asking(data_dir):
    # 验收第 2、3 条：在分支里回答排在询问中之前；问它自己发出的询问时是询问中，原因写等待谁的回答
    system = _system(data_dir, _reask_script())
    project_id = system.projects.register("询问分支的状态", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    application = _application(system)
    asked: dict[tuple[str, str], Any] = {}
    answered: list[Any] = []

    def take(event: Any) -> None:
        key = (event.payload.get("requester"), event.payload.get("recipient"))
        asked.setdefault(key, _departments(application, project_id, work_item_id))

    _capture(system, lambda event: event.type == EventType.ASK_STARTED, take)
    _capture(system, lambda event: event.type == EventType.ASK_ANSWERED,
             lambda event: answered.append(_departments(application, project_id, work_item_id)))
    system.run_until_stop(run_id)

    # 工程停在自己发出的询问上，产品在自己的分支里回答
    first = asked[("engineering", "product")]
    assert first["engineering"] == DepartmentState(state="asking", note="在等待产品的回答")
    assert first["product"] == DepartmentState(state="working", note="回答工程的询问")

    # 产品在自己的分支里回问工程：两个部门都在回答，回答排在工程自己的询问中之前
    second = asked[("product", "engineering")]
    assert second["product"] == DepartmentState(state="working", note="回答工程的询问")
    assert second["engineering"] == DepartmentState(state="working", note="回答产品的询问")

    # 两次询问都回答完以后回到一轮工作中、核验中或等待工作，不再写「回答…的询问」
    after = answered[-1]
    assert after is not None
    assert after["engineering"].state in {"working", "verifying", "waiting"}
    assert after["engineering"].note is None
    assert after["product"].note is None


def _rework_script(snapshots: dict[str, Any], take) -> dict[str, list[Any]]:
    # 工程交付 r1，质检退回，工程返工再交付；质检的核验轮与工程的返工轮各取一份状态。
    # 这两轮各有一条没有结束的激活，部门状态在这一步读得到
    deliveries = {"count": 0}
    verdicts = {"reworked": False}

    def engineering_turn(call):
        if deliveries["count"]:
            snapshots.setdefault("rework", take())
        deliveries["count"] += 1
        return delivery_turn()(call)

    def quality_turn(call):
        if not prompt_part(call, "current_delivery_spec"):
            return explore_turn()
        if not verdicts["reworked"]:
            verdicts["reworked"] = True
            snapshots.setdefault("verify", take())
            return review_turn("rework_engineering", "缺少带空格参数的检查",
                               defects=[{"severity": "major", "summary": "缺少带空格参数的检查"}])(call)
        return review_turn("release", "checks passed on the current snapshot")(call)

    return {"product": [product_spec()], "engineering": [engineering_turn] * 4, "quality": [quality_turn] * 10}


def test_verifying_waits_for_the_review_and_rework_returns_to_working(data_dir):
    # 验收第 4 条：工程交付 r1 以后等质检核验；质检提交缺陷记录以后工程回到一轮工作中
    snapshots: dict[str, Any] = {}
    holder: dict[str, Any] = {}

    def take() -> Any:
        return _departments(holder["application"], holder["project_id"], holder["work_item_id"])

    system = _system(data_dir, _rework_script(snapshots, take))
    project_id = system.projects.register("核验中", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    holder.update(application=_application(system), project_id=project_id, work_item_id=work_item_id)
    system.run_until_stop(run_id)

    # 工程的一轮工作已经结束、最新的交付还没有质检的结论
    assert snapshots["verify"]["engineering"] == DepartmentState(state="verifying", note="等质检核验交付 r1")
    # 质检提交缺陷记录以后工程开始返工，回到一轮工作中
    assert snapshots["rework"]["engineering"] == DepartmentState(state="working", note=None)


def _request_decision(system: LoopSystem, run_id: str, department: str) -> None:
    # 运行中提出一个阻塞事项的决定请求（模型不可用）：经写入口写入，与流程编排自己提出的决定同一条路径
    system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
        EventType.DECISION_REQUESTED, actor="system", department=department,
        state_before=transaction.projection.status, state_after=transaction.projection.status,
        payload={"kind": "model_unavailable", "blocks": "run",
                 "options": [{"id": "continue", "label": "继续执行"}, {"id": "stop", "label": "停止事项"}],
                 "description": f"部门 {department} 的模型无法使用", "facts": [], "department": department,
                 "target": None, "reason": "provider_unavailable",
                 "message": "Missing configuration: provider credential"})))


def _answer_decision(system: LoopSystem, run_id: str) -> None:
    [decision] = [item for item in saved_decisions(system.store)[1]
                  if item.status == "open" and item.run_id == run_id]
    command = Command(str(uuid.uuid4()), "decision.answer", "sha256:continue", "user:local")
    resumed = system.orchestrator.answer_decision(decision.decision_id, "continue", None,
                                                  base_version=decision.version, command=command)
    assert resumed == run_id


def test_a_blocking_decision_puts_only_its_department_in_waiting_user(data_dir):
    # 验收第 5 条：阻塞的待恢复请求写明的部门是等用户，其他部门不受影响；回答以后恢复
    system = _system(data_dir, _happy_script())
    project_id = system.projects.register("等用户", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    application = _application(system)
    system.activate_once(run_id)                        # 产品提出 PRD
    _request_decision(system, run_id, "product")

    departments = _departments(application, project_id, work_item_id)
    assert departments["product"] == DepartmentState(state="waiting_user", note=None)
    assert departments["engineering"].state != "waiting_user"
    assert departments["quality"].state != "waiting_user"

    resumed: dict[str, Any] = {}
    _capture(system, lambda event: event.type == EventType.DEPARTMENT_ACTIVATED,
             lambda event: resumed.setdefault("departments", _departments(application, project_id, work_item_id)))
    _answer_decision(system, run_id)
    system.run_until_stop(run_id)
    assert resumed["departments"]["product"].state != "waiting_user"


def test_departments_are_null_without_a_run_and_while_interrupted(data_dir):
    # 验收第 6 条：没有 run、恢复观察状态是中断时没有部门状态
    system = _system(data_dir, _happy_script())
    project_id = system.projects.register("没有状态", GOAL)
    application = _application(system)
    # 还没有 run：排空期间登记的事项
    queued = system.projects.queue_work_item(project_id, "排队等开始的事项")
    assert _departments(application, project_id, queued) is None
    # run 建好、还没有一次激活：进程在步骤之间退出（中断）
    work_item_id, run_id = system.projects.start_work_item(project_id, "中断的事项")
    assert _departments(application, project_id, work_item_id) is None
    # 结束以后也没有：跑完一个完整的三部门循环
    system.run_until_stop(run_id)
    assert _departments(application, project_id, work_item_id) is None


def test_run_asks_gives_the_ask_id_parent_chain_depth_and_prd_revision(data_dir):
    # 验收第 7 条：回问的上一层、询问链与层数；产品的回答附带 PRD 新版本时有修订号
    system = _system(data_dir, _reask_script())
    project_id = system.projects.register("询问链", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    asks = _application(system).query("run.asks", RunAsks(run_id=run_id)).data.asks
    outer, inner = asks

    assert outer.id.startswith("ses_ask_")
    assert outer.id != inner.id
    assert outer.parent is None
    assert outer.chain == ["engineering"]
    assert outer.depth == 1
    assert outer.status == "已回答"
    assert outer.prd_revision == 2
    assert outer.started_at and outer.ended_at and outer.started_at <= outer.ended_at

    assert inner.parent == outer.id
    assert inner.chain == ["engineering", "product"]
    assert inner.depth == 2
    assert inner.prd_revision is None
    assert inner.started_at and inner.ended_at


def test_run_asks_gives_the_reason_of_an_ask_that_could_not_be_answered(data_dir):
    # 验收第 7 条后半：没能回答的询问有原因（质检问工程，工程的分支反复只回文字、不调用工具）
    limit = DEFINITIONS.rule_value("tool_call_required_limit")
    plain = lambda index: ModelResponse(output=[{"id": f"plain-{index}", "type": "message", "role": "assistant",
                                                  "content": [{"type": "output_text", "text": "普通文本，未调用工具。"}]}])
    system = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [ask_turn("engineering", "执行入口在哪里？", call_id="ask-1"),
                    review_turn("release", "checks passed on the current snapshot")],
        "engineering:ask": [plain(index) for index in range(limit + 1)],
    })
    project_id = system.projects.register("没能回答", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    [ask] = [item for item in _application(system).query("run.asks", RunAsks(run_id=run_id)).data.asks
             if item.question == "执行入口在哪里？"]
    assert ask.status == "没能回答"
    assert ask.answer is None
    assert ask.reason is not None and "without calling a tool" in ask.reason


def test_the_room_counts_the_questions_waiting_for_its_department(data_dir):
    # 验收第 8 条：房间的传信数等于问本部门、还没有回答的询问数
    system = _system(data_dir, _reask_script())
    project_id = system.projects.register("传信数", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    application = _application(system)
    captured: dict[str, Any] = {}

    def take(event: Any) -> None:
        if "rooms" not in captured:
            captured["rooms"] = {
                department: application.query(
                    "department.workspace",
                    DepartmentWorkspace(project_id=project_id, department=department, work_item=work_item_id)
                ).data.room.pipes.letters_waiting
                for department in ("product", "engineering", "quality")
            }

    _capture(system, lambda event: (event.type == EventType.ASK_STARTED
                                    and event.payload.get("recipient") == "product"), take)
    system.run_until_stop(run_id)

    # 工程问产品：产品房间的传信数是 1，其他部门是 0
    assert captured["rooms"] == {"product": 1, "engineering": 0, "quality": 0}


def test_every_event_that_changes_the_departments_is_in_the_three_refresh_lists():
    # 验收第 9 条：会改变部门状态的事件种类都在三个查询的刷新清单里（重放核对另有用例）
    needed = {EventType.DEPARTMENT_ACTIVATED, EventType.ACTIVATION_FINISHED, EventType.ASK_STARTED,
              EventType.ASK_ANSWERED, EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED,
              EventType.DECISION_WITHDRAWN, EventType.SPEC_ACCEPTED, EventType.DELIVERY_ACCEPTED,
              EventType.QA_SUBMITTED, EventType.RUN_CONTINUED, EventType.RUN_PAUSED, EventType.RUN_FAILED,
              EventType.RUN_DONE}
    for definition in (PROJECT_OVERVIEW, PROJECT_LOOP, DEPARTMENT_WORKSPACE):
        missing = needed - set(definition.changed_by)
        assert not missing, f"{definition.name} 的刷新清单缺少 {sorted(missing)}"
    assert {EventType.ASK_STARTED, EventType.ASK_ANSWERED} <= set(RUN_ASKS.changed_by)


def test_the_departments_do_not_read_the_run_projection_or_decisions_more_often(data_dir):
    # 验收第 10 条：每个事项读取 run 投影与决定请求的次数不增加（决定请求随投影一起读出）
    system = _system(data_dir, _happy_script())
    project_id = system.projects.register("读取次数", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.run_until_stop(run_id)
    application = _application(system)
    reads: list[str] = []
    original = system.store.projection
    system.store.projection = lambda stream: (reads.append(stream), original(stream))[1]
    try:
        for name, request in (
            ("project.overview", ProjectOverview(project_id=project_id)),
            ("project.loop", ProjectLoop(project_id=project_id)),
            ("department.workspace", DepartmentWorkspace(project_id=project_id, department="quality",
                                                         work_item=work_item_id)),
        ):
            reads.clear()
            application.query(name, request)
            # 一个事项两次：项目投影按事项取 run 的一次，查询自己取 run 与它的决定请求的一次
            assert reads.count(run_stream(run_id)) <= 2, (name, reads)
    finally:
        system.store.projection = original


# 三个部门各自的状态与原因（三部门的循环结构 docs/design/department-loop.md「职能的状态」，工单 #903）。
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
from harness.proposals import answer_turn, ask_turn, delivery_turn, judgement_turn, product_spec, review_turn
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
        "quality": [explore_turn(), judgement_turn(), review_turn("release", "checks passed on the current snapshot")],
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
        "quality": [explore_turn(), judgement_turn(), review_turn("release", "checks passed on the current snapshot")],
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
    state: dict[str, Any] = {"judged": None}

    def engineering_turn(call):
        if deliveries["count"]:
            snapshots.setdefault("rework", take())
        deliveries["count"] += 1
        return delivery_turn()(call)

    def quality_turn(call):
        if not prompt_part(call, "current_delivery_spec"):
            return explore_turn()
        # 这份交付还没有独立判断时先交独立判断（先判断后看解释，工单 #358）
        if state["judged"] != prompt_part(call, "current_delivery_spec"):
            state["judged"] = prompt_part(call, "current_delivery_spec")
            return judgement_turn()(call)
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


def test_the_role_bar_does_not_use_the_item_title_as_the_current_task(data_dir):
    # 工单 #1230：角色的 task 只在有事实说明它此刻做什么时才填。现在系统里没有这样的事实
    # （一个部门只有一个角色，没有哪一项记录写着它此刻手上的事），所以事项进行中时它也是空；
    # 事项标题只留在房间屏幕的目标行（crt.target），不再借过来当角色的任务
    system = _system(data_dir, _happy_script())
    project_id = system.projects.register("角色条", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    application = _application(system)
    captured: dict[str, Any] = {}

    def take(event: Any) -> None:
        if "rooms" not in captured:
            # 事项进行中：工程刚开始这一步，run 还没有结束
            captured["rooms"] = {
                department: application.query(
                    "department.workspace",
                    DepartmentWorkspace(project_id=project_id, department=department, work_item=work_item_id)
                ).data.room
                for department in ("product", "engineering", "quality")
            }
            captured["item"] = application.query(
                "project.overview", ProjectOverview(project_id=project_id, work_item=work_item_id)
            ).data.work_items[0]

    _capture(system, lambda event: (event.type == EventType.DEPARTMENT_ACTIVATED
                                    and event.department == "engineering"), take)
    system.run_until_stop(run_id)

    assert captured["item"].status == "in_progress"
    for department, room in captured["rooms"].items():
        assert room.roles[0].task is None, (department, room.roles[0])
        assert room.crt.target == "做一件事"


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


def _ask_user_turn(call_id: str, questions: list[dict[str, object]], note: str | None = None) -> Any:
    import json
    payload: dict[str, object] = {"questions": questions}
    if note is not None:
        payload["note"] = note
    return ModelResponse(output=[{
        "id": call_id, "call_id": call_id, "type": "function_call",
        "name": "ask_user", "arguments": json.dumps(payload, ensure_ascii=False),
    }])


def _definitions_with_ask_user(
    target: Any,
    *,
    source_dir: Any = None,
    roles: tuple[str, ...] = ("product", "engineering", "quality"),
) -> Any:
    import json
    import shutil
    from harness.definitions import DEFINITIONS_DIR, load_definitions

    if not target.exists():
        shutil.copytree(source_dir or DEFINITIONS_DIR, target)
    roles_path = target / "roles.json"
    roles_doc = json.loads(roles_path.read_text(encoding="utf-8"))
    for role in roles:
        if role in roles_doc and "ask_user" not in roles_doc[role]["tools"]:
            roles_doc[role]["tools"].append("ask_user")
    roles_path.write_text(json.dumps(roles_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    work_items_path = target / "work_items.json"
    work_items_doc = json.loads(work_items_path.read_text(encoding="utf-8"))
    departments = work_items_doc["kinds"]["change"]["departments"]
    for role in roles:
        dept_cfg = departments.get(role)
        if isinstance(dept_cfg, dict) and "tools" in dept_cfg and "ask_user" not in dept_cfg["tools"]:
            dept_cfg["tools"].append("ask_user")
    work_items_path.write_text(json.dumps(work_items_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(target)


def test_role_choice_marks_only_asker_waiting_user_without_blocking_other_departments_and_pauses_timers(data_dir):
    # 守 R1 与 R2：工程调用 ask_user 生成 role_choice（blocks=round），等待期间仅工程显示 waiting_user（附原因），
    # 同一事项的质检照常推进探索而不被阻塞；等待耗时不计入会话或运行总墙钟耗时，单职能限时按实际等待时长顺延
    import threading
    import time
    import traceback
    from harness.definitions import DEFAULT_FORM
    from harness.models import TERMINAL_STATUSES
    from harness.tests.signals import Signals, SignallingAdapter
    from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
    from harness.tightening import WATCHED_OUTPUTS

    questions = [
        {
            "id": "q1",
            "question": "CLI 参数为空时是否返回非零退出码？",
            "options": [
                {"id": "nonzero", "label": "返回退出码 1"},
                {"id": "empty", "label": "输出空行并成功退出"},
            ],
            "recommended": "nonzero",
            "rationale": "便于脚本检测输入错误",
        },
        {
            "id": "q2",
            "question": "是否保留末尾换行符？",
            "options": [{"id": "keep", "label": "保留"}, {"id": "strip", "label": "去除"}],
            "recommended": "keep",
            "rationale": "保持原始输出",
        },
    ]

    qa_finished = threading.Event()
    eng_waiting = threading.Event()
    decision_id_box: list[str] = []
    abort_notes: list[str] = []
    snapshots: dict[str, Any] = {}
    timings: dict[str, int] = {}
    thread_errors: list[str] = []

    defs = _definitions_with_ask_user(data_dir / "defs_wait")
    signals = Signals({"ask_opened": "工程已发出 role_choice 决定请求"})
    adapter = SignallingAdapter(
        {
            "product": [product_spec()],
            "engineering": [_ask_user_turn("au-eng-1", questions, note="确认 CLI 边界"), delivery_turn()],
            "quality": [explore_turn(), judgement_turn(), review_turn("release", "checks passed on the current snapshot")],
        },
        waits={("quality", 0): "ask_opened"},
        signals=signals,
    )
    system = LoopSystem.for_testing(
        data_dir / "run_wait",
        adapter,
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        project_id = system.projects.register("向用户提问局域阻塞", GOAL)
        work_item_id, run_id = system.projects.start_work_item(project_id, "验证 role_choice 不阻塞质检")
        application = _application(system)

        def on_events(events: list[Any]) -> None:
            for event in events:
                if event.type == EventType.DECISION_REQUESTED and (event.payload or {}).get("kind") == "role_choice":
                    decision_id_box.append(event.event_id)
                    eng_waiting.set()
                elif event.type == EventType.ACTIVATION_FINISHED and event.department == "quality":
                    qa_finished.set()
                elif ((event.type == EventType.ACTIVATION_FINISHED and event.department == "engineering"
                       and not eng_waiting.is_set())
                      or (event.state_after in TERMINAL_STATUSES and not qa_finished.is_set())):
                    abort_notes.append(f"{event.type}:{event.department}:{event.state_after}:{event.payload}")
                    eng_waiting.set()
                    qa_finished.set()

        system.store.subscribe(on_events)

        def answer_after_qa_and_pause() -> None:
            try:
                assert eng_waiting.wait(timeout=WAIT_FOR_HOST_WORK_SEC)
                assert not abort_notes, repr(abort_notes)
                snapshots["while_waiting"] = _departments(application, project_id, work_item_id)
                snapshots["overview_while_waiting"] = application.query(
                    "project.overview", ProjectOverview(project_id=project_id, work_item=work_item_id)
                ).data.work_items[0]
                signals.fire("ask_opened")
                assert qa_finished.wait(timeout=WAIT_FOR_HOST_WORK_SEC)
                assert not abort_notes, repr(abort_notes)
                # 等待薄驱动在质检 ACTIVATION_FINISHED 提交紧接的 rebase_run_clock 与暂停态完成落表再采样
                thin = system.orchestrator._thin_driver
                settled_deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
                while (thin.segment_ms.get(run_id, 0) != 0
                       or run_id in thin._segment_start
                       or (run_id, "engineering") not in thin._waiting_rounds):
                    if time.monotonic() >= settled_deadline:
                        raise AssertionError("计时器未在等待质检收尾后进入暂停稳态")
                    time.sleep(0.01)
                snapshots["after_qa"] = _departments(application, project_id, work_item_id)
                # 此时质检已完成本轮、唯独工程等待用户：等待 1.5 秒期间运行与会话计时器保持暂停
                # （wait 前后已用毫秒完全不变），等待结束回答后继续完成本轮
                eng_session_id = system.project(run_id).sessions["engineering"].session_id
                timings["run_before"] = system.orchestrator._elapsed_ms(run_id)
                timings["eng_before"] = int(system.orchestrator._session_elapsed_sec(run_id, eng_session_id) * 1000)
                time.sleep(1.5)
                timings["run_after"] = system.orchestrator._elapsed_ms(run_id)
                timings["eng_after"] = int(system.orchestrator._session_elapsed_sec(run_id, eng_session_id) * 1000)
                dec = next(item for item in saved_decisions(system.store, statuses=("open",))[1]
                           if item.decision_id == decision_id_box[0])
                cmd = Command(str(uuid.uuid4()), "decision.answer", "sha256:rc", "user:local")
                system.orchestrator.answer_decision(
                    dec.decision_id, "submit", "按推荐与约定", base_version=dec.version,
                    command=cmd, answers={"q1": "nonzero"},
                )
            except BaseException:
                thread_errors.append(traceback.format_exc())
                try:
                    system.orchestrator.cancel(run_id)
                except Exception:
                    pass

        answerer = threading.Thread(target=answer_after_qa_and_pause, daemon=True)
        answerer.start()
        result = system.run_until_stop(run_id)
        answerer.join(timeout=WAIT_FOR_HOST_WORK_SEC)

        assert not thread_errors, "\n".join(thread_errors)
        assert adapter.wait_failures == []
        assert result.status == "done"
        assert snapshots["overview_while_waiting"].status == "in_progress"
        while_waiting = snapshots["while_waiting"]
        assert while_waiting["engineering"] == DepartmentState(
            state="waiting_user", note="向用户提问，等待选择（2 题）")
        assert while_waiting["quality"].state != "waiting_user"

        after_qa = snapshots["after_qa"]
        assert after_qa["engineering"].state == "waiting_user"
        assert after_qa["quality"].state == "waiting"

        # 验证纯等待的 1.5s 未增加工程会话累计耗时与运行总墙钟耗时
        assert timings["run_after"] == timings["run_before"]
        assert timings["eng_after"] == timings["eng_before"]
        assert result.delivery_spec is not None
    finally:
        system.close()


def test_waiting_role_choice_is_withdrawn_when_run_cancels_or_ends(data_dir):
    # 守 R1 与 R2：在等待 role_choice 回答期间取消事项，未答决定自动撤销且等待中的轮次干净收尾
    import threading
    import traceback
    from harness.definitions import DEFAULT_FORM
    from harness.models import TERMINAL_STATUSES
    from harness.tests.signals import Signals, SignallingAdapter
    from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
    from harness.tightening import WATCHED_OUTPUTS

    questions = [
        {
            "id": "q1",
            "question": "是否需要额外日志开关？",
            "options": [{"id": "yes", "label": "需要"}, {"id": "no", "label": "不需要"}],
            "recommended": "no",
            "rationale": "保持简洁",
        }
    ]
    opened = threading.Event()
    cancel_abort_notes: list[str] = []
    cancel_errors: list[str] = []
    defs = _definitions_with_ask_user(data_dir / "defs_cancel")
    signals = Signals({"ask_opened": "工程已发出 role_choice 决定请求"})
    adapter = SignallingAdapter(
        {
            "product": [product_spec()],
            "engineering": [_ask_user_turn("au-cancel", questions), delivery_turn()],
            "quality": [explore_turn(), judgement_turn(), review_turn("release", "ok")],
        },
        waits={("quality", 0): "ask_opened"},
        signals=signals,
    )
    system = LoopSystem.for_testing(
        data_dir / "run_cancel",
        adapter,
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        project_id = system.projects.register("取消撤销提问", GOAL)
        _work_item_id, run_id = system.projects.start_work_item(project_id, "等待中取消")

        def on_events(evs: list[Any]) -> None:
            for ev in evs:
                if ev.type == EventType.DECISION_REQUESTED and (ev.payload or {}).get("kind") == "role_choice":
                    signals.fire("ask_opened")
                    opened.set()
                elif ((ev.type == EventType.ACTIVATION_FINISHED and ev.department == "engineering"
                       and not opened.is_set())
                      or (ev.state_after in TERMINAL_STATUSES and not opened.is_set())):
                    cancel_abort_notes.append(f"{ev.type}:{ev.department}:{ev.state_after}:{ev.payload}")
                    signals.fire("ask_opened")
                    opened.set()

        system.store.subscribe(on_events)

        def cancel_when_waiting() -> None:
            try:
                assert opened.wait(timeout=WAIT_FOR_HOST_WORK_SEC)
                assert not cancel_abort_notes, repr(cancel_abort_notes)
                system.orchestrator.cancel(run_id)
            except BaseException:
                cancel_errors.append(traceback.format_exc())
                try:
                    system.orchestrator.cancel(run_id)
                except Exception:
                    pass

        canceller = threading.Thread(target=cancel_when_waiting, daemon=True)
        canceller.start()
        result = system.run_until_stop(run_id)
        canceller.join(timeout=WAIT_FOR_HOST_WORK_SEC)

        assert not cancel_errors, "\n".join(cancel_errors)

        assert result.status == "failed"
        assert result.stop_reason == "cancelled"
        decisions = [d for d in saved_decisions(system.store)[1] if d.run_id == run_id and d.kind == "role_choice"]
        assert len(decisions) == 1
        assert decisions[0].status == "withdrawn"
    finally:
        system.close()

    # 另一并发职能在等待期间因失败终止事项，同样自动撤销未答 role_choice 并收束等待中的轮次
    from harness.adapters.base import ProviderError
    fail_signals = Signals({"ask_opened_fail": "工程已发出 role_choice 决定请求"})
    fail_adapter = SignallingAdapter(
        {
            "product": [product_spec()],
            "engineering": [_ask_user_turn("au-fail", questions), delivery_turn()],
            "quality": [ProviderError("boom", reason="provider_error", retryable=False)],
        },
        waits={("quality", 0): "ask_opened_fail"},
        signals=fail_signals,
    )
    fail_sys = LoopSystem.for_testing(
        data_dir / "run_end_withdraw",
        fail_adapter,
        forms={DEFAULT_FORM: (defs, WATCHED_OUTPUTS)},
    )
    try:
        pid2 = fail_sys.projects.register("失败撤销提问", GOAL)
        _wid2, rid2 = fail_sys.projects.start_work_item(pid2, "等待中他方结束")
        fail_sys.store.subscribe(lambda evs: [
            fail_signals.fire("ask_opened_fail") for ev in evs
            if ev.type == EventType.DECISION_REQUESTED and (ev.payload or {}).get("kind") == "role_choice"
        ])
        end_res = fail_sys.run_until_stop(rid2)
        assert fail_adapter.wait_failures == []
        assert end_res.status == "failed"
        assert end_res.stop_reason == "provider_error"
        decs2 = [d for d in saved_decisions(fail_sys.store)[1] if d.run_id == rid2 and d.kind == "role_choice"]
        assert len(decs2) == 1
        assert decs2[0].status == "withdrawn"
    finally:
        fail_sys.close()


def test_http_work_item_create_ask_user_decision_answer_completes_without_no_new_work(data_dir):
    # 守 R1 与 R2：经真实 HTTP API（project.create -> work_item.create -> decisions.list -> decision.answer）
    # 全链路驱动三类场景（默认形态单职能发起、默认形态多职能并发、single_role_direct 直做形态），
    # 确认均不会并发启动第二个 run_until_stop 或触发 no_new_work 失败，且最终收敛到 done 与 DELIVERABLE_ADOPTED
    import threading
    import time
    from harness.adapters.fake import FakeTurn
    from harness.definitions import DEFAULT_FORM, DEFINITIONS_DIR
    from harness.direct import DIRECT_TIGHTENING, SINGLE_ROLE_DIRECT
    from harness.models import ProjectEventType, TERMINAL_STATUSES
    from harness.proposals import completion_turn
    from harness.tests.api_helpers import running_api
    from harness.tests.helpers import quality_turns
    from harness.tests.signals import Signals, SignallingAdapter
    from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
    from harness.tightening import WATCHED_OUTPUTS

    questions = [
        {
            "id": "q1",
            "question": "默认输出是否保留前缀？",
            "options": [{"id": "keep", "label": "保留"}, {"id": "plain", "label": "去前缀"}],
            "recommended": "keep",
            "rationale": "便于识别输出格式",
        }
    ]
    default_defs = _definitions_with_ask_user(data_dir / "defs_http_default")
    direct_defs = _definitions_with_ask_user(
        data_dir / "defs_http_direct",
        source_dir=DEFINITIONS_DIR / "forms" / SINGLE_ROLE_DIRECT,
        roles=("engineering",),
    )
    forms = {
        DEFAULT_FORM: (default_defs, WATCHED_OUTPUTS),
        SINGLE_ROLE_DIRECT: (direct_defs, DIRECT_TIGHTENING),
    }

    def run_http_scenario(
        subdir: str,
        adapter: Any,
        *,
        expected_asker: str,
        expected_stop_reason: str,
        form: str | None = None,
        answer_option: str = "submit",
        answer_extra: dict[str, Any] | None = None,
        extra_wait: threading.Event | None = None,
        on_event: Any = None,
    ) -> None:
        system = LoopSystem.for_testing(data_dir / subdir, adapter, forms=forms)
        opened = threading.Event()
        abort_notes: list[str] = []

        def watch(evs: list[Any]) -> None:
            for ev in evs:
                if on_event is not None:
                    on_event(ev)
                if ev.type == EventType.DECISION_REQUESTED and (ev.payload or {}).get("kind") == "role_choice":
                    opened.set()
                elif getattr(ev, "state_after", None) in TERMINAL_STATUSES and not opened.is_set():
                    abort_notes.append(f"{ev.type}:{getattr(ev, 'department', None)}:{ev.state_after}:{ev.payload}")
                    opened.set()
                    if extra_wait is not None:
                        extra_wait.set()

        system.store.subscribe(watch)
        with running_api(lambda: Application(system)) as client:
            proj_resp = client.post("/api/commands/project.create", json={
                "command_id": str(uuid.uuid4()),
                "name": f"HTTP {subdir}",
                "goal": GOAL,
            })
            assert proj_resp.status_code == 200, proj_resp.text
            project_id = proj_resp.json()["refs"]["project_id"]

            item_body: dict[str, Any] = {
                "command_id": str(uuid.uuid4()),
                "project_id": project_id,
                "text": "经真实接口完成带 ask_user 的工作项",
            }
            if form is not None:
                item_body["form"] = form
            item_resp = client.post("/api/commands/work_item.create", json=item_body)
            assert item_resp.status_code == 200, item_resp.text
            refs = item_resp.json()["refs"]
            work_item_id, run_id = refs["work_item_id"], refs["run_id"]

            assert opened.wait(timeout=WAIT_FOR_HOST_WORK_SEC), abort_notes
            if extra_wait is not None:
                assert extra_wait.wait(timeout=WAIT_FOR_HOST_WORK_SEC), abort_notes
            assert not abort_notes, repr(abort_notes)

            listed = client.get("/api/queries/decisions.list", params={
                "project_id": project_id,
                "work_item_id": work_item_id,
                "status": ["open"],
            })
            assert listed.status_code == 200, listed.text
            [dec] = listed.json()["data"]["decisions"]
            assert dec["kind"] == "role_choice"
            assert dec["blocks"] == "round"
            assert dec["request"]["department"] == expected_asker

            ans_body: dict[str, Any] = {
                "command_id": str(uuid.uuid4()),
                "decision_id": dec["decision_id"],
                "option": answer_option,
                "base_version": dec["version"],
            }
            if answer_extra:
                ans_body.update(answer_extra)
            ans_resp = client.post("/api/commands/decision.answer", json=ans_body)
            assert ans_resp.status_code == 200, ans_resp.text

            deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
            while time.monotonic() < deadline:
                proj = system.project(run_id)
                if (proj.status in TERMINAL_STATUSES
                        and system.orchestrator.execution(run_id) is None
                        and system.orchestrator.work_item_execution(run_id) is None):
                    break
                time.sleep(0.02)
            else:
                raise AssertionError(f"{subdir} 未在 {WAIT_FOR_HOST_WORK_SEC}s 内收敛结束：{system.project(run_id)}")

            assert [e for e in system.store.list_events(run_id) if e.type == EventType.RUN_FAILED] == []
            final_proj = system.project(run_id)
            assert (final_proj.status, final_proj.stop_reason) == ("done", expected_stop_reason)
            adopted = [
                e for e in system.store.list_project_events(project_id)
                if e.type == ProjectEventType.DELIVERABLE_ADOPTED and (e.payload or {}).get("run_id") == run_id
            ]
            assert len(adopted) == 1

    # 1) 默认 WATCHED_OUTPUTS 形态，单职能发起：product 提问 -> HTTP 回答 -> 流转工程与质检放行至 done
    run_http_scenario(
        "http_single_product",
        FakeAdapter({
            "product": [_ask_user_turn("au-http-prod", questions), product_spec()],
            "engineering": [delivery_turn()],
            "quality": quality_turns("release", "checks passed on the current snapshot"),
        }),
        expected_asker="product",
        expected_stop_reason="released",
        answer_extra={"answers": {"q1": "keep"}, "note": "接口回答继续执行"},
    )

    # 2) 默认 WATCHED_OUTPUTS 形态，多职能并发：engineering 提问暂停同时 quality 完成预测性探索 -> HTTP 回答 -> done
    concurrent_signals = Signals({"eng_asked": "工程已发出 role_choice 决定请求"})
    qa_explored = threading.Event()
    concurrent_adapter = SignallingAdapter(
        {
            "product": [product_spec()],
            "engineering": [_ask_user_turn("au-http-eng", questions), delivery_turn()],
            "quality": [explore_turn(), judgement_turn(), review_turn("release", "checks passed on the current snapshot")],
        },
        waits={("quality", 0): "eng_asked"},
        signals=concurrent_signals,
    )

    def on_concurrent_event(ev: Any) -> None:
        if ev.type == EventType.DECISION_REQUESTED and (ev.payload or {}).get("kind") == "role_choice":
            concurrent_signals.fire("eng_asked")
        elif ev.type == EventType.ACTIVATION_FINISHED and getattr(ev, "department", None) == "quality":
            qa_explored.set()
        elif getattr(ev, "state_after", None) in TERMINAL_STATUSES:
            concurrent_signals.fire("eng_asked")

    run_http_scenario(
        "http_concurrent_eng",
        concurrent_adapter,
        expected_asker="engineering",
        expected_stop_reason="released",
        answer_option="recommended",
        extra_wait=qa_explored,
        on_event=on_concurrent_event,
    )
    assert concurrent_adapter.wait_failures == []

    # 3) 直做路由 single_role_direct 形态：work_item.create 指定 form=SINGLE_ROLE_DIRECT -> 回答后开环完成 done
    run_http_scenario(
        "http_single_role_direct",
        FakeAdapter({
            "engineering": [
                _ask_user_turn("au-http-direct", questions),
                FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}, checks={}),
                completion_turn("按用户选择补全直做实现"),
            ],
        }),
        expected_asker="engineering",
        expected_stop_reason="open_loop",
        form=SINGLE_ROLE_DIRECT,
        answer_extra={"answers": {"q1": "keep"}, "note": "直做回答继续执行"},
    )



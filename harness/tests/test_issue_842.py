# 工单 #842：询问被回答以后，事项的「所在部门」回到提问的部门。
#
# 原因：询问分支是被询问方的一次旁支工作，它的激活（DEPARTMENT_ACTIVATED）以前
# 无条件改写 run 的 active_department，提问方拿到回答以后继续工作，页面上仍然
# 停在被询问的部门（工单正文里的 run_874f4b3925164593：工程在工作，显示产品）。
# 现在分支会话的激活不改写事项的所在部门，所在部门只由主线会话的激活推出。

from pathlib import Path
from typing import Any

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import DepartmentWorkspace, ProjectOverview
from harness.models import EventType
from harness.proposals import answer_turn, ask_turn, delivery_turn, product_spec, review_turn
from harness.projection import replay_events
from harness.runtime import LoopSystem

GOAL = "把文本按行处理清楚"


def _ask_script() -> dict[str, Any]:
    # 工程在主线会话里询问产品，产品在询问分支会话里回答，工程拿到回答以后接着工作
    return {
        "product": [product_spec()],
        "engineering": [
            ask_turn(recipient="product", question="输出要不要改成大写？"),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [answer_turn(answer="不改，保持原样。")],
        "quality": [review_turn("release", "ok")],
    }


def _system(data_dir: Path) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(_ask_script()))


def test_active_department_stays_with_the_asking_department_after_the_answer(tmp_path: Path):
    # 询问被回答以后，所在部门回到提出询问的部门：工程继续工作，显示工程
    system = _system(tmp_path)
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # 产品提交初始 PRD
    projection = system.activate_once(run_id)  # 工程询问产品，产品在分支里回答，工程接着工作

    events = system.store.list_events(run_id)
    assert any(event.type == EventType.ASK_STARTED for event in events)
    assert any(event.type == EventType.ASK_ANSWERED for event in events)
    # 询问确实发生过：被询问的是产品，提问的是工程
    answered = next(event for event in events if event.type == EventType.ASK_ANSWERED)
    assert answered.payload["requester"] == "engineering"
    assert answered.payload["recipient"] == "product"
    # 回答以后工程继续工作，所在部门是工程
    assert projection.active_department == "engineering"


def test_ask_branch_activation_does_not_take_over_the_department(tmp_path: Path):
    # 根因那一处：询问分支会话的激活不改写事项的所在部门（工单 #842）
    system = _system(tmp_path)
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # 产品提交初始 PRD
    system.activate_once(run_id)  # 工程询问产品并继续工作

    events = system.store.list_events(run_id)
    branch = next(
        event for event in events
        if event.type == EventType.DEPARTMENT_ACTIVATED and event.department == "product"
        and event.session_id != next(
            main.session_id for main in events
            if main.type == EventType.DEPARTMENT_ACTIVATED and main.department == "product"
            and main.session_id.startswith("ses_pro"))
    )
    assert branch.session_id.startswith("ses_ask")
    # 分支激活发生的那一刻，所在部门仍是主线上的工程
    through_branch = replay_events(events[:events.index(branch) + 1])
    assert through_branch.active_department == "engineering"
    # 分支结束以后仍然是工程
    assert replay_events(events).active_department == "engineering"


def test_overview_and_department_page_agree_on_who_is_working(tmp_path: Path):
    # 事项卡、概览与部门页说同一件事：所在部门是工程，部门页上工程在工作、产品没有
    system = _system(tmp_path)
    project_id = system.projects.register("事项所在部门", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    system.activate_once(run_id)  # 产品提交初始 PRD
    system.activate_once(run_id)  # 工程询问产品，产品在分支里回答，工程接着工作

    application = Application(system)
    overview = application.query("project.overview", ProjectOverview(project_id=project_id)).data
    card = next(entry for entry in overview.work_items if entry.work_item_id == work_item_id)
    assert card.department == "engineering"

    engineering = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="engineering", work_item=work_item_id)).data
    product = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="product", work_item=work_item_id)).data
    assert engineering.active is True
    assert engineering.room.status == "working"
    assert product.active is False
    assert product.room.status != "working"


def test_run_failed_carries_the_department_that_was_working(tmp_path: Path):
    # run_failed 事件里的 department 取失败发生时正在工作的部门（工程），不是被询问的产品
    system = _system(tmp_path)
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # 产品提交初始 PRD
    system.activate_once(run_id)  # 工程询问产品，产品在分支里回答，工程接着工作
    system.cancel(run_id)

    events = system.store.list_events(run_id)
    failed = next(event for event in events if event.type == EventType.RUN_FAILED)
    assert failed.department == "engineering"

def test_ask_branch_activation_does_not_count_as_a_cycle(tmp_path: Path):
    # 工单 #857：轮次只计主线会话的激活。工程询问产品，产品在分支里回答，
    # 分支的那一次激活不算一轮，事项的 cycle_count 仍等于主线激活的次数。
    system = _system(tmp_path)
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # 产品提交初始 PRD
    projection = system.activate_once(run_id)  # 工程询问产品，产品在分支里回答

    events = system.store.list_events(run_id)
    activated = [event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED]
    main = [event for event in activated if not event.session_id.startswith("ses_ask")]
    branch = [event for event in activated if event.session_id.startswith("ses_ask")]
    assert main and branch
    # 主线两次激活（产品、工程），分支的一次激活不加一
    assert projection.cycle_count == len(main) == 2
    # 分支激活事件里的 cycle 与回答以后投影的 cycle_count 相同（设计第 4.2 节）
    assert branch[0].payload["cycle"] == projection.cycle_count


def _finishing_script() -> dict[str, Any]:
    # 一次询问走完整个事项：产品提交 PRD，工程询问产品以后交付，质检起草用例后放行
    return {
        "product": [product_spec()],
        "engineering": [
            ask_turn(recipient="product", question="输出要不要改成大写？"),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        ],
        "product:ask": [answer_turn(answer="不改，保持原样。")],
        "quality": [review_turn("release", "按 PRD 起草了测试用例；还没有交付可以核验"),
                    review_turn("release", "ok")],
    }


def test_cycle_count_of_a_full_ask_run_counts_only_the_main_activations(tmp_path: Path):
    # 整件事项跑完：投影的 cycle_count 等于主线的激活次数，不含询问分支的那一次
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(_finishing_script()))
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"

    events = system.store.list_events(run_id)
    activated = [event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED]
    main = [event for event in activated if not event.session_id.startswith("ses_ask")]
    branch = [event for event in activated if event.session_id.startswith("ses_ask")]
    assert len(branch) == 1
    assert projection.cycle_count == len(main)
    # 分支激活的 cycle 与回答那一刻的投影相同：回答以后主线接着工作才加一
    answered_at = next(index for index, event in enumerate(events) if event.type == EventType.ASK_ANSWERED)
    through_answer = replay_events(events[:answered_at + 1])
    assert branch[0].payload["cycle"] == through_answer.cycle_count


def test_max_cycles_equal_to_the_main_activations_does_not_stop_an_ask(tmp_path: Path):
    # 轮次上限恰好等于主线激活次数时，一次询问分支不让事项因轮次上限停止
    counting = LoopSystem.for_testing(tmp_path / "counting", FakeAdapter(_finishing_script()))
    counting_run = counting.create_run("build echo")
    counting.run_until_stop(counting_run)
    main_activations = len([
        event for event in counting.store.list_events(counting_run)
        if event.type == EventType.DEPARTMENT_ACTIVATED and not event.session_id.startswith("ses_ask")
    ])
    assert main_activations > 0

    system = LoopSystem.for_testing(tmp_path / "bounded", FakeAdapter(_finishing_script()))
    run_id = system.create_run("build echo", max_cycles=main_activations)
    projection = system.run_until_stop(run_id)
    assert projection.cycle_count == main_activations
    assert (projection.status, projection.stop_reason) == ("done", "released")

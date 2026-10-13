# 工单 #317：建档在进程中断时的行为（docs/design/existing-project-onboarding.md 第 6 节前三行，
# 第 10 节第 11 项的前三段）。三个场景都用真实的子进程运行系统并被终止：检查是真实进程，等它写下
# started 标记以后终止；「run 结束以后、结算以前」与「回答以后、新 run 建立以前」这两个窗口没有子进程
# 可等，在对应事件提交以后停住。每次终止以后都用同一个数据目录重新打开系统，走启动时的自动继续。
# 「补做之前」的状态从只读连接读出（run.observed）：系统打开数据目录时会立刻补做结算与补建缺少的 run。
# 模型回答由 FakeAdapter 给出，不使用 mock。辅助代码在 harness/tests/process_kill.py（与 #307 共用）。

from harness.artifacts import ArtifactRef
from harness.models import EventType, ProjectEventType
from harness.projection import saved_decisions
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.tests import process_kill as killed
from harness.tests.helpers import run_wait_command
from harness.tests.onboarding_project import (
    ONBOARDING_GOAL as GOAL,
    ONBOARDING_REQUIREMENT as REQUIREMENT,
    onboarding_source as _source,
)

NOTE = "现有 CLI 还没有 --help，初始 PRD 要把这个用法说明写进去"


def _product_turn() -> dict:
    return {"proposal": product_spec(requirements=[REQUIREMENT],
                                     acceptance=["run the CLI with a word"])}


def _structure_turn(checks: dict | None = None) -> dict:
    # 结构说明与它要求的检查写在同一次回答里：回执必须绑定同一次激活（设计第 4.1 节）
    checks = {"smoke": 0} if checks is None else checks
    turn = structure_turn(requirement_locations=[{"requirement": REQUIREMENT,
                                                 "locations": ["src/echo.py"]}], checks=checks)
    return {"proposal": turn.proposal, "checks": checks}


def _review_turn(checks: dict | None = None) -> dict:
    checks = {"smoke": 0} if checks is None else checks
    turn = baseline_review_turn(
        conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}],
        checks=checks)
    return {"proposal": turn.proposal, "checks": checks}


def _happy() -> list[dict]:
    return [_product_turn(), _structure_turn(), _review_turn()]



def _check_action(run) -> str:
    # 那个逻辑动作的编号（工程部在这一次激活里跑检查）
    started = [event.payload for event in run.before_events if event.type == EventType.TOOL_STARTED
               and event.payload.get("name") == "run_check"]
    assert started, "建档中的 run_check 没有被执行"
    return str(started[-1]["id"])


def _attempts(run, action_id: str) -> list[dict]:
    return killed.tool_attempts(run.after, run.run_id, action_id)


def _open_initial_prd(system, project_id: str) -> list:
    _position, decisions = saved_decisions(system.store, projects=(project_id,),
                                           kinds=("initial_prd",), statuses=("open",))
    return decisions


def _candidates(system, project_id: str) -> list:
    return system.projects.projection(project_id).initial_prd_candidates




def test_a_killed_onboarding_check_is_retried_and_the_round_finishes(tmp_path):
    # 验收一：建档 run 在 run_check 的真实进程执行中被终止，重启后自动重新执行一次
    # （检查的契约声明可以重复，不发决定请求），建档照常走完第一轮
    data_dir = tmp_path / "data"
    signals = tmp_path / "signals"
    signals.mkdir()
    blocking = {"smoke": {"command": run_wait_command(signals)}}
    # 产品的规格以后是带着阻塞检查的结构说明：进程在这个检查的进程里被终止
    script = [_product_turn(), _structure_turn(blocking)]

    # 第一次：检查的真实进程开始运行以后终止
    first = killed.interrupted(data_dir, script, task=GOAL, onboard=_source(tmp_path / "source"),
                               started=signals / "started", resume_after=False)
    action_id = _check_action(first)
    assert len(_attempts(first, action_id)) == 1, "第一次执行只留下一条 tool_started"
    assert _attempts(first, action_id)[0]["result_type"] is None, "被终止的检查没有落盘结果"

    # 重启：放行检查，启动恢复自动重新执行它（用记录下来的 argv），跑完以后结构说明重新提交，
    # 基线核验的回答由恢复的脚本给出；子进程直接运行到停止
    (signals / "release").write_text("go", encoding="utf-8")
    second = killed.restarted(data_dir, [_structure_turn(), _review_turn()], resume_after=False)
    attempts = _attempts(second, action_id)
    assert len(attempts) == 2, "自动重新执行一次，尝试次数是两次"
    assert attempts[1]["auto_retry_of"] == attempts[0]["event_id"], "新的一次尝试指向被取代的那次"
    assert attempts[1]["result_type"] == "tool_called", "重新执行的检查跑完了"
    assert killed.unknown_action_requests(second.after, first.run_id) == [], \
        "检查的契约声明可以重复，不需要问用户"

    # 重启的子进程跑完这一轮并结算：基线核验通过以后有一个候选与一个决定请求
    after = second.after
    finished = after.project(first.run_id)
    assert finished.phase == "DONE", finished.error
    assert finished.stop_reason == "baseline_verified"
    project_id = after.store.list_project_ids()[0]
    assert len(_candidates(after, project_id)) == 1, "第一轮结算出一个初始 PRD 的候选"
    assert len(_open_initial_prd(after, project_id)) == 1, "并且发出一个决定请求"

    second.close()
    first.close()


def test_a_kill_between_run_done_and_settlement_settles_once_on_startup(tmp_path):
    # 验收二：run 结束以后、候选写入之前终止进程。候选与决定请求在同一个事务中写入，
    # 重启时启动补做结算：只有一个候选与一个决定请求
    data_dir = tmp_path / "data"
    # 子进程在 run_done 提交以后停住：结算还没有发生
    with killed.interrupted(data_dir, _happy(), task=GOAL, onboard=_source(tmp_path / "source"),
                            hold_after=EventType.RUN_DONE) as run:
        project_id = str(run.observed["project_id"])
        events = run.observed["events"]
        assert [event.type for event in events].count(EventType.RUN_DONE) == 1, "run 已经结束"
        proposed = [event for event in run.observed["project_events"]
                    if event.type == ProjectEventType.INITIAL_PRD_PROPOSED]
        assert proposed == [], "补做结算以前还没有候选"
        assert run.observed["open_decisions"] == [], "补做结算以前还没有决定请求"

        # 重启：启动补做结算，一个候选与一个决定请求
        after = run.after
        assert len(_candidates(after, project_id)) == 1, "启动补做结算写出一个候选"
        assert len(_open_initial_prd(after, project_id)) == 1, "并且发出一个决定请求"
        events = after.store.list_project_events(project_id)
        proposed = [event for event in events if event.type == ProjectEventType.INITIAL_PRD_PROPOSED]
        assert len(proposed) == 1, "候选只写入一次，补做结算不重复写入"


def test_a_kill_after_the_revision_answer_rebuilds_the_missing_run(tmp_path):
    # 验收三：回答「提出修改」以后、新 run 创建以前终止进程。重启时按 onboarding_revision_started
    # 建立缺少的 run，修改意见仍然作为这一轮的用户输入，第二轮照常进行
    data_dir = tmp_path / "data"
    # 子进程跑完第一轮、结算、回答「提出修改」，在修改轮事件提交以后停住：新 run 还没有建立
    with killed.interrupted(data_dir, _happy(), task=GOAL, onboard=_source(tmp_path / "source"),
                            settle=True, answer_revise=NOTE,
                            hold_after=ProjectEventType.ONBOARDING_REVISION_STARTED,
                            revision=True, tail=_happy()) as run:
        project_id = str(run.observed["project_id"])
        # 终止前：修改轮事件已经写入，新 run 的流还没有任何事件
        assert run.observed["events"] == [], "终止发生在新 run 建立以前"
        first_round = run.observed["first_round_events"]
        assert [event.type for event in first_round].count(EventType.RUN_DONE) == 1

        # 重启：启动按事件建立缺少的修改轮 run（补建发生在打开数据目录时），然后运行它
        assert run.run_id in run.before.recovered_revision_runs, "启动按修改轮事件补建缺少的 run"
        after = run.after
        second = after.project(run.run_id)
        assert second.round == 2, "补建的是第二轮的 run"
        assert second.kind == "onboarding"
        assert second.phase == "DONE", second.error
        assert second.stop_reason == "baseline_verified"

        # 修改意见仍然是这一轮的用户输入：run_created 同一步写入的第二项输入
        created = killed.events(after, run.run_id, EventType.RUN_CREATED)[0]
        note_ref = created.payload["onboarding_basis"]["note_ref"]
        assert note_ref is not None, "修改意见有工件引用"
        assert after.artifacts.get(ArtifactRef(**note_ref)).decode("utf-8") == NOTE
        received = killed.events(after, run.run_id, EventType.USER_INPUT_RECEIVED)
        assert created.payload["initial_input"]["text"] == GOAL, "第一轮目标仍是最初项输入"
        assert [event.payload["text"] for event in received] == [NOTE], "修改意见作为用户输入写进第二轮"
        # 第二轮照常结算：启动继续已经把它跑完并结算，不再重复写入
        assert after.projects.settle(run.run_id) is None
        assert len(_candidates(after, project_id)) == 2, "两轮各有一个候选"
        assert len(_open_initial_prd(after, project_id)) == 1, "等待确认的是第二轮的请求"
        assert _open_initial_prd(after, project_id)[0].request["round"] == 2
# 薄驱动的内核不变式（可信内核 docs/design/trusted-kernel.md「内核的边界」「内核清单」「路径守卫」；
# 骨架与应用 docs/design/skeleton-and-application.md「薄驱动」；总图第二节「只由你批准」、
# 第四节「写入口」「执行」的缝；工单 #1514）。
#
# 薄驱动直接调用，用真实的 SQLite 事件日志与流处理者，看它写下的结果。五条：
# 1. 每一步先问边界：执行实现拿到的是薄驱动的安全节点，每一步都经它问一次边界，没到上限就继续；
# 2. 到上限会停，停止原因来自封闭清单：运行时间用完时这一步停下，run 以 time_limit 结束；
# 3. 结果只经写入口写回：一轮的收尾由写入口写下（带这一轮的派发编号、用量与身份），最小投影从这条
#    事件折出已结算量；暂停或失败事件的应用字段由应用经钩子给出；
# 4. 旧派发编号交回的结果不生效：重派以后拿旧编号交回的收尾只记录，不并入投影与最小投影；
# 5. 停止判断过期由应用回答：应用说这次判断已经过期时，薄驱动不写暂停或失败事件，运行继续（工单 #1678）。
#
# 一轮工作的准备（选模型与提示词）是应用的事，这里用测试里的最小钩子；读事实、写入与折叠仍走真实的
# 运行视图、写入口与事件库。不跑模型、不起服务、不用网络，属于模块层。
#
# 守 R1（测试分层 docs/design/test-pyramid.md「测试按三环留」）：只由你批准的一环的不变式——
# 每一步先问边界、结果经写入口写回。

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from harness import assembly_contract, execution_contract
from harness.adapters.fake import FakeAdapter
from harness.adjudication import WorkBasis
from harness.definitions import DEFINITIONS
from harness.event_store import run_stream
from harness.kernel_events import SkeletonEventType
from harness.runtime import LoopSystem
from harness.thin_driver import RoundDependencies, RoundPreparation, StopEventFields, ThinDriver

DEPARTMENT = "product"
SESSION = "ses_product_1"


class _Prompt:
    # 一轮工作的提示：薄驱动只取它的版本与内容摘要，类型归应用
    version = 1
    prompt_ref = SimpleNamespace(content_hash="sha256:thin-driver-prompt")


class _Assembly:
    # 装配实现：薄驱动只核对它声明的契约版本，然后原样交给执行实现
    CONTRACT_VERSION = assembly_contract.CURRENT_VERSION


def _execution(*, steps: int, advance=None):
    # 测试用的执行实现：每一步以前问安全节点；到停止时交出这一轮写下的范围与版本。
    # 走到第几步、什么时候把运行时间推过上限由每一步的动作决定
    class _Execution:
        CONTRACT_VERSION = execution_contract.CURRENT_VERSION
        instance = None

        @classmethod
        def start(cls, request, *, nodes, cancelled, **dependencies):
            cls.instance = cls(nodes)
            return cls.instance

        def __init__(self, nodes) -> None:
            self._nodes = nodes
            self.asked: list[bool] = []
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

        async def result(self):
            version = 0
            for index in range(steps):
                judgment = self._nodes.proceed()
                self.asked.append(judgment.proceed)
                version = judgment.version
                if not judgment.proceed:
                    break
                if advance is not None and index == 0:
                    advance()
            await asyncio.sleep(0)
            return execution_contract.RoundResult(version=version)

    return _Execution


class _Hooks:
    # 应用一侧的钩子协议在测试里的最小实现：准备一轮工作、事务与要读的事实仍然走真实的系统，
    # 与这一轮结果相关的收尾记下来供断言
    def __init__(self, system: LoopSystem) -> None:
        self.system = system
        self.driver: ThinDriver | None = None
        self.prepared = 0
        self.finished: list[object] = []
        self.lessons: list[str] = []
        self.dependencies: RoundDependencies | None = None
        # 停止判断过期与暂停、失败事件的应用字段由应用回答（工单 #1678）：这里按运行视图给答案，
        # 与 orchestrator.py 的钩子实现同一读法
        self.superseded = False
        self.superseded_asks = 0

    # 运行视图、定义与判断 ---------------------------------------------------------------
    def project(self, run_id: str):
        return self.system.project(run_id)

    def definitions(self, run_id: str):
        return DEFINITIONS

    def stop_superseded(self, transaction, basis, department: str, version: int) -> bool:
        self.superseded_asks += 1
        return self.superseded

    def stop_event_fields(self, transaction) -> StopEventFields:
        # 暂停与失败事件要写的应用字段：故意给与运行视图不同的值，事件里出现它们才说明值来自钩子（工单 #1678）
        return StopEventFields(
            department=DEPARTMENT, provider="hook-provider", model="hook-model",
            cycle_count=7, max_cycles=99, token_used=42,
        )

    def run_view(self, transaction):
        # 事务里的运行视图：薄驱动不读它，原样交给路由
        return transaction.projection

    def aborted(self, run_id: str) -> bool:
        return False

    def blocks_run(self, decisions) -> bool:
        return False

    def blocked_by_other_session(self, decisions, department: str) -> bool:
        return False

    def assign_new_inputs(self, transaction):
        return transaction.projection

    def transact_run(self, run_id: str, decide, **options):
        return self.system.writes.transact(
            run_stream(run_id), decide, definitions=DEFINITIONS, **options)

    # 一轮工作的准备、开始与收尾 --------------------------------------------------------
    def prepare_round(self, run_id: str, transaction, connections, department: str) -> RoundPreparation:
        self.prepared += 1
        # 应用的准备会恢复这个 run 的段计时（工单 #1520）；这里同样做，运行时间才从这一刻算起
        assert self.driver is not None
        self.driver.resume_run_clock(run_id)
        return RoundPreparation(
            session_id=SESSION, activation_id=f"act_{self.prepared}", prompt=_Prompt(), adapter=object(),
            settings=None, basis=WorkBasis(effective_contract_hash=None, input_version=0, guidance_version=0),
            guidance_ids=(), provider="fake",
        )

    def round_environment(self, round_work):
        return object(), None

    def round_dependencies(self, round_work, environment) -> RoundDependencies:
        assert self.dependencies is not None
        return self.dependencies

    def round_failure(self, exc: Exception):
        return None

    def after_round_finished(self, transaction, round_work, happened) -> None:
        self.finished.append(round_work)

    def apply_round_result(self, round_work, result, current) -> None:
        raise AssertionError("这一组用例的一轮没有交上提案")

    def record_lesson_candidate(self, transaction, reason: str, source_event) -> None:
        self.lessons.append(reason)

    def close_run(self, run_id: str) -> None:
        pass

    def resume_after_pause(self, transaction, reason: str, department: str, message, facts) -> None:
        pass

    def await_model(self, transaction, round_work, reason: str, message: str, *, target=None) -> None:
        pass


class _Rig:
    # 一次真实的 run（真实的事件日志与流处理者）加上直接调用薄驱动；执行实现由每个用例换上
    def __init__(self, tmp_path, *, run_time_limit_sec: int = 1, run_clock=None) -> None:
        self.system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter([]), resume_on_startup=False,
                                             run_clock=run_clock)
        self.run_id = self.system.create_run("build echo", run_time_limit_sec=run_time_limit_sec)
        self.hooks = _Hooks(self.system)
        self.driver = ThinDriver(self.system.writes, self.hooks, run_clock=run_clock)
        self.hooks.driver = self.driver
        self.hooks.dependencies = RoundDependencies(
            execution=_execution(steps=1), assembly=_Assembly, artifacts=None, facade=None, deltas=None,
            tightening=None, definitions=None, environment=None, limits=None, work_ref=None,
            refresh_workspace=None,
        )

    def __enter__(self) -> "_Rig":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.system.close()

    def execution(self, *, steps: int, advance=None) -> object:
        # 换掉这一轮用的执行实现（每一次开始一轮工作都会新建一个实例，实例挂在类上）
        execution = _execution(steps=steps, advance=advance)
        self.hooks.dependencies = RoundDependencies(
            execution=execution, assembly=_Assembly, artifacts=None, facade=None, deltas=None,
            tightening=None, definitions=None, environment=None, limits=None, work_ref=None,
            refresh_workspace=None,
        )
        return execution

    def begin(self):
        # 开始一轮工作：准备、取派发编号、写开始事件，与应用的 activate_department 走同一个入口
        return self.hooks.transact_run(
            self.run_id, lambda transaction: self.driver.begin_round(
                transaction, self.run_id, DEPARTMENT, None))

    def events(self, event_type: str) -> list[object]:
        return [event for event in self.system.store.list_events(self.run_id) if event.type == event_type]


def test_every_step_asks_the_bound_before_it_runs(tmp_path):
    # 验收第 1 条：执行实现拿到的安全节点是薄驱动的，每一步都经它问一次边界；上限没到时每一步都继续
    now = [0.0]
    with _Rig(tmp_path, run_time_limit_sec=10, run_clock=lambda: now[0]) as rig:
        execution = rig.execution(steps=3)
        round_work = rig.begin()
        now[0] = 0.5
        asyncio.run(rig.driver.invoke_round(round_work))
        # 三步各问了一次边界，三次都在上限以内：三次都继续，一轮没有因此停下
        assert execution.instance.asked == [True, True, True]
        assert rig.system.project(rig.run_id).status == "running"
        assert rig.driver.stop_requested(round_work,
                                         rig.system.writes.minimal(run_stream(rig.run_id)), ()) is False


def test_the_bound_stops_the_round_and_the_stop_reason_comes_from_the_closed_list(tmp_path):
    # 验收第 2 条：运行时间用完时这一步停下，run 以封闭清单里的 time_limit 结束；
    # 停止说明与事件里的原因一致
    now = [0.0]
    with _Rig(tmp_path, run_time_limit_sec=1, run_clock=lambda: now[0]) as rig:
        execution = rig.execution(steps=4, advance=lambda: now.__setitem__(0, 2.0))
        round_work = rig.begin()
        asyncio.run(rig.driver.invoke_round(round_work))
        assert execution.instance.asked == [True, False], "运行时间用完以后还继续走了下一步"
        projection = rig.system.project(rig.run_id)
        assert (projection.status, projection.stop_reason) == ("failed", "time_limit")
        # 停止原因来自封闭清单：这份定义里查得到它，事件与载荷里写的都是它
        assert DEFINITIONS.stop_reason("time_limit").outcome == "failed"
        [failed] = rig.events(SkeletonEventType.RUN_FAILED)
        assert failed.stop_reason == failed.payload["stop_reason"] == "time_limit"
        assert "exceeded limit of 1s" in failed.error
        # 暂停或失败事件的应用字段由应用经钩子给出（工单 #1678）：部门与模型引用照旧写进事件；
        # 运行时间用完不核对停止判断是否过期，应用不被问这一项
        assert (failed.department, failed.provider, failed.model) == (
            DEPARTMENT, "hook-provider", "hook-model")
        assert rig.hooks.superseded_asks == 0
        # 这是薄驱动的安全节点给的停止，记下教训候选（应用一侧的钩子）也带着同一个原因
        assert rig.hooks.lessons == ["time_limit"]


def test_a_pause_writes_the_application_fields_from_the_hook(tmp_path):
    # 暂停事件的应用字段由应用经钩子给出（工单 #1678）：部门、模型引用与累计用量原样写进事件；
    # 钩子给的值与运行视图不同，事件里出现这些值才说明薄驱动没有去读运行视图
    with _Rig(tmp_path, run_time_limit_sec=10) as rig:
        round_work = rig.begin()
        rig.driver.end_run(round_work, "no_tool_call", "the model kept answering without a tool call",
                           round_work.version)
        [paused] = rig.events(SkeletonEventType.RUN_PAUSED)
        assert (paused.department, paused.provider, paused.model) == (
            DEPARTMENT, "hook-provider", "hook-model")
        assert paused.stop_reason == paused.payload["stop_reason"] == "no_tool_call"
        assert paused.payload["cycle_count"] == 7
        assert paused.payload["max_cycles"] == 99
        assert paused.payload["token_used"] == 42
        assert rig.system.project(rig.run_id).status == "paused"


def test_the_result_is_written_back_through_the_write_path(tmp_path):
    # 验收第 3 条：一轮工作的收尾只经写入口写进事实：一条带派发编号与这一轮身份的
    # activation_finished，用量由最小投影从这条事件折出，薄驱动不自己存
    now = [0.0]
    with _Rig(tmp_path, run_time_limit_sec=10, run_clock=lambda: now[0]) as rig:
        round_work = rig.begin()
        now[0] = 0.25
        rig.driver.finish_round(round_work, started=time.monotonic())
        [finished] = rig.events(SkeletonEventType.ACTIVATION_FINISHED)
        assert finished.dispatch_number == round_work.scope.dispatch_number == 1
        assert finished.actor == "system"
        assert finished.session_id == SESSION
        assert finished.payload["activation_id"] == round_work.round_id == "act_1"
        assert finished.payload["elapsed_ms"] == 250
        assert finished.payload["stop_reason"] is None
        # 开始事件的轮次读最小投影（工单 #1678）：第一轮是 1
        [activated] = rig.events(SkeletonEventType.DEPARTMENT_ACTIVATED)
        assert activated.payload["cycle"] == 1
        minimal = rig.system.writes.minimal(run_stream(rig.run_id))
        assert minimal.used.settled_ms == 250
        assert minimal.sessions[SESSION].settled_ms == 250
        # 收尾不改变事项的状态：一轮结束不等于事项结束
        assert rig.system.project(rig.run_id).status == "running"


def test_a_result_returned_under_a_superseded_dispatch_number_is_only_recorded(tmp_path):
    # 验收第 4 条：重派以后拿旧编号交回的收尾只记录，不并入投影与最小投影；
    # 新编号的那一次收尾照常生效
    now = [0.0]
    with _Rig(tmp_path, run_time_limit_sec=10, run_clock=lambda: now[0]) as rig:
        first = rig.begin()
        second = rig.begin()
        assert (first.scope.dispatch_number, second.scope.dispatch_number) == (1, 2)
        before = rig.system.project(rig.run_id).to_dict()
        stream = run_stream(rig.run_id)
        assert rig.system.writes.minimal(stream).used.settled_ms == 0
        # 旧编号的一轮收尾：事件写进日志，投影与最小投影都不变
        rig.driver.finish_round(first, started=time.monotonic())
        assert rig.system.project(rig.run_id).to_dict() == before
        assert rig.system.writes.minimal(stream).used.settled_ms == 0
        [late] = [event for event in rig.events(SkeletonEventType.ACTIVATION_FINISHED)
                  if event.dispatch_number == 1]
        assert late.payload["activation_id"] == "act_1"
        # 重放同样不把这条旧编号的收尾并进去
        assert rig.system.writes.rebuild(stream).to_dict() == before
        # 新编号的那一次收尾照常生效：薄驱动下一段的计时从这里重新开始
        rig.driver.resume_run_clock(rig.run_id)
        now[0] = 0.5
        rig.driver.finish_round(second, started=time.monotonic())
        assert rig.system.writes.minimal(stream).used.settled_ms == 500
        numbers = [event.dispatch_number for event in rig.events(SkeletonEventType.ACTIVATION_FINISHED)]
        assert numbers == [1, 2]


def test_a_stop_judgment_the_application_calls_expired_does_not_end_the_run(tmp_path):
    # 停止判断过期与否由应用回答（工单 #1678）：应用说这次判断已经过期时，薄驱动不写暂停或失败事件，
    # 运行继续；输入与指导的版本是应用的数据，判断在应用一侧，薄驱动只把答案写进事实
    with _Rig(tmp_path, run_time_limit_sec=10) as rig:
        round_work = rig.begin()
        rig.hooks.superseded = True
        rig.driver.end_run(round_work, "provider_error", "the model reference is unavailable",
                           round_work.version)
        assert rig.hooks.superseded_asks == 1
        assert rig.events(SkeletonEventType.RUN_FAILED) == []
        assert rig.system.project(rig.run_id).status == "running"

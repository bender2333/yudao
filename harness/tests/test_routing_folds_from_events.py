# 路由这只缝的守卫：路由只从事件折叠要用的状态，新建实例给出同样的回答（工单 #1400；总图第四节「路由」缝的规矩
# 「只读事实与冻结的定义，自己从事件折叠要用的状态，不存别的」；骨架与应用设计说明第 5.1 节「路由契约」；
# 差异报告 docs/evaluation/seam-diff-2026-10-31-5f5ff252.md 的结论第 4 条）。
#
# 做法：一个事项从开始到结束，每写完一条事件就问一次同样三个问题（谁开工、这一轮怎么结束、事项是否结束），
# 问话的两个实例拿到的输入完全相同——到这条事件为止的事件折出来的投影与只读的事件读取器，以及事项创建时
# 冻结的定义：
# - 长期存活的实例：整段事项里只建一个，从第一条事件一直用到最后一条。组装处给一个事项接上的那一个实例就是这样；
# - 新建的实例：每一条事件前缀重建一个，只给它同样的事件与定义。
# 两次的回答必须逐项相同。成果驱动（`harness/watched_outputs.py` 的 `WatchedOutputs`）与只在测试里用的
# 任务池（`harness/tests/second_routing.py` 的 `TaskPool`）各一条：两种路由各跑一个完整的事项，一次一个部门
# 激活、走到事项结束（不跑 `run_until_stop` 的循环）。
#
# 它拦什么：路由在实例里记下事件之外的状态、回答随之不同时这条失败。第一次折叠以后的池子、上一次问出来的
# 谁在等、已经派给谁的任务、第几轮、缓存，只要留在实例上，同一条事件前缀上新旧两个实例的回答就会分叉；
# 分叉一出现，失败信息写明是第几条事件、哪个问题、两边的回答各是什么。
# 限度：两个实例在同一个进程里，模块级的缓存两边都看得见，这条用例分不出；这一类要靠进程重启以后的用例
# （恢复、重放）兜住。回答本身要随事件变，比较才有意义，用例因此再核对两件：整段事项里「谁开工」的回答
# 确实变过；事项结束那一件按各自的场景对（任务池：池子见底时问出来的原因就是这次运行的停止原因；成果驱动：
# 事项由放行结束，路由仍给出它的事项结束判断）。
#
# 层：模块层（SQLite 事件库、工件库与工作区，用假模型跑完一个事项，一次一个部门激活）。缝的合同检查按
# 测试分层设计说明第 12 节登记在单元层或模块层，由 CI 的 module 作业在每次推送时运行。
# 守 R2（路由这只缝的两侧交换什么与它的规矩：同样的事件与冻结的定义，三个问题的回答相同）。

from __future__ import annotations

from typing import Any

from harness import runtime as runtime_module
from harness import watched_outputs
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS
from harness.models import EventType, json_dumps
from harness.projection import replay_events
from harness.proposals import delivery_turn, product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests import second_routing, task_pool_assembly
from harness.tests.helpers import quality_turns

# 三个问题：路由契约回答的就这三件（设计说明第 5.1 节）
QUESTIONS = ("谁开工", "这一轮怎么结束", "事项是否结束")

# 事项从开始到结束要几次部门激活：真跑不完时以一条说清原因的失败结束，不挂在 60 秒的上限上
MAX_ACTIVATIONS = 32


class _Facts:
    """只读的事件读取器：组装处交给路由的那一个只有 list_events(run_id)（路由契约第三版，工单 #1164）。

    长期存活的实例一直拿这一个；每问一条事件前缀，先把它的内容换成那个前缀的事件——与当时的事件库
    给出同样的事件。新建的实例每条前缀拿一个新的，内容就是那一条前缀。
    """

    def __init__(self, events: list[Any] | None = None) -> None:
        self.events = list(events or [])

    def list_events(self, run_id: str) -> list[Any]:
        return list(self.events)


def _turn(calls: list[list[Any]]):
    """一次回答里的一组函数调用：名字与参数由脚本给出，调用身份按激活与步骤编，不同部门的身份不重复。

    任务池的提交方式是它自己那份定义里的工具（`submit_task`、`complete_task`、`judge_task`），
    `harness/proposals.py` 的构造函数只管成果驱动的几种，所以这里直接写函数调用。
    """

    def turn(call: Any) -> ModelResponse:
        output = []
        for index, (name, arguments) in enumerate(calls, start=1):
            identity = f"call-{call.activation_id}-{call.step_id}-{index}"
            output.append({"id": identity, "call_id": identity, "type": "function_call",
                           "name": name, "arguments": json_dumps(arguments)})
        return ModelResponse(output=output)

    return turn


def _run_to_its_end(system: LoopSystem, run_id: str) -> Any:
    """一次一个部门激活，走到事项结束：每次激活与薄驱动自己按路由挑部门时走的是同一个入口。"""
    projection = system.project(run_id)
    for _ in range(MAX_ACTIVATIONS):
        if projection.stop_reason:
            return projection
        projection = system.activate_once(run_id)
    raise AssertionError(
        f"事项在 {MAX_ACTIVATIONS} 次部门激活以后还没有结束：status={projection.status}")


def _waiting(view: Any, departments: tuple[str, ...]) -> set[str]:
    """在等待工作的部门：这个进程里没有正在工作的会话的那些（薄驱动交给路由的那份事实）。

    这里从投影里的会话状态折出来：一轮工作开始时投影记下会话「工作中」，结束时记下它结束了，
    所以在每一条事件之后都与当时进程里的状态一致。
    """
    return {department for department in departments
            if (session := view.sessions.get(department)) is None or session.status != "active"}


def _latest_round(events: list[Any]) -> tuple[str, str | None, str] | None:
    """最近开始的那一轮（部门、会话、这一轮的编号）：一轮怎么结束要按这一轮问。"""
    for event in reversed(events):
        if event.type == EventType.DEPARTMENT_ACTIVATED:
            return (event.department, event.session_id,
                    str((event.payload or {}).get("activation_id") or ""))
    return None


def _answers(routing: Any, view: Any, events: list[Any], departments: tuple[str, ...]) -> dict[str, Any]:
    """路由对三个问题的回答，一项一项摆出来比对。

    「谁开工」不只有开始的部门：薄驱动同时用得到三个入口（同时运行、下一个、这个部门能不能开始），
    开始一轮工作的请求还带路由自己的工作引用，一并问出来。
    """
    waiting = _waiting(view, departments)
    ready = list(routing.ready_departments(view, waiting=waiting))
    started = _latest_round(events)
    return {
        "谁开工": (
            tuple(ready),
            routing.next_department(view, waiting=waiting),
            tuple((department, routing.department_ready(view, department=department, waiting=waiting))
                  for department in departments),
            tuple((department, routing.work_reference(view, department=department)) for department in ready),
        ),
        "这一轮怎么结束": None if started is None else routing.round_end(
            view, list(events), department=started[0], session_id=started[1], activation_id=started[2]),
        "事项是否结束": routing.item_end(view),
    }


def _check_every_event(name: str, events: list[Any], departments: tuple[str, ...], *, long_lived: Any,
                       fresh: Any, advance: Any = None, system_routing: Any) -> list[dict[str, Any]]:
    """一个事项从开始到结束的每一条事件之后：长期存活的实例与新建的实例回答相同。

    fresh 是「按这一条前缀新建一个实例」的函数；advance 把长期存活那个实例读到的事实换到这一条前缀
    （成果驱动不用事件读取器，传 None）。交回逐条事件之后观察到的回答，用例按自己的场景再核对结束的一两件。
    """
    seen: list[dict[str, Any]] = []
    for index, event in enumerate(events, start=1):
        prefix = events[:index]
        if advance is not None:
            advance(prefix)
        # 两个实例各拿一份重新折叠出来的投影：路由改动了传进去的投影时，这一条也失败
        lived = _answers(long_lived, replay_events(prefix), prefix, departments)
        new = _answers(fresh(prefix), replay_events(prefix), prefix, departments)
        for question in QUESTIONS:
            assert new[question] == lived[question], (
                f"{name}：第 {index} 条事件（{event.type}）之后，新建的实例与长期存活的实例在"
                f"「{question}」上的回答不同：\n长期存活：{lived[question]!r}\n新建：{new[question]!r}")
        seen.append(lived)

    # 比较有意义：整段事项里「谁开工」的回答确实变过（从某个部门开始，到没有部门可以开始）
    starts = {repr(answer["谁开工"]) for answer in seen}
    assert len(starts) > 1, f"{name}：整段事项里「谁开工」的回答没有变过，这条用例没有比较到什么"
    assert seen[-1]["事项是否结束"] is not None, f"{name}：事项结束以后路由没有给出结束判断"
    # 真正服务过这个事项的那一个实例（组装处按名称接上的）在事项结束以后也与新建实例回答相同
    final = _answers(system_routing, replay_events(events), events, departments)
    assert final == _answers(fresh(events), replay_events(events), events, departments), (
        f"{name}：组装处接上的那个实例与新建实例在事项结束以后回答不同：\n{final!r}")
    return seen


def test_the_watched_outputs_routing_answers_the_same_way_from_the_same_events(tmp_path):
    # 成果驱动的一个事项，从用户输入到质检放行：产品交 PRD、工程交交付、质检先交独立判断再放行
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current delivery"),
    }))
    run_id = system.create_run("build an echo CLI")
    projection = _run_to_its_end(system, run_id)
    events = system.store.list_events(run_id)

    # 长期存活的实例：整段事项里只建这一个（成果驱动不读事件读取器，只拿投影与定义）
    long_lived = watched_outputs.WatchedOutputs()

    observed = _check_every_event(
        "成果驱动", events, tuple(DEFINITIONS.departments),
        long_lived=long_lived,
        fresh=lambda prefix: watched_outputs.WatchedOutputs(),
        system_routing=system.orchestrator._routing,
    )
    # 这个事项由核验角色的放行结束（结束原因是放行那一件），「没有部门还有新工作」不是这次运行停下来的原因；
    # 这条用例核对的是每一条事件之后路由的回答，结束的一件在这里只核对事项确实走到了结束
    assert projection.status == "done" and projection.last_review is not None
    assert observed[-1]["事项是否结束"].stop_reason == watched_outputs.ITEM_END_REASON
    system.close()


def test_the_task_pool_routing_answers_the_same_way_from_the_same_events(tmp_path, monkeypatch):
    # 任务池的一个事项（只在测试里用的第二种路由，工单 #864）：发任务、完成、打回、重做、接纳，池子见底结束。
    # 事项所用的那份定义只在测试目录里，交给组装处按名称接上路由（与 test_second_routing.py 改模块里的定义
    # 同一个做法；停止原因与部门由薄驱动交给写入口，工单 #1165，所以模块加载的那份定义不动）
    definitions = second_routing.DEFINITIONS
    monkeypatch.setattr(runtime_module, "DEFINITIONS", definitions)
    script = {
        "product": [_turn([("submit_task", {"title": "整理 README 的用法一节"})])],
        "engineering": [_turn([("complete_task", {"summary": "补了用法一节"})]),
                        _turn([("complete_task", {"summary": "补了退出码说明"})])],
        "quality": [_turn([("judge_task", {"verdict": "return", "reason": "用法一节没有写退出码"})]),
                    _turn([("judge_task", {"verdict": "accept", "reason": "与任务要求一致"})])],
    }
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(script),
                                   assembly=task_pool_assembly.TaskPoolAssembly())
    # 收紧检查是这条路由的另一半，事项所用的定义也交给薄驱动
    system.orchestrator._tightening = second_routing.TIGHTENING
    system.orchestrator._definitions = definitions
    run_id = system.create_run("把 README 的用法一节整理清楚")
    projection = _run_to_its_end(system, run_id)
    events = system.store.list_events(run_id)

    # 长期存活的实例与它一直读的那份事实：每问一条前缀，事实换成那个前缀的事件
    facts = _Facts()
    long_lived = second_routing.TaskPool()
    long_lived.use_facts(facts)

    def fresh(prefix: list[Any]) -> Any:
        routing = second_routing.TaskPool()
        routing.use_facts(_Facts(prefix))
        return routing

    observed = _check_every_event(
        "任务池", events, tuple(definitions.departments),
        long_lived=long_lived,
        fresh=fresh,
        advance=lambda prefix: setattr(facts, "events", list(prefix)),
        system_routing=system.orchestrator._routing,
    )
    # 池子见底时薄驱动问的正是路由的「事项是否结束」：路由给出的原因就是这次运行记下的停止原因
    assert observed[-1]["事项是否结束"].stop_reason == second_routing.ITEM_END_REASON
    assert projection.stop_reason == second_routing.ITEM_END_REASON
    system.close()

"""用 fake adapter 跑一个可观察的端到端样例，填满四个视图。"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from .adapters.fake import FakeAdapter, FakeTurn, prompt_part
from .app.application import Application
from .app.contracts import Rejected
from .app.project_and_work_item_commands import WorkItemAppendInput, WorkItemCreate
from .app.project_commands import ProjectCreate
from .definitions import DEFINITIONS
from .environment import QA_TESTS_DIR
from .proposals import (ask_turn, answer_turn, delivery_turn, product_spec,
                        product_spec_turn, review, review_turn)
from .providers.call import ModelResponse, ModelStreamEvent
from .providers.selection import ModelSelection
from .runtime import LoopSystem

def _pause_generator(_call):
    yield ModelStreamEvent(kind="stream_event", id="evt-pause")
    return ModelResponse(output=[])

DEMO_TASK = "Build a local echo CLI that prints its argument and follows product decisions on flags."
DEMO_CHANGE = "\n  Change direction: treat every single argument, including --unknown, as ordinary text and echo it unchanged. Retire unknown-flag rejection. Keep ordinary echo and missing-argument usage with exit 2.\r\n"
V1 = product_spec(
    goal="Build a local echo CLI",
    requirements=["Print the given argument to stdout"],
    acceptance=["echo hello prints hello"],
    non_goals=["network access", "configuration files"],
)

V3 = product_spec_turn(
    goal="Echo any single argument as ordinary text",
    requirements=["Print every given argument unchanged, including text beginning with '-'",
                  "Missing arguments must print usage and exit 2"],
    acceptance=["echo hello prints hello and exits 0", "echo --unknown prints --unknown and exits 0",
                "missing arguments print usage and exit 2"],
    constraints=["single file implementation", "no third-party packages"],
    non_goals=["network access", "configuration files"],
    change_record={
        "changed": ["Arguments beginning with '-' are ordinary text and exit 0"],
        "retained": ["Ordinary input is printed unchanged", "Missing arguments print usage and exit 2",
                     "No network, configuration files, or third-party packages"],
        "retired": ["Unknown flags are rejected with exit 2"],
        "rationale": "The user's additional original input explicitly replaces flag rejection while preserving echo and usage.",
    },
)

V2 = product_spec_turn(
    goal="Build a local echo CLI with strict flags",
    requirements=[
        "Print the given argument to stdout",
        "Unknown flags must be rejected",
        "Missing arguments must print usage and exit 2",
    ],
    acceptance=[
        "echo hello prints hello",
        "unknown flags exit 2",
        "missing arguments print usage and exit 2",
    ],
    constraints=["single file implementation", "no third-party packages"],
    non_goals=["network access", "configuration files"],
    change_record={
        "changed": ["Unknown flags exit 2", "Missing arguments print usage and exit 2"],
        "retained": ["Ordinary input is printed unchanged", "No network or configuration files"],
        "retired": [],
        "rationale": "Resolve the engineering request by explicitly deciding invalid-input behavior.",
    },
)

def demo_script():
    # 检查命令用跑 demo 的这个解释器，不写 PATH 上的 `python`：有的 Windows 机器上 `python` 是
    # Microsoft Store 的占位程序，bash 里跑到它就返回 49，检查一律失败，质检的放行被拒、再被唤醒，
    # 假模型的脚本迟早用尽（工单 #1274）。路径按 bash 认的写法给：正斜杠、加引号
    interpreter = '"' + sys.executable.replace("\\", "/") + '"'
    quality_checks = {
        "echo": {"command": interpreter + " -c \"import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py','hello'],capture_output=True,text=True); assert r.returncode==0 and r.stdout.strip()=='hello'\""},
        "flags": {"command": interpreter + " -c \"import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py','--unknown'],capture_output=True,text=True); assert r.returncode==0 and r.stdout.strip()=='--unknown' and not r.stderr\""},
        "usage": {"command": interpreter + " -c \"import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py'],capture_output=True,text=True); assert r.returncode==2 and 'usage' in r.stderr\""},
    }
    echo_flags = (
        "import sys\n"
        "if len(sys.argv) < 2:\n"
        "    raise SystemExit(2)\n"
        "print(sys.argv[1])\n"
    )
    echo_help = (
        "import sys\n"
        "USAGE = 'usage: echo.py TEXT'\n"
        "if len(sys.argv) < 2:\n"
        "    print(USAGE, file=sys.stderr)\n"
        "    raise SystemExit(2)\n"
        "print(sys.argv[1])\n"
    )
    # 质检的每一轮按当前有没有交付决定做什么（工单 #557：同时运行的会话轮数随交付到达变化，
    # 写死的脚本会在交付到达的时机上耗尽）。没有交付时起草测试用例（预测性探索），
    # 有交付时先记下缺陷记录，返工以后的交付核验通过以后放行。
    quality_state = {"defect_recorded": False}

    def quality_turn(call):
        delivery = prompt_part(call, "current_delivery_spec")
        if not delivery:
            return FakeTurn(
                writes={f"{QA_TESTS_DIR}/test_echo.py":
                        "import subprocess, sys\nr = subprocess.run([sys.executable, 'src/echo.py', 'hello'],"
                        "capture_output=True, text=True)\nassert r.returncode == 0 and r.stdout.strip() == 'hello'\n"},
                proposal=review("release", "按 PRD 起草了测试用例；还没有交付可以核验"))
        if not quality_state["defect_recorded"]:
            quality_state["defect_recorded"] = True
            return review_turn(
                "rework_engineering",
                "Missing usage text when no argument is provided.",
                checks={"usage": quality_checks["usage"]},
                defects=[{"severity": "major", "summary": "no usage text on empty argv"}],
            )(call)
        return review_turn(
            "release",
            "Quality independently verified preserved ordinary echo and usage, plus the newly accepted dash-prefixed argument behavior.",
            checks=quality_checks,
        )(call)

    # 工程的每一轮按它自己的进度决定做什么（工单 #557：同时运行的会话轮数随交付与要求变化，
    # 写死的脚本会在时机变化时耗尽）：先询问产品，暂停一下让界面看到流式输出，
    # 然后交付；质检记下缺陷记录以后补上用法说明。
    engineering_state = {"asked": False, "paused": False}

    def engineering_turn(call):
        if not engineering_state["asked"]:
            engineering_state["asked"] = True
            return ask_turn(
                recipient="product",
                question="How should unknown flags be handled?",
                background="Clarification needed on flags.",
                expected="Publish requirements for invalid flags and missing arguments.",
            )
        if not engineering_state["paused"]:
            engineering_state["paused"] = True
            return _pause_generator(call)
        if prompt_part(call, "qa_defects"):
            # 质检记下了缺陷记录：这一轮补上用法说明
            return delivery_turn(
                "added usage text",
                files={"src/echo.py": echo_help},
                checks={"smoke": {"command": interpreter + " src/echo.py hello"}},
                transcript="added usage",
            )(call)
        return delivery_turn(
            "first delivery treats dash-prefixed input as ordinary text",
            files={"src/echo.py": echo_flags},
            checks={"smoke": {"command": interpreter + " src/echo.py hello"}},
            transcript="implemented the user's revised argument behavior",
        )(call)

    return {
        "product": [
            ask_turn(
                recipient="engineering",
                question="Is a single-file local Python CLI appropriate?",
                background="The initial product requirements are being prepared.",
                expected="Confirm implementation feasibility without changing files.",
            ),
            V1,
            V3,
        ],
        "engineering": [
            engineering_turn,
            engineering_turn,
            engineering_turn,
            engineering_turn,
            engineering_turn,
            engineering_turn,
        ],
        "quality": [
            # 先按 PRD 起草测试用例（预测性探索），再询问工程；交付到达以后核验
            quality_turn,
            ask_turn(
                recipient="engineering",
                question="Where is the CLI entry point?",
                background="Quality is preparing its independent checks.",
                expected="Identify the existing executable path without changing the delivery.",
            ),
            quality_turn,
            quality_turn,
            quality_turn,
            quality_turn,
        ],
        "product:ask": [
            answer_turn(
                answer="The revised product requirements define flags and usage.",
                goal="Build a local echo CLI with strict flags",
                requirements=[
                    "Print the given argument to stdout",
                    "Unknown flags must be rejected",
                    "Missing arguments must print usage and exit 2",
                ],
                acceptance=[
                    "echo hello prints hello",
                    "unknown flags exit 2",
                    "missing arguments print usage and exit 2",
                ],
                constraints=["single file implementation", "no third-party packages"],
                non_goals=["network access", "configuration files"],
                change_record={
                    "changed": ["Unknown flags exit 2", "Missing arguments print usage and exit 2"],
                    "retained": ["Ordinary input is printed unchanged", "No network or configuration files"],
                    "retired": [],
                    "rationale": "Resolve the engineering request by explicitly deciding invalid-input behavior.",
                },
            ),
        ],
        "engineering:ask": [
            answer_turn(answer="Python's standard library supports this CLI without external dependencies."),
            answer_turn(answer="Run python src/echo.py with the intended arguments."),
        ],
    }


def run_demo(data_dir: str | Path) -> tuple[LoopSystem, str]:
    # demo 经应用层的命令新建项目与事项（应用层与接口层设计说明第 7.4 节）：
    # 事项由流程编排在接口进程的事件循环中作为任务运行，run 结束时由流程编排结算
    system = LoopSystem.for_testing(data_dir, FakeAdapter(demo_script(), stream_gap_sec=0.05))
    application = Application(system)
    return asyncio.run(_run_demo(application, system))


async def _run_demo(application: Application, system: LoopSystem) -> tuple[LoopSystem, str]:
    created_project = await _command(application, "project.create",
                                     ProjectCreate(command_id=str(uuid.uuid4()), name="Demo 项目", goal=DEMO_TASK))
    project_id = created_project.refs.project_id
    # work_item.create 的 handle 已经由流程编排在事件循环中把 run 作为任务开始（run 结束时自动结算）
    created = await _command(application, "work_item.create",
                             WorkItemCreate(command_id=str(uuid.uuid4()), project_id=project_id, text=DEMO_TASK))
    work_item_id, run_id = created.refs.work_item_id, created.refs.run_id
    task = system.orchestrator.work_item_execution(run_id)
    assert task is not None, "work_item.create did not start the run task"
    # 等到修订要求的协作请求已关闭（V2 接纳且 engineering 回复 completed），再追加变更：
    # 主分支上这笔输入在首次计划接纳后才追加；删计划后等价点是请求关闭后，V3 消费它。
    # 同时运行的会话里还要等质检对工程的询问回答完（工单 #557）：否则询问的分支会话还在工作，
    # 那笔输入进产品以后变成 V3 时它还在工作。依据变了不再让分支停下来
    # （工单 #558 的 PRD 新版本、工单 #964 的用户输入都作为通知送达），分支接着回答。
    await _wait_for(lambda: len(system.project(run_id).effective_contracts) >= 2
                    and _answers_done(system, run_id))
    await _command(application, "work_item.append_input",
                   WorkItemAppendInput(command_id=str(uuid.uuid4()), work_item_id=work_item_id, text=DEMO_CHANGE))
    system.projects.configure_department_settings(
        project_id, "product",
        ModelSelection(department_prompt=DEFINITIONS.role("product").prompt
                       + "\nExplicitly account for changed, retained, and retired requirements."),
        base_version=system.projects.read_department_setting(project_id, "product")["version"])
    await task
    projection = system.project(run_id)
    if projection.status != "done":
        raise RuntimeError(f"demo did not finish: {projection.status} {projection.stop_reason} {projection.error}")
    return system, run_id


async def _wait_for(predicate, timeout_sec: float = 300.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise RuntimeError("demo did not reach its initial accepted contract")


def _answers_done(system: LoopSystem, run_id: str) -> bool:
    # 质检对工程的询问已经回答完（同时运行的会话里，这笔输入进产品以后，
    # 还在工作着的会话依据就变旧了，询问的分支会话会停下来）
    events = system.store.list_events(run_id)
    asked = [event for event in events
             if event.type == "ask_started" and event.payload.get("requester") == "quality"]
    if not asked:
        return False
    branches = {event.payload.get("branch_session_id") for event in asked}
    answered = {event.session_id for event in events
                if event.type == "ask_answered" and event.payload.get("status") == "answered"}
    return branches <= answered


async def _command(application: Application, name: str, request):
    result = await application.command(name, request, actor="user:local")
    if isinstance(result, Rejected):
        raise RuntimeError(f"{name} rejected: {result.reason} {result.message}")
    return result

"""用 fake adapter 跑一个可观察的端到端样例，填满四个视图。"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from .adapters.fake import FakeAdapter
from .app.application import Application
from .app.contracts import Rejected
from .app.project_and_work_item_commands import WorkItemAppendInput, WorkItemCreate
from .app.project_commands import ProjectCreate
from .definitions import DEFINITIONS
from .proposals import collaboration_request, delivery_turn, product_spec, response_turn, review_turn
from .providers.selection import ModelSelection
from .runtime import LoopSystem

DEMO_TASK = "Build a local echo CLI that prints its argument and follows product decisions on flags."
DEMO_CHANGE = "\n  Change direction: treat every single argument, including --unknown, as ordinary text and echo it unchanged. Retire unknown-flag rejection. Keep ordinary echo and missing-argument usage with exit 2.\r\n"
V1 = product_spec(
    goal="Build a local echo CLI",
    requirements=["Print the given argument to stdout"],
    acceptance=["echo hello prints hello"],
    non_goals=["network access", "configuration files"],
)

V3 = product_spec(
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

V2 = product_spec(
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
    quality_checks = {
        "echo": {"argv": ["python", "-c", "import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py','hello'],capture_output=True,text=True); assert r.returncode==0 and r.stdout.strip()=='hello'"]},
        "flags": {"argv": ["python", "-c", "import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py','--unknown'],capture_output=True,text=True); assert r.returncode==0 and r.stdout.strip()=='--unknown' and not r.stderr"]},
        "usage": {"argv": ["python", "-c", "import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py'],capture_output=True,text=True); assert r.returncode==2 and 'usage' in r.stderr"]},
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
    return [
        collaboration_request("engineering", "Is a single-file local Python CLI appropriate?",
                              background="The initial product requirements are being prepared.",
                              expected_result="Confirm implementation feasibility without changing files."),
        response_turn("answered", "Python's standard library supports this CLI without external dependencies."),
        V1,
        collaboration_request(
            question="How should unknown flags be handled?",
            request_type="action", action="revise_requirements",
            expected_result="Publish requirements for invalid flags and missing arguments.",
        ),
        V2,
        response_turn("completed", "The revised product requirements define flags and usage.",
                      result_types=["spec_accepted"]),
        V3,
        delivery_turn(
            "first delivery treats dash-prefixed input as ordinary text",
            files={"src/echo.py": echo_flags},
            checks={"smoke": {"argv": ["python", "src/echo.py", "hello"]}},
            transcript="implemented the user's revised argument behavior",
        ),
        collaboration_request("engineering", "Where is the CLI entry point?",
                              background="Quality is preparing its independent checks.",
                              expected_result="Identify the existing executable path without changing the delivery."),
        response_turn("answered", "Run python src/echo.py with the intended arguments."),
        review_turn(
            "rework_engineering",
            "Missing usage text when no argument is provided.",
            checks={"usage": quality_checks["usage"]},
            defects=[{"severity": "major", "summary": "no usage text on empty argv"}],
        ),
        delivery_turn(
            "added usage text",
            files={"src/echo.py": echo_help},
            checks={"smoke": {"argv": ["python", "src/echo.py", "hello"]}},
            transcript="added usage",
        ),
        review_turn(
            "release",
            "Quality independently verified preserved ordinary echo and usage, plus the newly accepted dash-prefixed argument behavior.",
            checks=quality_checks,
        ),
    ]


def run_demo(data_dir: str | Path) -> tuple[LoopSystem, str]:
    # demo 经应用层的命令新建项目与事项（应用层与接口层设计说明第 7.4 节）：
    # 事项由流程编排在接口进程的事件循环中作为任务运行，run 结束时由流程编排结算
    system = LoopSystem.for_testing(data_dir, FakeAdapter(demo_script()))
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
    # 主分支上这笔输入在首次计划接纳后才追加；删计划后等价点是请求关闭后，V3 消费它
    await _wait_for(lambda: (len(system.project(run_id).effective_contracts) >= 2
                             and system.project(run_id).pending_request is None))
    await _command(application, "work_item.append_input",
                   WorkItemAppendInput(command_id=str(uuid.uuid4()), work_item_id=work_item_id, text=DEMO_CHANGE))
    system.projects.configure_department_settings(
        project_id, "product",
        ModelSelection(department_prompt=DEFINITIONS.role("product").prompt
                       + "\nExplicitly account for changed, retained, and retired requirements."),
        base_version=system.projects.read_department_setting(project_id, "product")["version"])
    await task
    projection = system.project(run_id)
    if projection.phase != "DONE":
        raise RuntimeError(f"demo did not finish: {projection.phase} {projection.stop_reason} {projection.error}")
    return system, run_id


async def _wait_for(predicate, timeout_sec: float = 300.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise RuntimeError("demo did not reach its initial accepted contract")


async def _command(application: Application, name: str, request):
    result = await application.command(name, request, actor="user:local")
    if isinstance(result, Rejected):
        raise RuntimeError(f"{name} rejected: {result.reason} {result.message}")
    return result

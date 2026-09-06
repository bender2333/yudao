"""用 fake adapter 跑一个可观察的端到端样例，填满四个视图。"""

from __future__ import annotations

from pathlib import Path

from .adapters.fake import FakeAdapter
from .proposals import collaboration_request, delivery_turn, plan_turn, product_spec, response_turn, review_turn
from .runtime import LoopSystem

DEMO_TASK = "Build a local echo CLI that prints its argument and follows product decisions on flags."

V1 = product_spec(
    goal="Build a local echo CLI",
    requirements=["Print the given argument to stdout"],
    acceptance=["echo hello prints hello"],
    non_goals=["network access", "configuration files"],
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
)

def demo_script():
    quality_checks = {
        "echo": {"argv": ["python", "-c", "import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py','hello'],capture_output=True,text=True); assert r.returncode==0 and r.stdout.strip()=='hello'"]},
        "flags": {"argv": ["python", "-c", "import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py','--unknown'],capture_output=True,text=True); assert r.returncode==2 and 'unknown flag' in r.stderr"]},
        "usage": {"argv": ["python", "-c", "import subprocess,sys; r=subprocess.run([sys.executable,'src/echo.py'],capture_output=True,text=True); assert r.returncode==2 and 'usage' in r.stderr"]},
    }
    echo_flags = (
        "import sys\n"
        "if len(sys.argv) < 2:\n"
        "    raise SystemExit(2)\n"
        "if sys.argv[1].startswith('-'):\n"
        "    print('unknown flag', file=sys.stderr)\n"
        "    raise SystemExit(2)\n"
        "print(sys.argv[1])\n"
    )
    echo_help = (
        "import sys\n"
        "USAGE = 'usage: echo.py TEXT'\n"
        "if len(sys.argv) < 2:\n"
        "    print(USAGE, file=sys.stderr)\n"
        "    raise SystemExit(2)\n"
        "if sys.argv[1].startswith('-'):\n"
        "    print('unknown flag', file=sys.stderr)\n"
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
        plan_turn(),
        delivery_turn(
            "first delivery with flag rejection",
            files={"src/echo.py": echo_flags},
            checks={"smoke": {"argv": ["python", "src/echo.py", "hello"]}},
            transcript="implemented flag rejection",
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
        plan_turn(reason="Address the quality review by adding the missing usage behavior"),
        delivery_turn(
            "added usage text",
            files={"src/echo.py": echo_help},
            checks={"smoke": {"argv": ["python", "src/echo.py", "hello"]}},
            transcript="added usage",
        ),
        review_turn(
            "release",
            "Quality independently verified ordinary input, unknown flags, and missing arguments against the current requirements.",
            checks=quality_checks,
        ),
    ]


def run_demo(data_dir: str | Path) -> tuple[LoopSystem, str]:
    system = LoopSystem(data_dir, FakeAdapter(demo_script()))
    run_id = system.create_run(DEMO_TASK, max_cycles=20)
    projection = system.run_until_stop(run_id)
    if projection.phase != "DONE":
        raise RuntimeError(f"demo did not finish: {projection.phase} {projection.stop_reason} {projection.error}")
    return system, run_id

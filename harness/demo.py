"""用 fake adapter 跑一个可观察的端到端样例，填满四个视图。"""

from __future__ import annotations

from pathlib import Path

from .adapters.fake import FakeAdapter
from .proposals import ask_request, delivery_turn, plan_turn, product_spec, reaction, review_turn
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
    ],
    acceptance=[
        "echo hello prints hello",
        "unknown flags exit 2",
    ],
    constraints=["single file implementation", "no third-party packages"],
    non_goals=["network access", "configuration files"],
)

def demo_script():
    echo_flags = (
        "import sys\n"
        "if len(sys.argv) < 2:\n"
        "    raise SystemExit('usage: echo.py TEXT')\n"
        "if sys.argv[1].startswith('-'):\n"
        "    raise SystemExit('unknown flag')\n"
        "print(sys.argv[1])\n"
    )
    echo_help = (
        "import sys\n"
        "USAGE = 'usage: echo.py TEXT'\n"
        "if len(sys.argv) < 2:\n"
        "    raise SystemExit(USAGE)\n"
        "if sys.argv[1].startswith('-'):\n"
        "    raise SystemExit('unknown flag')\n"
        "print(sys.argv[1])\n"
    )
    return [
        V1,
        ask_request(
            question="How should unknown flags be handled?",
            options=["exit 2 with an error", "ignore unknown flags"],
            recommendation="exit 2 with an error",
        ),
        reaction(
            "reply",
            "Unknown flags are part of the public contract and must fail closed.",
            spec_update=V2,
        ),
        plan_turn(),
        delivery_turn(
            "first delivery with flag rejection",
            files={"src/echo.py": echo_flags},
            checks={"smoke": 0},
            transcript="implemented flag rejection",
        ),
        review_turn(
            "rework_engineering",
            "Missing usage text when no argument is provided.",
            checks={"smoke": 0},
            defects=[{"severity": "major", "summary": "no usage text on empty argv"}],
        ),
        plan_turn(reason="Address the quality review by adding the missing usage behavior"),
        delivery_turn(
            "added usage text",
            files={"src/echo.py": echo_help},
            checks={"smoke": 0},
            transcript="added usage",
        ),
        review_turn(
            "release",
            "Quality ran smoke on the current ProductSpec and code snapshot.",
            checks={"smoke": 0},
        ),
    ]


def run_demo(data_dir: str | Path) -> tuple[LoopSystem, str]:
    system = LoopSystem(data_dir, FakeAdapter(demo_script()))
    run_id = system.create_run(DEMO_TASK, max_cycles=12)
    projection = system.run_until_stop(run_id)
    if projection.phase != "DONE":
        raise RuntimeError(f"demo did not finish: {projection.phase} {projection.stop_reason} {projection.error}")
    return system, run_id

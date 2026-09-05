from pathlib import Path

from harness.adapters.fake import FakeAdapter
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.runtime import LoopSystem


def system_with(data_dir: Path, script) -> LoopSystem:
    return LoopSystem(data_dir, FakeAdapter(script))


def run_scripted(data_dir: Path, script, task: str = "build echo", **kwargs):
    system = system_with(data_dir, script)
    run_id = system.create_run(task, **kwargs)
    return system, system.run_until_stop(run_id)


def happy_script():
    return [
        product_spec(),
        delivery_turn(),
        review_turn("release", "checks passed on the current snapshot"),
    ]

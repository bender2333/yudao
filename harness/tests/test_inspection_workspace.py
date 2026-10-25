"""工单 #481：每个会话的检查工作区（工单 #481 与 ADR-0038 第 6 节）。

检查工作区是「查看执行」与「修改执行」的分界：非工程交接的会话在自己的检查工作区里读、写、运行命令，
写入与运行结果不进入运行工作区与交付；会话结束时整个目录删除。
"""

from __future__ import annotations

import asyncio
from pathlib import Path


from harness.collaboration import has_new_work
from harness.actions import Action, ActionReceipt
from harness.adapters.fake import FakeAdapter
from harness.environment import LocalEnvironment, inspection_root
from harness.providers.call import ModelCall, ModelResponse
from harness.runtime import LoopSystem
from harness.tests import event_scenarios
from harness.tools import tool_action
from harness.tree_archive import load_tree

DEPARTMENTS = ("product", "engineering", "quality")


def _session_id(system, run_id: str, department: str) -> str:
    # 部门主线会话的标识：检查工作区按会话一个（工单 #473）
    return system.orchestrator.sessions.get(run_id, department).session_id


def test_the_inspection_workspaces_are_removed_when_the_run_reaches_done(tmp_path: Path) -> None:
    # 运行到 DONE：三个部门的检查工作区都已删除，运行工作区与交付内容仍然保留
    system, _adapter, run_id = event_scenarios._system(tmp_path, {
        "product": [event_scenarios.product_spec()],
        "engineering": [event_scenarios._deliver()],
        "quality": [event_scenarios._explore(), event_scenarios._release()],
    })
    system.run_until_stop(run_id)
    run_root = tmp_path / "workspaces" / run_id

    assert system.project(run_id).status == "done"
    for department in DEPARTMENTS:
        assert not inspection_root(run_root, _session_id(system, run_id, department)).exists()
    assert (run_root / "src" / "echo.py").exists()


def _quality_bash_turn(call: ModelCall) -> ModelResponse:
    # 质检一轮里先用 bash 读交付、写下自己看到的版本并写入自己的文件，跑主机检查，最后退回返工；
    # 返工让 run 继续，检查工作区保留，可以就这一轮 bash 写下的内容断言
    turn = event_scenarios.review_turn(
        "rework_engineering", "the sealed output needs a newline check",
        checks=event_scenarios.CHECKS,
        defects=[{"severity": "major", "summary": "no check covers the sealed output"}])
    return ModelResponse(output=[
        event_scenarios._call("q-read-1", "bash", {"command": "cat src/echo.py > seen.txt"}),
        event_scenarios._call("q-write-2", "bash", {"command": "mkdir -p qa && printf x > qa/new.txt"}),
        event_scenarios._call("q-check-3", "run_check", {"name": "smoke"}),
        event_scenarios._call("q-submit-4", "submit_review",
                              {key: value for key, value in turn(call).proposal.items() if key != "kind"}),
    ])


def _quality_bash_script() -> dict[str, list]:
    return {
        "product": [event_scenarios.product_spec()],
        "engineering": [event_scenarios.delivery_turn(
            files={"src/echo.py": "SEALED_VERSION\n"}, checks=event_scenarios.CHECKS)],
        "quality": [_quality_bash_turn],
    }


def _inspection_bash_reads_the_sealed_delivery(tmp_path: Path) -> tuple:
    # 交付封存以后改动运行工作区，再激活质检：bash 在检查工作区里读到的是封存版本，
    # 它的写入留在检查工作区，运行工作区与封存树都不变
    system, _adapter, run_id = event_scenarios._system(tmp_path, _quality_bash_script())
    run_root = tmp_path / "workspaces" / run_id
    system.activate_once(run_id)   # 产品：产品要求
    system.activate_once(run_id)   # 工程：交付并封存 src/echo.py
    assert has_new_work(system.project(run_id), "quality")
    delivery = system.project(run_id).delivery_spec
    sealed = load_tree(system.artifacts, run_id, delivery.tree_ref)

    # 交付之后再改运行工作区：这一步以前，若检查工作区从运行工作区取源，质检就会看到改后的内容
    system.workspace(run_id).write_file("src/echo.py", "CHANGED_AFTER_DELIVERY\n")
    system.activate_once(run_id)   # 质检一轮：bash 读交付、写自己的文件、跑检查并退回返工

    quality_root = inspection_root(run_root, _session_id(system, run_id, "quality"))
    assert has_new_work(system.project(run_id), "quality")
    assert (quality_root / "seen.txt").read_text(encoding="utf-8") == "SEALED_VERSION\n"
    assert (run_root / "src" / "echo.py").read_text(encoding="utf-8") == "CHANGED_AFTER_DELIVERY\n"
    assert not (run_root / "qa").exists()
    assert not (run_root / "seen.txt").exists()
    assert sealed.digest == delivery.code_tree_digest
    return system, run_id, run_root


def test_quality_bash_reads_the_sealed_delivery(tmp_path: Path) -> None:
    # 验收 (a)(b)：质检在会话里用 bash 读到的是封存交付，写下的文件不泄漏到运行工作区，
    # 也不进入封存交付树
    _inspection_bash_reads_the_sealed_delivery(tmp_path)


def test_product_bash_views_and_runs_the_snapshot(tmp_path: Path) -> None:
    # 验收 (c)：产品会话 bash 查看快照里的现有代码并运行它：清单、运行结果、
    # 自己写下的文件都在检查工作区，运行工作区不变
    spec = event_scenarios.product_spec()
    system, _adapter, run_id = event_scenarios._system(tmp_path, {"product": [ModelResponse(output=[
        event_scenarios._call("p-list-1", "bash", {"command": "ls src > listing.txt"}),
        event_scenarios._call("p-run-2", "bash", {"command": "python src/echo.py hello > result.txt"}),
        event_scenarios._call("p-write-3", "bash", {"command": "printf p > notes.txt"}),
        event_scenarios._call("p-submit-4", "submit_product_spec",
                              {key: value for key, value in spec.items() if key != "kind"}),
    ])]})
    run_root = tmp_path / "workspaces" / run_id
    system.workspace(run_id).write_file("src/echo.py", "import sys\nprint(sys.argv[1])\n")
    system.activate_once(run_id)   # 产品一轮：bash 查看与运行现有代码，写下自己的文件并提交产品要求

    product_root = inspection_root(run_root, _session_id(system, run_id, "product"))
    assert has_new_work(system.project(run_id), "engineering")
    assert (product_root / "src" / "echo.py").read_text(encoding="utf-8") == "import sys\nprint(sys.argv[1])\n"
    assert "echo.py" in (product_root / "listing.txt").read_text(encoding="utf-8")
    assert (product_root / "result.txt").read_text(encoding="utf-8") == "hello\n"
    assert (product_root / "notes.txt").read_text(encoding="utf-8") == "p"
    assert (run_root / "src" / "echo.py").read_text(encoding="utf-8") == "import sys\nprint(sys.argv[1])\n"
    assert not (run_root / "listing.txt").exists()
    assert not (run_root / "result.txt").exists()
    assert not (run_root / "notes.txt").exists()


async def _run_bash(environment: LocalEnvironment, department: str, command: str) -> ActionReceipt:
    # 真实的动作调用链：环境执行一次 bash 命令，交回回执（不使用任何替身）
    return await environment.perform(Action(
        action_id=f"test-{department}-{command}", kind=tool_action("bash"), tool="bash",
        department=department, input={"command": command}))


def test_two_sessions_do_not_share_their_inspection_workspace(tmp_path: Path) -> None:
    # 验收 (d)：产品要求接纳以后，产品与质检两个会话的交错动作互不影响：
    # 一个会话写下的文件另一个会话读不到，也不进入运行工作区
    system, _adapter, run_id = event_scenarios._system(
        tmp_path, {"product": [event_scenarios.product_spec()]})
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")
    orchestrator = system.orchestrator
    quality = orchestrator._environment_for(run_id, "quality", refresh=True)
    product = orchestrator._environment_for(run_id, "product", refresh=True)

    assert asyncio.run(_run_bash(quality, "quality", "printf quality-only > only_quality.txt")).ok
    cross = asyncio.run(_run_bash(product, "product", "cat only_quality.txt"))
    assert cross.ok
    assert cross.output["exit_code"] != 0
    assert asyncio.run(_run_bash(product, "product", "printf product-only > only_product.txt")).ok
    reverse = asyncio.run(_run_bash(quality, "quality", "cat only_product.txt"))
    assert reverse.ok
    assert reverse.output["exit_code"] != 0

    run_root = tmp_path / "workspaces" / run_id
    inspections = run_root.parent / "inspections" / run_id
    quality_root = inspections / _session_id(system, run_id, "quality")
    product_root = inspections / _session_id(system, run_id, "product")
    assert (quality_root / "only_quality.txt").exists()
    assert not (quality_root / "only_product.txt").exists()
    assert (product_root / "only_product.txt").exists()
    assert not (product_root / "only_quality.txt").exists()
    assert not (run_root / "only_quality.txt").exists()
    assert not (run_root / "only_product.txt").exists()


def _leave_inspection_dirs(data_dir: Path, run_id: str) -> None:
    # 手工留下检查工作区：上一次异常退出（on_commit 没有跑过）的现场。
    # 目录名是会话标识（工单 #473），启动扫描按 run 整体删除
    run_root = data_dir / "workspaces" / run_id
    for session_id in ("ses_pro_1", "ses_eng_1", "ses_qua_1"):
        root = inspection_root(run_root, session_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / "wip.txt").write_text("left behind\n", encoding="utf-8")


def test_startup_keeps_inspections_of_a_run_that_is_still_open(tmp_path: Path) -> None:
    # 验收 (e)：run 还没有结束：启动核对不动它的检查工作区，会话恢复以后仍要继续使用
    data_dir = tmp_path / "data"
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    run_id = system.create_run("build an echo CLI")
    system.close()
    _leave_inspection_dirs(data_dir, run_id)

    reopened = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    try:
        for session_id in ("ses_pro_1", "ses_eng_1", "ses_qua_1"):
            root = inspection_root(data_dir / "workspaces" / run_id, session_id)
            assert (root / "wip.txt").read_text(encoding="utf-8") == "left behind\n"
    finally:
        reopened.close()


def test_quality_before_any_delivery_starts_from_the_work_item(tmp_path: Path) -> None:
    # 验收（还没有封存的交付）：产品要求已提交、工程还没有交付，质检的检查工作区从事项开始时的
    # 项目起点（本例为空树）建立，运行工作区里尚未交付的修改不在其中；产品会话仍看当前快照
    system, _adapter, run_id = event_scenarios._system(
        tmp_path, {"product": [event_scenarios.product_spec()]})
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")
    assert system.project(run_id).delivery_spec is None
    run_root = tmp_path / "workspaces" / run_id
    system.workspace(run_id).write_file("src/echo.py", "NOT_DELIVERED\n")
    orchestrator = system.orchestrator

    quality = orchestrator._environment_for(run_id, "quality", refresh=True)
    assert quality.workspace.root == inspection_root(
        run_root, _session_id(system, run_id, "quality"))
    assert [item.path for item in quality.snapshot().tree.files] == []

    product = orchestrator._environment_for(run_id, "product", refresh=True)
    assert [item.path for item in product.snapshot().tree.files] == ["src/echo.py"]
    assert (run_root / "src" / "echo.py").read_text(encoding="utf-8") == "NOT_DELIVERED\n"

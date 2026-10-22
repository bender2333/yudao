"""工单 #481：每个会话的检查工作区（工单 #481 与 ADR-0038 第 6 节）。

检查工作区是「查看执行」与「修改执行」的分界：非工程交接的会话在自己的检查工作区里读、写、运行命令，
写入与运行结果不进入运行工作区与交付；会话结束时整个目录删除。
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from harness.actions import Action, ActionReceipt
from harness.adapters.fake import FakeAdapter
from harness.environment import (
    LocalEnvironment,
    cleanup_inspection_workspace,
    inspection_root,
)
from harness.public_tree import capture_public_tree
from harness.providers.call import ModelCall, ModelResponse
from harness.runtime import LoopSystem
from harness.sessions import SessionFactory
from harness.tests import event_scenarios
from harness.tools import tool_action
from harness.tree_archive import load_tree

DEPARTMENTS = ("product", "engineering", "quality")


def _establish_run(root: Path, files: dict[str, str]) -> LocalEnvironment:
    """建立运行工作区：先按空树建根，再写入文件，得到有内容的工作区。"""
    environment = LocalEnvironment.establish(root, None)
    for relative, content in files.items():
        environment.workspace.write_file(relative, content)
    assert environment.snapshot().digest == capture_public_tree(root, True).digest
    return environment


def _session_id(system, run_id: str, department: str) -> str:
    # 部门主线会话的标识：检查工作区按会话一个（工单 #473）
    return system.orchestrator.sessions.get(run_id, department).session_id


def test_inspection_root_is_outside_the_run_workspace(tmp_path: Path) -> None:
    # 检查工作区与运行工作区同级，不在运行工作区内部：否则 capture_public_tree
    # 会把它当作运行内容，交付封存与快照摘要都会漂移。
    # 每个会话一个（工单 #473）：路径的最后一段是会话标识
    run_root = tmp_path / "run_1"
    root = inspection_root(run_root, "ses_qua_1")
    assert root == tmp_path / "inspections" / "run_1" / "ses_qua_1"
    assert run_root not in root.parents


def test_establish_materializes_the_delivery_tree(tmp_path: Path) -> None:
    # 质检的检查工作区来自封存交付：交付里的文件在场，运行工作区里后来才有的文件不在场
    run_root = tmp_path / "run_1"
    run_root.mkdir()
    _establish_run(run_root, {"src/delivered.py": "sealed = 1\n"})
    delivered = capture_public_tree(run_root, True)
    environment = _establish_run(run_root, {"src/delivered.py": "sealed = 1\n"})
    environment.workspace.write_file("src/after_seal.py", "later = 2\n")

    inspection = LocalEnvironment.establish(inspection_root(run_root, "ses_qua_1"), delivered)
    files = [item.path for item in inspection.snapshot().tree.files]
    assert files == ["src/delivered.py"]
    assert inspection.snapshot().digest == delivered.digest


def test_establish_is_idempotent_for_an_existing_root(tmp_path: Path) -> None:
    # 已存在的根原样打开：会话内写入的内容在提交判断时必须仍然可见（工单 #481 的回归点）
    run_root = tmp_path / "run_1"
    _establish_run(run_root, {"src/echo.py": "print('echo')\n"})
    root = inspection_root(run_root, "ses_pro_1")
    first = LocalEnvironment.establish(root, capture_public_tree(run_root, True))
    first.workspace.write_file("notes/analysis.md", "draft\n")
    digest_with_notes = first.snapshot().digest

    second = LocalEnvironment.establish(root, None)
    assert second.snapshot().digest == digest_with_notes
    assert (root / "notes" / "analysis.md").read_text(encoding="utf-8") == "draft\n"


def test_inspection_writes_do_not_reach_the_run_workspace(tmp_path: Path) -> None:
    # 检查工作区里的写入与删除只改自己：运行工作区与它的快照保持原样
    run_root = tmp_path / "run_1"
    _establish_run(run_root, {"src/echo.py": "print('echo')\n"})
    before = capture_public_tree(run_root, True).digest

    inspection = LocalEnvironment.establish(inspection_root(run_root, "ses_pro_1"), None)
    inspection.workspace.write_file("src/echo.py", "tampered\n")
    inspection.workspace.write_file("scratch/scratch.txt", "scratch\n")

    assert capture_public_tree(run_root, True).digest == before
    assert (run_root / "src" / "echo.py").read_text(encoding="utf-8") == "print('echo')\n"
    assert not (run_root / "scratch").exists()


def test_sessions_have_independent_inspection_roots(tmp_path: Path) -> None:
    # 三个会话的检查工作区互不影响：各自写入的同名文件只出现在自己的根里
    run_root = tmp_path / "run_1"
    _establish_run(run_root, {"src/echo.py": "print('echo')\n"})
    contents = {"ses_pro_1": "p\n", "ses_eng_1": "e\n", "ses_qua_1": "q\n"}
    for session_id, content in contents.items():
        environment = LocalEnvironment.establish(
            inspection_root(run_root, session_id), capture_public_tree(run_root, True))
        environment.workspace.write_file("department.txt", content)

    for session_id, content in contents.items():
        assert (inspection_root(run_root, session_id) / "department.txt").read_text(
            encoding="utf-8") == content


def test_cleanup_is_idempotent_for_a_missing_root(tmp_path: Path) -> None:
    # 删除一个从来不存在的检查工作区是幂等的：会话结束的每条路径都调用它
    run_root = tmp_path / "run_1"
    run_root.mkdir()
    cleanup_inspection_workspace(run_root, "ses_qua_1")
    cleanup_inspection_workspace(run_root, "ses_qua_1")


def test_cleanup_retries_while_a_handle_is_still_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows 上仍有进程持有目录句柄时 rmtree 会抛 PermissionError（工单 #479）：
    # 按固定次数重试成功，调用方不收到错误
    run_root = tmp_path / "run_1"
    root = inspection_root(run_root, "ses_qua_1")
    root.mkdir(parents=True)
    (root / "held.txt").write_text("held\n", encoding="utf-8")
    real_rmtree = shutil.rmtree
    attempts = {"count": 0}

    def flaky_rmtree(path: Path) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("file is in use by another process")
        real_rmtree(path)

    monkeypatch.setattr("harness.environment.shutil.rmtree", flaky_rmtree)
    monkeypatch.setattr("harness.environment.time.sleep", lambda _seconds: None)
    cleanup_inspection_workspace(run_root, "ses_qua_1")

    assert attempts["count"] == 3
    assert not root.exists()


def test_cleanup_reports_a_handle_that_never_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 尝试用尽仍然失败：把最后一次异常透传给调用方，由编排器记进关闭错误而不是静默留下目录
    run_root = tmp_path / "run_1"
    root = inspection_root(run_root, "ses_qua_1")
    root.mkdir(parents=True)
    monkeypatch.setattr("harness.environment.shutil.rmtree",
                        lambda _path: (_ for _ in ()).throw(PermissionError("still held")))
    monkeypatch.setattr("harness.environment.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError) as raised:
        cleanup_inspection_workspace(run_root, "ses_qua_1")

    assert isinstance(raised.value.__cause__, PermissionError)
    assert "ses_qua_1" in str(raised.value)
    assert root.exists()


def test_close_run_removes_every_session_inspection(tmp_path: Path) -> None:
    # 会话结束（DONE / PAUSED / FAILED / 取消 / 异常）：三个部门的检查工作区都删除，
    # 运行工作区仍然保留
    run_root = tmp_path / "run_1"
    _establish_run(run_root, {"src/echo.py": "print('echo')\n"})
    tree = capture_public_tree(run_root, True)
    factory = SessionFactory(tmp_path)
    factory.create_run_sessions("run_1")
    for department in DEPARTMENTS:
        LocalEnvironment.establish(inspection_root(run_root, factory.get("run_1", department).session_id), tree)

    assert factory.close_run("run_1") == []
    assert not (tmp_path / "inspections" / "run_1").exists()
    assert (run_root / "src" / "echo.py").exists()


def test_close_run_reports_a_session_that_could_not_be_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 清理失败不吞掉：会话已关闭，错误作为清单交给编排器
    run_root = tmp_path / "run_1"
    factory = SessionFactory(tmp_path)
    factory.create_run_sessions("run_1")
    root = inspection_root(run_root, factory.get("run_1", "quality").session_id)
    root.mkdir(parents=True)
    monkeypatch.setattr("harness.environment.shutil.rmtree",
                        lambda _path: (_ for _ in ()).throw(PermissionError("still held")))
    monkeypatch.setattr("harness.environment.time.sleep", lambda _seconds: None)

    errors = factory.close_run("run_1")

    assert len(errors) == 1
    assert factory.get("run_1", "quality").status == "closed"


def _system_with_handoff(data_dir: Path):
    # 产品一份、工程一份、质检一份的脚本：逐步激活到工程交付完成、阶段转到质检
    system, adapter, run_id = event_scenarios._system(data_dir, {
        "product": [event_scenarios.product_spec()],
        "engineering": [event_scenarios._deliver()],
        "quality": [event_scenarios._release()],
    })
    return system, adapter, run_id


def test_engineering_delivers_from_the_run_workspace_and_quality_from_its_own(tmp_path: Path) -> None:
    # 持有交接的工程写入运行工作区并交付；质检在自己的检查工作区里看到同一份交付内容，
    # 它的写入与命令不进入运行工作区，也不进入封存的交付树
    system, _adapter, run_id = _system_with_handoff(tmp_path)
    run_root = tmp_path / "workspaces" / run_id
    orchestrator = system.orchestrator
    system.activate_once(run_id)   # 产品：产品要求
    system.activate_once(run_id)   # 工程：交付，运行工作区里的 src/echo.py 被封存
    assert system.project(run_id).phase == "QUALITY"

    # 交付之后阶段已转到质检，工程不再是交接持有者：它此时回答协作请求，
    # 用的是自己的检查工作区，运行工作区交给质检之后的部门不动
    engineering = orchestrator._environment_for(run_id, "engineering", refresh=True)
    assert engineering.workspace.root == inspection_root(
        run_root, _session_id(system, run_id, "engineering"))

    quality = orchestrator._environment_for(run_id, "quality", refresh=True)
    assert quality.workspace.root == inspection_root(
        run_root, _session_id(system, run_id, "quality"))
    delivered = [item.path for item in quality.snapshot().tree.files]
    quality.workspace.write_file("qa/notes.md", "reviewed\n")

    assert delivered == ["src/echo.py"]
    assert capture_public_tree(run_root, True).digest == system.project(run_id).delivery_spec.code_tree_digest
    assert not (run_root / "qa").exists()


def test_the_inspection_workspaces_are_removed_when_the_run_reaches_done(tmp_path: Path) -> None:
    # 运行到 DONE：三个部门的检查工作区都已删除，运行工作区与交付内容仍然保留
    system, _adapter, run_id = event_scenarios._system(tmp_path, {
        "product": [event_scenarios.product_spec()],
        "engineering": [event_scenarios._deliver()],
        "quality": [event_scenarios._release()],
    })
    system.run_until_stop(run_id)
    run_root = tmp_path / "workspaces" / run_id

    assert system.project(run_id).phase == "DONE"
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
    assert system.project(run_id).phase == "QUALITY"
    delivery = system.project(run_id).delivery_spec
    sealed = load_tree(system.artifacts, run_id, delivery.tree_ref)

    # 交付之后再改运行工作区：这一步以前，若检查工作区从运行工作区取源，质检就会看到改后的内容
    system.workspace(run_id).write_file("src/echo.py", "CHANGED_AFTER_DELIVERY\n")
    system.activate_once(run_id)   # 质检一轮：bash 读交付、写自己的文件、跑检查并退回返工

    quality_root = inspection_root(run_root, _session_id(system, run_id, "quality"))
    assert system.project(run_id).phase == "QUALITY"
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
    assert system.project(run_id).phase == "ENGINEERING"
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
    assert system.project(run_id).phase == "ENGINEERING"
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


def test_startup_removes_inspections_of_a_run_that_already_finished(tmp_path: Path) -> None:
    # 验收 (e)：run 已经结束（终态）但 on_commit 没有跑过：重新打开系统时遗留的检查工作区删除
    data_dir = tmp_path / "data"
    system, _adapter, run_id = event_scenarios._system(data_dir, {
        "product": [event_scenarios.product_spec()],
        "engineering": [event_scenarios._deliver()],
        "quality": [event_scenarios._release()],
    })
    assert system.run_until_stop(run_id).phase == "DONE"
    system.close()
    _leave_inspection_dirs(data_dir, run_id)

    reopened = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    try:
        assert not (data_dir / "workspaces" / "inspections").exists()
    finally:
        reopened.close()


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


def test_a_cancelled_run_removes_its_inspection_workspaces(tmp_path: Path) -> None:
    # 验收 (e) 的取消路径：质检会话的检查工作区在场时取消运行，检查工作区随即删除，
    # 不留运行工作区以外的目录（_fail 的 on_commit 走会话结束同一条清理）
    system, _adapter, run_id = event_scenarios._system(tmp_path, {
        "product": [event_scenarios.product_spec()],
        "engineering": [event_scenarios.delivery_turn(
            files={"src/echo.py": "SEALED_VERSION\n"}, checks=event_scenarios.CHECKS)],
        "quality": [event_scenarios._release()],
    })
    system.activate_once(run_id)   # 产品：产品要求
    system.activate_once(run_id)   # 工程：交付，阶段转到质检
    assert system.project(run_id).phase == "QUALITY"
    orchestrator = system.orchestrator
    orchestrator._environment_for(run_id, "quality", refresh=True)
    run_root = tmp_path / "workspaces" / run_id
    assert inspection_root(run_root, _session_id(system, run_id, "quality")).exists()

    system.cancel(run_id)

    assert system.project(run_id).phase == "FAILED"
    assert system.project(run_id).stop_reason == "cancelled"
    assert not (run_root.parent / "inspections" / run_id).exists()
    assert not (run_root.parent / "inspections").exists()
    assert (run_root / "src" / "echo.py").exists()


def test_quality_before_any_delivery_starts_from_the_work_item(tmp_path: Path) -> None:
    # 验收（还没有封存的交付）：产品要求已提交、工程还没有交付，质检的检查工作区从事项开始时的
    # 项目起点（本例为空树）建立，运行工作区里尚未交付的修改不在其中；产品会话仍看当前快照
    system, _adapter, run_id = event_scenarios._system(
        tmp_path, {"product": [event_scenarios.product_spec()]})
    system.activate_once(run_id)
    assert system.project(run_id).phase == "ENGINEERING"
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

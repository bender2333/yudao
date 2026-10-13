"""工单 #481：每个会话的检查工作区（工单 #481 与 ADR-0038 第 6 节）。

检查工作区是「查看执行」与「修改执行」的分界：非工程交接的会话在自己的检查工作区里读、写、运行命令，
写入与运行结果不进入运行工作区与交付；会话结束时整个目录删除。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from harness.environment import (
    LocalEnvironment,
    cleanup_inspection_workspace,
    inspection_root,
)
from harness.public_tree import capture_public_tree
from harness.sessions import SessionFactory
from harness.tests import event_scenarios


DEPARTMENTS = ("product", "engineering", "quality")


def _establish_run(root: Path, files: dict[str, str]) -> LocalEnvironment:
    """建立运行工作区：先按空树建根，再写入文件，得到有内容的工作区。"""
    environment = LocalEnvironment.establish(root, None)
    for relative, content in files.items():
        environment.workspace.write_file(relative, content)
    assert environment.snapshot().digest == capture_public_tree(root, True).digest
    return environment


def test_inspection_root_is_outside_the_run_workspace(tmp_path: Path) -> None:
    # 检查工作区与运行工作区同级，不在运行工作区内部：否则 capture_public_tree
    # 会把它当作运行内容，交付封存与快照摘要都会漂移
    run_root = tmp_path / "run_1"
    root = inspection_root(run_root, "quality")
    assert root == tmp_path / "inspections" / "run_1" / "quality"
    assert run_root not in root.parents


def test_establish_materializes_the_delivery_tree(tmp_path: Path) -> None:
    # 质检的检查工作区来自封存交付：交付里的文件在场，运行工作区里后来才有的文件不在场
    run_root = tmp_path / "run_1"
    run_root.mkdir()
    _establish_run(run_root, {"src/delivered.py": "sealed = 1\n"})
    delivered = capture_public_tree(run_root, True)
    environment = _establish_run(run_root, {"src/delivered.py": "sealed = 1\n"})
    environment.workspace.write_file("src/after_seal.py", "later = 2\n")

    inspection = LocalEnvironment.establish(inspection_root(run_root, "quality"), delivered)
    files = [item.path for item in inspection.snapshot().tree.files]
    assert files == ["src/delivered.py"]
    assert inspection.snapshot().digest == delivered.digest


def test_establish_is_idempotent_for_an_existing_root(tmp_path: Path) -> None:
    # 已存在的根原样打开：会话内写入的内容在提交判断时必须仍然可见（工单 #481 的回归点）
    run_root = tmp_path / "run_1"
    _establish_run(run_root, {"src/echo.py": "print('echo')\n"})
    root = inspection_root(run_root, "product")
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

    inspection = LocalEnvironment.establish(inspection_root(run_root, "product"), None)
    inspection.workspace.write_file("src/echo.py", "tampered\n")
    inspection.workspace.write_file("scratch/scratch.txt", "scratch\n")

    assert capture_public_tree(run_root, True).digest == before
    assert (run_root / "src" / "echo.py").read_text(encoding="utf-8") == "print('echo')\n"
    assert not (run_root / "scratch").exists()


def test_departments_have_independent_inspection_roots(tmp_path: Path) -> None:
    # 三个部门的检查工作区互不影响：各自写入的同名文件只出现在自己的根里
    run_root = tmp_path / "run_1"
    _establish_run(run_root, {"src/echo.py": "print('echo')\n"})
    contents = {"product": "p\n", "engineering": "e\n", "quality": "q\n"}
    for department, content in contents.items():
        environment = LocalEnvironment.establish(
            inspection_root(run_root, department), capture_public_tree(run_root, True))
        environment.workspace.write_file("department.txt", content)

    for department, content in contents.items():
        assert (inspection_root(run_root, department) / "department.txt").read_text(
            encoding="utf-8") == content


def test_cleanup_is_idempotent_for_a_missing_root(tmp_path: Path) -> None:
    # 删除一个从来不存在的检查工作区是幂等的：会话结束的每条路径都调用它
    run_root = tmp_path / "run_1"
    run_root.mkdir()
    cleanup_inspection_workspace(run_root, "quality")
    cleanup_inspection_workspace(run_root, "quality")


def test_cleanup_retries_while_a_handle_is_still_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows 上仍有进程持有目录句柄时 rmtree 会抛 PermissionError（工单 #479）：
    # 按固定次数重试成功，调用方不收到错误
    run_root = tmp_path / "run_1"
    root = inspection_root(run_root, "quality")
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
    cleanup_inspection_workspace(run_root, "quality")

    assert attempts["count"] == 3
    assert not root.exists()


def test_cleanup_reports_a_handle_that_never_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 尝试用尽仍然失败：把最后一次异常透传给调用方，由编排器记进关闭错误而不是静默留下目录
    run_root = tmp_path / "run_1"
    root = inspection_root(run_root, "quality")
    root.mkdir(parents=True)
    monkeypatch.setattr("harness.environment.shutil.rmtree",
                        lambda _path: (_ for _ in ()).throw(PermissionError("still held")))
    monkeypatch.setattr("harness.environment.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError) as raised:
        cleanup_inspection_workspace(run_root, "quality")

    assert isinstance(raised.value.__cause__, PermissionError)
    assert "quality" in str(raised.value)
    assert root.exists()


def test_close_run_removes_every_department_inspection(tmp_path: Path) -> None:
    # 会话结束（DONE / PAUSED / FAILED / 取消 / 异常）：三个部门的检查工作区都删除，
    # 运行工作区仍然保留
    run_root = tmp_path / "run_1"
    _establish_run(run_root, {"src/echo.py": "print('echo')\n"})
    tree = capture_public_tree(run_root, True)
    factory = SessionFactory(tmp_path)
    factory.create_run_sessions("run_1")
    for department in DEPARTMENTS:
        LocalEnvironment.establish(inspection_root(run_root, department), tree)

    assert factory.close_run("run_1") == []
    assert not (tmp_path / "inspections" / "run_1").exists()
    assert (run_root / "src" / "echo.py").exists()


def test_close_run_reports_a_department_that_could_not_be_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 清理失败不吞掉：会话已关闭，错误作为清单交给编排器
    run_root = tmp_path / "run_1"
    root = inspection_root(run_root, "quality")
    root.mkdir(parents=True)
    factory = SessionFactory(tmp_path)
    factory.create_run_sessions("run_1")
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
    assert engineering.workspace.root == inspection_root(run_root, "engineering")

    quality = orchestrator._environment_for(run_id, "quality", refresh=True)
    assert quality.workspace.root == inspection_root(run_root, "quality")
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
        assert not inspection_root(run_root, department).exists()
    assert (run_root / "src" / "echo.py").exists()

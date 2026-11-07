# 故障矩阵第 8 行：数据库/工件/封存/Git 写入失败（恢复契约与故障矩阵 docs/design/recovery-contract-and-fault-matrix.md「故障矩阵」）。
# 工程部门的交付提案提交时，这个 run 的工件目录在真实的文件系统上不可写（写成一个普通文件）：接纳所需的
# 工件写不进去。没有持久接纳就没有成功确认：运行以 host_commit_error 停止，交付没有被接纳。
# 模型已经写进工作区的文件留在磁盘上，但它不是正式成果：事件日志里没有交付接纳，重启以后也不被当作成果。
#
# 层：集成层（完整的三部门循环、真实事件库与工件库、真实文件系统上的写入失败）。
# 守 R1（写入口的接纳不变式：没有持久接纳就没有成功确认；接纳事实只经写入口写入）
# 与 R3（交付封存失败的处理：残留文件不算正式成果）。

import shutil

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import WorkItemMaterials
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import after_event, quality_turns


def test_a_delivery_whose_artifacts_cannot_be_written_is_not_accepted(tmp_path):
    # 工程把交付写进工作区并提交提案；提交时要写的工件在真实的文件系统上失败。
    # 没有持久接纳（交付接纳事件与封存工件都不在），运行以 host_commit_error 停止，
    # 工作区里留下的 src/echo.py 只是残留文件，重启以后仍然不是正式成果
    data_dir = tmp_path / "data"
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }))
    try:
        project_id = system.projects.register("写入失败", "核对没有持久接纳就没有成功确认")
        work_item_id, run_id = system.projects.start_work_item(project_id, "交付写不进去")

        def break_the_artifact_store(event):
            # 提交工具回执写入以后，把这个 run 的工件目录换成一个普通文件：之后这个 run 的工件写入
            # 在真实的文件系统上失败（mkdir 的父路径不是目录），不是替身注入
            if (event.payload or {}).get("name") != "submit_delivery":
                return
            run_dir = system.artifacts.root / run_id
            shutil.rmtree(run_dir)
            run_dir.write_bytes(b"not a directory")

        after_event(system, EventType.TOOL_CALLED, break_the_artifact_store)

        result = system.run_until_stop(run_id)
        assert result.status == "failed"
        assert result.stop_reason == "host_commit_error"
        assert any(name in result.error for name in (
            "NotADirectoryError", "FileExistsError", "PermissionError", "OSError")), result.error
        assert result.delivery_spec is None

        events = system.store.list_events(run_id)
        # 没有成功确认：交付接纳与运行完成都没有写入事件
        assert not any(event.type in {EventType.DELIVERY_ACCEPTED, EventType.RUN_DONE} for event in events)
        # 残留文件：模型写进工作区的交付文件还在磁盘上，但它不是正式成果
        assert "src/echo.py" in system.workspace(run_id).list_files()
        materials = Application(system).query("work_item.materials", WorkItemMaterials(
            project_id=project_id, work_item=work_item_id)).data
        assert materials.deliveries == []
    finally:
        system.close()

    # 工件存储修好（这个 run 的目录重新可写）以后重新启动：已停止的 run 不继续，
    # 工作区里的残留文件仍然不是正式成果
    run_dir = data_dir / "artifacts" / run_id
    if run_dir.is_file():
        run_dir.unlink()
    run_dir.mkdir(parents=True, exist_ok=True)
    restarted = LoopSystem.for_testing(data_dir, FakeAdapter({"product": [], "engineering": [], "quality": []}))
    try:
        projection = restarted.project(run_id)
        assert projection.status == "failed"
        assert projection.stop_reason == "host_commit_error"
        assert projection.delivery_spec is None
        assert "src/echo.py" in restarted.workspace(run_id).list_files()
        assert not any(event.type == EventType.DELIVERY_ACCEPTED
                       for event in restarted.store.list_events(run_id))
    finally:
        restarted.close()

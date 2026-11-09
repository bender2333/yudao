# 路径守卫（可信内核 docs/design/trusted-kernel.md「路径守卫」）：采纳之前把交付相对基线的改动路径与
# 运行实例的内核清单比较，有交集时不自动采纳，发出决定请求「内核修改」并附差异。工单 #1514 加一条：
# 改到薄驱动 `harness/thin_driver.py` 时同样不自动采纳——薄驱动列入内核清单以后，它就在路径守卫
# 比较的那张表里。
#
# 这条用例走路径守卫自己那一段：从清单取路径、按交付相对基线的改动路径求交集、给出差异；另一条走
# 项目流发出决定请求的那一段（`harness/projects.py` 的 `_guard_kernel_paths`，通用行为另由
# `test_projects.py::test_release_touching_kernel_paths_is_not_adopted_without_approval` 用
# `bounds.py` 覆盖）。清单与静态路径读仓库里的文件，后一条用真实的事件库、工件库与树归档（临时目录），
# 不用网络与子进程，属于模块层。
#
# 守 R1（测试分层 docs/design/test-pyramid.md「测试按三环留」）：只由你批准的一环的不变式——
# 改到薄驱动要经用户批准，不能自动采纳。

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from harness.artifacts import ArtifactStore
from harness.event_store import EventStore
from harness.path_guard import changed_paths, kernel_diff, kernel_hits, kernel_manifest_paths
from harness.projects import ProjectService
from harness.projection import run_handler
from harness.public_tree import CapturedFile, CapturedTree
from harness.tree_archive import store_tree
from harness.write_path import WritePath

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "harness" / "definitions" / "kernel-manifest.json"
THIN_DRIVER = "harness/thin_driver.py"


def _tree(text: str) -> CapturedTree:
    return CapturedTree(directories=("harness",),
                        files=(CapturedFile(THIN_DRIVER, text.encode("utf-8")),))


def test_a_delivery_that_changes_the_thin_driver_is_not_adopted_automatically():
    # 清单里的薄驱动是内核模块：路径守卫必须把它识别为内核路径，交付改了它就不自动采纳
    modules = {entry["path"] for entry in json.loads(MANIFEST.read_text(encoding="utf-8"))["paths"]
               if entry["kind"] == "module"}
    assert THIN_DRIVER in modules, "薄驱动没有列入内核清单的 kind=module"

    baseline = _tree("# 旧的薄驱动\n")
    delivery = _tree("# 交付改动的薄驱动\n")
    hits = kernel_hits(changed_paths(baseline, delivery), kernel_manifest_paths())
    assert hits == [THIN_DRIVER], f"改到薄驱动没有命中内核清单：{hits}"
    diff = kernel_diff(baseline, delivery, hits)
    assert "+# 交付改动的薄驱动" in diff and "-# 旧的薄驱动" in diff


def test_a_thin_driver_change_is_a_kernel_modification_request(tmp_path):
    # 项目流按路径守卫的交集决定采纳（`harness/projects.py` 的 `_guard_kernel_paths`）：改到薄驱动时
    # 不自动采纳，交出一个「内核修改」的决定请求，材料带路径与差异。事件库、工件库与树归档都是真的；
    # 事务、事项与交付只是这一条判断的输入数据
    store = EventStore(tmp_path / "events.sqlite")
    try:
        artifacts = ArtifactStore(tmp_path / "artifacts")
        service = ProjectService(store, WritePath(store, lambda _stream: run_handler()), artifacts, None)
        delivery_tree = _tree("# 交付改动的薄驱动\n")
        tree_ref = store_tree(artifacts, "run_1514", delivery_tree)
        transaction = SimpleNamespace(decisions={}, projection=SimpleNamespace(initial_snapshot=None))
        request = service._guard_kernel_paths(
            transaction,
            SimpleNamespace(run_id="run_1514"),
            SimpleNamespace(work_item_id="wi_1514", baseline=None),
            SimpleNamespace(tree_ref=tree_ref, issuer="engineering"),
            {"adoption_id": "a1"},
        )
        assert request["kind"] == "kernel_modification" and request["blocks"] == "run"
        assert request["kernel_paths"] == [THIN_DRIVER]
        assert "+# 交付改动的薄驱动" in request["diff"]
        assert request["department"] == "engineering"
        assert request["work_item_id"] == "wi_1514" and request["delivery_run_id"] == "run_1514"
        assert request["held_adoption"] == {"adoption_id": "a1"}
    finally:
        store.close()

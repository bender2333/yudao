from dataclasses import replace
import json

import pytest

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.public_tree import CapturedFile, CapturedTree
from harness.tests.helpers import system_on_copy
from harness.tests.saved_rewrite import rewrite_saved_projection

# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次停在等质检让步的运行并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上放行交付与检查。数据来自真实运行，登记为集成层。

REVIEW_TURN = review_turn("release", "Checks passed")

def _saved_quality_ready(tmp_path, *, runs=1):
    # runs 个事项各激活两次，停在等待质检让步：放行发生在每项测试自己的副本上
    script = []
    for _ in range(runs):
        script.extend([product_spec(),delivery_turn()])
    script.extend(review_turn("release", "Checks passed") for _ in range(runs))
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_ids = [system.create_run(f"Build echo {index}") for index in range(runs)]
    for run_id in run_ids:
        for _ in range(2):
            result = system.activate_once(run_id)
        # 交付到达以后质检开始一轮工作（工单 #556：质检关注新的交付）
        assert has_new_work(result, "quality"), result.error
    saved = system.data_dir
    system.close()
    return saved, run_ids

@pytest.fixture(scope="module")
def quality_ready(tmp_path_factory):
    return _saved_quality_ready(tmp_path_factory.mktemp("ready"))

@pytest.fixture
def ready_run(quality_ready, tmp_path):
    saved, run_ids = quality_ready
    # 保存的运行停在等待质检放行：重新打开的系统要能回答这一步，脚本里补上这次放行
    return system_on_copy(saved, tmp_path / "ready", [REVIEW_TURN]), run_ids

@pytest.fixture(scope="module")
def quality_ready_two_runs(tmp_path_factory):
    return _saved_quality_ready(tmp_path_factory.mktemp("ready-two"), runs=2)

@pytest.fixture
def two_ready_runs(quality_ready_two_runs, tmp_path):
    saved, run_ids = quality_ready_two_runs
    return system_on_copy(saved, tmp_path / "ready-two", [REVIEW_TURN] * len(run_ids)), run_ids

def _events(system, run_id):
    return system.store.list_events(run_id)


@pytest.mark.parametrize("damage", ["manifest_missing", "manifest_corrupt", "blob_missing", "blob_corrupt"])
def test_release_rejects_missing_or_corrupt_persisted_delivery_tree(ready_run, damage):
    system, run_ids = ready_run
    run_id = run_ids[0]
    delivery = system.project(run_id).delivery_spec
    manifest_path = system.artifacts.root / delivery.tree_ref.path
    archive = json.loads(system.artifacts.get_for_run(run_id, delivery.tree_ref))
    blob_path = system.artifacts.root / archive["blobs"][0]["artifact"]["path"]

    if damage == "manifest_missing":
        manifest_path.unlink()
    elif damage == "manifest_corrupt":
        manifest_path.write_bytes(b"{}")
    elif damage == "blob_missing":
        blob_path.unlink()
    else:
        blob_path.write_bytes(blob_path.read_bytes() + b"\x00")

    result = system.activate_once(run_id)

    assert result.status == "failed"
    assert result.stop_reason == "host_commit_error"
    assert "persisted delivery tree" in result.error
    assert result.last_review is None
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, run_id))


def test_release_rejects_delivery_digest_that_does_not_match_current_snapshot(ready_run):
    system, run_ids = ready_run
    run_id = run_ids[0]
    projection = system.project(run_id)
    delivery = replace(projection.delivery_spec, code_tree_digest="sha256:" + "0" * 64)
    # 保存的运行状态中，当前交付的摘要与工作区不同：写回这个流保存的投影
    rewrite_saved_projection(system.store, run_id, replace(projection, delivery_spec=delivery))
    result = system.activate_once(run_id)
    recorded = system.project(run_id)

    assert has_new_work(result, "quality")
    assert recorded.rejections[-1]["errors"] == [
        {"field": "code_snapshot_hash", "message": "workspace snapshot no longer matches the current delivery"}
    ]
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, run_id))

def test_release_rejects_a_snapshot_that_differs_before_submission_commit(ready_run, monkeypatch):
    system, run_ids = ready_run
    run_id = run_ids[0]
    original_prepare = system.orchestrator.submissions.prepare

    def prepare(transaction, **kwargs):
        snapshot = kwargs["snapshot"]
        if kwargs["artifact"]["kind"] == "qa_review" and kwargs["artifact"]["verdict"] == "release":
            changed_tree = CapturedTree(
                snapshot.tree.directories,
                snapshot.tree.files + (CapturedFile("unreviewed.txt", b"changed"),),
            )
            kwargs = {**kwargs, "snapshot": replace(snapshot, tree=changed_tree)}
        return original_prepare(transaction, **kwargs)

    monkeypatch.setattr(system.orchestrator.submissions, "prepare", prepare)
    result = system.activate_once(run_id)

    assert result.status == "failed"
    assert result.stop_reason == "host_commit_error"
    assert "does not match the validated workspace snapshot" in result.error
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, run_id))


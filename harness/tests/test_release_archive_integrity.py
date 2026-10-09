from dataclasses import replace
import json
import shutil

import pytest

from harness.adapters.fake import FakeAdapter
from harness.models import ArtifactRef, EventType
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.public_tree import CapturedFile, CapturedTree, capture_public_tree, materialize_tree
from harness.tests.helpers import system_on_copy
from harness.tests.saved_rewrite import rewrite_saved_projection
from harness.tree_archive import load_tree

# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次停在等质检让步的运行并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上放行交付与检查。数据来自真实运行，登记为集成层。

REVIEW_TURN = review_turn("release", "Checks passed")


def _saved_quality_ready(tmp_path, *, runs=1):
    # runs 个事项各激活三次，停在等待质检让步：放行发生在每项测试自己的副本上
    script = []
    for _ in range(runs):
        script.extend([product_spec(), plan_turn(), delivery_turn()])
    script.extend(review_turn("release", "Checks passed") for _ in range(runs))
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_ids = [system.create_run(f"Build echo {index}") for index in range(runs)]
    for run_id in run_ids:
        for _ in range(3):
            result = system.activate_once(run_id)
        assert result.phase == "QUALITY", result.error
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


def _accept_with(monkeypatch, system, run_id, change_delivery):
    # 放行的接纳所依据的运行状态中，当前交付被 change_delivery 改动
    original_prepare = system.orchestrator.submissions.prepare

    def prepare(transaction, **kwargs):
        projection = kwargs["projection"]
        if projection.run_id == run_id and projection.phase == "QUALITY":
            kwargs = {**kwargs, "projection": replace(projection,
                                                      delivery_spec=change_delivery(projection.delivery_spec))}
        return original_prepare(transaction, **kwargs)

    monkeypatch.setattr(system.orchestrator.submissions, "prepare", prepare)


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

    assert result.phase == "FAILED"
    assert result.stop_reason == "host_commit_error"
    assert "persisted delivery tree" in result.error
    assert result.last_review is None
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, run_id))


def test_release_verifies_the_persisted_tree_before_marking_done(ready_run):
    system, run_ids = ready_run
    run_id = run_ids[0]

    result = system.activate_once(run_id)

    assert result.phase == "DONE", result.error
    assert result.last_review.verdict == "release"
    archive = load_tree(system.artifacts, run_id, result.delivery_spec.tree_ref)
    assert archive.digest == result.delivery_spec.code_tree_digest
    assert any(event.type == EventType.QA_SUBMITTED for event in _events(system, run_id))
    assert any(event.type == EventType.RUN_DONE for event in _events(system, run_id))


def test_release_rejects_a_delivery_archive_bound_to_another_run(two_ready_runs, monkeypatch):
    system, run_ids = two_ready_runs
    first_run, second_run = run_ids
    other_tree_ref = system.project(second_run).delivery_spec.tree_ref
    _accept_with(monkeypatch, system, first_run, lambda delivery: replace(delivery, tree_ref=other_tree_ref))
    result = system.activate_once(first_run)

    assert result.phase == "FAILED"
    assert result.stop_reason == "host_commit_error"
    assert "persisted delivery tree" in result.error
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, first_run))
    assert system.project(second_run).phase == "QUALITY"


def test_release_rejects_a_same_run_reference_that_is_not_a_tree_manifest(ready_run, monkeypatch):
    system, run_ids = ready_run
    run_id = run_ids[0]
    delivery = system.project(run_id).delivery_spec
    archive = json.loads(system.artifacts.get_for_run(run_id, delivery.tree_ref))
    wrong_ref = ArtifactRef(**archive["blobs"][0]["artifact"])
    _accept_with(monkeypatch, system, run_id, lambda delivery: replace(delivery, tree_ref=wrong_ref))
    result = system.activate_once(run_id)

    assert result.phase == "FAILED"
    assert result.stop_reason == "host_commit_error"
    assert "persisted delivery tree" in result.error
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

    assert result.phase == "QUALITY"
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

    assert result.phase == "FAILED"
    assert result.stop_reason == "host_commit_error"
    assert "does not match the validated workspace snapshot" in result.error
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, run_id))


def test_persisted_delivery_tree_restores_independently_of_workspace(ready_run, tmp_path):
    system, run_ids = ready_run
    run_id = run_ids[0]
    result = system.activate_once(run_id)
    assert result.phase == "DONE", result.error
    delivery = result.delivery_spec

    shutil.rmtree(system.workspace(run_id).root)
    restored = materialize_tree(load_tree(system.artifacts, run_id, delivery.tree_ref), tmp_path / "restored")

    assert capture_public_tree(restored).digest == delivery.code_tree_digest

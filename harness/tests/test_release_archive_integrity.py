from dataclasses import replace
import json
import shutil

import pytest

from harness.adapters.fake import FakeAdapter
from harness.event_store import run_stream
from harness.models import ArtifactRef, EventType
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.public_tree import CapturedFile, CapturedTree, capture_public_tree, materialize_tree
from harness.tree_archive import load_tree


def _quality_ready(tmp_path, *, runs=1):
    script = []
    for _ in range(runs):
        script.extend([product_spec(), plan_turn(), delivery_turn()])
    script.extend(review_turn("release", "Checks passed") for _ in range(runs))
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_ids = [system.create_run(f"Build echo {index}") for index in range(runs)]
    ready = []
    for run_id in run_ids:
        for _ in range(3):
            result = system.activate_once(run_id)
        assert result.phase == "QUALITY", result.error
        ready.append(result)
    return system, run_ids, ready


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
def test_release_rejects_missing_or_corrupt_persisted_delivery_tree(tmp_path, damage):
    system, run_ids, ready = _quality_ready(tmp_path)
    run_id = run_ids[0]
    delivery = ready[0].delivery_spec
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


def test_release_verifies_the_persisted_tree_before_marking_done(tmp_path):
    system, run_ids, ready = _quality_ready(tmp_path)
    run_id = run_ids[0]

    result = system.activate_once(run_id)

    assert result.phase == "DONE", result.error
    assert result.last_review.verdict == "release"
    archive = load_tree(system.artifacts, run_id, result.delivery_spec.tree_ref)
    assert archive.digest == result.delivery_spec.code_tree_digest
    assert any(event.type == EventType.QA_SUBMITTED for event in _events(system, run_id))
    assert any(event.type == EventType.RUN_DONE for event in _events(system, run_id))


def test_release_rejects_a_delivery_archive_bound_to_another_run(tmp_path, monkeypatch):
    system, run_ids, ready = _quality_ready(tmp_path, runs=2)
    first_run, second_run = run_ids
    other_tree_ref = ready[1].delivery_spec.tree_ref
    _accept_with(monkeypatch, system, first_run, lambda delivery: replace(delivery, tree_ref=other_tree_ref))
    result = system.activate_once(first_run)

    assert result.phase == "FAILED"
    assert result.stop_reason == "host_commit_error"
    assert "persisted delivery tree" in result.error
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, first_run))
    assert system.project(second_run).phase == "QUALITY"


def test_release_rejects_a_same_run_reference_that_is_not_a_tree_manifest(tmp_path, monkeypatch):
    system, run_ids, ready = _quality_ready(tmp_path)
    run_id = run_ids[0]
    delivery = ready[0].delivery_spec
    archive = json.loads(system.artifacts.get_for_run(run_id, delivery.tree_ref))
    wrong_ref = ArtifactRef(**archive["blobs"][0]["artifact"])
    _accept_with(monkeypatch, system, run_id, lambda delivery: replace(delivery, tree_ref=wrong_ref))
    result = system.activate_once(run_id)

    assert result.phase == "FAILED"
    assert result.stop_reason == "host_commit_error"
    assert "persisted delivery tree" in result.error
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, run_id))


def test_release_rejects_delivery_digest_that_does_not_match_current_snapshot(tmp_path, monkeypatch):
    system, run_ids, ready = _quality_ready(tmp_path)
    run_id = run_ids[0]
    original_read = system.writes.read

    def read(stream):
        # 提案校验读取的运行状态中，当前交付的摘要与工作区不同
        snapshot = original_read(stream)
        if stream == run_stream(run_id) and snapshot.projection.phase == "QUALITY":
            delivery = replace(snapshot.projection.delivery_spec, code_tree_digest="sha256:" + "0" * 64)
            snapshot.projection = replace(snapshot.projection, delivery_spec=delivery)
        return snapshot

    monkeypatch.setattr(system.writes, "read", read)
    result = system.activate_once(run_id)
    recorded = system.project(run_id)

    assert result.phase == "QUALITY"
    assert recorded.rejections[-1]["errors"] == [
        {"field": "code_snapshot_hash", "message": "workspace snapshot no longer matches the current delivery"}
    ]
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, run_id))


def test_release_rejects_a_snapshot_that_differs_before_submission_commit(tmp_path, monkeypatch):
    system, run_ids, ready = _quality_ready(tmp_path)
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


def test_persisted_delivery_tree_restores_independently_of_workspace(tmp_path):
    system, run_ids, ready = _quality_ready(tmp_path)
    run_id = run_ids[0]
    result = system.activate_once(run_id)
    assert result.phase == "DONE", result.error
    delivery = result.delivery_spec

    shutil.rmtree(system.workspace(run_id).root)
    restored = materialize_tree(load_tree(system.artifacts, run_id, delivery.tree_ref), tmp_path / "restored")

    assert capture_public_tree(restored).digest == delivery.code_tree_digest

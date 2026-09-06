from dataclasses import replace
import json
import shutil

import pytest

from harness.adapters.fake import FakeAdapter
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
    system = LoopSystem(tmp_path / "data", FakeAdapter(script))
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
    original_project = system.orchestrator.project

    def project(run_id):
        projection = original_project(run_id)
        if run_id == first_run and projection.phase == "QUALITY":
            delivery = replace(projection.delivery_spec, tree_ref=other_tree_ref)
            return replace(projection, delivery_spec=delivery)
        return projection

    monkeypatch.setattr(system.orchestrator, "project", project)
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
    original_project = system.orchestrator.project

    def project(identity):
        projection = original_project(identity)
        if identity == run_id and projection.phase == "QUALITY":
            return replace(projection, delivery_spec=replace(projection.delivery_spec, tree_ref=wrong_ref))
        return projection

    monkeypatch.setattr(system.orchestrator, "project", project)
    result = system.activate_once(run_id)

    assert result.phase == "FAILED"
    assert result.stop_reason == "host_commit_error"
    assert "persisted delivery tree" in result.error
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in _events(system, run_id))


def test_release_rejects_delivery_digest_that_does_not_match_current_snapshot(tmp_path, monkeypatch):
    system, run_ids, ready = _quality_ready(tmp_path)
    run_id = run_ids[0]
    original_project = system.orchestrator.project

    def project(identity):
        projection = original_project(identity)
        if identity == run_id and projection.phase == "QUALITY":
            delivery = replace(projection.delivery_spec, code_tree_digest="sha256:" + "0" * 64)
            return replace(projection, delivery_spec=delivery)
        return projection

    monkeypatch.setattr(system.orchestrator, "project", project)
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
    original_commit = system.orchestrator.submissions.commit

    def commit(**kwargs):
        snapshot = kwargs["snapshot"]
        if kwargs["artifact"]["kind"] == "qa_review" and kwargs["artifact"]["verdict"] == "release":
            changed_tree = CapturedTree(
                snapshot.tree.directories,
                snapshot.tree.files + (CapturedFile("unreviewed.txt", b"changed"),),
            )
            kwargs = {**kwargs, "snapshot": replace(snapshot, tree=changed_tree)}
        return original_commit(**kwargs)

    monkeypatch.setattr(system.orchestrator.submissions, "commit", commit)
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

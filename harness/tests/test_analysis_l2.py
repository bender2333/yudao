import json
import subprocess
from pathlib import Path

import pytest

from harness.analysis import load_evidence_pack
from harness.analysis.records import EvidenceError
from harness.analysis.review import MATERIAL_PROTOCOL, review_from_manifest
from harness.models import json_dumps
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

REQ_EMPTY = {"id": "empty-input", "version": "v1", "text": "空输入不会崩溃"}
REQ_ECHO = {"id": "echo", "version": "v1", "text": "正常输入结果保持正确"}
CHECK_EMPTY = {
    "id": "empty-input",
    "requirement_id": "empty-input",
    "stdin_utf8": "",
    "expected_stdout_utf8": "",
    "expected_exit_code": 0,
    "repeats": 1,
    "timeout_sec": WAIT_FOR_HOST_WORK_SEC,
}
CHECK_ECHO = {
    "id": "echo",
    "requirement_id": "echo",
    "stdin_utf8": "hello\n",
    "expected_stdout_utf8": "hello\n",
    "expected_exit_code": 0,
    "repeats": 1,
    "timeout_sec": WAIT_FOR_HOST_WORK_SEC,
}
CRASH_EMPTY = "import sys\ndata = sys.stdin.read()\nif not data:\n    raise SystemExit(1)\nsys.stdout.write(data)\n"
BREAK_ECHO = "import sys\ndata = sys.stdin.read()\nsys.stdout.write(data[::-1] if data else '')\n"
ECHO = "import sys\nsys.stdout.write(sys.stdin.read())\n"
HANG = "import sys, time\ntime.sleep(8)\nsys.stdout.write(sys.stdin.read())\n"
MARKER = "from pathlib import Path\nPath('executed').write_text('ran', encoding='utf-8')\n"


def _write_delivery(root: Path, code: str) -> None:
    src = root / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text(MARKER + code, encoding="utf-8")


def _qa(decision: str, digest=None) -> dict:
    return {
        "decision": decision,
        "source": "calibration",
        "reviewed_requirement_ids": ["empty-input", "echo"],
        "delivery_digest": digest,
        "summary": f"{decision} QA",
    }


def _round(round_id: str, delivery, decision="rework_engineering", digest=None, checks=None, extra_req=None):
    requirements = [REQ_EMPTY, REQ_ECHO]
    if extra_req:
        requirements.append(extra_req)
    return {
        "id": round_id,
        "delivery": delivery,
        "requirements": requirements,
        "checks": list(checks or [CHECK_EMPTY, CHECK_ECHO]),
        "qa": _qa(decision, digest),
    }


def _material():
    return {
        "id": "calib-fail-pass-fail",
        "source": "calibration",
        "calibration": True,
        "family": "text-lines",
        "project_id": "eval",
        "work_item_id": "item-1",
        "run_id": "run-1",
    }


def _write_manifest(directory: Path, rounds) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    path.write_text(
        json_dumps({
            "protocol": MATERIAL_PROTOCOL,
            "review_id": "review-1",
            "material": _material(),
            "rounds": rounds,
        }),
        encoding="utf-8",
    )
    return path


def test_manifest_fail_pass_fail_runs_isolated_copies(tmp_path):
    materials = tmp_path / "materials"
    _write_delivery(materials / "round-1", CRASH_EMPTY)
    _write_delivery(materials / "round-2", BREAK_ECHO)
    _write_delivery(materials / "round-3", CRASH_EMPTY)
    manifest = _write_manifest(materials, [
        _round("round-1", "round-1"),
        _round("round-2", "round-2"),
        _round("round-3", "round-3", decision="release"),
    ])
    pack = review_from_manifest(manifest, tmp_path / "pack")
    loaded = load_evidence_pack(pack)
    issues = {issue.requirement_id: issue for issue in loaded.trajectory.issues}
    assert [point.verdict for point in issues["empty-input"].points] == ["fail", "pass", "fail"]
    assert issues["empty-input"].status == "regressed"
    assert [point.verdict for point in issues["echo"].points] == ["pass", "fail", "pass"]
    assert issues["echo"].status == "new_failure"
    assert loaded.review.model_requests is None
    assert loaded.review.check_seconds is not None and loaded.review.check_seconds > 0
    assert not (materials / "round-1" / "executed").exists()
    assert not (materials / "round-2" / "executed").exists()
    assert (pack / "rounds" / "round-1" / "delivery" / "src" / "main.py").is_file()


def test_static_error_in_later_round_starts_no_program(tmp_path, monkeypatch):
    materials = tmp_path / "materials"
    _write_delivery(materials / "round-1", ECHO)
    _write_delivery(materials / "round-2", ECHO)
    manifest = _write_manifest(materials, [
        _round("round-1", "round-1"),
        _round("round-2", "round-2", extra_req=None),
    ])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["rounds"][1]["checks"][0]["requirement_id"] = "missing-req"
    manifest.write_text(json_dumps(payload), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("static manifest errors must not start a program")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(EvidenceError, match="does not refer to a round requirement"):
        review_from_manifest(manifest, tmp_path / "pack")
    assert not (tmp_path / "pack").exists()
    assert not (materials / "round-1" / "executed").exists()


def test_timeout_and_missing_rounds_are_kept(tmp_path):
    materials = tmp_path / "materials"
    _write_delivery(materials / "round-1", ECHO)
    _write_delivery(materials / "round-3", ECHO)
    hang_check = dict(CHECK_ECHO, timeout_sec=0.3)
    manifest = _write_manifest(materials, [
        _round("round-1", "round-1"),
        _round("round-2", None),
        _round("round-3", "round-3", checks=[CHECK_EMPTY, hang_check]),
    ])
    (materials / "round-3" / "src" / "main.py").write_text(MARKER + HANG, encoding="utf-8")
    pack = review_from_manifest(manifest, tmp_path / "pack")
    loaded = load_evidence_pack(pack)
    assert [item.id for item in loaded.rounds] == ["round-1", "round-2", "round-3"]
    missing = {obs.check_id: obs for obs in loaded.rounds[1].observations}
    assert missing["empty-input"].termination == "launch_failure"
    assert missing["echo"].termination == "launch_failure"
    assert missing["empty-input"].verdict == "unknown"
    timed = {obs.check_id: obs for obs in loaded.rounds[2].observations}
    assert timed["echo"].termination == "timeout"
    assert timed["echo"].verdict == "unknown"
    assert timed["echo"].exit_code is None
    issues = {issue.requirement_id: issue for issue in loaded.trajectory.issues}
    assert issues["empty-input"].status == "not_comparable"
    assert issues["echo"].status == "not_comparable"


def test_qa_without_delivery_digest_cannot_confirm_false_release(tmp_path):
    materials = tmp_path / "materials"
    _write_delivery(materials / "round-1", CRASH_EMPTY)
    manifest = _write_manifest(materials, [
        _round("round-1", "round-1", decision="release", digest=None),
    ])
    pack = review_from_manifest(manifest, tmp_path / "pack")
    loaded = load_evidence_pack(pack)
    assert loaded.rounds[0].qa.delivery_digest is None
    contrast = loaded.trajectory.qa_contrasts[0]
    assert contrast.decision == "release"
    assert contrast.confirmed_false_release is False
    assert contrast.reason == "missing_delivery_evidence"
    assert contrast.counterexamples == ("empty-input",)
    assert loaded.rounds[0].observations[0].verdict == "fail"


def test_existing_or_nested_output_is_rejected(tmp_path, monkeypatch):
    materials = tmp_path / "materials"
    delivery = materials / "round-1"
    _write_delivery(delivery, ECHO)
    manifest = _write_manifest(materials, [_round("round-1", "round-1")])

    def forbidden(*args, **kwargs):
        raise AssertionError("rejected destinations must not start a program")

    monkeypatch.setattr("harness.analysis.review.subprocess.run", forbidden)
    existing = tmp_path / "already"
    existing.mkdir()
    with pytest.raises(EvidenceError, match="already exists"):
        review_from_manifest(manifest, existing)
    nested = delivery / "evidence-out"
    with pytest.raises(EvidenceError, match="inside a delivery"):
        review_from_manifest(manifest, nested)
    assert not nested.exists()
    assert not (delivery / "executed").exists()

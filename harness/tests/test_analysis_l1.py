import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.analysis import (
    ANALYZER,
    COMPARISON_RULES,
    Check,
    EVALUATOR,
    Environment,
    EvidenceError,
    MaterialDeclaration,
    ObservationInput,
    PROTOCOL,
    QARecord,
    Requirement,
    ReviewIdentity,
    RoundInput,
    load_evidence_pack,
    verify_evidence_pack,
    write_evidence_pack,
)
from harness.analysis.__main__ import main as analysis_main
from harness.models import json_dumps
from harness.public_tree import CapturedFile, CapturedTree


REQ_EMPTY = Requirement("empty-input", "v1", "空输入不会崩溃")
REQ_ECHO = Requirement("echo", "v1", "正常输入结果保持正确")
CHECK_EMPTY = Check("empty-input", "empty-input", b"", b"", 0)
CHECK_ECHO = Check("echo", "echo", b"hello\n", b"hello\n", 0)
ENV = Environment("historical-python", "trusted-local-python", COMPARISON_RULES)
MATERIAL = MaterialDeclaration(
    "calib-fail-pass-fail", "calibration", True,
    family="text-lines", project_id="eval", work_item_id="item-1", run_id="run-1",
)
REVIEW = ReviewIdentity("review-1", EVALUATOR, COMPARISON_RULES, ANALYZER, model_requests=None)


def _delivery(code: str) -> CapturedTree:
    marker = (
        "from pathlib import Path\n"
        "Path('executed').write_text('ran', encoding='utf-8')\n"
    )
    return CapturedTree(("src",), (CapturedFile("src/main.py", (marker + code).encode("utf-8")),))


def _obs(check_id: str, *, exit_code: int, stdout: bytes, stdin: bytes, duration=None) -> ObservationInput:
    return ObservationInput(
        check_id=check_id,
        termination="completed",
        stdin=stdin,
        stdout=stdout,
        stderr=b"",
        exit_code=exit_code,
        duration_sec=duration,
    )


def _round(round_id: str, code: str, empty_exit: int, echo_stdout: bytes, decision: str) -> RoundInput:
    delivery = _delivery(code)
    return RoundInput(
        id=round_id,
        delivery=delivery,
        requirements=(REQ_EMPTY, REQ_ECHO),
        checks=(CHECK_EMPTY, CHECK_ECHO),
        observations=(
            _obs("empty-input", exit_code=empty_exit, stdout=b"", stdin=b""),
            _obs("echo", exit_code=0, stdout=echo_stdout, stdin=b"hello\n"),
        ),
        environment=ENV,
        qa=QARecord(
            decision,
            "calibration",
            ("empty-input", "echo"),
            delivery.digest,
            f"{round_id} QA",
        ),
    )


CRASH_EMPTY = "import sys\ndata = sys.stdin.read()\nif not data:\n    raise SystemExit(1)\nsys.stdout.write(data)\n"
BREAK_ECHO = "import sys\ndata = sys.stdin.read()\nsys.stdout.write(data[::-1] if data else '')\n"


def _fixture_rounds():
    return (
        _round("round-1", CRASH_EMPTY, 1, b"hello\n", "rework_engineering"),
        _round("round-2", BREAK_ECHO, 0, b"\nolleh", "rework_engineering"),
        _round("round-3", CRASH_EMPTY, 1, b"hello\n", "release"),
    )


def _write_pack(tmp_path) -> Path:
    return write_evidence_pack(tmp_path / "pack", material=MATERIAL, review=REVIEW, rounds=_fixture_rounds())


def _manifest(root: Path) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def _rewrite_manifest(root: Path, mutate) -> None:
    data = _manifest(root)
    mutate(data)
    (root / "manifest.json").write_text(json_dumps(data), encoding="utf-8")


def test_fail_pass_fail_pack_moves_and_recomputes_without_executing(tmp_path, monkeypatch):
    source = tmp_path / "original-deliveries"
    source.mkdir()
    (source / "must-not-run.py").write_text("raise SystemExit('source executed')\n", encoding="utf-8")
    pack = _write_pack(tmp_path)
    shutil.rmtree(source)
    moved = tmp_path / "moved" / "evidence"
    moved.parent.mkdir()
    shutil.move(str(pack), str(moved))

    def forbidden(*args, **kwargs):
        raise AssertionError("loading must not execute a command")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    loaded = load_evidence_pack(moved)
    assert loaded.protocol == PROTOCOL
    assert loaded.material.id == MATERIAL.id
    assert loaded.review.id == REVIEW.id
    assert loaded.analysis_mismatch is False
    issues = {issue.requirement_id: issue for issue in loaded.trajectory.issues}
    assert [point.verdict for point in issues["empty-input"].points] == ["fail", "pass", "fail"]
    assert issues["empty-input"].status == "regressed"
    assert [point.verdict for point in issues["echo"].points] == ["pass", "fail", "pass"]
    assert issues["echo"].status == "new_failure"
    release = loaded.trajectory.qa_contrasts[-1]
    assert release.decision == "release"
    assert release.confirmed_false_release is True
    assert release.counterexamples == ("empty-input",)
    assert not (moved / "rounds" / "round-1" / "delivery" / "executed").exists()
    receipt = verify_evidence_pack(moved)
    assert receipt.content_digest == loaded.content_digest
    assert receipt.analysis_mismatch is False


def test_tampering_stdout_without_updating_listing_fails_integrity(tmp_path):
    pack = _write_pack(tmp_path)
    stdout = pack / "rounds" / "round-1" / "observations" / "empty-input" / "stdout"
    stdout.write_bytes(b"tampered")
    with pytest.raises(EvidenceError):
        load_evidence_pack(pack)


def test_tampered_analysis_is_recomputed_and_not_trusted(tmp_path):
    pack = _write_pack(tmp_path)
    path = pack / "analysis" / "trajectory.json"
    fake = json.loads(path.read_text(encoding="utf-8"))
    fake["issues"][0]["status"] = "stable"
    path.write_text(json_dumps(fake), encoding="utf-8")
    loaded = load_evidence_pack(pack)
    assert loaded.analysis_mismatch is True
    assert loaded.trajectory.issues[0].status == "regressed"


def test_extra_delivery_file_fails_complete_listing(tmp_path):
    pack = _write_pack(tmp_path)
    (pack / "rounds" / "round-1" / "delivery" / "extra.txt").write_bytes(b"undeclared")
    with pytest.raises(EvidenceError):
        load_evidence_pack(pack)


def test_pack_rejects_parent_and_absolute_observation_paths(tmp_path):
    pack = _write_pack(tmp_path)

    def point_outside(data):
        data["rounds"][0]["observations"][0]["stdout"] = "../secret"

    _rewrite_manifest(pack, point_outside)
    with pytest.raises(EvidenceError):
        load_evidence_pack(pack)


@pytest.mark.parametrize("raw", [
    b'{"protocol":"one","protocol":"two"}',
    b'{"protocol":NaN}',
    b"[]",
    b"\xff",
])
def test_manifest_requires_strict_utf8_json(tmp_path, raw):
    pack = _write_pack(tmp_path)
    (pack / "manifest.json").write_bytes(raw)
    with pytest.raises(EvidenceError):
        load_evidence_pack(pack)


def test_valid_utf8_recorded_as_undecodable_is_inconsistent(tmp_path):
    pack = _write_pack(tmp_path)

    def lie(data):
        data["rounds"][0]["observations"][1]["stdout_text_status"] = "undecodable"
        data["content_digest"] = "sha256:" + "0" * 64

    _rewrite_manifest(pack, lie)
    with pytest.raises(EvidenceError, match="undecodable"):
        load_evidence_pack(pack)


def test_changing_requirements_without_matching_digest_fails(tmp_path):
    pack = _write_pack(tmp_path)

    def edit(data):
        data["rounds"][0]["requirements"][0]["text"] = "changed"

    _rewrite_manifest(pack, edit)
    with pytest.raises(EvidenceError, match="digest"):
        load_evidence_pack(pack)


def test_cli_verify_is_read_only_and_prints_receipt(tmp_path, monkeypatch, capsys):
    pack = _write_pack(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("verify CLI must not execute a command")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert analysis_main(["verify", str(pack)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["protocol"] == PROTOCOL
    assert receipt["analysis_mismatch"] is False
    assert receipt["trajectory"]["issues"][0]["status"] == "regressed"
    assert analysis_main(["verify", str(tmp_path / "missing")]) == 1


def test_bool_repeats_and_missing_cost_are_not_coerced(tmp_path):
    pack = _write_pack(tmp_path)
    loaded = load_evidence_pack(pack)
    assert loaded.review.model_requests is None
    assert loaded.review.check_seconds is None
    assert loaded.rounds[0].observations[0].duration_sec is None

    def bool_repeats(data):
        data["rounds"][0]["checks"][0]["repeats"] = True

    _rewrite_manifest(pack, bool_repeats)
    with pytest.raises(EvidenceError, match="repeats"):
        load_evidence_pack(pack)

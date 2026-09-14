import shutil
from pathlib import Path

from harness.analysis.batch import analyze_batch
from harness.analysis.records import (
    ANALYZER,
    COMPARISON_RULES,
    EVALUATOR,
    Check,
    Environment,
    MaterialDeclaration,
    ObservationInput,
    Requirement,
    ReviewIdentity,
    RoundInput,
)
from harness.analysis.pack import write_evidence_pack
from harness.public_tree import CapturedFile, CapturedTree

REQ = Requirement("echo", "v1", "正常输入结果保持正确")
CHECK = Check("echo", "echo", b"", b"", 0)
ENV = Environment("historical-python", "trusted-local-python", COMPARISON_RULES)
MATERIAL_A = MaterialDeclaration("material-a", "calibration", True)
MATERIAL_B = MaterialDeclaration("material-b", "calibration", True)
REVIEW_A = ReviewIdentity("review-a", EVALUATOR, COMPARISON_RULES, ANALYZER)
REVIEW_A2 = ReviewIdentity("review-a-2", EVALUATOR, COMPARISON_RULES, ANALYZER)
REVIEW_B = ReviewIdentity("review-b", EVALUATOR, COMPARISON_RULES, ANALYZER)


def _rounds() -> tuple[RoundInput, ...]:
    delivery = CapturedTree(("src",), (CapturedFile("src/main.py", b"print(1)\n"),))
    return (
        RoundInput(
            id="round-1",
            delivery=delivery,
            requirements=(REQ,),
            checks=(CHECK,),
            observations=(
                ObservationInput(
                    check_id="echo",
                    termination="completed",
                    stdin=b"",
                    stdout=b"",
                    stderr=b"",
                    exit_code=0,
                ),
            ),
            environment=ENV,
        ),
    )


def _write(path: Path, material: MaterialDeclaration, review: ReviewIdentity) -> Path:
    return write_evidence_pack(path, material=material, review=review, rounds=_rounds())


def test_six_item_calibration_counts(tmp_path):
    pack_a = _write(tmp_path / "A", MATERIAL_A, REVIEW_A)
    pack_a_copy = tmp_path / "A-copy"
    shutil.copytree(pack_a, pack_a_copy)
    pack_a_rereview = _write(tmp_path / "A-rereview", MATERIAL_A, REVIEW_A2)
    pack_b = _write(tmp_path / "B", MATERIAL_B, REVIEW_B)
    damaged = tmp_path / "damaged"
    damaged.mkdir()
    missing = tmp_path / "missing"

    report = analyze_batch([pack_a, pack_a_copy, pack_a_rereview, pack_b, damaged, missing])

    assert report.submission_count == 6
    assert report.valid_count == 4
    assert report.duplicate_count == 1
    assert report.damaged_count == 1
    assert report.missing_count == 1
    assert report.unique_review_count == 3
    assert report.unique_material_count == 2
    assert len(report.submissions) == 6
    assert [row.verified for row in report.submissions] == [True, True, True, True, False, False]
    assert [row.duplicate for row in report.submissions] == [False, True, False, False, False, False]
    assert [row.readable for row in report.submissions] == [True, True, True, True, True, False]
    assert {row.review_id for row in report.submissions if row.verified and not row.duplicate} == {
        "review-a",
        "review-a-2",
        "review-b",
    }
    assert report.submissions[1].review_id == "review-a"
    assert report.submissions[1].content_digest == report.submissions[0].content_digest
    assert report.submissions[4].error is not None
    assert report.submissions[5].error == "missing"


def test_damaged_declared_identity_stays_in_damaged_denominator(tmp_path):
    pack_a = _write(tmp_path / "A", MATERIAL_A, REVIEW_A)
    broken = tmp_path / "broken"
    shutil.copytree(pack_a, broken)
    (broken / "rounds" / "round-1" / "observations" / "echo" / "stdout").write_bytes(b"tampered")

    report = analyze_batch([pack_a, broken])

    assert report.submission_count == 2
    assert report.valid_count == 1
    assert report.duplicate_count == 0
    assert report.damaged_count == 1
    assert report.unique_review_count == 1
    assert report.unique_material_count == 1
    damaged = report.submissions[1]
    assert damaged.verified is False
    assert damaged.duplicate is False
    assert damaged.review_id == "review-a"
    assert damaged.material_id == "material-a"
    assert damaged.content_digest is None

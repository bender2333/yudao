"""Tests for the scenario 3 scorer.

They run the scorer against the reference implementation, against an empty
delivery and against a delivery with a wrong fare rule, and check the
completion, correctness and failure classification of each. No mock is used:
the scorer runs the real reference code.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORER = os.path.join(EVALS_DIR, "scorer", "scorer.py")
REFERENCE_SRC = os.path.join(EVALS_DIR, "scenarios", "scenario-3", "reference", "src")
DATA_FILE = os.path.join(EVALS_DIR, "scenarios", "scenario-3", "files", "subway_data.json")
FIXTURES = os.path.join(EVALS_DIR, "scenarios", "scenario-3", "checks", "fixtures")


def make_delivery(root, copy_reference=True):
    delivery = os.path.join(root, "delivery")
    os.makedirs(delivery, exist_ok=True)
    if copy_reference:
        src = os.path.join(delivery, "src")
        shutil.copytree(REFERENCE_SRC, src)
        shutil.copy(DATA_FILE, os.path.join(src, "subway_data.json"))
    return delivery


def run_scorer(delivery, result_path):
    completed = subprocess.run(
        [sys.executable, SCORER, "--delivery", delivery, "--result", result_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert completed.returncode == 0, completed.stderr
    with open(result_path, encoding="utf-8") as handle:
        return json.load(handle)


def test_reference_scores_full_marks(tmp_path):
    delivery = make_delivery(str(tmp_path))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert result["completion"] == 1.0
    assert result["correctness"] == 1.0
    assert result["not_done"] == []
    assert result["wrong"] == []
    assert len(result["checks"]) == 23


def test_empty_delivery_scores_zero(tmp_path):
    delivery = make_delivery(str(tmp_path), copy_reference=False)
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert result["completion"] == 0.0
    assert result["correctness"] == 0.0
    assert result["not_done_count"] == 23
    assert result["wrong"] == []
    for check in result["checks"]:
        assert check["status"] == "not_done"


def test_wrong_fare_is_classified_as_wrong(tmp_path):
    delivery = make_delivery(str(tmp_path))
    fare_path = os.path.join(delivery, "src", "fare_calculator.py")
    with open(fare_path, encoding="utf-8") as handle:
        source = handle.read()
    source = source.replace("if distance < 6000:", "if distance < 6001:")
    with open(fare_path, "w", encoding="utf-8") as handle:
        handle.write(source)

    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert "unit_6_1" in result["wrong"]
    assert "unit_6_1" not in result["not_done"]
    # the other fare checks are unaffected by the boundary change
    assert "unit_2_2" not in result["wrong"]
    assert "unit_6_2" not in result["wrong"]
    # correctness counts passes among attempted checks only
    assert result["not_done"] == []
    assert result["correctness"] == pytest.approx(22 / 23)
    assert result["completion"] < 1.0
    assert result["completion"] > 0.9


def test_missing_module_is_not_done_for_its_checks(tmp_path):
    delivery = make_delivery(str(tmp_path))
    os.remove(os.path.join(delivery, "src", "pathfinding.py"))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    by_id = {check["id"]: check for check in result["checks"]}
    # checks that need the pathfinding module are not done
    for check_id in ("unit_2_3", "unit_2_4", "unit_5_2", "unit_9_1", "unit_12_1"):
        assert by_id[check_id]["status"] == "not_done"
    # fare checks do not need it and still pass
    assert by_id["unit_2_2"]["status"] == "pass"
    assert by_id["unit_6_1"]["status"] == "pass"


def test_missing_cli_is_not_done(tmp_path):
    delivery = make_delivery(str(tmp_path))
    os.remove(os.path.join(delivery, "src", "cli.py"))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    command_checks = [check for check in result["checks"] if check["id"].startswith("cmd_")]
    assert command_checks
    for check in command_checks:
        assert check["status"] == "not_done"
    file_checks = [check for check in result["checks"] if check["id"].startswith("file_")]
    for check in file_checks:
        assert check["status"] == "not_done"
    # the unit checks do not need the entry point and still pass
    assert result["completion"] > 0.0

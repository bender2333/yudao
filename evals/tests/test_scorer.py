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


CHECKS_PARENT = os.path.join(EVALS_DIR, "scenarios", "scenario-3")

def load_checks():
    """Import the hidden checks package the same way the scorer does."""
    if CHECKS_PARENT not in sys.path:
        sys.path.insert(0, CHECKS_PARENT)
    from checks.command_checks import COMMAND_CHECKS, REQUIREMENT_TABLE
    from checks.unit_scripts import SCRIPTS
    return COMMAND_CHECKS, REQUIREMENT_TABLE, SCRIPTS

def test_requirement_table_matches_the_scorer():
    command_checks, requirement_table, scripts = load_checks()
    with open(os.path.join(CHECKS_PARENT, "materials", "requirement-table.json"),
              encoding="utf-8") as handle:
        published = json.load(handle)

    implemented = set(scripts) | set(command_checks) | {"file_11_1", "file_11_2"}
    assert published["check_count"] == len(implemented)

    counts = {"unit": len(scripts), "command": len(command_checks), "file_comparison": 2}
    assert published["check_types"] == counts

    listed = {}
    for requirement in published["requirements"]:
        for check_id in requirement["checks"]:
            assert check_id not in listed, "check %s is listed twice" % check_id
            listed[check_id] = requirement["id"]

    # every check the scorer runs is published, and every published check exists
    assert sorted(listed) == sorted(implemented)

    # the published table and the scorer's own table assign the same requirements
    for check_id, name in listed.items():
        value = requirement_table[check_id]
        names = value if isinstance(value, list) else [value]
        assert names == [name], check_id

def test_text_export_separator_matches_the_interface_agreement():
    """The layout in the interface agreement is what the export is compared to.

    A delivery that follows the agreement must produce the fixture byte for
    byte, so the separator the agreement prints and the separator the fixture
    uses have to be the same character.
    """
    agreement_path = os.path.join(CHECKS_PARENT, "materials", "interface-agreement.md")
    with open(agreement_path, encoding="utf-8") as handle:
        agreement = handle.read()
    layout = agreement.split("```")[1]
    separator = layout[layout.index("<station>") + len("<station>"):].strip().split()[0]

    with open(os.path.join(FIXTURES, "path_fengtai_xidan.txt"), encoding="utf-8") as handle:
        fixture = handle.read()
    assert (" %s " % separator) in fixture, separator

    # the start point handed to the system under test carries the same agreement
    with open(os.path.join(CHECKS_PARENT, "materials", "start", "files",
                           "interface_agreement.md"), encoding="utf-8") as handle:
        assert handle.read() == agreement

def test_reference_scores_full_marks(tmp_path):
    delivery = make_delivery(str(tmp_path))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert result["completion"] == 1.0
    assert result["correctness"] == 1.0
    assert result["not_done"] == []
    assert result["wrong"] == []
    assert len(result["checks"]) == 24


def test_empty_delivery_scores_zero(tmp_path):
    delivery = make_delivery(str(tmp_path), copy_reference=False)
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    assert result["completion"] == 0.0
    assert result["correctness"] == 0.0
    assert result["not_done_count"] == 24
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
    assert result["correctness"] == pytest.approx(23 / 24)
    assert result["completion"] < 1.0
    assert result["completion"] > 0.9


def test_line_preference_is_required_for_its_requirement(tmp_path):
    delivery = make_delivery(str(tmp_path))
    # Drop the preference handling: the reference reroutes the path when a
    # preferred line is set, this build ignores the setting entirely.
    pathfinding_path = os.path.join(delivery, "src", "pathfinding.py")
    with open(pathfinding_path, encoding="utf-8") as handle:
        source = handle.read()
    source = source.replace(
        "                if self._line_preferred(edge.line):\n"
        "                    key = (key[0] - 1, key[1])\n",
        "")
    with open(pathfinding_path, "w", encoding="utf-8") as handle:
        handle.write(source)

    result = run_scorer(delivery, str(tmp_path / "result.json"))
    by_id = {check["id"]: check for check in result["checks"]}
    assert by_id["unit_2_5"]["status"] == "wrong"
    # the requirement the check belongs to scores nothing
    assert result["requirements"]["R3"]["score"] == 0.0
    assert result["completion"] < 1.0
    # the other pathfinding checks still pass, so only R3 is affected
    assert by_id["unit_2_3"]["status"] == "pass"
    assert by_id["unit_9_1"]["status"] == "pass"

def test_missing_module_is_not_done_for_its_checks(tmp_path):
    delivery = make_delivery(str(tmp_path))
    os.remove(os.path.join(delivery, "src", "pathfinding.py"))
    result = run_scorer(delivery, str(tmp_path / "result.json"))
    by_id = {check["id"]: check for check in result["checks"]}
    # checks that need the pathfinding module are not done
    for check_id in ("unit_2_3", "unit_2_4", "unit_2_5", "unit_5_2", "unit_9_1", "unit_12_1"):
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

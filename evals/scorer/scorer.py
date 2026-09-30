"""Scenario 3 scorer.

Runs the 23 hidden checks against one delivery directory and writes a
machine-readable result. The scorer does not know which side produced the
delivery: it only reads a directory containing a ``src/`` folder.

Completion is the mean over the 7 requirements of the per-requirement pass
ratio. Correctness is the pass ratio among the checks that were attempted.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

SCENARIO = "scenario-3"
MATERIAL_VERSION = "scenario-3@1"
SCORER_VERSION = "scorer-3@1"
REQUIREMENTS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7"]

FILE_CHECKS = {
    "file_11_1": {
        "stdin": "Fengtai East Street;Xidan\n",
        "args": ["--output_file", "output_text.txt", "--format", "text"],
        "fixture": "path_fengtai_xidan.txt",
        "assert_file": "text",
    },
    "file_11_2": {
        "stdin": "Tiananmen East;Zhongguancun\n",
        "args": ["--output_file", "output_data.json", "--format", "json"],
        "fixture": "path_tiananmen_zhongguancun.json",
        "assert_file": "json",
    },
}


def load_checks(checks_dir):
    """Import the hidden checks package from the scoring directory."""
    parent = os.path.dirname(os.path.abspath(checks_dir))
    if parent not in sys.path:
        sys.path.insert(0, parent)
    import checks.check_harness as harness_module
    from checks.command_checks import COMMAND_CHECKS
    from checks.unit_scripts import REQUIRED_SYMBOLS, SCRIPTS
    return harness_module, COMMAND_CHECKS, REQUIRED_SYMBOLS, SCRIPTS


def build_subject(delivery_dir, work_dir, python):
    src = os.path.join(delivery_dir, "src")
    if not os.path.isdir(src):
        return None
    python_command = [python] if isinstance(python, str) else list(python)

    def run(command, cwd, stdin_text="", extra_path=None):
        env = dict(os.environ)
        if extra_path:
            env["PYTHONPATH"] = extra_path + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            command, cwd=cwd, input=stdin_text, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env)

    return {
        "delivery_dir": delivery_dir,
        "src_dir": src,
        "work_dir": work_dir,
        "python": python_command,
        "run": run,
    }


def run_check(check_id, subject, context):
    """Return (status, detail). status is 'pass', 'wrong' or 'not_done'."""
    if check_id.startswith("unit_"):
        return _run_unit(check_id, subject, context)
    if check_id.startswith("cmd_"):
        return _run_command(check_id, subject, context)
    if check_id.startswith("file_"):
        return _run_file(check_id, subject, context)
    raise ValueError("unknown check: " + check_id)


def _run_unit(check_id, subject, context):
    harness = context["harness"]
    try:
        harness.require_symbols(subject, context["required_symbols"][check_id])
    except harness.NotDone as error:
        return "not_done", str(error)
    result = harness.run_python(subject, context["scripts"][check_id])
    payload = _last_json(result.stdout)
    if payload is None:
        return "wrong", _tail(result.stderr or result.stdout)
    if payload.get("ok"):
        return "pass", ""
    return "wrong", payload.get("detail", "")


def _run_command(check_id, subject, context):
    spec = context["command_checks"][check_id]
    harness = context["harness"]
    try:
        harness.require_cli(subject)
    except harness.NotDone as error:
        return "not_done", str(error)
    result = harness.run_cli(subject, spec["args"], spec["stdin"])
    ok, detail = spec["assert"](result.stdout, result.stderr, result.returncode)
    if ok:
        return "pass", ""
    return "wrong", detail


def _run_file(check_id, subject, context):
    spec = FILE_CHECKS[check_id]
    harness = context["harness"]
    checks_dir = context["checks_dir"]
    try:
        harness.require_cli(subject)
    except harness.NotDone as error:
        return "not_done", str(error)
    produced = os.path.join(subject["src_dir"], spec["args"][1])
    if os.path.exists(produced):
        os.remove(produced)
    harness.run_cli(subject, spec["args"], spec["stdin"])
    if not os.path.isfile(produced):
        return "wrong", "the export file was not created"
    if spec["assert_file"] == "text":
        return _compare_text(produced, os.path.join(checks_dir, "fixtures", spec["fixture"]))
    return _compare_json(produced, os.path.join(checks_dir, "fixtures", spec["fixture"]))


def _compare_text(produced, fixture):
    with open(produced, encoding="utf-8") as handle:
        actual = handle.read()
    with open(fixture, encoding="utf-8") as handle:
        expected = handle.read()
    if actual.strip() != expected.strip():
        return "wrong", "the text export does not match the agreed layout"
    return "pass", ""


def _compare_json(produced, fixture):
    with open(produced, encoding="utf-8") as handle:
        actual = json.load(handle)
    with open(fixture, encoding="utf-8") as handle:
        expected = json.load(handle)
    if actual.get("query", {}).get("start_station") != expected["query"]["start_station"]:
        return "wrong", "query start station mismatch"
    if actual.get("query", {}).get("end_station") != expected["query"]["end_station"]:
        return "wrong", "query end station mismatch"
    result = actual.get("result", {})
    expected_result = expected["result"]
    if result.get("path") != expected_result["path"]:
        return "wrong", "path mismatch"
    for field in ("total_distance", "fare", "estimated_time", "transfer_count"):
        if result.get(field) != expected_result[field]:
            return "wrong", "%s mismatch: %s != %s" % (field, result.get(field), expected_result[field])
    if sorted(result.get("lines_involved", [])) != sorted(expected_result["lines_involved"]):
        return "wrong", "lines_involved mismatch"
    return "pass", ""


def _last_json(text):
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _tail(text):
    return "\n".join(text.strip().splitlines()[-3:]) if text.strip() else "no output"


def score(delivery_dir, checks_dir, python):
    checks_dir = os.path.abspath(checks_dir)
    work_root = os.path.join(checks_dir, "_work")
    if os.path.exists(work_root):
        shutil.rmtree(work_root)
    os.makedirs(work_root)
    harness, command_checks, required_symbols, scripts = load_checks(checks_dir)
    from checks.command_checks import REQUIREMENT_TABLE
    context = {
        "harness": harness,
        "command_checks": command_checks,
        "required_symbols": required_symbols,
        "scripts": scripts,
        "checks_dir": checks_dir,
        "requirement_table": REQUIREMENT_TABLE,
    }
    subject = build_subject(delivery_dir, work_root, python)

    check_ids = sorted(list(scripts.keys()) + list(command_checks.keys()) + list(FILE_CHECKS.keys()))

    records = []
    for check_id in check_ids:
        if subject is None:
            status, detail = "not_done", "the delivery has no src directory"
        else:
            status, detail = run_check(check_id, subject, context)
        records.append({"id": check_id,
                        "requirement": context["requirement_table"][check_id],
                        "status": status, "detail": detail})

    shutil.rmtree(work_root, ignore_errors=True)
    return _aggregate(records, context["requirement_table"])


def _requirements_of(check_id, table):
    value = table[check_id]
    if isinstance(value, list):
        return value
    return [value]


def _aggregate(records, table):
    requirement_checks = {name: [] for name in REQUIREMENTS}
    for record in records:
        for name in _requirements_of(record["id"], table):
            requirement_checks[name].append(record)

    requirement_scores = {}
    for name in REQUIREMENTS:
        items = requirement_checks[name]
        passed = sum(1 for item in items if item["status"] == "pass")
        requirement_scores[name] = {
            "passed": passed,
            "total": len(items),
            "score": passed / len(items) if items else 0.0,
        }

    completion = sum(item["score"] for item in requirement_scores.values()) / len(REQUIREMENTS)

    attempted = [item for item in records if item["status"] != "not_done"]
    passed_attempts = sum(1 for item in attempted if item["status"] == "pass")
    correctness = passed_attempts / len(attempted) if attempted else 0.0

    not_done = [item["id"] for item in records if item["status"] == "not_done"]
    wrong = [item["id"] for item in records if item["status"] == "wrong"]

    return {
        "scenario": SCENARIO,
        "material_version": MATERIAL_VERSION,
        "scorer_version": SCORER_VERSION,
        "completion": completion,
        "correctness": correctness,
        "not_done_count": len(not_done),
        "wrong_count": len(wrong),
        "not_done": not_done,
        "wrong": wrong,
        "requirements": requirement_scores,
        "checks": records,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scenario 3 scorer")
    parser.add_argument("--delivery", required=True, help="directory containing src/")
    parser.add_argument("--checks", default=os.path.join(os.path.dirname(__file__), "..",
                                                         "scenarios", "scenario-3", "checks"))
    parser.add_argument("--result", help="path to write the machine-readable result")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)

    checks_dir = os.path.abspath(args.checks)
    result = score(args.delivery, checks_dir, args.python)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.result:
        with open(args.result, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The 10 command checks and 2 file comparison checks.

Each command check gives standard input and an assertion over the program's
standard output. The expected distances, fares and transfer counts are computed
from the problem data.
"""

# Command checks: id -> dict(stdin, args, assert_fn(stdout, stderr, returncode))
# assert_fn returns (ok, detail).


def _has_all(text, needles):
    missing = [needle for needle in needles if needle not in text]
    return (not missing), "missing: %s" % missing


def cmd_0_1(stdout, stderr, code):
    if code != 0:
        return False, "program exited with code %s" % code
    combined = (stdout + stderr).lower()
    if ";" not in combined or "station" not in combined:
        return False, "the program starts without an input prompt describing the query format"
    return True, ""


def cmd_1_1(stdout, stderr, code):
    combined = stdout + stderr
    if code != 0:
        return False, "program exited with code %s" % code
    if "Xidan" not in combined:
        return False, "the valid query produced no result"
    if "format incorrect" in combined.lower():
        return False, "valid input rejected as a format error"
    return True, ""


def cmd_2_1(stdout, stderr, code):
    combined = stdout + stderr
    required = ["Fengtai East Street", "Qilizhuang", "Military Museum", "Xidan"]
    return _has_all(combined, required)


def cmd_3_1a(stdout, stderr, code):
    combined = stdout + stderr
    required = ["Tiananmen East", "Tiananmen West", "Xidan", "Zhongguancun"]
    return _has_all(combined, required)


def cmd_3_1b(stdout, stderr, code):
    combined = stdout + stderr
    required = ["11451", "4 yuan"]
    ok, detail = _has_all(combined, required)
    if not ok:
        return False, detail
    return True, ""


def cmd_4_1(stdout, stderr, code):
    combined = stdout + stderr
    ok, detail = _has_all(combined, ["format"])
    if not ok:
        return False, detail
    if "Xidan" not in combined:
        return False, "the valid query in the same input produced no result"
    return True, ""


def cmd_4_2(stdout, stderr, code):
    combined = stdout + stderr
    if code != 0:
        return False, "program exited with code %s instead of reporting the invalid station" % code
    if "NonExistentStation" not in combined:
        return False, "the invalid station name is not mentioned"
    lowered = combined.lower()
    if "does not exist" not in lowered and "not in the system" not in lowered:
        return False, "the invalid station is not clearly reported as missing"
    return True, ""


def cmd_5_1a(stdout, stderr, code):
    combined = stdout + stderr
    required = ["Military Museum", "Line 1", "Xidan"]
    ok, detail = _has_all(combined, required)
    if not ok:
        return False, detail
    return True, ""


def cmd_7_1(stdout, stderr, code):
    combined = stdout + stderr
    if combined.count("Zhongguancun") < 1:
        return False, "the second query produced no result"
    if "Tiananmen East" not in combined:
        return False, "the first query produced no result"
    return True, ""


def cmd_8_1(stdout, stderr, code):
    combined = stdout + stderr
    lowered = combined.lower()
    if "same" not in lowered:
        return False, "the same start and end station is not reported"
    return True, ""


COMMAND_CHECKS = {
    "cmd_0_1": {
        "stdin": "",
        "args": [],
        "assert": cmd_0_1,
        "requirement": "R7",
    },
    "cmd_1_1": {
        "stdin": "Tiananmen East;Xidan\n",
        "args": [],
        "assert": cmd_1_1,
        "requirement": "R7",
    },
    "cmd_2_1": {
        "stdin": "Fengtai East Street;Xidan\n",
        "args": [],
        "assert": cmd_2_1,
        "requirement": "R1",
    },
    "cmd_3_1a": {
        "stdin": "Tiananmen East;Zhongguancun\n",
        "args": [],
        "assert": cmd_3_1a,
        "requirement": "R1",
    },
    "cmd_3_1b": {
        "stdin": "Fengtai East Street;Xidan\n",
        "args": [],
        "assert": cmd_3_1b,
        "requirement": "R1",
    },
    "cmd_4_1": {
        "stdin": "Tiananmen East,Xidan\nTiananmen East Xidan\nTiananmen East\nTiananmen East;Xidan\n",
        "args": [],
        "assert": cmd_4_1,
        "requirement": "R7",
    },
    "cmd_4_2": {
        "stdin": "NonExistentStation;Xidan\n",
        "args": [],
        "assert": cmd_4_2,
        "requirement": "R7",
    },
    "cmd_5_1a": {
        "stdin": "Fengtai East Street;Xidan\n",
        "args": [],
        "assert": cmd_5_1a,
        "requirement": "R2",
    },
    "cmd_7_1": {
        "stdin": "Tiananmen East;Xidan\nTiananmen East;Zhongguancun\n",
        "args": [],
        "assert": cmd_7_1,
        "requirement": "R7",
    },
    "cmd_8_1": {
        "stdin": "Tiananmen East;Tiananmen East\n",
        "args": [],
        "assert": cmd_8_1,
        "requirement": "R7",
    },
}

REQUIREMENT_TABLE = {
    "unit_2_2": "R4", "unit_2_3": "R1", "unit_2_4": "R2", "unit_2_5": "R3",
    "unit_5_2": "R2", "unit_6_1": "R4", "unit_6_2": "R4",
    "unit_8_2": "R7", "unit_9_1": "R1", "unit_10_1": "R7",
    "unit_10_2": "R7", "unit_12_1": "R5",
    "file_11_1": "R6", "file_11_2": "R6",
}

for _name, _spec in COMMAND_CHECKS.items():
    REQUIREMENT_TABLE[_name] = _spec["requirement"]

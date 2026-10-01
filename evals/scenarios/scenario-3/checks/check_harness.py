"""Shared helpers for the scenario 3 hidden checks.

A ``subject`` describes one delivery. The scorer builds it from a directory that
contains a ``src/`` folder. Checks only use ``run_python`` (a script run with
``src`` on the path) and ``run_cli`` (the program entry with arguments and
standard input).
"""

import json
import os


class NotDone(Exception):
    """Raised when the delivery has not implemented the checked behaviour."""


def cli_present(subject):
    return os.path.isfile(os.path.join(subject["src_dir"], "cli.py"))


def run_python(subject, script, args=None):
    """Run a Python script with the delivery's src directory on the path."""
    path = os.path.join(subject["work_dir"], "_check_script.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    command = list(subject["python"]) + [path] + list(args or [])
    return subject["run"](command, cwd=subject["src_dir"], extra_path=subject["src_dir"])


def run_cli(subject, args, stdin_text):
    command = list(subject["python"]) + ["cli.py"] + list(args)
    return subject["run"](command, cwd=subject["src_dir"], stdin_text=stdin_text)


def require_symbols(subject, required):
    """Raise NotDone if a required module or symbol is missing."""
    result = run_python(subject, PROBE)
    symbols = _parse_json(result.stdout)
    for name in required:
        if not symbols.get(name):
            raise NotDone("missing symbol: " + name)


def require_cli(subject):
    if not cli_present(subject):
        raise NotDone("missing program entry: src/cli.py")


def _parse_json(text):
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {}


PROBE = r'''
import json

result = {}
try:
    from models import Edge, Graph
    graph = Graph()
    result["models"] = all(hasattr(graph, name) for name in ("add_edge", "set_station_lines", "adj"))
except Exception:
    result["models"] = False
try:
    from pathfinding import ShortestPath, PathfindingConfig
    config = PathfindingConfig()
    result["pathfinding"] = all(hasattr(config, name) for name in ("mode", "max_transfers", "preferred_lines"))
except Exception:
    result["pathfinding"] = False
try:
    from fare_calculator import Sum_money, calculate_estimated_time
    result["fare"] = callable(Sum_money) and callable(calculate_estimated_time)
except Exception:
    result["fare"] = False
try:
    from data_loader import load_subway_data, DATA_FILE_PATH
    loaded = load_subway_data(DATA_FILE_PATH)
    result["data_loader"] = bool(loaded) and "stations" in loaded and "connections" in loaded
except Exception:
    result["data_loader"] = False
print(json.dumps(result))
'''

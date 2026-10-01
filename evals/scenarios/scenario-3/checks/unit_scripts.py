"""The 12 unit checks. Each value is Python source run inside the delivery src."""

COMMON = r'''
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def build():
    from models import Edge, Graph
    from data_loader import load_subway_data, DATA_FILE_PATH
    data = load_subway_data(DATA_FILE_PATH)
    graph = Graph()
    station_to_number = {}
    number_to_station = {}
    for index, station in enumerate(data["stations"], start=1):
        station_to_number[station["name"]] = index
        number_to_station[index] = station["name"]
        graph.set_station_lines(station["name"], station["lines"])
    for connection in data["connections"]:
        source = station_to_number.get(connection["source"])
        dest = station_to_number.get(connection["dest"])
        if source is not None and dest is not None:
            graph.add_edge(Edge(source, dest, connection["distance"], connection["line"]))
    return graph, station_to_number, number_to_station


def report(name, ok, detail=""):
    print(json.dumps({"ok": bool(ok), "detail": detail}))
    return 0 if ok else 1
'''

UNIT_2_2 = COMMON + r'''
from fare_calculator import Sum_money
cases = [(3000, 3), (5000, 3), (8000, 4), (15000, 5), (25000, 6)]
bad = [(d, e, Sum_money(d)) for d, e in cases if Sum_money(d) != e]
sys.exit(report("unit_2_2", not bad, "fare mismatches: %s" % bad))
'''

UNIT_2_3 = COMMON + r'''
from pathfinding import ShortestPath, PathfindingConfig
graph, station_to_number, number_to_station = build()
start = station_to_number["Tiananmen East"]
end = station_to_number["Zhongguancun"]

shortest = PathfindingConfig()
shortest.mode = "shortest_distance"
finder = ShortestPath(graph, start, shortest)
if end not in finder.dist_to:
    sys.exit(report("unit_2_3", False, "shortest distance mode found no path"))
path_ids, edges = finder.path_with_edges(end)
distance = sum(edge.weight for edge in edges)

least = PathfindingConfig()
least.mode = "least_transfer"
least_finder = ShortestPath(graph, start, least)
least_transfers = least_finder.get_transfer_count(end)

comprehensive = PathfindingConfig()
comprehensive.mode = "comprehensive"
comprehensive_finder = ShortestPath(graph, start, comprehensive)
comprehensive_transfers = comprehensive_finder.get_transfer_count(end)
comprehensive_distance = comprehensive_finder.dist_to.get(end, None)

ok = (distance == 13771 and least_transfers == 1
      and comprehensive_transfers <= 2 and comprehensive_distance is not None
      and comprehensive_distance < 20000)
sys.exit(report("unit_2_3", ok,
    "shortest=%s least=%s comprehensive_distance=%s comprehensive_transfers=%s" % (
        distance, least_transfers, comprehensive_distance, comprehensive_transfers)))
'''

UNIT_2_4 = COMMON + r'''
from pathfinding import ShortestPath, PathfindingConfig
graph, station_to_number, number_to_station = build()
start = station_to_number["Tiananmen East"]
end = station_to_number["Zhongguancun"]

zero = PathfindingConfig()
zero.mode = "shortest_distance"
zero.max_transfers = 0
zero_finder = ShortestPath(graph, start, zero)
zero_ok = end not in zero_finder.dist_to

one = PathfindingConfig()
one.mode = "shortest_distance"
one.max_transfers = 1
one_finder = ShortestPath(graph, start, one)
one_ok = end in one_finder.dist_to and one_finder.get_transfer_count(end) <= 1

sys.exit(report("unit_2_4", zero_ok and one_ok,
    "max_transfers=0 no path: %s, max_transfers=1 transfer<=1: %s" % (zero_ok, one_ok)))
'''

UNIT_2_5 = COMMON + r'''
from pathfinding import ShortestPath, PathfindingConfig
graph, station_to_number, number_to_station = build()

def run(start_name, end_name, preferred):
    config = PathfindingConfig()
    config.mode = "least_transfer"
    config.preferred_lines = preferred
    finder = ShortestPath(graph, station_to_number[start_name], config)
    end = station_to_number[end_name]
    if end not in finder.dist_to:
        return None
    _path_ids, edges = finder.path_with_edges(end)
    return {
        "distance": sum(edge.weight for edge in edges),
        "transfers": finder.get_transfer_count(end),
        "lines": [edge.line for edge in edges],
    }

# 线路偏好在路径真的走上偏好线路时才成立。两条路线各选一条基准路径没有经过的线路：
# 天安门东到中关村最少换乘时基准走 Line 1 与 Line 4，丰台东大街到西单基准走 Line 1 与 Line 9。
# 只按某一个线路名称特殊处理的交付会在另一条路线上露出来。
ROUTES = [
    ("Tiananmen East", "Zhongguancun", ["Line 10"], "Line 10"),
    ("Fengtai East Street", "Xidan", ["Line 4"], "Line 4"),
    ("Fengtai East Street", "Xidan", ["Line 2", "Line 4"], "Line 4"),
]

problems = []
for start_name, end_name, preferred, expected_line in ROUTES:
    baseline = run(start_name, end_name, [])
    chosen = run(start_name, end_name, preferred)
    label = "%s->%s preferred %s" % (start_name, end_name, preferred)
    if baseline is None or chosen is None:
        problems.append("%s: least_transfer mode found no path" % label)
        continue
    if expected_line not in chosen["lines"]:
        problems.append("%s: path does not run on %s: %s" % (label, expected_line, chosen["lines"]))
        continue
    if chosen["lines"] == baseline["lines"]:
        problems.append("%s: preference did not change the route from the baseline" % label)
    if chosen["distance"] == baseline["distance"] and chosen["transfers"] == baseline["transfers"]:
        problems.append("%s: preference left distance %s and transfers %s unchanged"
            % (label, chosen["distance"], chosen["transfers"]))
sys.exit(report("unit_2_5", not problems, "; ".join(problems)))
'''

UNIT_5_2 = COMMON + r'''
from pathfinding import ShortestPath
graph, station_to_number, number_to_station = build()
start = station_to_number["Tiananmen East"]
end = station_to_number["Zhongguancun"]
finder = ShortestPath(graph, start)
if end not in finder.dist_to:
    sys.exit(report("unit_5_2", False, "no path found"))
path_ids, edges = finder.path_with_edges(end)
problems = []
previous_line = None
for index, edge in enumerate(edges):
    if previous_line is not None and previous_line != edge.line:
        station_name = number_to_station[path_ids[index]]
        lines = graph.station_lines.get(station_name, [])
        if len(lines) <= 1:
            problems.append(station_name)
    previous_line = edge.line
sys.exit(report("unit_5_2", not problems, "transfer stations with one line: %s" % problems))
'''

UNIT_6_1 = COMMON + r'''
from fare_calculator import Sum_money
cases = [
    (5999, 3), (6000, 4), (6001, 4),
    (11999, 4), (12000, 5), (12001, 5),
    (21999, 5), (22000, 6), (22001, 6),
    (31999, 6), (32000, 7), (32001, 7),
]
bad = [(d, e, Sum_money(d)) for d, e in cases if Sum_money(d) != e]
sys.exit(report("unit_6_1", not bad, "boundary mismatches: %s" % bad))
'''

UNIT_6_2 = COMMON + r'''
from fare_calculator import Sum_money
cases = [
    (35000, 7), (45000, 7), (51999, 7), (52000, 8), (52001, 8),
    (65000, 8), (71999, 8), (72000, 9), (72001, 9), (85000, 9),
    (92000, 10), (100000, 10),
]
bad = [(d, e, Sum_money(d)) for d, e in cases if Sum_money(d) != e]
sys.exit(report("unit_6_2", not bad, "extended mismatches: %s" % bad))
'''

UNIT_8_2 = COMMON + r'''
import time
from pathfinding import ShortestPath
graph, station_to_number, number_to_station = build()
cases = [
    ("Tiananmen East", "Xidan"),
    ("Tiananmen East", "Zhongguancun"),
    ("Tiananmen East", "Dongdan"),
    ("Xidan", "Yonghegong Lama Temple"),
    ("Chaoyangmen", "Zhongguancun"),
]
slow = []
for start_name, end_name in cases:
    start = station_to_number.get(start_name)
    end = station_to_number.get(end_name)
    if start is None or end is None:
        continue
    begin = time.time()
    finder = ShortestPath(graph, start)
    if end in finder.dist_to:
        finder.path_with_edges(end)
    elapsed = time.time() - begin
    if elapsed > 1.0:
        slow.append((start_name, end_name, elapsed))
sys.exit(report("unit_8_2", not slow, "queries over 1 second: %s" % slow))
'''

UNIT_9_1 = COMMON + r'''
from pathfinding import ShortestPath, PathfindingConfig
graph, station_to_number, number_to_station = build()
cases = [
    ("Tiananmen East", "Xidan", 2142),
    ("Tiananmen East", "Zhongguancun", 13771),
    ("Xidan", "Dongdan", 3768),
]
problems = []
for start_name, end_name, expected in cases:
    start = station_to_number.get(start_name)
    end = station_to_number.get(end_name)
    if start is None or end is None:
        problems.append("%s->%s missing station" % (start_name, end_name))
        continue
    config = PathfindingConfig()
    config.mode = "shortest_distance"
    finder = ShortestPath(graph, start, config)
    if end not in finder.dist_to:
        problems.append("%s->%s no path" % (start_name, end_name))
        continue
    path_ids, edges = finder.path_with_edges(end)
    distance = sum(edge.weight for edge in edges)
    if distance != expected:
        problems.append("%s->%s distance %s != %s" % (start_name, end_name, distance, expected))
sys.exit(report("unit_9_1", not problems, "; ".join(problems)))
'''

UNIT_10_1 = COMMON + r'''
from data_loader import load_subway_data, DATA_FILE_PATH
required = [
    "Tiananmen East", "Xidan", "Chaoyangmen", "Dongzhimen",
    "Zhongguancun", "Dongdan", "Yonghegong Lama Temple", "Tiananmen West",
]
data = load_subway_data(DATA_FILE_PATH)
available = {station["name"] for station in data["stations"]}
found = [name for name in required if name in available]
sys.exit(report("unit_10_1", len(found) >= 6, "found %s of required stations: %s" % (len(found), found)))
'''

UNIT_10_2 = COMMON + r'''
from data_loader import load_subway_data, DATA_FILE_PATH
data = load_subway_data(DATA_FILE_PATH)
stations = data["stations"]
connections = data["connections"]
names = {station["name"] for station in stations}
invalid = []
for connection in connections:
    if connection["source"] not in names:
        invalid.append(connection["source"])
    if connection["dest"] not in names:
        invalid.append(connection["dest"])
valid_ratio = 1 - len(invalid) / len(connections) if connections else 0

distance_issues = [c for c in connections if c.get("distance", 0) <= 0 or c.get("distance", 0) > 50000]
distance_ratio = 1 - len(distance_issues) / len(connections) if connections else 0

lines = {}
for station in stations:
    for line in station.get("lines", []):
        lines[line] = lines.get(line, 0) + 1

structure_ok = all("name" in s and "lines" in s for s in stations) and all(
    field in c for c in connections for field in ("source", "dest", "distance", "line"))

ok = (len(stations) > 0 and len(connections) > 0 and valid_ratio >= 0.95
      and distance_ratio >= 0.9 and len(lines) >= 3 and structure_ok)
sys.exit(report("unit_10_2", ok,
    "valid=%s distance=%s lines=%s structure=%s" % (valid_ratio, distance_ratio, len(lines), structure_ok)))
'''

UNIT_12_1 = COMMON + r'''
from pathfinding import ShortestPath
from fare_calculator import calculate_estimated_time
graph, station_to_number, number_to_station = build()
cases = [("Tiananmen East", "Xidan"), ("Tiananmen East", "Zhongguancun")]
problems = []
for start_name, end_name in cases:
    start = station_to_number.get(start_name)
    end = station_to_number.get(end_name)
    if start is None or end is None:
        continue
    finder = ShortestPath(graph, start)
    if end not in finder.dist_to:
        continue
    path_ids, edges = finder.path_with_edges(end)
    distance = sum(edge.weight for edge in edges)
    transfers = finder.get_transfer_count(end)
    minutes = calculate_estimated_time(distance, transfers)
    low = (distance / 1000.0) * 1 + transfers * 2
    high = (distance / 1000.0) * 3 + transfers * 5
    if not (minutes > 0 and low <= minutes <= high):
        problems.append((start_name, end_name, minutes, low, high))
sys.exit(report("unit_12_1", not problems, "time estimation problems: %s" % problems))
'''

SCRIPTS = {
    "unit_2_2": UNIT_2_2,
    "unit_2_3": UNIT_2_3,
    "unit_2_4": UNIT_2_4,
    "unit_2_5": UNIT_2_5,
    "unit_5_2": UNIT_5_2,
    "unit_6_1": UNIT_6_1,
    "unit_6_2": UNIT_6_2,
    "unit_8_2": UNIT_8_2,
    "unit_9_1": UNIT_9_1,
    "unit_10_1": UNIT_10_1,
    "unit_10_2": UNIT_10_2,
    "unit_12_1": UNIT_12_1,
}

REQUIRED_SYMBOLS = {
    "unit_2_2": ["fare"],
    "unit_2_3": ["models", "data_loader", "pathfinding"],
    "unit_2_4": ["models", "data_loader", "pathfinding"],
    "unit_2_5": ["models", "data_loader", "pathfinding"],
    "unit_5_2": ["models", "data_loader", "pathfinding"],
    "unit_6_1": ["fare"],
    "unit_6_2": ["fare"],
    "unit_8_2": ["models", "data_loader", "pathfinding"],
    "unit_9_1": ["models", "data_loader", "pathfinding"],
    "unit_10_1": ["data_loader"],
    "unit_10_2": ["data_loader"],
    "unit_12_1": ["models", "data_loader", "pathfinding", "fare"],
}

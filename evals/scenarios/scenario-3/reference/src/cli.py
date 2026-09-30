import argparse
import json
import sys

import data_loader
from data_loader import DATA_FILE_PATH, load_subway_data
from fare_calculator import Sum_money, calculate_estimated_time
from models import Edge, Graph, PathfindingConfig
from pathfinding import ShortestPath

REQUIRED_STATIONS = [
    "Tiananmen East", "Xidan", "Chaoyangmen", "Dongzhimen",
    "Zhongguancun", "Dongdan", "Yonghegong Lama Temple", "Tiananmen West",
]


def build_system(data_path):
    data = load_subway_data(data_path)
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
        if source is None or dest is None:
            continue
        graph.add_edge(Edge(source, dest, connection["distance"], connection["line"]))
    return data, graph, station_to_number, number_to_station


def check_data(data):
    names = {station["name"] for station in data["stations"]}
    missing = [name for name in REQUIRED_STATIONS if name not in names]
    problems = []
    if missing:
        problems.append("missing stations: " + ", ".join(missing))
    for connection in data["connections"]:
        if connection["source"] not in names:
            problems.append("source not a station: " + connection["source"])
        if connection["dest"] not in names:
            problems.append("destination not a station: " + connection["dest"])
        if not connection.get("distance", 0) > 0:
            problems.append("invalid distance: " + connection["source"])
    return problems


def format_lines(path_ids, edges, number_to_station):
    segments = []
    current_line = None
    current_stations = []
    for index, edge in enumerate(edges):
        station_name = number_to_station[path_ids[index]]
        if current_line != edge.line:
            if current_stations:
                segments.append((current_line, current_stations))
            current_line = edge.line
            current_stations = [station_name]
        next_name = number_to_station[path_ids[index + 1]]
        current_stations.append(next_name)
    if current_stations:
        segments.append((current_line, current_stations))

    lines = []
    for position, (line, stations) in enumerate(segments):
        rendered = " → ".join(stations)
        if position < len(segments) - 1:
            rendered += " [Transfer Station]"
        lines.append(f"  {line}: {rendered}")
    return "\n".join(lines)


def query_once(system, start_name, end_name, args):
    data, graph, station_to_number, number_to_station = system
    if start_name not in station_to_number:
        return f"Starting station '{start_name}' does not exist, please check the station name"
    if end_name not in station_to_number:
        return f"Ending station '{end_name}' does not exist, please check the station name"
    if start_name == end_name:
        return "Origin station cannot be the same as destination station"

    config = PathfindingConfig()
    config.mode = args.mode
    config.max_transfers = args.max_transfers
    if args.line_preference:
        config.preferred_lines = [args.line_preference]

    start_id = station_to_number[start_name]
    end_id = station_to_number[end_name]
    finder = ShortestPath(graph, start_id, config)
    if end_id not in finder.dist_to:
        return f"No path found from {start_name} to {end_name}"

    path_ids, edges = finder.path_with_edges(end_id)
    total_distance = sum(edge.weight for edge in edges)
    fare = Sum_money(total_distance)
    transfer_count = finder.get_transfer_count(end_id)
    estimated_time = calculate_estimated_time(total_distance, transfer_count)
    path_names = [number_to_station[node] for node in path_ids]
    lines_involved = []
    for edge in edges:
        if edge.line not in lines_involved:
            lines_involved.append(edge.line)

    if args.format == "json":
        payload = {
            "query": {"start_station": start_name, "end_station": end_name},
            "result": {
                "path": path_names,
                "total_distance": total_distance,
                "fare": fare,
                "estimated_time": estimated_time,
                "transfer_count": transfer_count,
                "lines_involved": lines_involved,
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = (
            "--- Path Query Result ---\n"
            f"Start Station: {start_name}\n"
            f"End Station: {end_name}\n\n"
            "Detailed Path:\n"
            f"{format_lines(path_ids, edges, number_to_station)}\n\n"
            f"Total Distance: {total_distance} meters ({total_distance / 1000:.2f} km)\n"
            f"Estimated Fare: {fare} yuan\n"
            f"Estimated Travel Time: {estimated_time} minutes\n"
            f"Transfer Count: {transfer_count} time" + ("s" if transfer_count != 1 else "")
        )

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return text


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Beijing Subway fare calculation")
    parser.add_argument("--output_file")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--mode", choices=["shortest_distance", "least_transfer", "comprehensive"],
                        default="shortest_distance")
    parser.add_argument("--max_transfers", type=int)
    parser.add_argument("--line_preference")
    parser.add_argument("--check_data", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    system = build_system(DATA_FILE_PATH)
    data = system[0]

    if args.check_data:
        problems = check_data(data)
        if problems:
            print("Data integrity check failed:")
            for problem in problems:
                print("  - " + problem)
        else:
            print("Data integrity check passed")
            print(f"  {len(data['stations'])} stations, {len(data['connections'])} connections")
        return 0

    print("Beijing Subway Fare Calculation System")
    print("Enter a query as 'Starting Station; Ending Station'")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split(";")
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            print("Input format incorrect, please use 'Starting Station; Ending Station' format")
            continue
        print(query_once(system, parts[0].strip(), parts[1].strip(), args))
    return 0


if __name__ == "__main__":
    sys.exit(main())

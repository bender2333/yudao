# Scenario 3 Interface Agreement (appended after the PRD)

The PRD above leaves several interfaces open. This agreement is given to both sides together with the PRD. Names, argument orders and output wording not fixed here are decided by the implementing side.

## 1. Data file and modules
- The data file is named `subway_data.json` and is placed next to the source code. `DATA_FILE_PATH` in `data_loader` points to it.
- The code lives under `src/`. The required modules are `models`, `data_loader`, `pathfinding` and `fare_calculator`.
- `data_loader.DATA_FILE_PATH` is a path (string or `pathlib.Path`) to `subway_data.json`.
- `data_loader.load_subway_data(path)` reads the file at `path` and returns a dictionary with the keys `stations` and `connections`.
  - `stations` is a list of objects; each has `name` (string) and `lines` (list of line names).
  - `connections` is a list of objects; each has `source` (string), `dest` (string), `distance` (number, meters) and `line` (string).

## 2. `models`
- `Edge(source, dest, weight, line)`: a directed edge. `source` and `dest` are station numbers, `weight` is the distance in meters, `line` is the line name. The attributes are readable as `edge.source`, `edge.dest`, `edge.weight`, `edge.line`. Equality of two `Edge` values agrees on all four attributes.
- `Graph()`:
  - `add_edge(edge)` adds an edge. The graph is undirected: an added edge can be traversed in both directions.
  - `set_station_lines(station_name, lines)` records the line names of a station.
  - `station_lines` is a mapping from station name to its list of line names.
  - `adj(node)` returns the edges leaving `node`.
- `MinPQ()`: a minimum priority queue with `insert(item, priority)`, `del_min()` and `is_empty()`. `del_min` returns the item with the smallest priority.
- `PathfindingConfig()`: holds `mode` (string, default `"shortest_distance"`), `max_transfers` (integer or `None`, default `None`), `preferred_lines` (list of line names, default empty).

## 3. `pathfinding`
- `ShortestPath(graph, source, config=None)`: `source` is a station number. With no `config`, the mode is `shortest_distance`.
  - `dist_to` is a mapping from station number to distance in meters from `source`; a station that cannot be reached is absent or maps to infinity.
  - `path_with_edges(dest)` returns `(path_ids, edges)`: `path_ids` is the list of station numbers from `source` to `dest`, `edges` is the list of `Edge` used, with `len(edges) == len(path_ids) - 1`.
  - `get_transfer_count(dest)` returns the number of transfers (line changes) along the path to `dest`.
  - Modes: `shortest_distance` minimizes total distance; `least_transfer` minimizes the number of transfers; `comprehensive` minimizes a composite score that balances distance and transfers, with each transfer counted as an additional 1000 meters.
  - `max_transfers` limits the number of transfers: a path with more transfers than the limit does not exist in `dist_to`.
  - A preferred line is used when it exists along the route; several line names may be given.

## 4. `fare_calculator`
- `Sum_money(distance_meters)` returns the integer fare in yuan for the given distance in meters. The argument unit is meters. The tier rule is the left-closed, right-open rule of the PRD.
- `calculate_estimated_time(distance_meters, transfer_count)` returns the estimated travel time in minutes as an integer, using approximately 1.5 minutes per kilometer plus 5 minutes per transfer, with the result rounded to the nearest integer.

## 5. Program entry
- The entry point is `src/cli.py`, started with `python src/cli.py`.
- The CLI reads one query per line from standard input, in the format `Starting Station; Ending Station` (semicolon separator). After each query it prints the result and reads the next line; it exits at end of input.
- When it starts, the program prints the input format (for example `Starting Station; Ending Station`) before reading the first line. That line is a usage hint, not a query.
- Arguments: `--output_file PATH`, `--format text|json`, `--mode shortest_distance|least_transfer|comprehensive`, `--max_transfers N`, `--line_preference LINE`, `--check_data`.
- `--check_data` runs the data integrity check, prints the result and exits without reading a query.

## 6. Text export layout
The text export written by `--output_file PATH --format text` has this layout (blank line after the header, path lines grouped by line, then the summary):

```
--- Path Query Result ---
Start Station: <start>
End Station: <end>

Detailed Path:
  <Line X>: <station> → <station> → ... [Transfer Station]
  <Line Y>: <station> → <station> → ...

Total Distance: <meters> meters (<km> km)
Estimated Fare: <fare> yuan
Estimated Travel Time: <minutes> minutes
Transfer Count: <n> time
```

The last line uses `time` for one transfer and `times` for any other count.

`<km>` is the distance divided by 1000 with two decimals. The transfer station ends the line segment and is marked `[Transfer Station]`; the same station starts the next segment.

## 7. JSON export fields
The JSON export written by `--output_file PATH --format json` has these fields:

```json
{
  "query": {"start_station": "...", "end_station": "..."},
  "result": {
    "path": ["..."],
    "total_distance": 0,
    "fare": 0,
    "estimated_time": 0,
    "transfer_count": 0,
    "lines_involved": ["..."]
  }
}
```

`path` is the ordered list of station names from start to end. `total_distance` is in meters. `fare` is in yuan. `estimated_time` is in minutes. `transfer_count` is the number of line changes. `lines_involved` lists every line name used by the path.

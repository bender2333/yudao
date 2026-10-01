import heapq


class Edge:
    def __init__(self, source, dest, weight, line):
        self.source = source
        self.dest = dest
        self.weight = weight
        self.line = line

    def other(self, node):
        return self.dest if node == self.source else self.source

    def __eq__(self, other):
        if not isinstance(other, Edge):
            return NotImplemented
        return (self.source, self.dest, self.weight, self.line) == (
            other.source, other.dest, other.weight, other.line)

    def __hash__(self):
        return hash((self.source, self.dest, self.weight, self.line))

    def __repr__(self):
        return f"Edge({self.source}, {self.dest}, {self.weight}, {self.line!r})"


class MinPQ:
    def __init__(self):
        self._heap = []
        self._counter = 0

    def insert(self, item, priority):
        heapq.heappush(self._heap, (priority, self._counter, item))
        self._counter += 1

    def del_min(self):
        return heapq.heappop(self._heap)[2]

    def is_empty(self):
        return not self._heap


class PathfindingConfig:
    def __init__(self):
        self.mode = "shortest_distance"
        self.max_transfers = None
        self.preferred_lines = []


class Graph:
    def __init__(self):
        self.adjacency = {}
        self.station_lines = {}

    def add_edge(self, edge):
        self.adjacency.setdefault(edge.source, []).append(edge)
        reverse = Edge(edge.dest, edge.source, edge.weight, edge.line)
        self.adjacency.setdefault(edge.dest, []).append(reverse)

    def set_station_lines(self, station_name, lines):
        self.station_lines[station_name] = list(lines)

    def adj(self, node):
        return self.adjacency.get(node, [])

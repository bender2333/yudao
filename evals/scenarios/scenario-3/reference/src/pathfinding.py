import heapq

from models import PathfindingConfig

TRANSFER_PENALTY = 1000


def _score(mode, distance, transfers):
    if mode == "least_transfer":
        return (transfers, distance)
    if mode == "comprehensive":
        return (distance + transfers * TRANSFER_PENALTY, distance)
    return (distance, transfers)


class ShortestPath:
    def __init__(self, graph, source, config=None):
        self.graph = graph
        self.source = source
        self.config = config if config is not None else PathfindingConfig()
        self._run()

    def _line_preferred(self, line):
        return line in self.config.preferred_lines

    def _run(self):
        source = self.source
        mode = self.config.mode
        limit = self.config.max_transfers

        self.dist_to = {}
        self.transfers_to = {}
        self._prev = {}
        self.dist_to[source] = 0
        self.transfers_to[source] = 0

        # (cost, distance, transfers, node, incoming_line)
        queue = [(0, 0, 0, source, None)]
        while queue:
            cost, distance, transfers, node, line = heapq.heappop(queue)
            if cost > self._cost_of(node):
                continue
            for edge in self.graph.adj(node):
                if edge.dest == node:
                    continue
                next_transfers = transfers
                if line is not None and line != edge.line:
                    next_transfers += 1
                if limit is not None and next_transfers > limit:
                    continue
                next_distance = distance + edge.weight
                key = _score(mode, next_distance, next_transfers)
                if self._line_preferred(edge.line):
                    key = (key[0] - 1, key[1])
                current = self._key_of(edge.dest)
                if current is None or key < current:
                    self.dist_to[edge.dest] = next_distance
                    self.transfers_to[edge.dest] = next_transfers
                    self._prev[edge.dest] = (node, edge)
                    heapq.heappush(
                        queue, (key[0], next_distance, next_transfers, edge.dest, edge.line))

    def _key_of(self, node):
        if node not in self.dist_to:
            return None
        distance = self.dist_to[node]
        transfers = self.transfers_to[node]
        key = _score(self.config.mode, distance, transfers)
        incoming = self._prev.get(node)
        if incoming is not None and self._line_preferred(incoming[1].line):
            key = (key[0] - 1, key[1])
        return key

    def _cost_of(self, node):
        return self._key_of(node)[0]

    def path_with_edges(self, dest):
        if dest not in self.dist_to:
            return [], []
        path_ids = [dest]
        edges = []
        node = dest
        while node != self.source:
            previous, edge = self._prev[node]
            edges.append(edge)
            path_ids.append(previous)
            node = previous
        path_ids.reverse()
        edges.reverse()
        return path_ids, edges

    def get_transfer_count(self, dest):
        return self.transfers_to.get(dest, 0)

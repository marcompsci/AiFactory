"""The conveyor network as a directed graph, derived from the district configuration.

Every district has a dispatch terminal (packages leave) and a receiving terminal (packages arrive), both
at the district's gate. Spoke belts join them to a junction on a ring around the plaza; the ring runs in
both directions, so every pair of districts has two independent paths — which is what makes rerouting
around a failed belt possible.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

RING_RADIUS = 16.0
BELT_HEIGHT = 1.2
TERMINAL_SPREAD = 3.0


@dataclass(frozen=True)
class Node:
    id: str
    kind: str  # dispatch | receiving | junction
    district: str | None
    position: tuple[float, float, float]


@dataclass(frozen=True)
class Segment:
    id: str
    from_node: str
    to_node: str
    length: float


def gate(district: dict) -> tuple[float, float]:
    x, _, z = district["position"]
    if x == 0 and z == 0:
        return (0.0, 9.0)  # south, toward the Logistics Network hub; north belongs to the Owner's Tower
    return (x * 0.72, z * 0.72)


def _perp(x: float, z: float) -> tuple[float, float]:
    n = math.hypot(x, z) or 1.0
    return (-z / n, x / n)


def build(districts: list[dict]) -> tuple[list[Node], list[Segment]]:
    nodes: list[Node] = []
    segs: list[Segment] = []
    junctions: list[tuple[float, str]] = []
    for d in districts:
        gx, gz = gate(d)
        px, pz = _perp(gx, gz)
        dispatch = Node(f"{d['id']}:dispatch", "dispatch", d["id"], (gx + px * TERMINAL_SPREAD, BELT_HEIGHT, gz + pz * TERMINAL_SPREAD))
        receiving = Node(f"{d['id']}:receiving", "receiving", d["id"], (gx - px * TERMINAL_SPREAD, BELT_HEIGHT, gz - pz * TERMINAL_SPREAD))
        n = math.hypot(gx, gz) or 1.0
        jx, jz = gx / n * RING_RADIUS, gz / n * RING_RADIUS
        junction = Node(f"junction:{d['id']}", "junction", d["id"], (jx, BELT_HEIGHT, jz))
        nodes += [dispatch, receiving, junction]
        segs.append(_seg(dispatch, junction))
        segs.append(_seg(junction, receiving))
        junctions.append((math.atan2(jz, jx), junction.id))
    junctions.sort(key=lambda j: (round(j[0], 6), j[1]))
    pos = {n.id: n.position for n in nodes}
    for i, (_, a) in enumerate(junctions):
        b = junctions[(i + 1) % len(junctions)][1]
        segs.append(Segment(f"{a}->{b}", a, b, _dist(pos[a], pos[b])))
        segs.append(Segment(f"{b}->{a}", b, a, _dist(pos[a], pos[b])))
    return nodes, segs


def _dist(a, b) -> float:
    return round(math.hypot(a[0] - b[0], a[2] - b[2]), 3)


def _seg(a: Node, b: Node) -> Segment:
    return Segment(f"{a.id}->{b.id}", a.id, b.id, _dist(a.position, b.position))


def shortest_path(segments: list[dict], start: str, goal: str, cost=lambda s: s["length"]) -> list[dict] | None:
    """Dijkstra over UP segments. `cost` lets callers add congestion. Returns the ordered segments or None."""
    out: dict[str, list[dict]] = {}
    for s in segments:
        if s["status"] == "UP":
            out.setdefault(s["from_node"], []).append(s)
    best = {start: 0.0}
    prev: dict[str, dict] = {}
    heap = [(0.0, start)]
    while heap:
        d, node = heapq.heappop(heap)
        if node == goal:
            break
        if d > best.get(node, math.inf):
            continue
        for s in out.get(node, []):
            nd = d + cost(s)
            if nd < best.get(s["to_node"], math.inf):
                best[s["to_node"]] = nd
                prev[s["to_node"]] = s
                heapq.heappush(heap, (nd, s["to_node"]))
    if goal not in prev and goal != start:
        return None
    path = []
    node = goal
    while node != start:
        s = prev[node]
        path.append(s)
        node = s["from_node"]
    return list(reversed(path))

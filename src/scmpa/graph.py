"""Small deterministic graph utilities (no external dependencies)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def find_cycle(edges: Mapping[str, Iterable[str]]) -> list[str] | None:
    """Return one directed cycle as ``[n0, n1, ..., n0]``, or ``None`` if the graph is acyclic.

    Nodes that appear only as edge targets are handled. Traversal order is
    sorted, so the same graph always yields the same cycle.
    """
    adjacency: dict[str, list[str]] = {}
    for src, dsts in edges.items():
        adjacency.setdefault(src, [])
        for dst in dsts:
            adjacency[src].append(dst)
            adjacency.setdefault(dst, [])
    for src in adjacency:
        adjacency[src] = sorted(set(adjacency[src]))

    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(adjacency, white)
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = grey
        path.append(node)
        for nxt in adjacency[node]:
            if colour[nxt] == grey:
                return path[path.index(nxt):] + [nxt]
            if colour[nxt] == white and (found := visit(nxt)):
                return found
        path.pop()
        colour[node] = black
        return None

    for start in sorted(adjacency):
        if colour[start] == white and (found := visit(start)):
            return found
    return None


def stable_topological_order(n: int, edges: Iterable[tuple[int, int]]) -> list[int] | None:
    """Order nodes ``0..n-1`` so every edge ``(a, b)`` has ``a`` before ``b``.

    Among nodes that are ready, the lowest index goes first, so an already
    consistent order is left unchanged. Returns ``None`` if the edges are cyclic.
    """
    import heapq

    succ: dict[int, list[int]] = {i: [] for i in range(n)}
    indeg = [0] * n
    for a, b in set(edges):
        succ[a].append(b)
        indeg[b] += 1
    ready = [i for i in range(n) if indeg[i] == 0]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        i = heapq.heappop(ready)
        order.append(i)
        for j in succ[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                heapq.heappush(ready, j)
    return order if len(order) == n else None

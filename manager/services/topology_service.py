from itertools import combinations
from math import gcd, log2
from typing import Any

import networkx as nx

from manager.models.topology_models import TopologyConfig, TopologyType


def _nx_to_adj(G: nx.Graph) -> dict[int, list[int]]:
    return {i: sorted(G.neighbors(i)) for i in sorted(G.nodes())}


def exchange_target_count(adjacency: dict[int, list[int]], max_hops: int, mix_enabled: bool) -> int:
    if not mix_enabled:
        return len(adjacency.get(0, []))
    current = {0}
    for _ in range(max_hops):
        next_level = set()
        for node in current:
            next_level.update(adjacency.get(node, []))
        current = next_level
    current.discard(0)
    return len(current)


def generate_adjacency(
        n_nodes: int,
        config: TopologyConfig,
) -> dict[int, list[int]]:
    if config.topology_type == TopologyType.CIRCULANT:
        offsets, _ = compute_circulant_params(n_nodes, config.degree)
        return _nx_to_adj(nx.circulant_graph(n_nodes, offsets))

    if config.topology_type == TopologyType.RING_LATTICE:
        if config.degree % 2 != 0:
            raise ValueError("Ring lattice degree must be even")
        if config.degree >= n_nodes:
            raise ValueError("Ring lattice degree must be less than n")
        offsets = list(range(1, config.degree // 2 + 1))
        return _nx_to_adj(nx.circulant_graph(n_nodes, offsets))

    if config.topology_type == TopologyType.HYPERCUBE:
        if n_nodes < 4 or (n_nodes & (n_nodes - 1)) != 0:
            raise ValueError("Hypercube requires n to be a power of 2 and >= 4")
        dimension = int(log2(n_nodes))
        G = nx.convert_node_labels_to_integers(nx.hypercube_graph(dimension))
        return _nx_to_adj(G)

    return _nx_to_adj(nx.complete_graph(n_nodes))


def compute_circulant_params(n_nodes: int, degree: int) -> tuple[list[int], int]:
    half_degree = degree // 2
    offsets = _find_best_offsets(n_nodes, half_degree)
    if offsets is None:
        raise ValueError(f"No valid circulant graph exists for n={n_nodes}, degree={degree}")
    diameter = nx.diameter(nx.circulant_graph(n_nodes, offsets))
    return offsets, diameter


def _find_best_offsets(n: int, half_degree: int) -> list[int] | None:
    max_offset = (n - 1) // 2
    best_offsets, best_diameter = None, n
    evaluated = 0

    for offsets in combinations(range(1, max_offset + 1), half_degree):
        if gcd(n, *offsets) != 1:
            continue
        if n % 2 == 0 and len(set(s % 2 for s in offsets)) == 1:
            continue

        diameter = nx.diameter(nx.circulant_graph(n, offsets))
        if diameter < best_diameter:
            best_diameter = diameter
            best_offsets = list(offsets)

        if best_diameter <= 2:
            break

        evaluated += 1
        if evaluated >= 15000:
            break

    return best_offsets


def compute_topology_info(n_nodes: int, topology_type: str, degree: int = 4) -> dict[str, Any]:
    topology = TopologyType(topology_type)

    if topology == TopologyType.FULL_MESH:
        return {
            "valid": True,
            "degree": n_nodes - 1,
            "diameter": 1,
            "valid_node_counts": list(range(2, 101)),
        }

    if topology in (TopologyType.CIRCULANT, TopologyType.RING_LATTICE):
        if degree % 2 != 0 or degree >= n_nodes:
            return {"valid": False, "error": "Degree must be even and < n_nodes"}
        if topology == TopologyType.CIRCULANT:
            try:
                _, diameter = compute_circulant_params(n_nodes, degree)
            except ValueError as e:
                return {"valid": False, "error": str(e)}
        else:
            offsets = list(range(1, degree // 2 + 1))
            diameter = nx.diameter(nx.circulant_graph(n_nodes, offsets))
        return {
            "valid": True,
            "degree": degree,
            "diameter": diameter,
            "valid_node_counts": list(range(3, 101)),
        }

    if topology == TopologyType.HYPERCUBE:
        valid = n_nodes >= 4 and (n_nodes & (n_nodes - 1)) == 0
        if not valid:
            return {
                "valid": False,
                "error": "n must be a power of 2 and >= 4",
                "valid_node_counts": [4, 8, 16, 32],
            }
        dimension = int(log2(n_nodes))
        return {
            "valid": True,
            "degree": dimension,
            "diameter": dimension,
            "valid_node_counts": [4, 8, 16, 32],
        }

    return {"valid": False, "error": f"Unknown topology type: {topology_type}"}

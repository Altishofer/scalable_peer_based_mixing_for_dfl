from math import ceil, log2
from typing import Any

from manager.models.config_models import ExperimentConfig
from manager.models.topology_models import TopologyConfig, TopologyType
from manager.services.topology_service import (
    compute_topology_info,
    generate_adjacency,
)

MODEL_APPROX_PARAMS = {
    "lenet5": 62_000,
    "squeezenet": 727_000,
    "mobilenetv2": 2_230_000,
}

SPHINX_BODY_LEN = 10240
SPHINX_PACKET_SIZE = SPHINX_BODY_LEN + 192 + 37  # 10469 bytes (body + header + MAC)


def _reachable_at_hops(adj: dict[int, list], start: int, hops: int) -> set:
    current = {start}
    for _ in range(hops):
        next_level = set()
        for node in current:
            next_level.update(adj.get(node, []))
        current = next_level

    current.discard(start)
    return current


def _chunk_capacity(bytes_per_chunk: int, quantize: bool) -> int:
    metadata_bytes = 8 if quantize else 0
    entry_bytes = 1 if quantize else 4
    return max(1, (bytes_per_chunk - metadata_bytes) // entry_bytes)


def compute_indicators(config: ExperimentConfig) -> dict[str, Any]:
    n = config.n_nodes

    topo_info = compute_topology_info(n, config.topology_type, config.graph_degree)
    if not topo_info.get("valid", True):
        return {"error": topo_info["error"]}
    degree = topo_info.get("degree", n - 1)
    diameter = topo_info.get("diameter", 1)

    topo_config = TopologyConfig(
        topology_type=TopologyType(config.topology_type),
        degree=config.graph_degree,
    )

    adj = generate_adjacency(n, topo_config)

    if config.mix_enabled and n > 1:
        reachable = _reachable_at_hops(adj, 0, config.max_hops)
        exchange_peers = len(reachable) if reachable else degree
    else:
        exchange_peers = degree

    outbox_size = config.mix_outbox_size
    max_hops = config.max_hops

    if config.mix_enabled:
        # path entropy is log2 of the total number of paths summed over 1..K hops
        total_paths = sum(outbox_size ** k for k in range(1, max_hops + 1))
        path_entropy = log2(total_paths) if total_paths > 0 else 0.0

        if max_hops > 1 and outbox_size > 0:
            p_forward = (max_hops - 1) / (max_hops * outbox_size)
            p_absorb = 1.0 / max_hops

            entropy = 0.0
            if p_forward > 0:
                entropy -= outbox_size * p_forward * log2(p_forward)
            if p_absorb > 0:
                entropy -= p_absorb * log2(p_absorb)
            relay_entropy = entropy
        else:
            relay_entropy = log2(outbox_size) if outbox_size > 1 else 0.0

        anon_set = len(_reachable_at_hops(adj, 0, max_hops)) if n > 1 else 0
    else:
        path_entropy = 0.0
        relay_entropy = 0.0
        anon_set = 0

    model_params = MODEL_APPROX_PARAMS.get(config.model_name, 62_000)
    quantize = config.quantization_bits == 8
    bytes_per_chunk = SPHINX_BODY_LEN - 512
    capacity = _chunk_capacity(bytes_per_chunk, quantize)
    fragments = ceil(model_params / capacity)

    redundancy = config.partial_update_ratio
    effective_peers = max(1, round(exchange_peers * redundancy))
    messages_per_node = fragments * effective_peers
    total_messages = messages_per_node * n
    bytes_per_round = total_messages * SPHINX_BODY_LEN

    mix_mu = config.mix_mu

    if config.mix_enabled:
        send_rate = 1.0 / mix_mu
        bandwidth_per_node = int(send_rate * SPHINX_PACKET_SIZE)
        mix_cycle_time = outbox_size * mix_mu
        theoretical_rtt_lower_bound = 2 * config.max_hops * mix_cycle_time
        outbox_cycles = ceil(messages_per_node / outbox_size) if outbox_size > 0 else 0
        total_packets_per_node = outbox_cycles * outbox_size
        total_bytes_network = total_packets_per_node * n * max_hops * SPHINX_PACKET_SIZE
    else:
        send_rate = 0.0
        bandwidth_per_node = 0
        mix_cycle_time = 0.0
        theoretical_rtt_lower_bound = 0.0
        total_packets_per_node = 0
        total_bytes_network = 0

    has_attack = config.attack_type != "none"
    byzantine_fraction = config.n_byzantine / n if n > 0 else 0.0

    if config.aggregation_algorithm == "krum":
        krum_safe = byzantine_fraction <= config.krum_byzantine_fraction
    else:
        krum_safe = not has_attack

    return {
        "topology": {
            "degree": degree,
            "diameter": diameter,
            "exchange_peers": exchange_peers,
            "adjacency": {str(k): v for k, v in adj.items()},
        },
        "anonymity": {
            "path_entropy_bits": round(path_entropy, 1),
            "relay_entropy_bits": round(relay_entropy, 1),
            "anonymity_set_size": anon_set,
            "mix_enabled": config.mix_enabled,
        },
        "communication": {
            "fragments_per_model": fragments,
            "model_params": model_params,
            "messages_per_node": messages_per_node,
            "total_messages": total_messages,
            "bytes_per_round": bytes_per_round,
            "partial_update_ratio": redundancy,
            "sphinx_payload_size": SPHINX_BODY_LEN,
            "sphinx_packet_size": SPHINX_PACKET_SIZE,
        },
        "mixnet_traffic": {
            "mix_enabled": config.mix_enabled,
            "send_rate": round(send_rate, 2),
            "bandwidth_per_node": bandwidth_per_node,
            "mix_cycle_time": round(mix_cycle_time, 2),
            "theoretical_rtt_lower_bound": round(theoretical_rtt_lower_bound, 2),
            "total_packets_per_node": total_packets_per_node,
            "total_bytes_network": total_bytes_network,
        },
        "robustness": {
            "has_attack": has_attack,
            "byzantine_fraction": round(byzantine_fraction, 2),
            "krum_safe": krum_safe,
            "aggregation": config.aggregation_algorithm,
        },
    }

import logging

import numpy as np
import torch
import torch.optim as optim
from scipy.spatial.distance import cdist

from learning.chunk_codec import decode_dense_chunk
from utils.config_store import ConfigStore

DEFAULT_LR = 1e-3
DEFAULT_WEIGHT_DECAY = 1e-4


def _log_aggregation_stats(part_hits: np.ndarray, algorithm: str = "FedAvg"):
    nonzero_parts = part_hits > 0
    hits_per_part = part_hits[nonzero_parts]
    if algorithm != "FedAvg":
        logging.info(f"Aggregation: {algorithm}")
    logging.info(f"Max fragments received for a part: {hits_per_part.max() if hits_per_part.size else 0}")
    logging.info(f"Min fragments received for a part: {hits_per_part.min() if hits_per_part.size else 0}")
    logging.info(
        f"Avg fragments per part: {hits_per_part.mean():.2f}" if hits_per_part.size else "Avg fragments per part: 0.00"
    )


class Aggregator:
    def __init__(self, model: torch.nn.Module, flatten_fn, unflatten_fn):
        self._model = model
        self._flatten = flatten_fn
        self._unflatten = unflatten_fn

    def aggregate(self, model_chunks: list):
        if ConfigStore.aggregation_algorithm == "krum":
            return self._aggregate_krum(model_chunks)
        return self._aggregate_fedavg(model_chunks)

    def _reset_optimizer(self):
        return optim.Adam(self._model.parameters(), lr=DEFAULT_LR, weight_decay=DEFAULT_WEIGHT_DECAY)

    def _init_accumulators(self):
        # local model always counts as the first contribution
        local = self._flatten()
        flat = np.zeros_like(local, dtype=np.float32)
        counter = np.zeros_like(local, dtype=np.int32)
        flat += local
        counter += 1

        part_hits = np.zeros_like(local, dtype=np.int32)
        return local, flat, counter, part_hits

    def _aggregate_fedavg(self, model_chunks: list):
        _, flat, counter, part_hits = self._init_accumulators()

        for chunk in model_chunks:
            start, end = chunk["start"], chunk["end"]
            array = decode_dense_chunk(chunk)
            flat[start:end] += array
            counter[start:end] += 1
            part_hits[start:end] += 1

        np.divide(flat, counter, out=flat, casting="unsafe")
        self._unflatten(flat)
        optimizer = self._reset_optimizer()

        _log_aggregation_stats(part_hits)
        return optimizer

    def _aggregate_krum(self, model_chunks: list):
        local, flat, counter, part_hits = self._init_accumulators()

        groups = {}
        for chunk in model_chunks:
            start, end = chunk["start"], chunk["end"]
            array = decode_dense_chunk(chunk)
            groups.setdefault((start, end), []).append(array)
            part_hits[start:end] += 1

        for (start, end), peer_arrays in groups.items():
            local_fragment = local[start:end]
            all_fragments = [local_fragment] + peer_arrays
            n = len(all_fragments)

            if n <= 2:
                flat[start:end] = np.mean(all_fragments, axis=0)
                counter[start:end] = 1
                continue

            f = max(0, int(ConfigStore.krum_byzantine_fraction * n))
            f = min(f, (n - 3) // 2)

            stacked = np.stack(all_fragments)
            dist_sq = cdist(stacked, stacked, metric="sqeuclidean")

            k = n - f - 2
            sorted_dists = np.sort(dist_sq, axis=1)
            scores = np.sum(sorted_dists[:, 1:k + 1], axis=1)

            best_idx = np.argmin(scores)
            flat[start:end] = stacked[best_idx]
            counter[start:end] = 1

        self._unflatten(flat)
        optimizer = self._reset_optimizer()

        _log_aggregation_stats(part_hits, f"Krum (byzantine_fraction={ConfigStore.krum_byzantine_fraction})")
        return optimizer

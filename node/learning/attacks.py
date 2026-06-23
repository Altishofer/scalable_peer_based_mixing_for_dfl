import numpy as np
from torch import Tensor

from utils.config_store import ConfigStore


def is_byzantine() -> bool:
    return ConfigStore.n_byzantine > 0 and ConfigStore.node_id >= ConfigStore.n_nodes - ConfigStore.n_byzantine


def flip_labels(labels: Tensor, num_classes: int) -> Tensor:
    return (num_classes - 1) - labels


def gaussian_noise(flat_weights: np.ndarray, node_id: int, round_num: int) -> np.ndarray:
    rng = np.random.default_rng(seed=node_id * 10000 + round_num)
    sigma = ConfigStore.attack_noise_sigma * float(np.std(flat_weights))
    noise = rng.normal(0.0, sigma, size=flat_weights.shape).astype(np.float32)
    return flat_weights + noise


def sign_flip(flat_weights: np.ndarray) -> np.ndarray:
    return -flat_weights


def apply_weight_attack(flat_weights: np.ndarray, node_id: int, round_num: int) -> np.ndarray:
    if not is_byzantine():
        return flat_weights
    if ConfigStore.attack_type == "gaussian_noise":
        return gaussian_noise(flat_weights, node_id, round_num)
    if ConfigStore.attack_type == "sign_flip":
        return sign_flip(flat_weights)
    return flat_weights

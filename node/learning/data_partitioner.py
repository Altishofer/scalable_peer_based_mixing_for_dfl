import contextlib
import logging
import os

import numpy as np
import torch
from torchvision import datasets, transforms

from utils.config_store import ConfigStore
from utils.logging_config import log_header

DATASET_CONFIG = {
    "mnist": {
        "cls": datasets.MNIST,
        "in_channels": 1,
        "num_classes": 10,
        "crop_size": 28,
        "norm_mean": [0.5],
        "norm_std": [0.5],
    },
    "cifar10": {
        "cls": datasets.CIFAR10,
        "in_channels": 3,
        "num_classes": 10,
        "crop_size": 32,
        "norm_mean": [0.4914, 0.4822, 0.4465],
        "norm_std": [0.2470, 0.2435, 0.2616],
    },
    "fashion_mnist": {
        "cls": datasets.FashionMNIST,
        "in_channels": 1,
        "num_classes": 10,
        "crop_size": 28,
        "norm_mean": [0.5],
        "norm_std": [0.5],
    },
}


def get_dataset_config() -> dict:
    name = ConfigStore.dataset
    return DATASET_CONFIG[name]


def load_partition(node_id: int, total_peers: int):
    log_header("Dataset")

    global_seed = 42
    torch.manual_seed(global_seed)
    np.random.seed(global_seed)

    ds_cfg = DATASET_CONFIG[ConfigStore.dataset]
    data_root = os.path.join(os.environ.get("DATA_ROOT", "/data"), ConfigStore.dataset)

    train_transform = transforms.Compose(
        [
            transforms.RandomRotation(10),
            transforms.RandomCrop(ds_cfg["crop_size"], padding=4),
            transforms.ToTensor(),
            transforms.Normalize(mean=ds_cfg["norm_mean"], std=ds_cfg["norm_std"]),
        ]
    )

    val_transform = transforms.Compose(
        [
            transforms.ToTensor(),
            transforms.Normalize(mean=ds_cfg["norm_mean"], std=ds_cfg["norm_std"]),
        ]
    )

    with open(os.devnull, "w") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            train_dataset = ds_cfg["cls"](root=data_root, train=True, transform=train_transform, download=False)

            val_dataset = ds_cfg["cls"](root=data_root, train=False, transform=val_transform, download=False)

    targets = torch.as_tensor(train_dataset.targets).detach().clone()
    indices_by_class = {int(c): (targets == c).nonzero(as_tuple=True)[0] for c in range(ds_cfg["num_classes"])}

    logging.info(f"Dirichlet alpha = {ConfigStore.dirichlet_alpha}")
    alpha = torch.full((total_peers,), float(ConfigStore.dirichlet_alpha), dtype=torch.float32)
    dirichlet = torch.distributions.Dirichlet(alpha)

    node_indices = []

    for class_label, class_indices in indices_by_class.items():
        class_indices = class_indices[torch.randperm(class_indices.size(0))]

        proportions = dirichlet.sample()
        counts = torch.floor(proportions * len(class_indices)).long()
        counts[-1] = len(class_indices) - counts[:-1].sum()

        start = 0
        for peer_id, count in enumerate(counts):
            end = start + count.item()
            if peer_id == node_id:
                node_indices.append(class_indices[start:end])
            start = end

    node_indices = torch.cat(node_indices)
    node_indices = node_indices[torch.randperm(node_indices.size(0))]

    train_subset = torch.utils.data.Subset(train_dataset, node_indices.tolist())

    train_loader = torch.utils.data.DataLoader(
        dataset=train_subset, batch_size=ConfigStore.batch_size, shuffle=True, num_workers=0
    )

    val_loader = torch.utils.data.DataLoader(
        dataset=val_dataset, batch_size=ConfigStore.batch_size, shuffle=False, num_workers=0
    )

    n_train_batches = len(train_loader)
    n_val_batches = len(val_loader)

    logging.info(f"Batch Size: {ConfigStore.batch_size}")
    logging.info(f"Validation Batches: {n_val_batches}")
    logging.info(f"Training Batches {n_train_batches}")

    return train_loader, val_loader, n_train_batches, n_val_batches

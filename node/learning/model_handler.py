import asyncio
import logging
import os
import secrets
import warnings

import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.exceptions import ConvergenceWarning

from learning.aggregator import Aggregator, DEFAULT_LR, DEFAULT_WEIGHT_DECAY
from learning.attacks import is_byzantine, flip_labels, apply_weight_attack
from learning.chunk_codec import create_chunks as _create_chunks
from learning.data_partitioner import get_dataset_config, load_partition
from learning.model_registry import create_model
from utils.config_store import ConfigStore
from utils.exception_decorator import log_exceptions

os.environ["TORCH_CPP_LOG_LEVEL"] = "WARNING"
warnings.filterwarnings("ignore", category=ConvergenceWarning)


def _deprioritize_current_thread():
    os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))


class ModelHandler:
    def __init__(self, node_id, total_peers):
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        dataset_config = get_dataset_config()
        self._num_classes = dataset_config["num_classes"]

        torch.manual_seed(42)
        self._model = create_model(
            ConfigStore.model_name, in_channels=dataset_config["in_channels"], num_classes=dataset_config["num_classes"]
        ).to(self._device)

        param_count = sum(p.numel() for p in self._model.parameters())
        logging.info(f"Model: {ConfigStore.model_name} | Parameters: {param_count:,}")

        self._loss_fn = nn.CrossEntropyLoss()
        self._optimizer = optim.Adam(self._model.parameters(), lr=DEFAULT_LR, weight_decay=DEFAULT_WEIGHT_DECAY)

        self._train_loader, self._val_loader, self._n_train_batches, self._n_val_batches = load_partition(
            node_id, total_peers
        )
        self._aggregator = Aggregator(self._model, self._flatten_state_dict, self._unflatten_state_dict)

    @log_exceptions
    async def train(self):
        def train_batches():
            _deprioritize_current_thread()
            n_batches = min(ConfigStore.n_batches_per_round, self._n_train_batches)
            logging.info(f"Training on {n_batches} of {self._n_train_batches} batches")
            self._model.train()
            is_label_flip = ConfigStore.attack_type == "label_flip" and is_byzantine()

            selected_batches = set(secrets.SystemRandom().sample(range(self._n_train_batches), n_batches))
            for i, (Xb, yb) in enumerate(self._train_loader):
                if i not in selected_batches:
                    continue
                Xb, yb = Xb.to(self._device), yb.to(self._device)
                if is_label_flip:
                    yb = flip_labels(yb, self._num_classes)
                self._optimizer.zero_grad()
                loss = self._loss_fn(self._model(Xb), yb)
                loss.backward()
                self._optimizer.step()

        await asyncio.to_thread(train_batches)

    @log_exceptions
    async def evaluate(self):
        logging.info(f"Validating on {len(self._val_loader)} batches")
        self._model.eval()

        def evaluate_batches():
            _deprioritize_current_thread()
            correct = total = 0
            with torch.no_grad():
                for Xb, yb in self._val_loader:
                    Xb, yb = Xb.to(self._device), yb.to(self._device)
                    pred = self._model(Xb)
                    correct += (pred.argmax(1) == yb).sum().item()
                    total += yb.size(0)
            return correct / total

        accuracy = await asyncio.to_thread(evaluate_batches)
        return round(accuracy, 3)

    async def aggregate(self, model_chunks):
        self._optimizer = await asyncio.to_thread(self._aggregator.aggregate, model_chunks)

    @log_exceptions
    async def create_chunks(self, bytes_per_chunk=None, current_round=0):
        flat = self._flatten_state_dict()
        flat = apply_weight_attack(flat, ConfigStore.node_id, current_round)
        return _create_chunks(flat, bytes_per_chunk)

    def _flatten_state_dict(self):
        tensors = [
            t.detach().cpu().float().view(-1)
            for k, t in self._model.state_dict().items()
            if "num_batches_tracked" not in k
        ]
        return torch.cat(tensors).numpy()

    def _unflatten_state_dict(self, flat):
        flat_tensor = torch.from_numpy(flat)
        new_state = {}
        offset = 0
        for key, tensor in self._model.state_dict().items():
            if "num_batches_tracked" in key:
                new_state[key] = tensor.clone()
                continue
            numel = tensor.numel()
            new_state[key] = flat_tensor[offset:offset + numel].view(tensor.shape).to(tensor.dtype)
            offset += numel
        self._model.load_state_dict(new_state)
        return self._model.state_dict()

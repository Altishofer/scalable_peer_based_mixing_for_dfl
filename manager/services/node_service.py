import asyncio
import contextlib
import datetime
import logging
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import torchvision.datasets as tv_datasets

from manager.config import settings

SUPPORTED_DATASETS = {
    "mnist": tv_datasets.MNIST,
    "cifar10": tv_datasets.CIFAR10,
    "fashion_mnist": tv_datasets.FashionMNIST,
}

from manager.models.config_models import ExperimentConfig, FullNodeConfig
from manager.models.schemas import NodeStatus
from manager.models.topology_models import TopologyConfig, TopologyType
from manager.services.metrics_service import metrics_service
from manager.services.topology_service import generate_adjacency
from manager.utils.docker_utils import get_docker_client, generate_keys, stop_all_nodes

logger = logging.getLogger(__name__)

NODE_TIMEOUT_SECONDS = 5


class NodeService:
    def __init__(self):
        self._client = get_docker_client()
        self._known_nodes: set[str] = set()
        self._nodes_lock = threading.Lock()

    async def start_nodes(self, config: ExperimentConfig) -> None:
        await asyncio.to_thread(stop_all_nodes)
        await metrics_service.drain_write_queue()
        await asyncio.to_thread(self._start_nodes_sync, config)

    def _start_nodes_sync(self, config: ExperimentConfig) -> None:
        with self._nodes_lock:
            self._known_nodes.clear()

        generate_keys(config.n_nodes)

        dataset_dir = os.path.join(settings.DATA_PATH, config.dataset)
        os.makedirs(dataset_dir, exist_ok=True)
        dataset_cls = SUPPORTED_DATASETS[config.dataset]
        logger.info(f"Pre-downloading {config.dataset} to {dataset_dir}")
        with open(os.devnull, "w") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                dataset_cls(root=dataset_dir, train=True, download=True)
                dataset_cls(root=dataset_dir, train=False, download=True)

        topology_config = TopologyConfig(
            topology_type=TopologyType(config.topology_type),
            degree=config.graph_degree,
        )
        adjacency = generate_adjacency(
            config.n_nodes,
            topology_config,
        )

        join_round = math.ceil(0.3 * config.n_rounds) if config.n_join_late > 0 else 0
        exit_round = math.floor(0.5 * config.n_rounds) if config.n_exit_early > 0 else 0
        join_schedule = {i: join_round for i in range(config.n_join_late)}
        exit_schedule = {config.n_join_late + i: exit_round for i in range(config.n_exit_early)}

        peer_endpoints = {i: ("127.0.0.1", settings.QUIC_BASE_PORT + i) for i in range(config.n_nodes)}

        oversubscribed = config.n_nodes > settings.NODE_CORES
        node_core_range = f"{settings.HOST_RESERVED_CORES}-{settings.HOST_RESERVED_CORES + settings.NODE_CORES - 1}"

        def _launch(i: int) -> None:
            name = f"node_{i}"
            with self._nodes_lock:
                self._known_nodes.add(name)
            full_config = FullNodeConfig(
                node_id=i,
                neighbors=adjacency[i],
                topology=adjacency,
                join_schedule=join_schedule,
                exit_schedule=exit_schedule,
                peer_endpoints=peer_endpoints,
                controller_url=settings.MGR_URL,
                **config.model_dump(),
            )
            container = self._client.containers.create(
                settings.IMAGE_NAME,
                name=name,
                environment=full_config.to_env_dict(),
                volumes={
                    settings.SECRETS_PATH: {"bind": "/config/", "mode": "ro"},
                    settings.NODE_PATH: {"bind": "/node", "mode": "ro"},
                    settings.DATA_PATH: {"bind": "/data", "mode": "ro"},
                },
                init=True,
                network_mode="host",
                cpuset_cpus=(node_core_range if oversubscribed else str(settings.HOST_RESERVED_CORES + i)),
            )
            container.start()

        with ThreadPoolExecutor(max_workers=min(config.n_nodes, 16)) as executor:
            futures = [executor.submit(_launch, i) for i in range(config.n_nodes)]
            for future in futures:
                future.result()

    async def stop_nodes(self) -> None:
        await asyncio.to_thread(stop_all_nodes)
        with self._nodes_lock:
            self._known_nodes.clear()
        await metrics_service.clear_last_seen()

    async def get_status(self) -> list[NodeStatus]:
        last_seen = await metrics_service.get_last_seen()
        first_seen = await metrics_service.get_first_seen()
        round_per_node = await metrics_service.get_round_per_node()
        now = datetime.datetime.now(datetime.UTC)

        with self._nodes_lock:
            all_nodes = set(self._known_nodes) | set(last_seen.keys())

        status = []
        for node_name in sorted(all_nodes):
            node_last_seen = last_seen.get(node_name)
            node_first_seen = first_seen.get(node_name)

            if node_last_seen:
                time_since_last_seen = (now - node_last_seen).total_seconds()
                if time_since_last_seen <= NODE_TIMEOUT_SECONDS:
                    node_status = "running"
                else:
                    node_status = "off"
            else:
                node_status = "off"

            started_at_str = node_first_seen.isoformat() if node_first_seen else ""

            status.append(
                NodeStatus(
                    name=node_name,
                    status=node_status,
                    started_at=started_at_str,
                    current_round=round_per_node.get(node_name, 0),
                )
            )

        return status


node_service = NodeService()

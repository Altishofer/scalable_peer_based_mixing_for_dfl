import asyncio
import csv
import datetime
import logging
import os
from collections import deque
from pathlib import Path

import docker.errors

from manager.config import settings
from manager.models.config_models import ExperimentConfig
from manager.models.schemas import MetricPoint
from manager.utils.docker_utils import get_docker_client

logger = logging.getLogger(__name__)

MAX_HISTORY_SIZE = 5_000_000

CGROUP_BASE = "/sys/fs/cgroup/system.slice"


def _read_container_resources(container_id: str) -> tuple[float, float] | None:
    scope = f"{CGROUP_BASE}/docker-{container_id}.scope"
    try:
        with open(f"{scope}/cpu.stat") as cpu_file:
            usage_usec = None
            for line in cpu_file:
                if line.startswith("usage_usec "):
                    usage_usec = int(line.split()[1])
                    break
        if usage_usec is None:
            return None

        with open(f"{scope}/memory.current") as memory_file:
            memory_bytes = int(memory_file.read().strip())
    except (FileNotFoundError, ValueError, PermissionError):
        return None

    cpu_value = (usage_usec * 1000) / 10e9
    mem_value = round(memory_bytes / (1024 * 1024), 2)
    return cpu_value, mem_value


class MetricsService:
    def __init__(self):
        self._running = False
        self._client = get_docker_client()
        self._write_queue = asyncio.Queue()
        self._experiment_config = None

        self._metrics_cache: deque[MetricPoint] = deque()
        self._last_seen: dict[str, datetime.datetime] = {}
        self._first_seen: dict[str, datetime.datetime] = {}
        self._highest_round: int = 0
        self._round_per_node: dict[str, int] = {}
        self._lock = asyncio.Lock()

        self._resource_cache: dict[str, tuple[float, float]] = {}
        self._name_to_id: dict[str, str] = {}

        self._history: deque[MetricPoint] = deque(maxlen=MAX_HISTORY_SIZE)

    def set_experiment_config(self, config: ExperimentConfig) -> None:
        self._experiment_config = config

    async def start_collecting(self, experiment_config: ExperimentConfig | None = None) -> None:
        if not self._running:
            self._running = True
            if experiment_config is not None:
                self._experiment_config = experiment_config
            asyncio.create_task(self._collect_loop())

    async def stop_collecting(self):
        self._running = False

    async def push(self, new_metrics: list[MetricPoint]) -> list[MetricPoint]:
        resource_points: list[MetricPoint] = []
        pushed_nodes = {m.node for m in new_metrics if m.node}
        push_timestamp = new_metrics[-1].timestamp if new_metrics else None
        for node_name in pushed_nodes:
            container_id = self._name_to_id.get(node_name)
            if container_id is None:
                continue
            cached = self._resource_cache.get(container_id)
            if cached is None:
                continue
            cpu_value, mem_value = cached
            resource_points.append(
                MetricPoint(
                    timestamp=push_timestamp,
                    field="cpu_total_ns",
                    name="CPU (ns)",
                    unit="ns",
                    group="Resources",
                    value=cpu_value,
                    node=node_name,
                )
            )
            resource_points.append(
                MetricPoint(
                    timestamp=push_timestamp,
                    field="memory_mb",
                    name="Mem (MB)",
                    unit="MB",
                    group="Resources",
                    value=mem_value,
                    node=node_name,
                )
            )
        new_metrics = list(new_metrics) + resource_points

        async with self._lock:
            self._metrics_cache.extend(new_metrics)
            now = datetime.datetime.now(datetime.UTC)
            for metric in new_metrics:
                if metric.node:
                    self._last_seen[metric.node] = now
                    if metric.node not in self._first_seen:
                        self._first_seen[metric.node] = now
                if metric.field == "current_round":
                    round_value = int(metric.value)
                    if round_value > self._highest_round:
                        self._highest_round = round_value
                    if metric.node:
                        prev = self._round_per_node.get(metric.node, 0)
                        if round_value > prev:
                            self._round_per_node[metric.node] = round_value
        await self.enqueue_metrics(new_metrics)
        for metric in new_metrics:
            self._history.append(metric)
        return new_metrics

    async def pop_all_metrics(self) -> list[MetricPoint]:
        async with self._lock:
            items = list(self._metrics_cache)
            self._metrics_cache.clear()
            return items

    async def get_highest_round(self) -> int:
        async with self._lock:
            return self._highest_round

    async def get_round_per_node(self) -> dict[str, int]:
        async with self._lock:
            return dict(self._round_per_node)

    async def all_completed(self) -> bool:
        config = self._experiment_config
        if config is None:
            return False

        exit_ids = {config.n_join_late + i for i in range(config.n_exit_early)}
        expected = [i for i in range(config.n_nodes) if i not in exit_ids]
        async with self._lock:
            return all(self._round_per_node.get(f"node_{i}", 0) > config.n_rounds for i in expected)

    async def get_history_paginated(self, offset: int = 0, limit: int = 50000) -> dict:
        total = len(self._history)
        history_list = list(self._history)
        offset = max(0, min(offset, total))
        end = min(offset + limit, total)
        return {
            "metrics": [m.model_dump() for m in history_list[offset:end]],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": end < total,
        }

    async def clear(self, output_dir: Path | None = None) -> None:
        await self.save_to_csv(output_dir)
        async with self._lock:
            self._metrics_cache.clear()
            self._highest_round = 0
            self._round_per_node.clear()
            self._resource_cache.clear()
            self._name_to_id.clear()
        self._history.clear()
        logger.info("Metrics cleared")

    async def save_to_csv(self, output_dir: Path | None = None):
        try:
            if self._write_queue.empty():
                logger.info("No metrics to save.")
                return

            target_dir = output_dir or settings.METRICS_DIR
            os.makedirs(target_dir, exist_ok=True)

            filename = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d_%H-%M-%S_metrics.csv")
            path = target_dir / filename

            with open(path, mode="w", newline="") as file:
                if self._experiment_config is not None:
                    file.write("#" + str(self._experiment_config.model_dump()) + "\n")
                else:
                    file.write("#no config available\n")

                writer = csv.writer(file)
                writer.writerow(["timestamp", "field", "value", "node"])

                while not self._write_queue.empty():
                    metric = await self._write_queue.get()
                    writer.writerow([metric.timestamp, metric.field, metric.value, metric.node])

        except Exception as e:
            logger.error(f"Failed to save metrics to CSV: {e}")

    async def get_last_seen(self) -> dict[str, datetime.datetime]:
        async with self._lock:
            return dict(self._last_seen)

    async def get_first_seen(self) -> dict[str, datetime.datetime]:
        async with self._lock:
            return dict(self._first_seen)

    async def clear_last_seen(self) -> None:
        async with self._lock:
            self._last_seen.clear()
            self._first_seen.clear()
            self._round_per_node.clear()

    async def enqueue_metrics(self, metrics: list[MetricPoint]) -> None:
        for metric in metrics:
            self._write_queue.put_nowait(metric)

    async def drain_write_queue(self) -> None:
        while not self._write_queue.empty():
            try:
                self._write_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _collect_loop(self):
        while self._running:
            try:
                await self._refresh_cache()
            except Exception as e:
                logger.debug("Metrics collection cycle failed: %s", e)
            await asyncio.sleep(settings.METRICS_INTERVAL)

    async def _refresh_cache(self) -> None:
        if self._client is None:
            return
        try:
            containers = await asyncio.to_thread(self._client.containers.list)
            active_nodes = [c for c in containers if c.name.startswith("node_")]
        except (docker.errors.DockerException, OSError):
            return

        self._name_to_id = {node.name: node.id for node in active_nodes}

        live_ids = {node.id for node in active_nodes}
        for stale_id in list(self._resource_cache.keys()):
            if stale_id not in live_ids:
                del self._resource_cache[stale_id]

        for container in active_nodes:
            result = _read_container_resources(container.id)
            if result is not None:
                self._resource_cache[container.id] = result


metrics_service = MetricsService()

import asyncio
import logging
import random
import time
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any

import aiohttp

from utils.config_store import ConfigStore


class MetricField(Enum):
    TOTAL_MSG_SENT = ("total_sent", "Msgs Sent", "msgs", "Communication")
    TOTAL_MSG_RECEIVED = ("total_received", "Msgs Received", "msgs", "Communication")
    TOTAL_MBYTES_SENT = ("total_mbytes_sent", "MB Sent", "MB", "Communication")
    TOTAL_MBYTES_RECEIVED = ("total_mbytes_received", "MB Received", "MB", "Communication")
    UNACKED_MSG = ("unacked_msg", "Unacked Frags", "frags", "Communication")
    RESENT = ("resent", "Frags Resent", "frags", "Communication")
    RECEIVED_DUPLICATE_MSG = ("received_duplicate_msg", "Dup Msgs", "msgs", "Communication")
    AVG_RTT = ("avg_rtt", "Avg RTT", "ms", "Communication")
    LAST_RTT = ("last_rtt", "Last RTT", "ms", "Communication")
    AVG_MSG_PER_SECOND = ("avg_msg_per_second", "Msg/sec", "msgs/s", "Communication")

    FRAGMENTS_SENT = ("fragments_sent", "Frags Sent", "frags", "Model Exchange")
    FRAGMENTS_RECEIVED = ("fragments_received", "Frags Received", "frags", "Model Exchange")
    FRAGMENT_COMPLETENESS = ("fragment_completeness", "Frag Completeness", "%", "Model Exchange")
    ACTIVE_PEERS = ("active_peers", "Peers", "prs", "Model Exchange")
    PEER_REACHABLE = ("peer_reachable", "Peer Reachable", "state", "Model Exchange")

    FORWARDED = ("forwarded", "Msgs Fwd", "msgs", "Mixnet")
    SURB_REPLIED = ("surb_replied", "SURBs Replied", "SURBs", "Mixnet")
    SURB_RECEIVED = ("surb_received", "SURBs Received", "SURBs", "Mixnet")
    COVERS_SENT = ("covers_sent", "Covers Sent", "covs", "Mixnet")
    COVERS_RECEIVED = ("covers_received", "Covers Received", "covs", "Mixnet")
    PROBES_SENT = ("probes_sent", "Probes Sent", "prbs", "Mixnet")
    PROBES_RECEIVED = ("probes_received", "Probes Received", "prbs", "Mixnet")
    SENDING_COVERS = ("sending_covers", "Sending Covers", "covs", "Mixnet")
    SENDING_MESSAGES = ("sending_messages", "Sending Msgs", "msgs", "Mixnet")
    QUEUED_PACKAGES = ("queued_packages", "Queued Pkgs", "pkgs", "Mixnet")
    OUT_INTERVAL = ("out_interval", "Queue Intvl", "s", "Mixnet")
    SENDING_TIME = ("sending_time", "Sending Time", "s", "Mixnet")
    TOTAL_OUT_INTERVAL = ("total_out_interval", "Total Outbox Intvl", "s", "Mixnet")
    DRIFT_RESETS = ("drift_resets", "Drift Resets", "resets", "Mixnet")
    DEAD_HOP_DROPS = ("dead_hop_drops", "Dead First-Hop Drops", "", "Mixnet")

    TRAINING_ACCURACY = ("accuracy", "Accuracy", "%", "Learning")
    AGGREGATED_ACCURACY = ("aggregated_accuracy", "Agg Accuracy", "%", "Learning")
    CURRENT_ROUND = ("current_round", "Round", "rnds", "Learning")
    ROUND_TIME = ("round_time", "Round Time", "s", "Learning")
    # stage codes: 0 bootstrap, 1 train, 2 local eval, 3 broadcast/forward/collect, 4 global eval
    STAGE = ("stage", "Stage", "stgs", "Learning")

    ERRORS = ("errors", "Errors", "errs", "Miscellaneous")
    DELETED_CACHE_FOR_INACTIVE = ("deleted_cache_for_inactive", "Cache Deleted", "items", "Miscellaneous")

    def __init__(self, key: str, display_name: str, unit: str, group: str):
        self._key = key
        self._display_name = display_name
        self._unit = unit
        self._group = group

    @property
    def key(self) -> str:
        return self._key

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def unit(self) -> str:
        return self._unit

    @property
    def group(self) -> str:
        return self._group

    @property
    def value(self) -> str:
        return self._key


_metrics_instance = None


def init_metrics(controller_url: str, host_name: str):
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = Metrics(controller_url, host_name)
    return _metrics_instance


def metrics():
    if _metrics_instance is None:
        raise RuntimeError("Metrics not initialized. Call init_metrics() first.")
    return _metrics_instance


class Metrics:
    def __init__(self, controller_url: str, host_name: str):
        self._data: dict[MetricField, int | str | float] = {field: 0 for field in MetricField}
        self._data[MetricField.PEER_REACHABLE] = "{}"  # JSON snapshot, replaced by PeerNode
        self._data_lock = Lock()
        self._change_log: deque = deque()
        self._controller_url = controller_url
        self._host = host_name
        self._start_time = 0
        self._push_task = None

    def start_push_loop(self):
        # call from inside the event loop
        if self._controller_url and self._push_task is None:
            self._push_task = asyncio.create_task(self._push_loop())

    async def stop_push_loop(self):
        if self._push_task is None:
            return
        # final push so the last round's metrics aren't lost when the loop is cancelled
        self.set_message_frequency()
        self._flush_metrics()
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5),
        ) as session:
            await self._push_metrics(session)
        self._push_task.cancel()
        try:
            await self._push_task
        except asyncio.CancelledError:
            pass
        self._push_task = None

    def increment(self, field: MetricField, amount: int = 1):
        if (field == MetricField.TOTAL_MSG_SENT and self._start_time == 0):
            self._start_time = time.time()
        with self._data_lock:
            self._data[field] += amount

    def decrement(self, field: MetricField, amount: int = 1):
        with self._data_lock:
            if field in self._data:
                self._data[field] -= amount
                if self._data[field] < 0:
                    self._data[field] = 0

    def set(self, field: MetricField, value: int | str | float):
        with self._data_lock:
            self._data[field] = value

    def _flush_metrics(self):
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self._data_lock:
            updates = [{
                "timestamp": timestamp,
                "field": field.key,
                "name": field.display_name,
                "unit": field.unit,
                "group": field.group,
                "value": value,
                "node": self._host
            } for field, value in self._data.items()]
            self._change_log = deque(updates)

    def get_all(self) -> dict[str, Any]:
        with self._data_lock:
            return {field.value: value for field, value in self._data.items()}

    async def _push_loop(self):
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                self.set_message_frequency()
                self._flush_metrics()
                await self._push_metrics(session)
                await asyncio.sleep(ConfigStore.push_metric_interval * random.uniform(0.5, 1.5))

    def set_message_frequency(self):
        if self._start_time == 0:
            return
        elapsed_time = time.time() - self._start_time
        frequency = self._data[MetricField.TOTAL_MSG_SENT] / elapsed_time
        self.set(MetricField.AVG_MSG_PER_SECOND, frequency)

    async def _push_metrics(self, session):
        with self._data_lock:
            if not self._change_log:
                return
            payload = list(self._change_log)
        try:
            async with session.post(
                    f"{self._controller_url}/metrics/push",
                    json=payload,
            ) as response:
                if response.status == 200:
                    with self._data_lock:
                        self._change_log.clear()
                else:
                    text = await response.text()
                    logging.warning(f"Push failed: {response.status} - {text}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logging.warning(f"Push exception: {type(e).__name__}: {e}")

    async def wait_for_round(self, round_number: int, poll_interval: float = 3):
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(
                            f"{self._controller_url}/metrics/highest-round",
                            timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if response.status == 200:
                            round_status = await response.json()
                            highest_round = round_status.get("highest_round", 0)
                            if highest_round >= round_number:
                                logging.info(f"Awaited round reached: {round_number}")
                                return
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logging.warning(f"Error polling highest-round: {e}")

                await asyncio.sleep(poll_interval)

import asyncio
import collections
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from scipy.stats import truncnorm

from metrics.node_metrics import metrics, MetricField
from utils.config_store import ConfigStore
from utils.exception_decorator import log_exceptions
from utils.logging_config import log_header

if TYPE_CHECKING:
    from communication.cover_generator import CoverGenerator


@dataclass
class QueueObject:
    send_message: Awaitable
    update_metrics: Callable
    next_hop: int | None = None


class Mixer:
    def __init__(
            self,
            is_live,
            cover_generator: "CoverGenerator | None" = None,
    ):
        self._outbox = []
        self._queue = collections.deque()
        self._cover_generator = cover_generator
        self._is_live = is_live
        self._outbox_loop_task = None
        self._next_send = None
        self._running = False
        self._intervals = []

    @staticmethod
    def secure_truncated_normal(mu, sigma, a=0.0):
        b = mu + 3 * sigma
        uniform_sample = secrets.SystemRandom().random()
        lower, upper = (a - mu) / sigma, (b - mu) / sigma
        return truncnorm.ppf(uniform_sample, lower, upper, loc=mu, scale=sigma)

    def _generate_interval_batch(self) -> list[float]:
        size = ConfigStore.mix_outbox_size
        return [Mixer.secure_truncated_normal(ConfigStore.mix_mu, ConfigStore.mix_std) for _ in range(size)]

    def _next_interval(self) -> float:
        if not self._intervals:
            self._intervals = self._generate_interval_batch()
        return self._intervals.pop()

    @log_exceptions
    async def _outbox_loop(self):
        self._next_send = asyncio.get_running_loop().time()
        while self._running:
            try:
                self._update_outbox()

                if not self.outbox_is_empty():
                    queue_obj = self._outbox.pop()
                    asyncio.create_task(self._dispatch(queue_obj))

                now = asyncio.get_running_loop().time()
                interval = self._next_interval()
                self._next_send += interval

                # only reset on >1 tick of drift
                drift = now - self._next_send
                if drift > interval:
                    missed = int(drift / interval) if interval > 0 else 0
                    self._next_send = now + interval
                    metrics().increment(MetricField.DRIFT_RESETS)
                    logging.debug(f"Mixer: drift of {missed} ticks ({drift * 1000:.1f}ms), resetting clock")

                sleep_time = max(0, self._next_send - now)
                metrics().set(MetricField.OUT_INTERVAL, sleep_time)
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break
            except Exception:
                logging.exception("Mixer: Error in outbox loop")
                await asyncio.sleep(ConfigStore.mix_mu)
        logging.info("Outbox loop exited")

    async def _dispatch(self, queue_obj):
        next_hop = queue_obj.next_hop
        if next_hop is not None and not self._is_live(next_hop):
            metrics().increment(MetricField.DEAD_HOP_DROPS)
            return
        try:
            await queue_obj.send_message()
            queue_obj.update_metrics()
        except Exception:
            logging.exception("Mixer: dispatch failed")

    async def start(self):
        if ConfigStore.mix_enabled:
            self._running = True
            self._outbox_loop_task = asyncio.create_task(self._outbox_loop())
            log_header("Peer-Based Mixer")
            logging.info(f"Enabled: {ConfigStore.mix_enabled}")
            logging.info(f"Shuffle: {ConfigStore.mix_shuffle}")
            logging.info(f"N Cover Bytes: {ConfigStore.nr_cover_bytes}")
        else:
            logging.info("Mixer disabled")

    async def stop(self):
        self._running = False
        if self._outbox_loop_task is not None:
            self._outbox_loop_task.cancel()
            try:
                await self._outbox_loop_task
            except asyncio.CancelledError:
                pass

    def _update_outbox(self):
        if not self.outbox_is_empty():
            return

        for _ in range(ConfigStore.mix_outbox_size):
            if not self.queue_is_empty():
                self._outbox.append(self._queue.popleft())
            elif self._cover_generator is not None:
                popped = self._cover_generator.pop_cover()
                if popped is not None:
                    cover, next_hop = popped
                    self._outbox.append(
                        QueueObject(
                            send_message=cover,
                            update_metrics=partial(self._update_message_metric, True),
                            next_hop=next_hop,
                        )
                    )

        if ConfigStore.mix_shuffle:
            self._shuffle_outbox()

    def _shuffle_outbox(self):
        n = len(self._outbox)
        for i in range(n):
            j = i + secrets.randbelow(n - i)
            self._outbox[i], self._outbox[j] = self._outbox[j], self._outbox[i]

    async def queue_item(self, msg_coroutine: Awaitable, update_metrics: Callable, next_hop: int | None = None):
        queue_obj = QueueObject(
            send_message=msg_coroutine,
            update_metrics=partial(self._run_message_metrics, update_metrics),
            next_hop=next_hop,
        )

        if ConfigStore.mix_enabled:
            self._queue.append(queue_obj)
            metrics().set(MetricField.QUEUED_PACKAGES, len(self._queue))
        else:
            start = asyncio.get_running_loop().time()
            await queue_obj.send_message()
            queue_obj.update_metrics()
            metrics().set(MetricField.SENDING_TIME, asyncio.get_running_loop().time() - start)

    def outbox_is_empty(self):
        return len(self._outbox) == 0

    def queue_is_empty(self):
        return len(self._queue) == 0

    def _run_message_metrics(self, update_metrics):
        update_metrics()
        self._update_message_metric(False)

    def _update_message_metric(self, sending_covers):
        metrics().set(MetricField.SENDING_COVERS, 1 if sending_covers else 0)
        metrics().set(MetricField.SENDING_MESSAGES, 0 if sending_covers else 1)

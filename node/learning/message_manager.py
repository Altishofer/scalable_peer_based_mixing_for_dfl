import asyncio
import logging
import time
from typing import TYPE_CHECKING

from communication.packages import format_model_package
from learning.model_handler import ModelHandler
from metrics.node_metrics import MetricField, metrics
from utils.config_store import ConfigStore
from utils.exception_decorator import log_exceptions

if TYPE_CHECKING:
    from communication.message_store import MessageStore
    from communication.sphinx.sphinx_transport import SphinxTransport

PHASE2_GRACE = 5.0


class MessageManager:
    def __init__(
        self,
        transport: "SphinxTransport",
        store: "MessageStore",
        model_handler: ModelHandler,
    ):
        self._transport = transport
        self._store = store
        self._model_handler = model_handler

    @log_exceptions
    async def send_model_updates(self, current_round):
        chunks = await self._model_handler.create_chunks(current_round=current_round)
        n_chunks = len(chunks)
        self._transport.set_fragments_per_model(n_chunks)
        n_probed = await self._transport.send_probes()
        if n_probed:
            logging.info(f"Round {current_round}: probed {n_probed} unreachable peer(s)")
        await self._broadcast_all(current_round, chunks, n_chunks)

    async def _broadcast_all(self, current_round, chunks, n_chunks):
        n_peers = 0
        for chunk_idx in range(n_chunks):
            n_peers = await self.send_model_chunk(current_round, chunk_idx, chunks[chunk_idx], n_chunks)
        logging.info(f"Sent {n_chunks} model chunks to {n_peers} peers.")

    async def send_model_chunk(self, current_round, chunk_idx, chunk, n_chunks):
        msg = format_model_package(current_round, chunk_idx, chunk, n_chunks)
        return await self._transport.send_to_peers(msg)

    async def await_fragments(self, round_id: int):
        start_time = time.time()
        last_count = 0
        last_progress = start_time

        poll_interval = 0.5

        while True:
            if await self._transport.received_all_expected_fragments(round_id):
                break

            current = self._store.incoming_count(round_id)
            expected = self._transport.expected_fragment_count()

            if current > last_count:
                last_count = current
                last_progress = time.time()
            elif (
                expected > 0
                and (time.time() - last_progress) > ConfigStore.stall_timeout
                and (ConfigStore.partial_update_ratio < 1.0 or current / expected >= ConfigStore.completeness_floor)
            ):
                logging.info(f"Round {round_id}: finalizing at {current}/{expected} after stall")
                return

            await asyncio.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.5, 5.0)

        grace_deadline = time.time() + PHASE2_GRACE
        while time.time() < grace_deadline:
            if await self._transport.transport_all_acked():
                logging.info(f"All fragments and SURBs received after {int(time.time() - start_time)}s")
                return
            await asyncio.sleep(0.5)

        logging.info(
            f"Round complete after {int(time.time() - start_time)}s; "
            "some SURBs still in flight (resend manager handles them)"
        )

    @log_exceptions
    async def collect_models(self, round_id: int):
        expected_count = self._transport.expected_fragment_count()
        reachable_peers = self._transport.exchange_peer_count()

        fragments = self._store.drain_round(round_id)
        fragment_contents = [msg["content"] for msg in fragments]

        completeness = (len(fragment_contents) / expected_count * 100) if expected_count > 0 else 0.0
        metrics().set(MetricField.FRAGMENT_COMPLETENESS, completeness)
        logging.info(
            f"Aggregating {len(fragment_contents)} parts ({completeness:.1f}% of expected {expected_count}) "
            f"from {reachable_peers} reachable peer(s)"
        )
        return fragment_contents

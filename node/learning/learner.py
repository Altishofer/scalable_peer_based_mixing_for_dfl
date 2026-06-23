import asyncio
import logging
import time
from typing import TYPE_CHECKING

from learning.message_manager import MessageManager
from learning.model_handler import ModelHandler
from metrics.node_metrics import metrics, MetricField
from utils.config_store import ConfigStore
from utils.exception_decorator import log_exceptions
from utils.logging_config import log_header

if TYPE_CHECKING:
    from communication.message_store import MessageStore
    from communication.sphinx.sphinx_transport import SphinxTransport


class Learner:
    def __init__(self, node_config: ConfigStore, transport: "SphinxTransport", store: "MessageStore"):
        self._node_id = node_config.node_id
        self._transport = transport
        self._store = store
        self._total_peers = node_config.n_nodes
        self._total_rounds = node_config.n_rounds
        self._join_round = node_config.my_join_round()
        self._exit_round = node_config.my_exit_round()
        self._current_round = self._join_round - 1 if self._join_round > 0 else 0
        self._model_handler = ModelHandler(self._node_id, self._total_peers)
        self._message_manager = MessageManager(
            transport,
            store,
            self._model_handler,
        )

    @log_exceptions
    async def run(self):
        aggregated_accuracy = 0.0
        start_time = time.time()
        first_iteration = True

        missing = await self._transport.wait_until_mesh_healthy(timeout=90.0)
        if missing:
            peers = sorted(missing)
            logging.warning(
                f"Activation: {len(peers)} neighbor(s) without a transport link, "
                f"proceeding anyway: {peers[:10]}{'...' if len(peers) > 10 else ''}"
            )

        while self._current_round < self._total_rounds:
            self._current_round += 1
            metrics().set(MetricField.CURRENT_ROUND, self._current_round)
            self._store.set_current_round(self._current_round)

            if first_iteration and self._join_round > 0:
                self._store.clear_rounds_before(self._current_round)
            first_iteration = False

            if self._exit_round > 0 and self._current_round > self._exit_round:
                logging.info(f"Exiting after round {self._exit_round} (schedule)")
                break

            log_header(f"ROUND {self._current_round}")

            if self._join_round > 0 and self._current_round < self._join_round:
                logging.info(f"Idling until join round {self._join_round} (current: {self._current_round})")
                await asyncio.sleep(1)
                continue

            if not ConfigStore.pause_training:
                await self._train_model()
                await self._broadcast_model_updates()
                await self._validate_local_model(aggregated_accuracy)

            await self._await_model_chunks()

            aggregated_accuracy = await self._aggregate_and_validate_models(aggregated_accuracy)

            self._log_round_end(start_time)
            start_time = time.time()

        logging.info(f"Completed training ({self._current_round} rounds)")

    async def _train_model(self):
        log_header("Start Training")
        metrics().set(MetricField.STAGE, 1)
        await self._model_handler.train()
        logging.info("Finished Training")

    async def _validate_local_model(self, aggregated_accuracy: float):
        log_header("Local Model Validation Accuracy")
        metrics().set(MetricField.STAGE, 2)
        accuracy = await self._model_handler.evaluate()
        logging.info(f"acc {aggregated_accuracy:.2f} -> {accuracy:.2f} ({accuracy - aggregated_accuracy:+.2f})")
        metrics().set(MetricField.TRAINING_ACCURACY, accuracy)

    async def _broadcast_model_updates(self):
        log_header("Broadcasting Model Updates")
        await self._message_manager.send_model_updates(self._current_round)

    async def _await_model_chunks(self):
        log_header("Awaiting Model Chunks from Peers.")
        metrics().set(MetricField.STAGE, 3)
        await self._message_manager.await_fragments(round_id=self._current_round)

    async def _aggregate_and_validate_models(self, aggregated_accuracy: float) -> float:
        model_chunks = await self._message_manager.collect_models(self._current_round)
        if not model_chunks:
            logging.warning(f"Round {self._current_round}: zero fragments received, retaining local model")
        log_header(f"Aggregating {len(model_chunks)} Model Chunks.")
        await self._model_handler.aggregate(model_chunks)

        log_header("Aggregated Model Validation Accuracy")
        metrics().set(MetricField.STAGE, 4)
        accuracy = await self._model_handler.evaluate()
        metrics().set(MetricField.STAGE, 0)
        logging.info(f"acc {aggregated_accuracy:.2f} -> {accuracy:.2f} ({accuracy - aggregated_accuracy:+.2f})")
        metrics().set(MetricField.AGGREGATED_ACCURACY, accuracy)

        return accuracy

    def _log_round_end(self, start_time: float):
        log_header(f"Finished Round {self._current_round}")
        elapsed_time = time.time() - start_time
        logging.info(f"Finished in {elapsed_time:.0f}s")
        metrics().set(MetricField.ROUND_TIME, elapsed_time)
        self._store.end_round(self._current_round)

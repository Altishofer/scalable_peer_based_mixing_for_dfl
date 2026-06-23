import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TYPE_CHECKING

from communication.peer_session import PeerState
from metrics.node_metrics import metrics, MetricField
from utils.config_store import ConfigStore
from utils.exception_decorator import log_exceptions

if TYPE_CHECKING:
    from communication.mixing import Mixer
    from communication.message_store import MessageStore
    from communication.peer_session import PeerSession
    from communication.sphinx.sphinx_router import SphinxRouter

MAX_RESENDS = 1

SendFn = Callable[[int, bytes], Awaitable[None]]


class ResendManager:
    def __init__(
            self,
            sessions: "dict[int, PeerSession]",
            sphinx_router: "SphinxRouter",
            mixer: "Mixer",
            send_fn: SendFn,
            message_store: "MessageStore",
            check_interval: float = 5.0,
    ):
        self._sessions = sessions
        self._sphinx_router = sphinx_router
        self._mixer = mixer
        self._send_fn = send_fn
        self._message_store = message_store
        self._check_interval = check_interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._resend_loop())
        logging.info("ResendManager: Started resend monitoring loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logging.info("ResendManager: Stopped resend monitoring loop")

    async def _resend_loop(self) -> None:
        while True:
            try:
                resent_count = await self._resend_stale()
                if resent_count > 0:
                    logging.warning(f"ResendManager: Resent {resent_count} unacked fragments")
                await asyncio.sleep(self._check_interval + secrets.SystemRandom().uniform(0, 1))
            except asyncio.CancelledError:
                break
            except Exception:
                logging.exception("ResendManager: Error in resend loop")
                await asyncio.sleep(self._check_interval + secrets.SystemRandom().uniform(0, 1))

    @log_exceptions
    async def _resend_stale(self) -> int:
        # don't resend if no inbound yet this round, forward path may be down
        store = self._message_store
        if not store.round_had_intake(store.current_round):
            return 0

        resent = 0
        for session in self._sessions.values():
            if session.state == PeerState.UNREACHABLE:
                continue
            stale = session.get_stale_fragments(ConfigStore.resend_time)
            flipped = False
            for fragment in stale:
                # stale but no inbound for this round, mixnet wasn't up, no one received anything, skip
                if fragment.round is not None and not self._message_store.round_had_intake(fragment.round):
                    fragment.pending_resend = False
                    continue
                # peer is still acking, missing SURB is maybe in-flight not loss, so wait
                if session.acked_since_last_send(fragment.payload_hash):
                    fragment.pending_resend = False
                    continue
                if session.get_retry_count(fragment.payload_hash) >= MAX_RESENDS:
                    session.record_resend_exhausted(fragment.payload_hash)
                    flipped = True
                    break

                path, msg_bytes, timestamp_callback, _, _ = await self._sphinx_router.create_forward_msg(
                    fragment.target_node,
                    fragment.payload,
                    cover=fragment.is_cover,
                    payload_hash=fragment.payload_hash,
                    round_id=fragment.round,
                )

                send_task = partial(self._send_fragment, path, msg_bytes, timestamp_callback)
                update_metrics_task = partial(metrics().increment, MetricField.RESENT)
                await self._mixer.queue_item(send_task, update_metrics_task, next_hop=path[0])

                session.bump_retry_count(fragment.payload_hash)
                resent += 1

            if flipped:
                logging.warning(
                    f"ResendManager: peer {session.peer_id} flipped to UNREACHABLE after K-resend exhaustion"
                )

        return resent

    async def _send_fragment(self, path: list, msg_bytes: bytes, timestamp_callback: Callable | None) -> None:
        if timestamp_callback is not None:
            timestamp_callback()
        await self._send_fn(path[0], msg_bytes)

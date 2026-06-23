import asyncio
import logging
import secrets
from collections.abc import Callable, Coroutine
from functools import partial
from typing import TYPE_CHECKING

from communication.packages import format_cover_package, serialize_msg
from communication.peer_session import PeerState
from utils.config_store import ConfigStore

if TYPE_CHECKING:
    from communication.mixing import Mixer
    from communication.peer_session import PeerSession
    from communication.sphinx.sphinx_router import SphinxRouter
    from communication.quic_server import QuicServer

CoverTaskFactory = Callable[[], Coroutine[None, None, None]]


class CoverGenerator:
    def __init__(
            self,
            sphinx_router: "SphinxRouter",
            transport_server: "QuicServer",
            sessions: "dict[int, PeerSession]",
            mixer: "Mixer | None" = None,
    ):
        self._sphinx_router = sphinx_router
        self._transport_server = transport_server
        self._sessions = sessions
        self._mixer = mixer

        self._cover_stash: list[tuple[CoverTaskFactory, int]] = []
        self._stash_loop_task: asyncio.Task | None = None

    async def start(self) -> None:
        if ConfigStore.cache_covers:
            self._stash_loop_task = asyncio.create_task(self._generate_cover_loop())
            logging.info("CoverGenerator: Started cover stash loop")

    def pop_cover(self) -> tuple[CoverTaskFactory, int] | None:
        if self._cover_stash:
            return self._cover_stash.pop()
        return None

    def invalidate_stash(self) -> None:
        stash_count = len(self._cover_stash)
        self._cover_stash.clear()
        if stash_count > 0:
            logging.info(f"CoverGenerator: Invalidated {stash_count} stashed covers")

    async def stop(self) -> None:
        if self._stash_loop_task is not None:
            self._stash_loop_task.cancel()
            try:
                await self._stash_loop_task
            except asyncio.CancelledError:
                pass
            logging.info("CoverGenerator: Stopped cover stash loop")

    async def _generate_cover(self) -> tuple[CoverTaskFactory, int] | None:
        target_node = self._select_random_peer()
        if target_node is None:
            return None

        content = secrets.token_bytes(ConfigStore.nr_cover_bytes)
        payload = format_cover_package(content)
        serialized = serialize_msg(payload)

        path, msg_bytes, _, _, tracking_info = await self._sphinx_router.create_forward_msg(
            target_node, serialized, cover=True, defer_tracking=True, make_surb=False
        )

        return (partial(self._send_cover, path, msg_bytes, tracking_info), path[0])

    async def _send_cover(self, path: list, msg_bytes: bytes, tracking_info: dict) -> None:
        surb_id = tracking_info["surb_id"]
        if surb_id is not None:
            session = self._sessions[tracking_info["target_node"]]
            session.track_outbound(
                surb_id=surb_id,
                surb_key_tuple=tracking_info["surb_key_tuple"],
                payload=tracking_info["payload"],
                is_cover=tracking_info["is_cover"],
                payload_hash=tracking_info["payload_hash"],
            )
            session.mark_sent(surb_id)
        await self._transport_server.send_to_peer(path[0], msg_bytes)

    def _select_random_peer(self) -> int | None:
        # match exchange targets, exclude UNREACHABLE but keep PENDING
        candidates = [
            peer_id
            for peer_id in self._sphinx_router.get_exchange_targets(ConfigStore.node_id)
            if self._sessions[peer_id].state != PeerState.UNREACHABLE
        ]
        if not candidates:
            logging.warning(
                f"CoverGenerator[{ConfigStore.node_id}]: No cover targets available "
                f"(mix_enabled={ConfigStore.mix_enabled}, max_hops={ConfigStore.max_hops})"
            )
            return None
        return secrets.choice(candidates)

    async def _generate_cover_loop(self) -> None:
        while True:
            try:
                while len(self._cover_stash) < ConfigStore.max_cover_cache:
                    item = await self._generate_cover()
                    if item is not None:
                        self._cover_stash.append(item)
                    else:
                        await asyncio.sleep(1)
                        break
                    await asyncio.sleep(ConfigStore.mix_mu)

                await asyncio.sleep(
                    ConfigStore.max_cover_cache / ConfigStore.mix_outbox_size * ConfigStore.mix_mu * 1 / 2
                )

            except asyncio.CancelledError:
                break
            except Exception:
                logging.exception("Error in cover stash loop")
                await asyncio.sleep(1)

import asyncio
import json
import logging

import aiohttp

from communication.cover_generator import CoverGenerator
from communication.message_store import MessageStore
from communication.packet_router import PacketRouter
from communication.peer_session import PeerSession, PeerState
from communication.resend_manager import ResendManager
from communication.sphinx.sphinx_transport import SphinxTransport
from learning.learner import Learner
from metrics.node_metrics import metrics, MetricField
from utils.config_store import ConfigStore


class PeerNode:
    def __init__(self, node_config: ConfigStore):
        self._node_id = node_config.node_id

        if node_config.neighbors:
            neighbor_ids = node_config.neighbors
        else:
            neighbor_ids = [i for i in range(node_config.n_nodes) if i != node_config.node_id]

        neighbor_peers = {i: node_config.peer_endpoints[i] for i in neighbor_ids}
        own_port = node_config.peer_endpoints[node_config.node_id][1]
        topology = node_config.topology

        session_ids = set(neighbor_ids)
        if topology:
            session_ids.update(pid for pid in topology if pid != node_config.node_id)
        self._sessions: dict[int, PeerSession] = {pid: PeerSession(pid) for pid in session_ids}

        my_join_round = ConfigStore.my_join_round()
        for peer_id, session in self._sessions.items():
            if ConfigStore.join_schedule.get(peer_id, 0) <= my_join_round:
                session.state = PeerState.REACHABLE
        self._message_store = MessageStore()

        self._transport = SphinxTransport(
            node_config.node_id,
            own_port,
            neighbor_peers,
            message_store=self._message_store,
            sessions=self._sessions,
            neighbors=neighbor_ids,
            topology=topology,
        )

        self._packet_router = PacketRouter(
            node_id=node_config.node_id,
            params=self._transport.params,
            sphinx_router=self._transport.sphinx_router,
            message_store=self._message_store,
            sessions=self._sessions,
            sphinx_transport=self._transport,
        )

        self._cover_generator = CoverGenerator(
            sphinx_router=self._transport.sphinx_router,
            transport_server=self._transport.server,
            sessions=self._sessions,
            mixer=self._transport.mixer,
        )

        self._transport.set_cover_generator(self._cover_generator)

        self._resend_manager = ResendManager(
            sessions=self._sessions,
            sphinx_router=self._transport.sphinx_router,
            mixer=self._transport.mixer,
            send_fn=self._transport.server.send_to_peer,
            message_store=self._message_store,
        )

        self._shutting_down = False
        self._snapshot_task: asyncio.Task | None = None
        self._learning = Learner(node_config, self._transport, self._message_store)

        self._transport.quic_server.set_packet_router(self._packet_router)
        self._transport.quic_server.set_peer_node(self)

    def _snapshot_peer_states(self) -> None:
        snapshot = {str(peer_id): session.state.value for peer_id, session in self._sessions.items()}
        metrics().set(MetricField.PEER_REACHABLE, json.dumps(snapshot))

    def sensed_unreachable(self, peer_id: int) -> bool:
        session = self._sessions.get(peer_id)
        return session is not None and session.state == PeerState.UNREACHABLE

    def mark_peer_unreachable(self, peer_id: int) -> None:
        session = self._sessions.get(peer_id)
        if session is not None:
            session.state = PeerState.UNREACHABLE

    async def _snapshot_loop(self) -> None:
        while not self._shutting_down:
            try:
                self._snapshot_peer_states()
                await asyncio.sleep(ConfigStore.push_metric_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logging.exception("PeerNode: snapshot loop error")
                await asyncio.sleep(1)

    async def _await_run_completion(self):
        url = f"{ConfigStore.controller_url}/metrics/all-completed"
        loop = asyncio.get_running_loop()

        # 30min cap so a stuck run can't pin this relay forever
        deadline = loop.time() + 1800
        timeout = aiohttp.ClientTimeout(total=5)
        while loop.time() < deadline:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as response:
                        if response.status == 200 and (await response.json()).get("completed"):
                            return
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(5)
        logging.warning(f"PeerNode {self._node_id} completion barrier hit the liveness cap")

    async def start(self):
        logging.info(f"PeerNode {self._node_id} starting...")
        await self._transport.start()
        await self._cover_generator.start()
        await self._resend_manager.start()
        self._snapshot_peer_states()
        self._snapshot_task = asyncio.create_task(self._snapshot_loop())

        try:
            await self._learning.run()
            if ConfigStore.my_exit_round() == 0:
                metrics().set(MetricField.CURRENT_ROUND, ConfigStore.n_rounds + 1)
                await self._await_run_completion()
        finally:
            self._shutting_down = True
            self._snapshot_peer_states()

            if self._snapshot_task is not None:
                self._snapshot_task.cancel()
                try:
                    await self._snapshot_task
                except asyncio.CancelledError:
                    pass
            logging.info(f"PeerNode {self._node_id} shutting down gracefully...")
            await metrics().stop_push_loop()
            await self._resend_manager.stop()
            await self._cover_generator.stop()
            await asyncio.sleep(2)
            await self._transport.close_all_connections()

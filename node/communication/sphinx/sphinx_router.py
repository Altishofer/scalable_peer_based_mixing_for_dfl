import asyncio
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor

from sphinxmix.SphinxClient import (
    create_forward_message,
    PFdecode,
    Nenc,
    pack_message,
    unpack_message,
    create_surb,
    package_surb,
    receive_surb,
)
from sphinxmix.SphinxNode import sphinx_process

from communication.peer_session import PeerSession, PeerState, find_surb_key
from communication.sphinx.key_store import KeyStore
from utils.config_store import ConfigStore
from utils.exception_decorator import log_exceptions


class SphinxRouter:
    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sphinx_crypto")

    def close(self):
        self._executor.shutdown(wait=False)

    def __init__(self, node_id, params, sessions: dict[int, PeerSession], is_live, topology: dict = None):
        self._max_hops = ConfigStore.max_hops
        self._node_id = node_id
        self._params = params
        self._sessions = sessions
        self._is_live = is_live
        self._key_store = KeyStore()
        self._topology = topology or {}
        self._reachable_cache = {}
        self._path_pool = {}  # (src, dst) -> [path, ...]
        if self._topology:
            self._build_path_pool()
            self._verify_topology()

    @log_exceptions
    def router_all_acked(self) -> bool:
        return all(session.all_acked() for session in self._sessions.values())

    @log_exceptions
    async def create_forward_msg(
            self,
            target_node,
            payload,
            cover,
            payload_hash: bytes | None = None,
            defer_tracking: bool = False,
            n_hops: int | None = None,
            round_id: int | None = None,
            make_surb: bool = True,
    ):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self._executor,
            self._create_forward_msg_sync,
            target_node,
            payload,
            cover,
            payload_hash,
            defer_tracking,
            n_hops,
            round_id,
            make_surb,
        )

        if defer_tracking:
            path, msg_bytes, surb_id, surb_key_tuple = result
            tracking_info = {
                "surb_id": surb_id,
                "surb_key_tuple": surb_key_tuple,
                "target_node": target_node,
                "payload": payload,
                "is_cover": cover,
                "payload_hash": payload_hash,
            }
            return path, msg_bytes, None, None, tracking_info
        else:
            path, msg_bytes, surb_id, returned_hash = result
            session = self._sessions[target_node]
            timestamp_callback = lambda sid=surb_id, s=session: s.mark_sent(sid)
            return path, msg_bytes, timestamp_callback, returned_hash, None

    def _create_forward_msg_sync(
            self,
            target_node,
            payload,
            cover,
            payload_hash: bytes | None = None,
            defer_tracking: bool = False,
            n_hops: int | None = None,
            round_id: int | None = None,
            make_surb: bool = True,
    ):
        path, nodes_routing, keys_nodes = self.build_forward_path(target_node, n_hops=n_hops)

        if make_surb:
            _, nodes_routing_back, keys_nodes_back = self.build_surb_reply_path(target_node)
            surb_id, surb_key_tuple, nymtuple = self.create_and_store_surb(nodes_routing_back, keys_nodes_back)
        else:
            surb_id, surb_key_tuple, nymtuple = None, None, None
        header, delta = self.create_forward_packet(nodes_routing, keys_nodes, nymtuple, payload)
        msg_bytes = pack_message(self._params, (header, delta))

        if defer_tracking:
            return path, msg_bytes, surb_id, surb_key_tuple
        else:
            returned_hash = self._sessions[target_node].track_outbound(
                surb_id,
                surb_key_tuple,
                payload,
                cover,
                payload_hash,
                round=round_id,
            )
            return path, msg_bytes, surb_id, returned_hash

    @log_exceptions
    def create_surb_reply(self, nymtuple):
        reply_msg = f"Message received by node {self._node_id}".encode()
        header, delta = package_surb(self._params, nymtuple, reply_msg)
        msg_bytes = pack_message(self._params, (header, delta))
        first_hop = PFdecode(self._params, nymtuple[0])[1]
        return msg_bytes, first_hop

    @log_exceptions
    def build_forward_path(self, target_node, n_hops: int | None = None):
        if n_hops is not None:
            if n_hops == 1:
                path = [target_node]
            else:
                path = self._find_exact_length_path(self._node_id, target_node, n_hops)
                if path is None:
                    path = [target_node]
        else:
            path = self._build_path_to(self._node_id, target_node)
        return path, list(map(Nenc, path)), [self._key_store.get_y(nid) for nid in path]

    @log_exceptions
    def build_surb_reply_path(self, target_node):
        path = self._build_path_to(target_node, self._node_id)
        return path, list(map(Nenc, path)), [self._key_store.get_y(nid) for nid in path]

    @log_exceptions
    def create_and_store_surb(self, routing, keys):
        surb_id, surb_key_tuple, nymtuple = create_surb(self._params, routing, keys, b"myself")
        return surb_id, surb_key_tuple, nymtuple

    @log_exceptions
    def create_forward_packet(self, routing, keys, nymtuple, payload):
        return create_forward_message(self._params, routing, keys, b"peer-message", (nymtuple, payload))

    @log_exceptions
    def decrypt_surb(self, delta: bytes, surb_id: bytes):
        key = find_surb_key(self._sessions, surb_id)
        if key is None:
            return None
        msg = receive_surb(self._params, key, delta)
        return msg

    def _build_path_pool(self):
        all_nodes = list(self._topology.keys())
        for src in all_nodes:
            reachable = self._get_reachable_at_hops(src, self._max_hops)
            for dst in reachable:
                paths = []
                self._collect_all_paths(src, dst, self._max_hops, {src}, [], paths)
                if not paths:
                    self._collect_all_paths(src, dst, self._max_hops, None, [], paths)
                if paths:
                    self._path_pool[(src, dst)] = paths

    def _collect_all_paths(self, current, target, remaining, visited, path, results):
        if remaining == 0:
            if current == target:
                results.append(list(path))
            return
        for neighbor in self._topology.get(current, []):
            if visited is not None and neighbor in visited:
                continue
            if visited is not None:
                visited.add(neighbor)
            path.append(neighbor)
            self._collect_all_paths(neighbor, target, remaining - 1, visited, path, results)
            path.pop()
            if visited is not None:
                visited.discard(neighbor)

    def _verify_topology(self):
        for node, neighbors in self._topology.items():  # bidirectionality
            for neighbor in neighbors:
                if node not in self._topology.get(neighbor, []):
                    logging.error(f"NOT bidirectional: {node}->{neighbor}")

        degrees = [len(self._topology[n]) for n in self._topology]
        unique = set(degrees)
        if len(unique) > 1:
            logging.error(f"Non-uniform degree: {unique}")
        else:
            logging.info(f"Topology: {len(self._topology)} nodes, degree {degrees[0]}")

        sizes = set()
        for node in self._topology:
            reachable_count = len(self._get_reachable_at_hops(node, self._max_hops))
            sizes.add(reachable_count)
        if len(sizes) > 1:
            logging.error(f"Non-uniform reachability at {self._max_hops} hops: {sizes}")
        else:
            logging.info(f"Reachability at {self._max_hops} hops: {sizes.pop()} peers/node")

        if self._path_pool:
            counts = [len(p) for p in self._path_pool.values()]
            logging.info(f"Path pool: {len(self._path_pool)} pairs, {min(counts)}-{max(counts)} paths/pair")

    @log_exceptions
    def _build_path_to(self, start, target):
        if not ConfigStore.mix_enabled:
            return [target]

        pool = self._path_pool.get((start, target))
        if pool:
            # prune paths through UNREACHABLE hops; fall back to full pool if all pruned
            usable = [
                path
                for path in pool
                if not any(hop in self._sessions and self._sessions[hop].state == PeerState.UNREACHABLE for hop in path)
            ]
            if start == self._node_id:
                live = [path for path in usable if self._is_live(path[0])]
                if live:
                    return list(secrets.choice(live))
            return list(secrets.choice(usable or pool))

        # fallback when the pair isn't in the pool
        path = self._find_exact_length_path(start, target, self._max_hops)
        if path is None:
            logging.warning(f"No {self._max_hops}-hop path from {start} to {target}")
            return [target]
        return path

    def get_exchange_targets(self, node_id: int) -> list:
        if ConfigStore.mix_enabled:
            return list(self._get_reachable_at_hops(node_id, self._max_hops))
        return list(self._topology.get(node_id, []))

    def _get_reachable_at_hops(self, start, hops):
        cache_key = (start, hops)
        if cache_key in self._reachable_cache:
            return self._reachable_cache[cache_key]

        topo = self._topology
        current = {start}
        for _ in range(hops):
            next_level = set()
            for node in current:
                next_level.update(topo.get(node, []))
            current = next_level
        current.discard(start)
        self._reachable_cache[cache_key] = current
        return current

    def _find_exact_length_path(self, start, target, length):
        rng = secrets.SystemRandom()

        result = self._dfs_exact(start, target, length, {start}, rng)
        if result is not None:
            return result
        return self._dfs_exact(start, target, length, None, rng)

    def _dfs_exact(self, current, target, remaining, visited, rng):
        if remaining == 0:
            return [] if current == target else None

        neighbors = list(self._topology.get(current, []))
        rng.shuffle(neighbors)

        for neighbor in neighbors:
            if visited is not None and neighbor in visited:
                continue

            if visited is not None:
                visited.add(neighbor)

            result = self._dfs_exact(neighbor, target, remaining - 1, visited, rng)

            if visited is not None:
                visited.discard(neighbor)

            if result is not None:
                return [neighbor] + result

        return None

    async def process_incoming(self, data: bytes):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._process_incoming_sync, data)

    def _process_incoming_sync(self, data: bytes):
        param_dict = {(self._params.max_len, self._params.m): self._params}
        _, (header, delta) = unpack_message(param_dict, data)
        x = self._key_store.get_x(self._node_id)
        _, info, (header, delta), mac_key = sphinx_process(self._params, x, header, delta)
        routing = PFdecode(self._params, info)
        return routing, header, delta, mac_key
